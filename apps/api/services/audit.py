"""Audit trail and approvals. Append-only; no update path for tool_runs."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

from apps.api.config import get_settings
from apps.api.db.models import Approval, ToolRun
from apps.api.db.session import session_scope


async def write_tool_run(
    *,
    tool_name: str,
    ok: bool,
    args: dict[str, Any] | None = None,
    result: dict[str, Any] | None = None,
    error: str | None = None,
    ms: int | None = None,
    conversation_id: str | None = None,
) -> None:
    async with session_scope() as session:
        session.add(
            ToolRun(
                tool_name=tool_name,
                ok=ok,
                args=args,
                result=result,
                error=error,
                ms=ms,
                conversation_id=conversation_id,
            )
        )


def preview_for(tool_name: str, args: dict[str, Any]) -> str:
    """Plain-English summary shown on the approval screen.

    For ``mail_send`` the operator must see the body, not a draft id: approving
    an opaque reference is the theatre T11 warns about.
    """
    if tool_name == "mail_send":
        from tools.mail import load_draft

        try:
            draft = load_draft(str(args.get("draft_id", "")))
        except Exception:  # noqa: BLE001 - preview must never break the approval flow
            return f"Send draft {args.get('draft_id')} (draft is missing)"
        taint = " [draft came from outside content]" if draft.get("tainted") else ""
        return (
            f"Send email to {draft.get('to')} — subject: {draft.get('subject')}{taint}\n\n"
            f"{draft.get('body')}"
        )
    if tool_name == "call_place":
        return f"Call {args.get('to_e164')} and speak on your behalf: {args.get('purpose')}"
    if tool_name == "shell":
        return f"Run in sandbox: {args.get('command')}"
    if tool_name == "telegram_send":
        return f"Message chat {args.get('chat_id')}: {args.get('text')}"
    if tool_name == "task_delete":
        return f"Permanently delete task {args.get('task_id')}"
    if tool_name == "fs_delete":
        return f"Permanently delete {args.get('path')}"
    return f"{tool_name} {args}"


async def ensure_approval(
    *, thread_id: str, tool_name: str, args: dict[str, Any], risk: str
) -> dict[str, Any]:
    """Idempotent by construction.

    LangGraph re-runs an interrupted node from the top on resume, so anything
    before ``interrupt()`` executes twice. The row id is a hash of
    (thread, tool, args), which makes the second pass find the first row
    (and its decision) instead of creating a duplicate prompt.
    """
    key = json.dumps({"t": thread_id, "n": tool_name, "a": args}, sort_keys=True)
    approval_id = hashlib.sha256(key.encode()).hexdigest()[:32]
    ttl = timedelta(minutes=get_settings().approval_ttl_minutes)
    async with session_scope() as session:
        row = await session.get(Approval, approval_id)
        if row is None:
            row = Approval(
                id=approval_id,
                thread_id=thread_id,
                tool_name=tool_name,
                args=args,
                risk=risk,
                expires_at=datetime.now(UTC) + ttl,
            )
            session.add(row)
            await session.flush()
        return {
            "id": row.id,
            "thread_id": row.thread_id,
            "tool_name": row.tool_name,
            "args": row.args,
            "risk": row.risk,
            "summary": preview_for(row.tool_name, row.args or {}),
            "expires_at": row.expires_at.isoformat(),
            "decision": row.decision,
        }


def _as_utc(moment: datetime) -> datetime:
    """SQLite hands back naive datetimes; PostgreSQL hands back aware ones."""
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def _is_expired(row: Approval, now: datetime | None = None) -> bool:
    return _as_utc(row.expires_at) <= (now or datetime.now(UTC))


async def pending() -> list[dict[str, Any]]:
    async with session_scope() as session:
        stmt = (
            select(Approval).where(Approval.decision.is_(None)).order_by(Approval.created_at.desc())
        )
        rows = (await session.execute(stmt)).scalars().all()
    out: list[dict[str, Any]] = []
    for row in rows:
        expired = _is_expired(row)
        out.append(
            {
                "id": row.id,
                "thread_id": row.thread_id,
                "tool_name": row.tool_name,
                "args": row.args,
                "risk": row.risk,
                "summary": preview_for(row.tool_name, row.args or {}),
                "expires_at": row.expires_at.isoformat(),
                "expired": expired,
            }
        )
    return out


async def decide(approval_id: str, decision: str) -> dict[str, Any]:
    """Record a decision.

    An expired approval is recorded as rejected, never as approved (fail closed).
    """
    if decision not in {"approved", "rejected"}:
        raise ValueError("decision must be approved or rejected")
    async with session_scope() as session:
        row = await session.get(Approval, approval_id)
        if row is None:
            raise LookupError("no such approval")
        final = "rejected" if _is_expired(row) else decision
        row.decision = final
        row.decided_at = datetime.now(UTC)
        return {"id": row.id, "thread_id": row.thread_id, "decision": final}


async def decision_of(approval_id: str) -> str | None:
    async with session_scope() as session:
        row = await session.get(Approval, approval_id)
        return None if row is None else row.decision


async def has_approval(thread_id: str, tool_name: str) -> bool:
    async with session_scope() as session:
        stmt = (
            select(Approval)
            .where(
                Approval.thread_id == thread_id,
                Approval.tool_name == tool_name,
                Approval.decision == "approved",
            )
            .limit(1)
        )
        return (await session.execute(stmt)).scalars().first() is not None
