"""The tool implementation used by every capability in this repository.

One class, one reason: a tool is data (name, risk, models) plus one coroutine.
Subclassing 28 near-identical classes would add no safety, only boilerplate to
mis-edit. Everything the policy engine needs lives on the instance.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel

from packages.contracts.tool import RiskLevel, ToolContext, coerce


class FunctionTool[InT: BaseModel, OutT: BaseModel]:
    """A registered capability.

    ``approval`` is optional. When it is None the risk class decides:
    EXTERNAL and IRREVERSIBLE always require a human, READ and WRITE never do.
    """

    def __init__(
        self,
        *,
        name: str,
        description: str,
        input_model: type[InT],
        output_model: type[OutT],
        risk: RiskLevel,
        idempotent: bool,
        timeout_s: float,
        handler: Callable[[Any, ToolContext], Awaitable[Any]],
        taints: bool = False,
        approval: Callable[[BaseModel, ToolContext], bool] | None = None,
    ) -> None:
        self.name = name
        self.description = description
        self.input_model = input_model
        self.output_model = output_model
        self.risk = risk
        self.idempotent = idempotent
        self.timeout_s = timeout_s
        self.taints = taints
        self._handler = handler
        self._approval = approval

    def requires_approval(self, args: BaseModel, ctx: ToolContext) -> bool:
        if self._approval is not None:
            return self._approval(args, ctx)
        return self.risk in (RiskLevel.EXTERNAL, RiskLevel.IRREVERSIBLE)

    async def run(self, args: BaseModel, ctx: ToolContext) -> BaseModel:
        # ``handler`` is deliberately loosely typed: each tool narrows its own
        # argument model with ``coerce``, which is where the type is reasserted.
        result: BaseModel = await self._handler(coerce(self.input_model, args), ctx)
        return result

    def __repr__(self) -> str:
        return f"<Tool {self.name} risk={self.risk} taints={self.taints}>"
