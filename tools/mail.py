"""Gmail tools. Reads taint the turn; sending is always approval-gated.

Two rules worth stating because they are the whole point of the module:

* ``mail_send`` may only reference a draft that ``mail_draft`` actually wrote.
  The operator sees the body before approving, so an injected page cannot turn
  itself into an email with one click.
* A draft written in a tainted turn is recorded as tainted, and the approval
  summary says so. The draft is allowed (PLANBOOK §1.3-7 needs read-then-draft
  in one turn); the send is not.
"""

from __future__ import annotations

import base64
import json
import time
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from apps.api.config import get_settings
from packages.contracts.errors import NotConfigured, ToolError
from packages.contracts.tool import RiskLevel, Tool, ToolContext
from providers import clients
from tools.base import FunctionTool

DRAFTS_DIR = Path(__file__).resolve().parents[1] / "var" / "drafts"


def _require_google() -> None:
    settings = get_settings()
    if not (settings.google_client_id and settings.google_client_secret):
        raise NotConfigured("Gmail is not configured: GOOGLE_CLIENT_ID/SECRET are empty")
    if not settings.google_refresh_token:
        raise NotConfigured("Gmail is not configured: GOOGLE_REFRESH_TOKEN is empty")


class MailReadIn(BaseModel):
    message_id: str


class MailReadOut(BaseModel):
    message_id: str
    subject: str
    sender: str
    snippet: str
    tainted: bool = True


class MailSearchIn(BaseModel):
    query: str = Field(description="Gmail search query, e.g. 'is:unread newer_than:2d'")
    limit: int = Field(default=10, ge=1, le=25)


class MailHit(BaseModel):
    message_id: str
    subject: str
    sender: str
    snippet: str


class MailSearchOut(BaseModel):
    messages: list[MailHit]
    tainted: bool = True


class MailDraftIn(BaseModel):
    to: str
    subject: str
    body: str
    in_reply_to: str | None = None


class MailDraftOut(BaseModel):
    draft_id: str
    to: str
    subject: str
    body: str
    tainted: bool


class MailSendIn(BaseModel):
    draft_id: str = Field(description="Id returned by mail_draft")


class MailSendOut(BaseModel):
    sent: bool
    draft_id: str
    provider_message_id: str | None = None


def _headers(payload: dict[str, Any]) -> dict[str, str]:
    raw_headers = payload.get("payload", {})
    if not isinstance(raw_headers, dict):
        return {}
    entries = raw_headers.get("headers", [])
    if not isinstance(entries, list):
        return {}
    out: dict[str, str] = {}
    for entry in entries:
        if isinstance(entry, dict):
            name = str(entry.get("name", "")).lower()
            value = str(entry.get("value", ""))
            if name:
                out[name] = value
    return out


async def _read(a: MailReadIn, ctx: ToolContext) -> MailReadOut:
    del ctx
    _require_google()
    try:
        payload = await clients.gmail_get(f"messages/{a.message_id}", {"format": "metadata"})
    except clients.GoogleAuthError as exc:
        raise NotConfigured(str(exc)) from exc
    headers = _headers(payload)
    return MailReadOut(
        message_id=a.message_id,
        subject=headers.get("subject", ""),
        sender=headers.get("from", ""),
        snippet=str(payload.get("snippet", "")),
    )


async def _search(a: MailSearchIn, ctx: ToolContext) -> MailSearchOut:
    del ctx
    _require_google()
    try:
        listing = await clients.gmail_get("messages", {"q": a.query, "maxResults": str(a.limit)})
    except clients.GoogleAuthError as exc:
        raise NotConfigured(str(exc)) from exc
    raw = listing.get("messages")
    entries: list[object] = raw if isinstance(raw, list) else []
    ids = [str(item["id"]) for item in entries if isinstance(item, dict) and "id" in item]
    hits: list[MailHit] = []
    for message_id in ids[: a.limit]:
        try:
            payload = await clients.gmail_get(f"messages/{message_id}", {"format": "metadata"})
        except clients.GoogleAuthError:
            continue
        headers = _headers(payload)
        hits.append(
            MailHit(
                message_id=message_id,
                subject=headers.get("subject", ""),
                sender=headers.get("from", ""),
                snippet=str(payload.get("snippet", "")),
            )
        )
    return MailSearchOut(messages=hits)


async def _draft(a: MailDraftIn, ctx: ToolContext) -> MailDraftOut:
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    draft_id = f"{int(time.time() * 1000):x}-{abs(hash((a.to, a.subject))) % 0xFFFFFF:06x}"
    record = {
        "draft_id": draft_id,
        "to": a.to,
        "subject": a.subject,
        "body": a.body,
        "in_reply_to": a.in_reply_to,
        "tainted": ctx.turn_tainted,
        "conversation_id": ctx.conversation_id,
    }
    (DRAFTS_DIR / f"{draft_id}.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    return MailDraftOut(
        draft_id=draft_id, to=a.to, subject=a.subject, body=a.body, tainted=ctx.turn_tainted
    )


def load_draft(draft_id: str) -> dict[str, Any]:
    path = DRAFTS_DIR / f"{draft_id}.json"
    if not path.exists():
        raise ToolError("no such draft; create it with mail_draft first")
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


async def _send(a: MailSendIn, ctx: ToolContext) -> MailSendOut:
    del ctx
    _require_google()
    draft = load_draft(a.draft_id)
    message = EmailMessage()
    message["To"] = str(draft["to"])
    message["Subject"] = str(draft["subject"])
    message.set_content(str(draft["body"]))
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
    try:
        provider_id = await clients.gmail_send(raw)
    except clients.GoogleAuthError as exc:
        raise NotConfigured(str(exc)) from exc
    (DRAFTS_DIR / f"{a.draft_id}.json").unlink(missing_ok=True)
    return MailSendOut(sent=True, draft_id=a.draft_id, provider_message_id=provider_id or None)


def build() -> list[Tool]:
    return [
        FunctionTool(
            name="mail_read",
            description="Read one email by id; the result is untrusted.",
            input_model=MailReadIn,
            output_model=MailReadOut,
            risk=RiskLevel.READ,
            idempotent=True,
            timeout_s=15.0,
            taints=True,
            handler=_read,
        ),
        FunctionTool(
            name="mail_search",
            description="Search the mailbox; the results are untrusted.",
            input_model=MailSearchIn,
            output_model=MailSearchOut,
            risk=RiskLevel.READ,
            idempotent=True,
            timeout_s=20.0,
            taints=True,
            handler=_search,
        ),
        FunctionTool(
            name="mail_draft",
            description="Write a draft email; nothing is sent.",
            input_model=MailDraftIn,
            output_model=MailDraftOut,
            risk=RiskLevel.WRITE,
            idempotent=False,
            timeout_s=5.0,
            handler=_draft,
        ),
        FunctionTool(
            name="mail_send",
            description="Send an existing draft to its recipient.",
            input_model=MailSendIn,
            output_model=MailSendOut,
            risk=RiskLevel.EXTERNAL,
            idempotent=False,
            timeout_s=20.0,
            handler=_send,
        ),
    ]
