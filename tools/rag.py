"""RAG search over ``memory_chunks`` — tier 3, with an honest degradation.

Vector search needs pgvector, which the SQLite dev profile does not have, so
this falls back to keyword matching over the same chunk table and reports
``mode`` so the answer can say how it was found. Nobody should read a keyword
hit as a semantic one.
"""

from __future__ import annotations

from pydantic import BaseModel, Field
from sqlalchemy import select

from apps.api.db.models import MemoryChunk
from apps.api.db.session import session_scope
from packages.contracts.tool import RiskLevel, Tool, ToolContext
from tools.base import FunctionTool


class RagSearchIn(BaseModel):
    query: str = Field(min_length=1)
    limit: int = Field(default=5, ge=1, le=20)


class RagHit(BaseModel):
    source: str
    content: str


class RagSearchOut(BaseModel):
    hits: list[RagHit]
    mode: str
    tainted: bool = True


async def _search(a: RagSearchIn, ctx: ToolContext) -> RagSearchOut:
    needle = f"%{a.query.strip()}%"
    async with session_scope() as session:
        stmt = (
            select(MemoryChunk)
            .where(MemoryChunk.user_id == ctx.user_id, MemoryChunk.content.ilike(needle))
            .limit(a.limit)
        )
        rows = (await session.execute(stmt)).scalars().all()
    return RagSearchOut(
        hits=[RagHit(source=r.source, content=r.content[:2000]) for r in rows],
        mode="keyword",
    )


def build() -> list[Tool]:
    return [
        FunctionTool(
            name="rag_search",
            description="Search ingested notes and documents; results are untrusted.",
            input_model=RagSearchIn,
            output_model=RagSearchOut,
            risk=RiskLevel.READ,
            idempotent=True,
            timeout_s=10.0,
            taints=True,
            handler=_search,
        )
    ]
