"""Policy engine. The only place that decides what the model may see and do.

Two functions do the work:

``filter_tools`` runs *before* the model chooses a tool. A tool the model must
not use is never in its list, so no prompt can talk it into trying.
``needs_approval`` runs per call, with the arguments, because approval depends
on arguments (PLANBOOK §7.3: a non-allowlisted shell binary is approved, an
allowlisted one is not).

Both rules are code. Nothing here reads a prompt file.

Decisions applied here: D-19 (taint), D-20 + D-34 (approval table),
D-35 (budget ceiling is total spend, fixed costs included).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from pydantic import BaseModel

from packages.contracts.errors import BudgetExceeded, PolicyViolation, TaintedRefused
from packages.contracts.tool import RiskLevel, Tool, ToolContext

# WRITE tools that may not run in a turn poisoned by outside content (D-34).
# Everything else that is WRITE stays available on purpose: C3's
# "scrape -> write a file" and PLANBOOK §1.3-8 need shell/python_run after a
# tainted fetch, and mail_draft after a tainted mail_read is the intended
# operator flow. Durable memory is different: a poisoned fact outlives the turn
# and is re-read later, when nothing is tainted any more. So this one is banned.
TAINT_BLOCKED_WRITE: frozenset[str] = frozenset({"memory_write_fact"})

EXTERNAL_EFFECT: frozenset[RiskLevel] = frozenset({RiskLevel.EXTERNAL, RiskLevel.IRREVERSIBLE})
_KNOWN_RISK = frozenset(member.value for member in RiskLevel)


def validate_tool(tool: Tool) -> None:
    """Fail closed on a tool whose risk is not one of the four known values."""
    risk = tool.risk
    value = risk.value if isinstance(risk, RiskLevel) else str(risk)
    if value not in _KNOWN_RISK:
        raise PolicyViolation(f"tool {tool.name!r} has unknown risk {value!r}")


def filter_tools(tools: Sequence[Tool], ctx: ToolContext) -> list[Tool]:
    """The tool list handed to the model. Untainted turns see everything."""
    visible: list[Tool] = []
    for tool in tools:
        validate_tool(tool)
        if not ctx.turn_tainted:
            visible.append(tool)
            continue
        if tool.risk in EXTERNAL_EFFECT:
            continue
        if tool.risk is RiskLevel.WRITE and tool.name in TAINT_BLOCKED_WRITE:
            continue
        visible.append(tool)
    return visible


def needs_approval(tool: Tool, args: BaseModel, ctx: ToolContext) -> bool:
    """Single authority: the tool's own rule. No second risk table here.

    A tainted turn may not reach an EXTERNAL/IRREVERSIBLE tool at all; if one
    somehow does (registry drift, a hand-built call), refuse rather than ask.
    """
    validate_tool(tool)
    if ctx.turn_tainted and tool.risk in EXTERNAL_EFFECT:
        raise TaintedRefused(f"{tool.name} is not available in a tainted turn")
    return tool.requires_approval(args, ctx)


def taint_after(tool: Tool, ctx: ToolContext) -> ToolContext:
    """Return the context for the rest of this turn."""
    if ctx.turn_tainted or not tool.taints:
        return ctx
    return ctx.model_copy(update={"turn_tainted": True})


@dataclass(frozen=True)
class BudgetState:
    """Money already committed this calendar month.

    ``fixed`` is a floor, not a fallback: if the infra rows are missing or only
    partly recorded, the guard still reserves the documented fixed cost, so a
    half-written ledger cannot make the ceiling look more generous than it is.
    """

    usage_usd: Decimal
    fixed_usd: Decimal
    ceiling_usd: Decimal
    alarm_usd: Decimal

    @property
    def total_usd(self) -> Decimal:
        return self.usage_usd + self.fixed_usd

    @property
    def usage_remaining_usd(self) -> Decimal:
        return max(Decimal(0), self.ceiling_usd - self.total_usd)

    @property
    def alarm(self) -> bool:
        return self.total_usd >= self.alarm_usd


def enforce_budget(tool: Tool, state: BudgetState) -> None:
    """Refuse spend-capable tools at the ceiling. Read and write keep working."""
    if tool.risk not in EXTERNAL_EFFECT:
        return
    if state.total_usd >= state.ceiling_usd:
        raise BudgetExceeded(
            f"monthly ceiling reached: {state.total_usd} of {state.ceiling_usd} USD committed"
        )
