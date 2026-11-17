"""Read-only calendar, and ``remind`` which is a dated task rather than a second system.

Calendar needs Google OAuth, so it fails closed with ``NotConfigured`` until the
credentials exist. It is read-only on purpose: writing events was never in scope
(PLANBOOK §2, C6 says "Gmail now"; calendar is read-only and optional).
"""

from __future__ import annotations

from datetime import datetime

import httpx
from pydantic import BaseModel, Field

from apps.api.config import get_settings
from packages.contracts.errors import NotConfigured, ToolError
from packages.contracts.tool import RiskLevel, Tool, ToolContext
from providers import clients
from tools.base import FunctionTool


class CalendarReadIn(BaseModel):
    days_ahead: int = Field(default=7, ge=1, le=60)


class CalendarEvent(BaseModel):
    title: str
    start: str
    end: str
    location: str | None = None


class CalendarReadOut(BaseModel):
    events: list[CalendarEvent]


class RemindIn(BaseModel):
    text: str = Field(min_length=1)
    when: datetime


class RemindOut(BaseModel):
    task_id: str
    when: datetime


async def _read(a: CalendarReadIn, ctx: ToolContext) -> CalendarReadOut:
    del ctx
    settings = get_settings()
    if not (settings.google_client_id and settings.google_refresh_token):
        raise NotConfigured("calendar is not configured: GOOGLE_* credentials are empty")
    token = await clients.refresh_access_token()
    params = {
        "timeMin": datetime.now().astimezone().isoformat(),
        "maxResults": str(a.days_ahead * 10),
        "singleEvents": "true",
        "orderBy": "startTime",
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(
            "https://www.googleapis.com/calendar/v3/calendars/primary/events",
            params=params,
            headers={"Authorization": f"Bearer {token}"},
        )
    if response.status_code != 200:
        raise ToolError(f"calendar read failed: {response.status_code}")
    items = response.json().get("items", [])
    events: list[CalendarEvent] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        start = item.get("start", {})
        end = item.get("end", {})
        events.append(
            CalendarEvent(
                title=str(item.get("summary", "(no title)")),
                start=str(start.get("dateTime", start.get("date", ""))),
                end=str(end.get("dateTime", end.get("date", ""))),
                location=item.get("location"),
            )
        )
    return CalendarReadOut(events=events)


async def _remind(a: RemindIn, ctx: ToolContext) -> RemindOut:
    from apps.api.db.models import Task
    from apps.api.db.session import session_scope

    async with session_scope() as session:
        task = Task(
            user_id=ctx.user_id,
            title=a.text,
            due_at=a.when,
            priority=2,
            source="agent",
        )
        session.add(task)
        await session.flush()
        task_id = task.id
    return RemindOut(task_id=task_id, when=a.when)


def build() -> list[Tool]:
    return [
        FunctionTool(
            name="calendar_read",
            description="List upcoming calendar events.",
            input_model=CalendarReadIn,
            output_model=CalendarReadOut,
            risk=RiskLevel.READ,
            idempotent=True,
            timeout_s=20.0,
            handler=_read,
        ),
        FunctionTool(
            name="remind",
            description="Create a dated reminder task.",
            input_model=RemindIn,
            output_model=RemindOut,
            risk=RiskLevel.WRITE,
            idempotent=False,
            timeout_s=5.0,
            handler=_remind,
        ),
    ]
