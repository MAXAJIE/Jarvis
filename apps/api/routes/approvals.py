"""Approval queue. A decision resumes the interrupted graph on the same thread."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from agent.runtime import Runtime
from apps.api.auth import require_session
from apps.api.db.models import Conversation
from apps.api.db.session import session_scope
from apps.api.services import audit
from packages.contracts.tool import Lang, ToolContext

router = APIRouter(prefix="/api/approvals", tags=["approvals"])


class DecisionIn(BaseModel):
    decision: Literal["approved", "rejected"]


def _runtime(request: Request) -> Runtime:
    runtime: Runtime = request.app.state.runtime
    return runtime


@router.get("")
async def list_pending(user_id: str = Depends(require_session)) -> dict[str, Any]:
    rows = await audit.pending()
    return {"approvals": rows, "count": len(rows), "user_id": user_id}


@router.post("/{approval_id}/decide")
async def decide(
    approval_id: str,
    body: DecisionIn,
    request: Request,
    user_id: str = Depends(require_session),
) -> dict[str, Any]:
    try:
        decided = await audit.decide(approval_id, body.decision)
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such approval") from exc

    async with session_scope() as session:
        conversation = await session.get(Conversation, decided["thread_id"])
        if conversation is None or conversation.user_id != user_id:
            return {"decision": decided["decision"], "turn": None}
        ctx = ToolContext(
            user_id=conversation.user_id,
            conversation_id=conversation.id,
            thread_id=conversation.id,
            lang=Lang(conversation.lang),
            deadline_ms=8000,
        )

    result = await _runtime(request).resume(ctx, decided["decision"])
    return {
        "decision": decided["decision"],
        "turn": {
            "answer": result.answer,
            "events": result.events,
            "approval": result.approval,
            "tainted": result.tainted,
        },
    }
