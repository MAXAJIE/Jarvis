"""Voice over WebSocket: press to talk, one utterance per turn, English this phase.

Protocol (JSON text frames, plus raw binary frames for the audio itself):

    client -> {"type": "audio_start", "mime": "audio/webm;codecs=opus"}
    client -> <binary chunks of recorded audio>
    client -> {"type": "audio_end"}
    server -> {"type": "transcript", "text": "...", "confidence": 0.98, "seconds": 3.1}
    server -> {"type": "turn", "answer": "...", "events": [...], "approval": ...}
    server -> {"type": "speech", "mime": "audio/mpeg", "data": "<base64 mp3>"}

Every stage reports its own failure and stops, rather than continuing with silence:
a failed transcription is a `stage: "stt"` error, not a turn on empty input.

This is deliberately not the streaming duplex loop. Sending one recorded utterance
per turn costs one HTTP call to Deepgram each way and works today; barge-in and
partial transcripts are the next step, not this one.
"""

from __future__ import annotations

import base64
import json
import logging
import time
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from apps.api.auth import COOKIE_NAME, read_token
from apps.api.config import get_settings
from apps.api.db.models import User
from apps.api.db.session import session_scope
from apps.api.routes.chat import _open_conversation, _turn_or_error
from apps.api.services.budget import record_cost
from media.stt import STT_USD_PER_MINUTE, transcribe
from media.tts import TTS_USD_PER_1K_CHARS, speak
from packages.contracts.tool import Lang, ToolContext, Transport

router = APIRouter()
logger = logging.getLogger(__name__)

MAX_UTTERANCE_BYTES = 8 * 1024 * 1024  # 8 MB: ~2 minutes of opus, far past a turn
ALLOWED_MIME = {"audio/webm", "audio/ogg", "audio/mp4", "audio/mpeg"}


async def _auth(ws: WebSocket) -> str | None:
    token = ws.cookies.get(COOKIE_NAME)
    user_id = read_token(token)
    if user_id is None:
        await ws.close(code=4401)
        return None
    async with session_scope() as session:
        if await session.get(User, user_id) is None:
            await ws.close(code=4401)
            return None
    return user_id


async def _record_stt(text_length: int, seconds: float, conversation_id: str, ok: bool) -> None:
    """P4: a billable call that produced nothing still costs, and must be visible."""
    await record_cost(
        kind="stt",
        provider="deepgram",
        model=get_settings().deepgram_stt_model,
        units=Decimal(str(round(seconds, 3))),
        unit_name="seconds",
        unit_price_usd=Decimal(str(STT_USD_PER_MINUTE)) / Decimal(60),
        usd=(Decimal(str(seconds)) * Decimal(str(STT_USD_PER_MINUTE)) / Decimal(60)).quantize(
            Decimal("0.000001")
        ),
        conversation_id=conversation_id,
        meta={"unverified_price": True, "chars": text_length, "ok": ok},
    )


async def _record_tts(chars: int, conversation_id: str, ok: bool) -> None:
    await record_cost(
        kind="tts",
        provider=get_settings().tts_provider,
        model=get_settings().deepgram_tts_model_en,
        units=Decimal(chars),
        unit_name="chars",
        unit_price_usd=Decimal(str(TTS_USD_PER_1K_CHARS)) / Decimal(1000),
        usd=(Decimal(chars) * Decimal(str(TTS_USD_PER_1K_CHARS)) / Decimal(1000)).quantize(
            Decimal("0.000001")
        ),
        conversation_id=conversation_id,
        meta={"unverified_price": True, "ok": ok},
    )


