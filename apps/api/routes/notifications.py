"""Reminders the operator can see and dismiss.

Delivery is the part that makes ``remind`` mean anything: a task with a due time in
the past produces one event, the UI lists it until it is acknowledged, and a repeat
rolls the same task forward instead of piling up copies.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from apps.api.auth import require_session
from apps.api.services.reminders import acknowledge, recent

router = APIRouter(tags=["reminders"])


class AckIn(BaseModel):
    ids: list[int]


@router.get("/api/notifications")
async def notifications(user_id: str = Depends(require_session)) -> dict[str, Any]:
    del user_id  # single-user: the one operator owns every row
    items = await recent()
    return {"reminders": items, "count": len(items)}


@router.post("/api/notifications/ack")
async def ack(body: AckIn, user_id: str = Depends(require_session)) -> dict[str, Any]:
    del user_id
    done: list[int] = []
    missing: list[int] = []
    for event_id in body.ids:
        (done if await acknowledge(event_id) else missing).append(event_id)
    if missing and not done:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such reminder")
    return {"acknowledged": done, "unknown": missing}
