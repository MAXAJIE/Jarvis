"""Memory tier 2: durable facts with mandatory provenance.

Tier 3 (vector RAG) needs pgvector and is therefore unavailable on the dev
SQLite profile; ``memory_search`` does a keyword match over tier-2 facts and
says so in its output instead of pretending to be semantic (D-31).

T8 mitigation, enforced in code (P3): a fact needs a ``source_message_id`` that
actually exists, ``memory_search`` hides unconfirmed facts unless asked, and
``policy.TAINT_BLOCKED_WRITE`` stops a fact being written in a tainted turn.
"""

from __future__ import annotations

from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select

from apps.api.db.models import MemoryFact, Message
from apps.api.db.session import session_scope
from packages.contracts.errors import ToolError
from packages.contracts.tool import RiskLevel, Tool, ToolContext
from tools.base import FunctionTool


class FactOut(BaseModel):
    id: str
    subject: str
    predicate: str
    object: str
    confidence: float
    confirmed: bool
    source_message_id: str | None


class FactWriteIn(BaseModel):
    subject: str = Field(min_length=1, max_length=128)
    predicate: str = Field(min_length=1, max_length=128)
    object: str = Field(min_length=1)
    source_message_id: str = Field(description="Id of the message this fact came from")
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)


class FactWriteOut(BaseModel):
    fact: FactOut


class FactSearchIn(BaseModel):
    query: str = Field(min_length=1)
    limit: int = Field(default=10, ge=1, le=50)
    include_unconfirmed: bool = False


class FactSearchOut(BaseModel):
    facts: list[FactOut]
    mode: str = "keyword"
    note: str = "tier-3 vector search requires PostgreSQL + pgvector"
    # Unconfirmed facts are hidden (T8), but saying "nothing" while a fact waits for
    # the operator is a false statement, so the count is reported instead.
    pending: int = 0


class FactConfirmIn(BaseModel):
    fact_id: str


class FactConfirmOut(BaseModel):
    fact: FactOut | None


def _out(row: MemoryFact) -> FactOut:
    return FactOut(
        id=row.id,
        subject=row.subject,
        predicate=row.predicate,
        object=row.object,
        confidence=row.confidence,
        confirmed=row.confirmed,
        source_message_id=row.source_message_id,
    )


async def _write(a: FactWriteIn, ctx: ToolContext) -> FactWriteOut:
    async with session_scope() as session:
        source = await session.get(Message, a.source_message_id)
        if source is None:
            raise ToolError("source_message_id does not exist; a fact needs provenance")
        row = MemoryFact(
            user_id=ctx.user_id,
            subject=a.subject,
            predicate=a.predicate,
            object=a.object,
            confidence=a.confidence,
            source_message_id=a.source_message_id,
            confirmed=False,
        )
        session.add(row)
        await session.flush()
        return FactWriteOut(fact=_out(row))


async def _search(a: FactSearchIn, ctx: ToolContext) -> FactSearchOut:
    needle = f"%{a.query.strip()}%"
    async with session_scope() as session:
        stmt = select(MemoryFact).where(
            MemoryFact.user_id == ctx.user_id,
            or_(
                MemoryFact.object.ilike(needle),
                MemoryFact.subject.ilike(needle),
                MemoryFact.predicate.ilike(needle),
            ),
        )
        if not a.include_unconfirmed:
            stmt = stmt.where(MemoryFact.confirmed.is_(True))
        stmt = stmt.order_by(MemoryFact.confidence.desc()).limit(a.limit)
        rows = (await session.execute(stmt)).scalars().all()
        mode = "keyword"
        note = "tier-3 vector search requires PostgreSQL + pgvector"
        if not rows:
            # "what do you know about me" carries no keyword, so a pure match returns
            # nothing and the agent says it remembers nothing while holding facts.
            # Fall back to the newest confirmed facts, labelled as such - an empty
            # answer and a labelled recency answer are different claims.
            recent = (
                select(MemoryFact)
                .where(MemoryFact.user_id == ctx.user_id)
                .order_by(MemoryFact.created_at.desc())
                .limit(a.limit)
            )
            if not a.include_unconfirmed:
                recent = recent.where(MemoryFact.confirmed.is_(True))
            rows = (await session.execute(recent)).scalars().all()
            if rows:
                mode = "recent"
                note = "no keyword match; showing the newest stored facts"
        pending = 0
        if not a.include_unconfirmed:
            waiting = (
                select(func.count())
                .select_from(MemoryFact)
                .where(MemoryFact.user_id == ctx.user_id, MemoryFact.confirmed.is_(False))
            )
            pending = int((await session.execute(waiting)).scalar_one())
            if pending:
                note += f"; {pending} fact(s) awaiting your confirmation"
        return FactSearchOut(facts=[_out(r) for r in rows], mode=mode, note=note, pending=pending)


async def _confirm(a: FactConfirmIn, ctx: ToolContext) -> FactConfirmOut:
    async with session_scope() as session:
        row = await session.get(MemoryFact, a.fact_id)
        if row is None or row.user_id != ctx.user_id:
            return FactConfirmOut(fact=None)
        row.confirmed = True
        return FactConfirmOut(fact=_out(row))


def build() -> list[Tool]:
    return [
        FunctionTool(
            name="memory_write_fact",
            description="Record a durable fact about the operator, with the message it came from.",
            input_model=FactWriteIn,
            output_model=FactWriteOut,
            risk=RiskLevel.WRITE,
            idempotent=False,
            timeout_s=5.0,
            handler=_write,
        ),
        FunctionTool(
            name="memory_search",
            description="Look up durable facts by keyword.",
            input_model=FactSearchIn,
            output_model=FactSearchOut,
            risk=RiskLevel.READ,
            idempotent=True,
            timeout_s=5.0,
            handler=_search,
        ),
        FunctionTool(
            name="memory_fact_confirm",
            description="Mark a stored fact as confirmed by the operator.",
            input_model=FactConfirmIn,
            output_model=FactConfirmOut,
            risk=RiskLevel.WRITE,
            idempotent=True,
            timeout_s=5.0,
            handler=_confirm,
        ),
    ]
