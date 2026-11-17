"""What happens to the money when the provider states the price itself.

The unit test covers the wire; this covers the wiring: a cost the provider reports
must reach the ledger unchanged, and a table guess must not overwrite it.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select

from agent.runtime import Runtime, default_context
from apps.api.db import session as db_session
from apps.api.db.models import CostLedgerRow
from providers.llm import ChatMessage, LLMReply, ToolSpec


class ReportedCostClient:
    """Answers immediately and claims a price, the way OpenRouter does."""

    provider = "openrouter"
    model = "openai/gpt-4o-mini"

    def __init__(self, cost_usd: float | None) -> None:
        self.cost_usd = cost_usd

    async def chat(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[ToolSpec],
        *,
        deadline_ms: int,
    ) -> LLMReply:
        del messages, tools, deadline_ms
        return LLMReply(content="hello", tokens_in=120, tokens_out=30, cost_usd=self.cost_usd)


async def _run_one_turn(client: ReportedCostClient, ids: dict[str, str]) -> None:
    runtime = Runtime(client=client)
    await runtime.start()
    try:
        ctx = default_context(
            user_id=ids["user_id"],
            conversation_id=ids["conversation_id"],
            thread_id=f"cost-{datetime.now(UTC).timestamp()}",
            lang="en",
            transport="web",
        )
        await runtime.turn(ctx, "say hello")
    finally:
        await runtime.stop()


async def _last_llm_row() -> CostLedgerRow:
    async with db_session.session_scope() as session:
        stmt = (
            select(CostLedgerRow)
            .where(CostLedgerRow.kind == "llm")
            .order_by(CostLedgerRow.id.desc())
            .limit(1)
        )
        return (await session.execute(stmt)).scalar_one()


@pytest.mark.anyio
async def test_a_provider_reported_price_lands_in_the_ledger_verbatim(
    db: dict[str, str],
) -> None:
    await _run_one_turn(ReportedCostClient(cost_usd=0.000042), db)
    row = await _last_llm_row()
    assert row.provider == "openrouter"
    assert row.model == "openai/gpt-4o-mini"
    assert str(row.usd) == "0.000042"
    assert row.meta == {"price_source": "provider"}
    assert row.units == 150


@pytest.mark.anyio
async def test_a_table_price_is_marked_as_a_guess_not_as_a_measured_cost(
    db: dict[str, str],
) -> None:
    # No reported cost: the ledger must say where the number came from, because
    # a guessed price and a billed price look identical once they are a row.
    await _run_one_turn(ReportedCostClient(cost_usd=None), db)
    row = await _last_llm_row()
    meta: dict[str, Any] = dict(row.meta or {})
    assert meta == {"price_source": "table"}
    # gpt-4o-mini table price: 120 in @0.15/M + 30 out @0.60/M = 0.000036
    assert row.usd == Decimal("0.000036")
