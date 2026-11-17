"""Telegram: one allowed chat, everything else needs a human (D-13 beats §7.3).

The target check lives in the tool, not in a comment (SKILL §5's
``# target-checked separately`` was the hole D-33 closes).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from apps.api.config import get_settings
from packages.contracts.errors import NotConfigured
from packages.contracts.tool import RiskLevel, Tool, ToolContext
from providers import clients
from tools.base import FunctionTool


class TelegramSendIn(BaseModel):
    chat_id: str
    text: str = Field(min_length=1, max_length=4096)


class TelegramSendOut(BaseModel):
    sent: bool
    chat_id: str


def _requires_approval(args: BaseModel, ctx: ToolContext) -> bool:
    del ctx
    allowed = get_settings().telegram_allowed_chat_id
    if not allowed:
        return True  # unset allowlist means "ask for every chat", never "allow all"
    if not isinstance(args, TelegramSendIn):
        return True
    return str(args.chat_id) != allowed


async def _send(a: TelegramSendIn, ctx: ToolContext) -> TelegramSendOut:
    del ctx
    if not get_settings().telegram_bot_token:
        raise NotConfigured("TELEGRAM_BOT_TOKEN is empty")
    await clients.telegram_send_message(a.chat_id, a.text)
    return TelegramSendOut(sent=True, chat_id=a.chat_id)


def build() -> list[Tool]:
    return [
        FunctionTool(
            name="telegram_send",
            description="Send a Telegram message from the operator's bot.",
            input_model=TelegramSendIn,
            output_model=TelegramSendOut,
            risk=RiskLevel.EXTERNAL,
            idempotent=False,
            timeout_s=15.0,
            handler=_send,
            approval=_requires_approval,
        )
    ]
