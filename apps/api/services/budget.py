"""Budget and cost accounting (D-21, D-35).

The ceiling is on *total* spend. Fixed monthly costs the app cannot charge --
VPS, domain, the Twilio number -- are recorded in ``infra_costs`` and treated as
a floor, so a missing or half-written ledger can never make the ceiling look
more generous than it is.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select

from agent.policy import BudgetState
from apps.api.config import get_settings
from apps.api.db.models import CostLedgerRow, InfraCost, Task, ToolRun
from apps.api.db.session import session_scope


def month_start(now: datetime | None = None) -> datetime:
    moment = now or datetime.now(UTC)
    return moment.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


async def budget_state() -> BudgetState:
    settings = get_settings()
    start = month_start()
    async with session_scope() as session:
        ledger = (
            await session.execute(
                select(func.coalesce(func.sum(CostLedgerRow.usd), 0)).where(
                    CostLedgerRow.ts >= start
                )
            )
        ).scalar_one()
        infra = (
            await session.execute(
                select(func.coalesce(func.sum(InfraCost.usd), 0)).where(
                    InfraCost.period_start == start.date()
                )
            )
        ).scalar_one()
    usage = Decimal(str(ledger))
    fixed = max(Decimal(str(infra)), settings.fixed_monthly_usd)
    return BudgetState(
        usage_usd=usage,
        fixed_usd=fixed,
        ceiling_usd=settings.monthly_budget_usd,
        alarm_usd=settings.budget_alarm_usd,
    )


async def record_cost(
    *,
    kind: str,
    provider: str,
    units: Decimal,
    unit_name: str,
    unit_price_usd: Decimal,
    usd: Decimal,
    model: str | None = None,
    conversation_id: str | None = None,
    call_id: str | None = None,
    meta: dict[str, Any] | None = None,
) -> None:
    async with session_scope() as session:
        session.add(
            CostLedgerRow(
                kind=kind,
                provider=provider,
                model=model,
                units=units,
                unit_name=unit_name,
                unit_price_usd=unit_price_usd,
                usd=usd,
                conversation_id=conversation_id,
                call_id=call_id,
                meta=meta,
            )
        )


async def record_llm_cost(
    *,
    provider: str,
    model: str,
    tokens_in: int,
    tokens_out: int,
    conversation_id: str | None,
    price_per_mtok: tuple[float, float] | None,
) -> Decimal:
    """One row per model call, including a zero-cost stub call (P4).

    A row at 0 USD is not padding: it is what makes "every LLM call has a cost
    row" checkable in the stub profile instead of vacuously true.
    """
    if price_per_mtok is None:
        price_in = price_out = Decimal(0)
        meta: dict[str, Any] = {"unverified_price": True}
    else:
        price_in = Decimal(str(price_per_mtok[0]))
        price_out = Decimal(str(price_per_mtok[1]))
        meta = {}
    usd = (Decimal(tokens_in) * price_in + Decimal(tokens_out) * price_out) / Decimal(1_000_000)
    await record_cost(
        kind="llm",
        provider=provider,
        model=model,
        units=Decimal(tokens_in + tokens_out),
        unit_name="tokens",
        unit_price_usd=price_in / Decimal(1_000_000),
        usd=usd.quantize(Decimal("0.000001")),
        conversation_id=conversation_id,
        meta=meta,
    )
    return usd


async def record_infra_cost(period: date, line: str, usd: Decimal, note: str | None = None) -> None:
    """Idempotent by primary key: re-running the monthly job cannot double-charge."""
    async with session_scope() as session:
        existing = await session.get(InfraCost, {"period_start": period, "line": line})
        if existing is None:
            session.add(InfraCost(period_start=period, line=line, usd=usd, note=note))
        else:
            existing.usd = usd
            existing.note = note


async def dashboard() -> dict[str, Any]:
    """Five metrics plus spend, all derived from SQL (D-27). Nothing hardcoded."""
    start = month_start()
    state = await budget_state()
    async with session_scope() as session:
        tasks_completed = (
            await session.execute(
                select(func.count(Task.id)).where(Task.status == "done", Task.completed_at >= start)
            )
        ).scalar_one()
        failures = (
            await session.execute(
                select(func.count(ToolRun.id)).where(ToolRun.ok.is_(False), ToolRun.ts >= start)
            )
        ).scalar_one()
        llm_calls = (
            await session.execute(
                select(func.count(CostLedgerRow.id)).where(
                    CostLedgerRow.kind == "llm", CostLedgerRow.ts >= start
                )
            )
        ).scalar_one()
        tokens = (
            await session.execute(
                select(func.coalesce(func.sum(CostLedgerRow.units), 0)).where(
                    CostLedgerRow.kind == "llm", CostLedgerRow.ts >= start
                )
            )
        ).scalar_one()
        voice_minutes = (
            await session.execute(
                select(func.coalesce(func.sum(CostLedgerRow.units), 0)).where(
                    CostLedgerRow.kind.in_(["stt", "tts", "telephony"]),
                    CostLedgerRow.unit_name == "minutes",
                    CostLedgerRow.ts >= start,
                )
            )
        ).scalar_one()
    return {
        "tasks_completed": int(tasks_completed),
        "failures": int(failures),
        "api_calls": int(llm_calls),
        "tokens_used": int(tokens),
        "voice_minutes": float(voice_minutes),
        "spend_usd": float(state.total_usd),
        "usage_usd": float(state.usage_usd),
        "fixed_usd": float(state.fixed_usd),
        "ceiling_usd": float(state.ceiling_usd),
        "remaining_usd": float(state.usage_remaining_usd),
        "alarm": state.alarm,
        "period_start": start.date().isoformat(),
    }
