"""The Tool contract (SKILL.md §4, amended by DECISIONS D-33).

Two deliberate changes from the original sketch, both approved in the build
review and logged as D-33:

* ``requires_approval(args, ctx)`` — the decision needs the arguments, because
  PLANBOOK §7.3 says "``shell`` with a non-allowlisted binary -> approval, and
  show the full command". A signature of ``(ctx)`` cannot express that.
* ``taints: bool`` — whether this tool's output originates outside our system.
  Kept on the tool so the taint set has one source of truth instead of a name
  list in ``policy.py`` that drifts away from the registry.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field


class RiskLevel(StrEnum):
    READ = "read"  # no side effects anywhere
    WRITE = "write"  # reversible state change inside our system
    EXTERNAL = "external"  # leaves our system: email, call, message
    IRREVERSIBLE = "irreversible"  # delete, overwrite, spend


class Lang(StrEnum):
    EN = "en"
    ZH_TW = "zh-TW"


class Transport(StrEnum):
    WEB = "web"
    VOICE = "voice"
    TELEGRAM = "telegram"
    PSTN = "pstn"


class ToolContext(BaseModel):
    """Everything a tool may know about the call. Frozen: tools cannot mutate it."""

    model_config = ConfigDict(frozen=True)

    user_id: str
    conversation_id: str
    thread_id: str
    lang: Lang = Lang.EN
    transport: Transport = Transport.WEB
    turn_tainted: bool = False
    # Wall budget for this call. Voice turns use 3000 ms (PLANBOOK §10.2 p95).
    deadline_ms: int = Field(default=8000, ge=1)


@runtime_checkable
class Tool(Protocol):
    name: str
    description: str
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    risk: RiskLevel
    idempotent: bool
    timeout_s: float
    taints: bool

    def requires_approval(self, args: BaseModel, ctx: ToolContext) -> bool: ...

    async def run(self, args: BaseModel, ctx: ToolContext) -> BaseModel: ...


def coerce[ModelT: BaseModel](model: type[ModelT], args: BaseModel) -> ModelT:
    """Narrow a validated BaseModel to the tool's declared input model.

    The registry validates against ``input_model`` before calling ``run``, so
    this is a type-narrowing step, not a second validation layer. If it ever
    fails, that is a programming error, and it raises rather than guessing.
    """
    if isinstance(args, model):
        return args
    return model.model_validate(args.model_dump())
