"""``delegate``: the supervisor's only way to reach a specialist.

Before D-33 this was a bare ``tool_runs(tool_name='delegate:<specialist>')``
row written by the graph, which meant a capability the model could trigger was
not a registered Tool, had no RiskLevel, and could not be filtered by the taint
rule. It is a Tool now, it shows up in ``tool_runs`` with a snake_case name, and
the specialist it calls is bound by the runtime (no import cycle).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Literal

from pydantic import BaseModel, Field

from packages.contracts.errors import NotConfigured
from packages.contracts.tool import RiskLevel, Tool, ToolContext
from tools.base import FunctionTool

Specialist = Literal["executor", "researcher", "scheduler", "comms"]

Runner = Callable[[Specialist, str, ToolContext], Awaitable[str]]

_runner: Runner | None = None


def bind_runner(runner: Runner | None) -> None:
    """Called once by the agent runtime at startup."""
    global _runner
    _runner = runner


class DelegateIn(BaseModel):
    specialist: Specialist
    instruction: str = Field(min_length=1)


class DelegateOut(BaseModel):
    specialist: str
    answer: str


async def _delegate(a: DelegateIn, ctx: ToolContext) -> DelegateOut:
    if _runner is None:
        raise NotConfigured("delegation is not wired")
    answer = await _runner(a.specialist, a.instruction, ctx)
    return DelegateOut(specialist=a.specialist, answer=answer)


def build() -> list[Tool]:
    return [
        FunctionTool(
            name="delegate",
            description="Hand a sub-task to one specialist and get its answer.",
            input_model=DelegateIn,
            output_model=DelegateOut,
            risk=RiskLevel.READ,
            idempotent=False,
            timeout_s=120.0,
            handler=_delegate,
        )
    ]
