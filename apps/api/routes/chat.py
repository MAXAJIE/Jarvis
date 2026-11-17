"""Chat over WebSocket. The transport adapter: it owns the conversation row and
the JSON protocol, and hands the agent a transport-neutral ToolContext."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from agent.runtime import Runtime
from apps.api.auth import COOKIE_NAME, read_token
from apps.api.config import get_settings
from apps.api.db.models import Conversation, User
from apps.api.db.session import session_scope
from packages.contracts.tool import Lang, ToolContext, Transport

router = APIRouter()


def _runtime(ws: WebSocket) -> Runtime:
    runtime: Runtime = ws.app.state.runtime
    return runtime


async def _open_conversation(user_id: str, lang: str) -> str:
    async with session_scope() as session:
        conversation = Conversation(user_id=user_id, transport="web", lang=lang, mode="text")
        session.add(conversation)
        await session.flush()
        return conversation.id


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
    lang = "en"
    conversation_id = await _open_conversation(user_id, lang)
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

            result = await _runtime(ws).turn(await context(), text)
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
