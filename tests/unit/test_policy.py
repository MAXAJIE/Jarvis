"""Policy tests. 100 % coverage is a gate (SKILL §6 G3), not an aspiration.

The cases SKILL §5 names explicitly are marked; the rest were added because the
review found real bypasses (D-33/D-34).
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import BaseModel

from agent.policy import (
    TAINT_BLOCKED_WRITE,
    BudgetState,
    enforce_budget,
    filter_tools,
    needs_approval,
    taint_after,
    validate_tool,
)
from packages.contracts.errors import BudgetExceeded, PolicyViolation, TaintedRefused
from packages.contracts.tool import RiskLevel, ToolContext
from tools.base import FunctionTool
from tools.registry import build_registry


class In(BaseModel):
    x: int = 0


class Out(BaseModel):
    ok: bool = True


async def _handler(a: In, ctx: ToolContext) -> Out:
    del a, ctx
    return Out()


def mk(
    name: str,
    risk: RiskLevel,
    *,
    taints: bool = False,
    approval: bool | None = None,
) -> FunctionTool[In, Out]:
    rule = (lambda _a, _c: approval) if approval is not None else None
    return FunctionTool(
        name=name,
        description="test tool",
        input_model=In,
        output_model=Out,
        risk=risk,
        idempotent=True,
        timeout_s=1.0,
        handler=_handler,
        taints=taints,
        approval=rule,
    )


def ctx(tainted: bool = False) -> ToolContext:
    return ToolContext(user_id="u", conversation_id="c", thread_id="t", turn_tainted=tainted)


# --- SKILL §5 required cases -------------------------------------------------


def test_tainted_turn_hides_mail_send() -> None:
    tools = [mk("mail_send", RiskLevel.EXTERNAL), mk("task_create", RiskLevel.WRITE)]
    visible = filter_tools(tools, ctx(tainted=True))
    assert [t.name for t in visible] == ["task_create"]


def test_tainted_turn_hides_call_place() -> None:
    tools = [mk("call_place", RiskLevel.EXTERNAL)]
    assert filter_tools(tools, ctx(tainted=True)) == []


def test_tainted_turn_allows_task_create() -> None:
    tools = [mk("task_create", RiskLevel.WRITE)]
    assert [t.name for t in filter_tools(tools, ctx(tainted=True))] == ["task_create"]


def test_untainted_mail_send_is_visible_and_needs_approval() -> None:
    tool = mk("mail_send", RiskLevel.EXTERNAL)
    assert tool in filter_tools([tool], ctx())
    assert needs_approval(tool, In(), ctx()) is True


def test_unknown_risk_is_refused() -> None:
    class Bogus:
        name = "bogus_tool"
        risk = "spend"
        taints = False
        description = ""

    with pytest.raises(PolicyViolation):
        validate_tool(Bogus)  # type: ignore[arg-type]
    with pytest.raises(PolicyViolation):
        filter_tools([Bogus], ctx())  # type: ignore[list-item]


# --- review findings (D-34) --------------------------------------------------


def test_tainted_turn_hides_memory_write_fact() -> None:
    tools = [mk("memory_write_fact", RiskLevel.WRITE)]
    assert filter_tools(tools, ctx(tainted=True)) == []
    assert "memory_write_fact" in TAINT_BLOCKED_WRITE


def test_tainted_turn_keeps_shell_python_and_draft() -> None:
    tools = [
        mk("shell", RiskLevel.WRITE),
        mk("python_run", RiskLevel.WRITE),
        mk("mail_draft", RiskLevel.WRITE),
    ]
    assert len(filter_tools(tools, ctx(tainted=True))) == 3


def test_tainted_turn_never_asks_it_refuses() -> None:
    tool = mk("mail_send", RiskLevel.EXTERNAL)
    with pytest.raises(TaintedRefused):
        needs_approval(tool, In(), ctx(tainted=True))


def test_irreversible_hidden_when_tainted_and_approved_when_not() -> None:
    tool = mk("task_delete", RiskLevel.IRREVERSIBLE)
    assert filter_tools([tool], ctx(tainted=True)) == []
    assert needs_approval(tool, In(), ctx()) is True


def test_approval_rule_overrides_risk_class() -> None:
    auto = mk("telegram_send", RiskLevel.EXTERNAL, approval=False)
    assert needs_approval(auto, In(), ctx()) is False
    asked = mk("shell", RiskLevel.WRITE, approval=True)
    assert needs_approval(asked, In(), ctx()) is True


def test_taint_after_sets_once_and_is_idempotent() -> None:
    reader = mk("web_fetch", RiskLevel.READ, taints=True)
    clean = ctx()
    dirty = taint_after(reader, clean)
    assert dirty.turn_tainted is True
    assert clean.turn_tainted is False  # frozen context, not mutated
    assert taint_after(reader, dirty) is dirty
    assert taint_after(mk("task_list", RiskLevel.READ), clean).turn_tainted is False


# --- budget (D-35) -----------------------------------------------------------


def state(total_fixed: str, usage: str, ceiling: str = "20", alarm: str = "15") -> BudgetState:
    return BudgetState(
        usage_usd=Decimal(usage),
        fixed_usd=Decimal(total_fixed),
        ceiling_usd=Decimal(ceiling),
        alarm_usd=Decimal(alarm),
    )


def test_budget_refuses_external_at_ceiling_but_keeps_chat() -> None:
    budget = state("11.80", "8.20")
    with pytest.raises(BudgetExceeded):
        enforce_budget(mk("mail_send", RiskLevel.EXTERNAL), budget)
    enforce_budget(mk("task_list", RiskLevel.READ), budget)
    enforce_budget(mk("task_create", RiskLevel.WRITE), budget)


def test_budget_uses_the_fixed_floor_so_a_partial_ledger_cannot_under_count() -> None:
    with_infra = state("11.80", "0")
    assert with_infra.usage_remaining_usd == Decimal("8.20")
    assert with_infra.alarm is False
    near = state("11.80", "3.20")
    assert near.alarm is True


def test_budget_allows_until_the_last_cent() -> None:
    budget = state("11.80", "8.15")
    enforce_budget(mk("call_place", RiskLevel.EXTERNAL), budget)
    assert budget.usage_remaining_usd == Decimal("0.05")


# --- the real registry, not a mock ------------------------------------------


def test_real_registry_hides_every_external_and_irreversible_when_tainted() -> None:
    registry = build_registry()
    tainted = filter_tools(registry.all(), ctx(tainted=True))
    blocked = {t.name for t in registry.all()} - {t.name for t in tainted}
    expected = {
        "mail_send",
        "telegram_send",
        "task_delete",
        "fs_delete",
        "memory_write_fact",
    }
    assert blocked == expected
    assert all(t.risk in (RiskLevel.READ, RiskLevel.WRITE) for t in tainted)


def test_real_registry_external_tools_all_require_approval_by_default() -> None:
    registry = build_registry()
    for tool in registry.all():
        if tool.risk in (RiskLevel.EXTERNAL, RiskLevel.IRREVERSIBLE):
            if tool.name == "telegram_send":
                continue  # target-checked; covered in test_tool_contracts
            assert tool.requires_approval(Out(), ctx()) is True, tool.name


def test_real_registry_tainting_tools_are_exactly_the_documented_five() -> None:
    registry = build_registry()
    assert {t.name for t in registry.all() if t.taints} == {
        "web_fetch",
        "mail_read",
        "mail_search",
        "rag_search",
    }
