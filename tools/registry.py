"""The single source of registered tools and of who may use which.

Two invariants are enforced at construction time, so a typo cannot ship:

1. every tool name is unique and snake_case;
2. every tool appears in at least one specialist allowlist, and every name in
   an allowlist exists. An unassigned tool is a tool nobody can call; a name
   with no tool is a silent capability hole.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from packages.contracts.errors import PolicyViolation
from packages.contracts.tool import RiskLevel, Tool
from tools import calendar, delegate, fs, mail, memory, phone, rag, sandbox, tasks, telegram, web

SNAKE = re.compile(r"^[a-z][a-z0-9_]*$")

# Tools the design names but this build does not implement. They are kept out of
# the registry entirely, so no planner is ever shown a capability that can only
# fail. A tool that raises NotConfigured every time is a lie told to the model, and
# the model then apologises to the operator for a feature that was never built.
WITHHELD: dict[str, str] = {
    "shell": "sandbox runner not implemented (needs Docker, absent here)",
    "python_run": "sandbox runner not implemented (needs Docker, absent here)",
    "browser_open": "sandbox runner not implemented (needs Docker, absent here)",
    "browser_click": "sandbox runner not implemented (needs Docker, absent here)",
    "browser_extract": "sandbox runner not implemented (needs Docker, absent here)",
    "call_place": "no TwiML / media-stream handler: a call would connect to silence",
}

SPECIALIST_TOOLS: dict[str, frozenset[str]] = {
    "supervisor": frozenset(
        {
            "delegate",
            "task_list",
            "task_get",
            "memory_search",
            "memory_write_fact",
            "memory_fact_confirm",
        }
    ),
    "executor": frozenset(
        {
            "shell",
            "python_run",
            "browser_open",
            "browser_click",
            "browser_extract",
            "fs_read",
            "fs_write",
            "fs_delete",
        }
    ),
    "researcher": frozenset({"web_fetch", "rag_search", "memory_search", "calendar_read"}),
    "scheduler": frozenset(
        {
            "task_list",
            "task_get",
            "task_create",
            "task_update",
            "task_complete",
            "task_delete",
            "remind",
            "calendar_read",
        }
    ),
    "comms": frozenset(
        {
            "telegram_send",
            "mail_read",
            "mail_search",
            "mail_draft",
            "mail_send",
            "call_place",
        }
    ),
}


class Registry:
    def __init__(self, tools: Sequence[Tool], withheld: dict[str, str] | None = None) -> None:
        self.withheld: dict[str, str] = dict(withheld or {})
        self._by_name: dict[str, Tool] = {}
        for tool in tools:
            if not SNAKE.match(tool.name):
                raise PolicyViolation(f"tool name {tool.name!r} is not snake_case")
            if tool.name in self._by_name:
                raise PolicyViolation(f"duplicate tool name {tool.name!r}")
            self._by_name[tool.name] = tool
        self._validate_allowlists()

    def _validate_allowlists(self) -> None:
        assigned: set[str] = set()
        for specialist, names in SPECIALIST_TOOLS.items():
            # A name may be allowlisted yet absent only when it is declared withheld;
            # a typo still fails loudly.
            missing = names - set(self._by_name) - set(self.withheld)
            if missing:
                raise PolicyViolation(f"{specialist} lists unknown tools: {sorted(missing)}")
            assigned |= names
        unassigned = set(self._by_name) - assigned
        if unassigned:
            raise PolicyViolation(f"registered but unreachable: {sorted(unassigned)}")

    def all(self) -> list[Tool]:
        return list(self._by_name.values())

    def get(self, name: str) -> Tool:
        tool = self._by_name.get(name)
        if tool is None:
            raise PolicyViolation(f"unknown tool {name!r}")
        return tool

    def names(self) -> list[str]:
        return sorted(self._by_name)

    def for_specialist(self, specialist: str) -> list[Tool]:
        names = SPECIALIST_TOOLS.get(specialist)
        if names is None:
            raise PolicyViolation(f"unknown specialist {specialist!r}")
        return [self._by_name[name] for name in sorted(names & set(self._by_name))]

    def by_risk(self, risk: RiskLevel) -> list[Tool]:
        return [t for t in self.all() if t.risk is risk]


def build_registry() -> Registry:
    """Every tool the code implements, minus the ones this build cannot run.

    Filtering here rather than inside each module keeps one list of what is withheld
    and why, which the System panel shows instead of silently pretending the tools
    exist.
    """
    tools: list[Tool] = []
    for module in (
        tasks,
        memory,
        web,
        mail,
        telegram,
        phone,
        sandbox,
        delegate,
        fs,
        rag,
        calendar,
    ):
        tools.extend(module.build())
    registered = [tool for tool in tools if tool.name not in WITHHELD]
    return Registry(registered, WITHHELD)
