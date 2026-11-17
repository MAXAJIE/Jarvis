"""Routing: which specialist gets a turn, and therefore which tools exist for it.

Routing is the quietest failure mode in the system. A turn sent to the wrong
specialist does not error - it answers, fluently, with a tool list that cannot do
what was asked. Two live examples: "remember that I live in KL" once went to the
scheduler (no memory tools, D-45), and "remind me to call mum at 9" went to comms
(no `remind`, so the reminder silently never existed).
"""

from __future__ import annotations

import pytest

from agent.router import SPECIALISTS, pick_model, route_specialist
from tools.registry import build_registry


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # A reminder that contains another verb is still a reminder.
        ("remind me to call mum at 9", "scheduler"),
        ("remind me to email the landlord tomorrow", "scheduler"),
        ("set a reminder for the dentist", "scheduler"),
        # ... while a bare comms request stays comms.
        ("call mum", "comms"),
        ("email the landlord", "comms"),
        ("read my unread telegram messages", "comms"),
        # Memory is a supervisor intent even when it mentions a schedule-adjacent word.
        ("remember that I live in Kuala Lumpur", "supervisor"),
        ("what do you remember about my sister", "supervisor"),
        # Plain scheduling and execution.
        ("plan my week", "scheduler"),
        ("create a task to buy milk", "scheduler"),
        ("run the script in tools/", "executor"),
        ("fetch that page and summarise it", "researcher"),
    ],
)
def test_route_specialist(text: str, expected: str) -> None:
    assert route_specialist(text) == expected


def test_every_route_lands_on_a_real_specialist() -> None:
    for text in ("", "hello", "?!?", "delete task 123", "wipe everything"):
        assert route_specialist(text) in SPECIALISTS


def test_the_reminder_route_can_actually_remind() -> None:
    """The route and the tool list have to agree, or the fix above is cosmetic."""
    registry = build_registry()
    assert "remind" in {
        tool.name for tool in registry.for_specialist(route_specialist("remind me at 9"))
    }
    assert "memory_write_fact" in {
        tool.name
        for tool in registry.for_specialist(route_specialist("remember that I live in KL"))
    }


def test_voice_turns_use_the_cheap_model() -> None:
    assert pick_model("voice", strong="big", cheap="small") == "small"
    assert pick_model("tools", strong="big", cheap="small") == "big"
