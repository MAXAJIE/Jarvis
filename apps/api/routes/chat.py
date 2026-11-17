"""Chat over WebSocket. The transport adapter: it owns the conversation row and
the JSON protocol, and hands the agent a transport-neutral ToolContext."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel
from sqlalchemy import select

from agent.runtime import Runtime
from apps.api.auth import COOKIE_NAME, read_token, require_session
from apps.api.config import get_settings
from apps.api.db.models import Conversation, Message, User
from apps.api.db.session import session_scope
from packages.contracts.tool import Lang, ToolContext, Transport

router = APIRouter()
logger = logging.getLogger(__name__)


def _runtime(ws: WebSocket) -> Runtime:
    runtime: Runtime = ws.app.state.runtime
    return runtime


async def _turn_or_error(ws: WebSocket, ctx: ToolContext, text: str) -> Any:
    """Run one turn; report a failed turn instead of dropping the socket.

    Provider faults are ordinary here: a rate limit, an exhausted OpenRouter
    balance, a rejected key. Closing the socket leaves the operator staring at a
    message that never answers; a typed error frame tells them what happened and
    keeps the conversation usable.
    """
    try:
        return await _runtime(ws).turn(ctx, text)
    except WebSocketDisconnect:
        raise
    except Exception as exc:  # the transport reports, the agent decides
        logger.exception("turn failed")
        await ws.send_json(
            {
                "type": "error",
                "message": str(exc) or exc.__class__.__name__,
                "detail": exc.__class__.__name__,
            }
        )
        return None


async def _open_conversation(
    user_id: str, lang: str, conversation_id: str | None
) -> tuple[str, str]:
    """Resume the operator's web conversation, or start a new one.

    Without this the socket opened a fresh conversation on every page load, so
    switching tabs or reloading silently threw away the visible transcript and
    reset the language. Only the socket reuses a conversation: a conversation id
    that does not belong to this user is treated as absent, not as an error, so a
    stale id in local storage cannot be used to read someone else's turns.
    """
    async with session_scope() as session:
        if conversation_id:
            existing = await session.scalar(
                select(Conversation).where(
                    Conversation.id == conversation_id,
                    Conversation.user_id == user_id,
                    Conversation.transport == "web",
                )
            )
            if existing is not None:
                return existing.id, existing.lang
        conversation = Conversation(user_id=user_id, transport="web", lang=lang, mode="text")
        session.add(conversation)
        await session.flush()
        return conversation.id, lang


class MessageView(BaseModel):
    role: str
    content: str
    tainted: bool
    created_at: str


@router.get("/api/chat/history")
async def history(
    conversation_id: str, user_id: str = Depends(require_session)
) -> dict[str, list[MessageView]]:
    """The transcript the browser should render when it reattaches."""
    async with session_scope() as session:
        owned = await session.scalar(
            select(Conversation.id).where(
                Conversation.id == conversation_id, Conversation.user_id == user_id
            )
        )
        if owned is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "conversation not found")
        rows = (
            await session.scalars(
                select(Message)
                .where(Message.conversation_id == conversation_id)
                .order_by(Message.created_at)
            )
        ).all()
    return {
        "messages": [
            MessageView(
                role=row.role,
                content=row.content,
                tainted=row.tainted,
                created_at=row.created_at.isoformat(),
            )
            for row in rows
            if row.role in {"user", "assistant"}
        ]
    }


@router.websocket("/ws/chat")
async def chat_socket(ws: WebSocket) -> None:
    token = ws.cookies.get(COOKIE_NAME)
    user_id = read_token(token)
    if user_id is None:
        await ws.close(code=4401)
        return
    async with session_scope() as session:
        if await session.get(User, user_id) is None:
            await ws.close(code=4401)
            return

    await ws.accept()
    settings = get_settings()
    conversation_id, lang = await _open_conversation(
        user_id, "en", ws.query_params.get("conversation_id")
    )
    await ws.send_json(
        {
            "type": "ready",
            "conversation_id": conversation_id,
            "lang": lang,
            "provider": settings.llm_provider,
            "transport": "web",
        }
    )

    async def context(transport: Transport = Transport.WEB) -> ToolContext:
        return ToolContext(
            user_id=user_id,
            conversation_id=conversation_id,
            thread_id=conversation_id,
            lang=Lang(lang),
            transport=transport,
            deadline_ms=3000 if transport is Transport.VOICE else 8000,
        )

    try:
        while True:
            frame: dict[str, Any] = await ws.receive_json()
            kind = frame.get("type")
            if kind == "set_lang":
                lang = str(frame.get("lang", "en"))
                if lang not in {member.value for member in Lang}:
                    await ws.send_json({"type": "error", "message": "unsupported language"})
                    lang = "en"
                    continue
                async with session_scope() as session:
                    conversation = await session.get(Conversation, conversation_id)
                    if conversation is not None:
                        conversation.lang = lang
                await ws.send_json({"type": "lang", "lang": lang})
                continue

            if kind != "user_message":
                await ws.send_json({"type": "error", "message": f"unknown frame {kind!r}"})
                continue

            text = str(frame.get("text", "")).strip()
            if not text:
                await ws.send_json({"type": "error", "message": "empty message"})
                continue

            result = await _turn_or_error(ws, await context(), text)
            if result is None:
                continue
            await ws.send_json(
                {
                    "type": "turn",
                    "answer": result.answer,
                    "events": result.events,
                    "approval": result.approval,
                    "tainted": result.tainted,
                    "stopped": result.stopped,
                }
            )
    except WebSocketDisconnect:
        return
