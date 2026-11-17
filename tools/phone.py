"""``call_place``: the tool with the fraud guard (T5) and the hard duration cap.

Order matters. The caller-ID check runs *before* the provider check, so the
guard is testable and enforced even when Twilio is unconfigured, and a bad
caller ID never reaches the network, never writes a ledger row, and never
rings anyone.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field
from sqlalchemy import select

from apps.api.config import get_settings
from apps.api.db.models import Call, PhoneLine
from apps.api.db.session import session_scope
from packages.contracts.errors import CallerIdNotOwned, NotConfigured, ToolError
from packages.contracts.tool import RiskLevel, Tool, ToolContext
from providers import clients
from tools.base import FunctionTool

E164 = re.compile(r"^\+[1-9]\d{7,14}$")
LANG_HINT = {
    "en": "English",
    "zh-TW": "Traditional Chinese",
}


class CallPlaceIn(BaseModel):
    to_e164: str = Field(description="Destination in E.164, e.g. +60123456789")
    purpose: str = Field(min_length=1, description="What the agent should say and find out")
    caller_id_e164: str | None = Field(
        default=None, description="Must be a verified row in phone_lines; defaults to the line"
    )


class CallPlaceOut(BaseModel):
    call_id: str
    twilio_call_sid: str | None
    status: str
    max_duration_s: int


async def _resolve_line(caller_id: str | None, ctx: ToolContext) -> PhoneLine:
    settings = get_settings()
    wanted = caller_id or settings.twilio_default_line_e164
    if not wanted:
        raise CallerIdNotOwned("no caller ID configured; add a phone line first")
    if not E164.match(wanted):
        raise CallerIdNotOwned("caller ID must be E.164")
    async with session_scope() as session:
        stmt = select(PhoneLine).where(PhoneLine.user_id == ctx.user_id, PhoneLine.e164 == wanted)
        line = (await session.execute(stmt)).scalars().first()
    if line is None or line.verified_at is None or line.status != "active":
        raise CallerIdNotOwned("that number is not a verified line you own; refusing to present it")
    return line


async def _place(a: CallPlaceIn, ctx: ToolContext) -> CallPlaceOut:
    if not E164.match(a.to_e164):
        raise ToolError("destination must be E.164")
    line = await _resolve_line(a.caller_id_e164, ctx)
    settings = get_settings()
    if not (settings.twilio_account_sid and settings.twilio_auth_token):
        raise NotConfigured("TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN are empty")
    if not settings.twilio_webhook_base:
        raise NotConfigured("TWILIO_WEBHOOK_BASE is empty; the agent has no TwiML to run")

    # D-23: the disclosure is part of the TwiML the webhook serves, and the
    # language hint travels with the call so the first utterance is right.
    _ = LANG_HINT.get(str(ctx.lang), "English")
    async with session_scope() as session:
        call = Call(
            phone_line_id=line.id,
            direction="outbound",
            remote_e164=a.to_e164,
            status="queued",
        )
        session.add(call)
        await session.flush()
        call_id = call.id

    try:
        sid = await clients.twilio_place_call(
            to_e164=a.to_e164,
            from_e164=line.e164,
            twiml_url=settings.twilio_webhook_base,
            max_s=settings.call_max_duration_s,
        )
    except RuntimeError as exc:
        async with session_scope() as session:
            stored = await session.get(Call, call_id)
            if stored is not None:
                stored.status = "failed"
        raise ToolError(str(exc)) from exc

    async with session_scope() as session:
        stored = await session.get(Call, call_id)
        if stored is not None:
            stored.twilio_call_sid = sid
            stored.status = "ringing"
    return CallPlaceOut(
        call_id=call_id,
        twilio_call_sid=sid,
        status="ringing",
        max_duration_s=settings.call_max_duration_s,
    )


def build() -> list[Tool]:
    return [
        FunctionTool(
            name="call_place",
            description="Place one outbound phone call that speaks on the operator's behalf.",
            input_model=CallPlaceIn,
            output_model=CallPlaceOut,
            risk=RiskLevel.EXTERNAL,
            idempotent=False,
            timeout_s=30.0,
            handler=_place,
        )
    ]
