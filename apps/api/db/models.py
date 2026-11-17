"""SQLAlchemy 2.0 models for PLANBOOK §3.3, plus ``infra_costs`` (D-35).

Portability notes, because dev runs on SQLite and prod runs on PostgreSQL 16:

* UUID primary keys are ``String(36)`` with a Python-side default. ``gen_random_uuid()``
  is PostgreSQL-only and would make the dev database unrunnable.
* ``JSON`` maps to ``jsonb`` on PostgreSQL via ``with_variant``.
* ``memory_chunks.embedding`` is stored as JSON here. The ``vector(1536)`` column and
  its HNSW index are PostgreSQL-only and live in migration 0002, which no-ops on
  SQLite. RAG tier 3 is therefore unverifiable in the dev profile and is reported
  as "unverified", never as passing (D-31).
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

JSONType = JSON().with_variant(JSONB(), "postgresql")
BigIntPK = BigInteger().with_variant(Integer, "sqlite")


def _uuid() -> str:
    return str(uuid4())


def _now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), default="")
    totp_secret: Mapped[str] = mapped_column(String(64), default="")
    lang_default: Mapped[str] = mapped_column(String(8), default="en")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    transport: Mapped[str] = mapped_column(String(16), default="web")
    lang: Mapped[str] = mapped_column(String(8), default="en")
    mode: Mapped[str] = mapped_column(String(8), default="text")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text, default="")
    tainted: Mapped[bool] = mapped_column(Boolean, default=False)
    tokens_in: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_out: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (Index("ix_tasks_user_status_due", "user_id", "status", "due_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(Text)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="open")
    priority: Mapped[int] = mapped_column(SmallInteger, default=3)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    parent_id: Mapped[str | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), nullable=True
    )
    source: Mapped[str] = mapped_column(String(16), default="user")
    recurrence: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TaskEvent(Base):
    __tablename__ = "task_events"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"))
    event: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class MemoryFact(Base):
    __tablename__ = "memory_facts"
    __table_args__ = (
        UniqueConstraint("user_id", "subject", "predicate", "object", name="ux_memory_fact"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    subject: Mapped[str] = mapped_column(String(128))
    predicate: Mapped[str] = mapped_column(String(128))
    object: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(default=0.8)
    source_message_id: Mapped[str | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"), nullable=True
    )
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class MemoryChunk(Base):
    __tablename__ = "memory_chunks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    source: Mapped[str] = mapped_column(String(255))
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float] | None] = mapped_column(JSONType, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class PhoneLine(Base):
    __tablename__ = "phone_lines"
    __table_args__ = (UniqueConstraint("user_id", "e164", name="ux_phone_line"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    e164: Mapped[str] = mapped_column(String(20))
    mode: Mapped[str] = mapped_column(String(24))
    twilio_sid: Mapped[str | None] = mapped_column(String(64), nullable=True)
    capability_voice_in: Mapped[bool] = mapped_column(Boolean, default=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    monthly_cost_usd: Mapped[Decimal] = mapped_column(Numeric(8, 4), default=Decimal(0))
    status: Mapped[str] = mapped_column(String(16), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Call(Base):
    __tablename__ = "calls"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    phone_line_id: Mapped[str] = mapped_column(ForeignKey("phone_lines.id"))
    direction: Mapped[str] = mapped_column(String(8))
    remote_e164: Mapped[str] = mapped_column(String(20))
    twilio_call_sid: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="queued")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_s: Mapped[int | None] = mapped_column(Integer, nullable=True)
    transcript: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONType, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    recording_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(10, 4), default=Decimal(0))


class CostLedgerRow(Base):
    """One row per billable unit, including failures, which still bill (P4).

    ``kind`` excludes 'infra' on purpose: fixed monthly costs live in
    ``infra_costs`` so there is exactly one place to record them and no way to
    count the same dollar twice (D-35).
    """

    __tablename__ = "cost_ledger"
    __table_args__ = (
        CheckConstraint(
            "kind in ('llm','stt','tts','telephony','other')", name="ck_cost_ledger_kind"
        ),
        Index("ix_cost_ledger_ts", "ts"),
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    kind: Mapped[str] = mapped_column(String(16))
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    units: Mapped[Decimal] = mapped_column(Numeric(12, 4))
    unit_name: Mapped[str] = mapped_column(String(16))
    unit_price_usd: Mapped[Decimal] = mapped_column(Numeric(12, 8))
    usd: Mapped[Decimal] = mapped_column(Numeric(12, 6))
    conversation_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    call_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    meta: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)


class InfraCost(Base):
    """Fixed monthly costs the app cannot charge, only record (VPS, domain, number)."""

    __tablename__ = "infra_costs"

    period_start: Mapped[date] = mapped_column(Date, primary_key=True)
    line: Mapped[str] = mapped_column(String(32), primary_key=True)
    usd: Mapped[Decimal] = mapped_column(Numeric(12, 6))
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Approval(Base):
    __tablename__ = "approvals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    thread_id: Mapped[str] = mapped_column(String(64))
    tool_name: Mapped[str] = mapped_column(String(64))
    args: Mapped[dict[str, Any]] = mapped_column(JSONType)
    risk: Mapped[str] = mapped_column(String(16))
    decision: Mapped[str | None] = mapped_column(String(16), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ToolRun(Base):
    __tablename__ = "tool_runs"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    tool_name: Mapped[str] = mapped_column(String(64))
    args: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    ok: Mapped[bool] = mapped_column(Boolean)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    conversation_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class VoiceLatency(Base):
    __tablename__ = "voice_latency"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    lang: Mapped[str] = mapped_column(String(8))
    capture_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    network_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stt_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    llm_first_token_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    llm_total_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tts_first_byte_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    playback_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