@router.websocket("/ws/voice")
async def voice_socket(ws: WebSocket) -> None:
    user_id = await _auth(ws)
    if user_id is None:
        return
    await ws.accept()
    conversation_id, lang = await _open_conversation(
        user_id, "en", ws.query_params.get("conversation_id")
    )
    await ws.send_json(
        {
            "type": "ready",
            "conversation_id": conversation_id,
            "lang": lang,
            "thresholds": {"stt": "deepgram", "tts": get_settings().tts_provider},
        }
    )

    def context() -> ToolContext:
        return ToolContext(
            user_id=user_id,
            conversation_id=conversation_id,
            thread_id=conversation_id,
            lang=Lang(lang),
            transport=Transport.VOICE,
            # Voice is impatient by design: a turn that takes longer than this is
            # better refused than held in silence (D-06).
            deadline_ms=3000,
        )

    audio = bytearray()
    mime = "audio/webm"
    try:
        while True:
            frame = await ws.receive()
            if frame.get("type") == "websocket.disconnect":
                return
            if frame.get("bytes") is not None:
                if len(audio) + len(frame["bytes"]) > MAX_UTTERANCE_BYTES:
                    audio.clear()
                    await ws.send_json(
                        {"type": "error", "stage": "stt", "message": "utterance too long"}
                    )
                    continue
                audio.extend(frame["bytes"])
                continue

            payload = frame.get("text")
            if payload is None:
                continue
            try:
                message: dict[str, Any] = json.loads(payload)
            except json.JSONDecodeError:
                await ws.send_json({"type": "error", "message": "frames must be JSON"})
                continue
            kind = message.get("type")
            if kind == "audio_start":
                audio.clear()
                declared = str(message.get("mime") or "audio/webm")
                mime = declared if declared in ALLOWED_MIME else "audio/webm"
                await ws.send_json({"type": "listening"})
                continue
            if kind != "audio_end":
                await ws.send_json({"type": "error", "message": f"unknown frame {kind!r}"})
                continue

            chunk = bytes(audio)
            audio.clear()
            if not chunk:
                await ws.send_json(
                    {"type": "error", "stage": "stt", "message": "no audio received"}
                )
                continue

            try:
                heard = await transcribe(chunk, mime=mime, lang="en")
            except Exception as exc:  # stt failures are reported, not swallowed
                logger.exception("stt failed")
                await _record_stt(0, 0.0, conversation_id, ok=False)
                await ws.send_json({"type": "error", "stage": "stt", "message": str(exc)[:300]})
                continue
            await _record_stt(len(heard.text), heard.seconds, conversation_id, ok=True)
            await ws.send_json(
                {
                    "type": "transcript",
                    "text": heard.text,
                    "confidence": round(heard.confidence, 3),
                    "seconds": round(heard.seconds, 2),
                }
            )
            if not heard.text:
                await ws.send_json(
                    {
                        "type": "error",
                        "stage": "stt",
                        "message": "heard nothing; hold the button while you speak",
                    }
                )
                continue

            started = time.monotonic()
            result = await _turn_or_error(ws, context(), heard.text)
            if result is None:
                continue
            # Measured, not assumed: the D-06 target is 3 s end to end, and a free
            # model will miss it. The number belongs on the wire so the UI and the
            # eval set can argue with the target honestly.
            turn_ms = int((time.monotonic() - started) * 1000)
            await ws.send_json(
                {
                    "type": "turn",
                    "answer": result.answer,
                    "events": result.events,
                    "approval": result.approval,
                    "tainted": result.tainted,
                    "stopped": result.stopped,
                    "latency_ms": turn_ms,
                }
            )

            spoken = result.answer
            if result.approval:
                # A paused action must be said out loud: a silent approval gate on
                # a voice channel is the same bug as a UI that shows nothing.
                spoken = "I need your approval before I do that. Check the screen."
            if not spoken:
                continue
            try:
                speech = await speak(spoken, lang="en")
            except Exception as exc:
                logger.exception("tts failed")
                await _record_tts(len(spoken), conversation_id, ok=False)
                await ws.send_json({"type": "error", "stage": "tts", "message": str(exc)[:300]})
                continue
            await _record_tts(len(spoken), conversation_id, ok=True)
            await ws.send_json(
                {
                    "type": "speech",
                    "mime": speech.mime,
                    "data": base64.b64encode(speech.audio).decode("ascii"),
                    "chars": len(spoken),
                }
            )
    except WebSocketDisconnect:
        return
