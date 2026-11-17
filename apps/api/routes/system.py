"""One read-only payload for the command center.

The dashboard in ``apps/web`` draws eleven panels. Querying eleven endpoints
means eleven chances to disagree with each other, so everything the operator
sees on the landing screen is assembled here from the same session and the same
:class:`datetime` reading.

Nothing in this module invents a number. Panels that the design calls for but
that have no real source yet (CPU load, free memory, weather) are left out
rather than filled with plausible-looking values, because a fabricated gauge is
indistinguishable from a broken one.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import func, select

from apps.api.auth import require_session
from apps.api.config import get_settings
from apps.api.db.models import (
    Approval,
    Conversation,
    CostLedgerRow,
    MemoryFact,
    Message,
    Task,
    ToolRun,
)
from apps.api.db.session import session_scope
from apps.api.routes.metrics import health
from apps.api.services.audit import preview_for
from apps.api.services.budget import dashboard
from media.tts import voice_status
from packages.contracts.tool import RiskLevel
from tools.registry import SPECIALIST_TOOLS, build_registry

router = APIRouter(prefix="/api/system", tags=["system"])

FEED_LIMIT = 12
TIMELINE_LIMIT = 8
CONVERSATION_LIMIT = 6

SPECIALIST_LABELS: dict[str, str] = {
    "supervisor": "Supervisor",
    "executor": "Executor",
    "researcher": "Researcher",
    "scheduler": "Scheduler",
    "comms": "Comms",
}


def _utc(value: datetime | None) -> datetime | None:
    """SQLite hands back naive datetimes even for ``DateTime(timezone=True)``.

    Comparing those to an aware ``now`` raises, and serialising them makes the
    browser read the value as local time. Everything stored is UTC, so say so.
    """
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


async def _scalar(session: Any, statement: Any) -> int:
    value = (await session.execute(statement)).scalar_one()
    return int(value or 0)


async def _counters(session: Any, user_id: str, start: datetime) -> dict[str, int]:
    open_tasks = await _scalar(
        session,
        select(func.count(Task.id)).where(Task.user_id == user_id, Task.status == "open"),
    )
    facts = await _scalar(
        session,
        select(func.count(MemoryFact.id)).where(MemoryFact.user_id == user_id),
    )
    conversations = await _scalar(
        session,
        select(func.count(Conversation.id)).where(Conversation.user_id == user_id),
    )
    messages = await _scalar(
        session,
        select(func.count(Message.id))
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(Conversation.user_id == user_id),
    )
    tool_runs = await _scalar(
        session,
        select(func.count(ToolRun.id)).where(ToolRun.ts >= start),
    )
    approvals_pending = await _scalar(
        session,
        select(func.count(Approval.id))
        .join(Conversation, Conversation.id == Approval.thread_id)
        .where(Approval.decision.is_(None), Conversation.user_id == user_id),
    )
    return {
        "open_tasks": open_tasks,
        "facts": facts,
        "conversations": conversations,
        "messages": messages,
        "tool_runs_month": tool_runs,
        "approvals_pending": approvals_pending,
    }


async def _feed(session: Any, user_id: str) -> list[dict[str, Any]]:
    """Recent events, newest first: approvals, tool runs, and the spend alarm."""
    items: list[dict[str, Any]] = []

    approvals = (
        await session.scalars(
            select(Approval)
            .join(Conversation, Conversation.id == Approval.thread_id)
            .where(Conversation.user_id == user_id)
            .order_by(Approval.created_at.desc())
            .limit(FEED_LIMIT)
        )
    ).all()
    for row in approvals:
        pending = row.decision is None
        items.append(
            {
                "kind": "approval",
                "level": "warn" if pending else ("info" if row.decision == "approved" else "tip"),
                "title": row.tool_name,
                "detail": preview_for(row.tool_name, row.args or {}),
                "ts": (_utc(row.created_at) or datetime.now(UTC)).isoformat(),
                "pending": pending,
            }
        )

    runs = (
        await session.scalars(select(ToolRun).order_by(ToolRun.ts.desc()).limit(FEED_LIMIT))
    ).all()
    for run in runs:
        items.append(
            {
                "kind": "tool",
                "level": "info" if run.ok else "warn",
                "title": run.tool_name,
                "detail": (run.error or f"ok in {run.ms or '?'} ms")[:160],
                "ts": (_utc(run.ts) or datetime.now(UTC)).isoformat(),
                "pending": False,
            }
        )

    items.sort(key=lambda item: str(item["ts"]), reverse=True)
    return items[:FEED_LIMIT]


async def _timeline(session: Any, user_id: str, now: datetime) -> list[dict[str, Any]]:
    soon = now + timedelta(days=14)
    rows = (
        await session.scalars(
            select(Task)
            .where(
                Task.user_id == user_id,
                Task.status == "open",
                Task.due_at.is_not(None),
                Task.due_at <= soon,
            )
            .order_by(Task.due_at)
            .limit(TIMELINE_LIMIT)
        )
    ).all()
    return [
        {
            "id": row.id,
            "title": row.title,
            "due_at": (_utc(row.due_at) or now).isoformat() if row.due_at else None,
            "priority": row.priority,
            "status": row.status,
            "overdue": bool(row.due_at and (_utc(row.due_at) or now) < now),
        }
        for row in rows
    ]


async def _conversations(session: Any, user_id: str, now: datetime) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            select(Conversation, func.count(Message.id))
            .outerjoin(Message, Message.conversation_id == Conversation.id)
            .where(Conversation.user_id == user_id)
            .group_by(Conversation.id)
            .order_by(Conversation.started_at.desc())
            .limit(CONVERSATION_LIMIT)
        )
    ).all()
    return [
        {
            "id": conversation.id,
            "started_at": (_utc(conversation.started_at) or now).isoformat(),
            "lang": conversation.lang,
            "transport": conversation.transport,
            "messages": int(count),
        }
        for conversation, count in rows
    ]


def _tools() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    registry = build_registry()
    tools: list[dict[str, Any]] = []
    for tool in sorted(registry.all(), key=lambda item: item.name):
        tools.append(
            {
                "name": tool.name,
                "description": tool.description.splitlines()[0][:140],
                "risk": tool.risk.value,
                "taints": bool(tool.taints),
                "idempotent": bool(tool.idempotent),
            }
        )
    specialists = [
        {
            "name": name,
            "label": SPECIALIST_LABELS.get(name, name.title()),
            "tools": len(names),
            "tool_names": sorted(names),
        }
        for name, names in SPECIALIST_TOOLS.items()
    ]
    return tools, specialists


@router.get("/overview")
async def overview(user_id: str = Depends(require_session)) -> dict[str, Any]:
    settings = get_settings()
    now = datetime.now(UTC)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    budget = await dashboard()
    health_body = await health(_NullResponse())  # type: ignore[arg-type]

    async with session_scope() as session:
        counters = await _counters(session, user_id, start)
        feed = await _feed(session, user_id)
        timeline = await _timeline(session, user_id, now)
        conversations = await _conversations(session, user_id, now)
        cost = await _scalar(
            session,
            select(func.coalesce(func.sum(CostLedgerRow.usd), 0)).where(CostLedgerRow.ts >= start),
        )

    tools, specialists = _tools()
    by_risk: dict[str, int] = {level.value: 0 for level in RiskLevel}
    for tool in tools:
        by_risk[str(tool["risk"])] += 1

    return {
        "now": now.isoformat(),
        "period_start": budget["period_start"],
        "health": {
            "status": health_body["status"],
            "components": health_body["components"],
            "missing": health_body["missing"],
            "app_env": health_body["app_env"],
        },
        "budget": {
            "spend_usd": budget["spend_usd"],
            "usage_usd": budget["usage_usd"],
            "fixed_usd": budget["fixed_usd"],
            "ceiling_usd": budget["ceiling_usd"],
            "remaining_usd": budget["remaining_usd"],
            "alarm": budget["alarm"],
        },
        "counters": {
            **counters,
            "tasks_completed": budget["tasks_completed"],
            "failures": budget["failures"],
            "api_calls": budget["api_calls"],
            "tokens_used": budget["tokens_used"],
            "voice_minutes": budget["voice_minutes"],
            "cost_cents": cost,
        },
        "feed": feed,
        "timeline": timeline,
        "conversations": conversations,
        "specialists": specialists,
        "tools": tools,
        "tools_by_risk": by_risk,
        "llm": {
            "provider": settings.llm_provider,
            "configured": settings.llm_configured,
            "model": settings.llm_model_strong if settings.llm_configured else "stub",
            "key_env": settings.llm_key_env_name,
        },
        "voice": voice_status(),
    }


class _NullResponse:
    """``health()`` wants a Response to set a status code; this payload does not."""

    status_code = 200
