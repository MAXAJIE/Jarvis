"""Routing and model tier selection.

Routing is deterministic keyword matching, not a model call. At one user and one
tool set, an LLM router costs tokens and introduces a failure mode ("it sent my
calendar question to comms") without buying accuracy. D-06's kill gate compares
topologies later; this keyword router is the baseline both arms can use.
"""

from __future__ import annotations

import re
from typing import Literal

SPECIALISTS: tuple[str, ...] = ("supervisor", "executor", "researcher", "scheduler", "comms")

ModelKind = Literal["route", "tools", "voice"]

COMMS = re.compile(r"\b(call|phone|dial|email|mail|inbox|unread|reply|telegram|message)\b", re.I)
SCHEDULE = re.compile(r"\b(task|todo|to-do|plan|remind|calendar|schedule|week|today)\b", re.I)
RESEARCH = re.compile(r"\b(fetch|read|url|http|web|page|research|search|note|document)\b", re.I)
EXECUTE = re.compile(r"\b(run|shell|python|script|browser|scrape|file)\b", re.I)
CALL_NUMBER = re.compile(r"\+[1-9]\d{7,14}")
REMIND = re.compile(r"\b(remind|reminder)\b", re.I)

# Supervisor owns memory writes and delegation. Without this branch the router never
# returned "supervisor", so memory_write_fact / memory_fact_confirm / delegate sat in
# a live allowlist that no turn could reach: the agent could not remember anything and
# the Memory panel would stay at 0 facts forever (D-45).
SUPERVISE = re.compile(
    r"(\bremember\s+(that|this|i|my)\b"
    r"|\bmemorise\b|\bmemorize\b"
    r"|\bnote\s+that\b|\bkeep\s+in\s+mind\b"
    r"|\bforget\s+(that|my)\b"
    r"|\bwhat\s+do\s+you\s+(know|remember)\b"
    r"|\bdelegate\b|\bsecond\s+opinion\b|\banother\s+model\b)",
    re.I,
)


def route_specialist(text: str) -> str:
    if CALL_NUMBER.search(text):
        return "comms"
    # Before the others: "remember that I live in KL" is a memory write, while
    # "remind me at 9" is a task, and the schedule regex matches both.
    if SUPERVISE.search(text) and not REMIND.search(text):
        return "supervisor"
    # "remind me to call mum at 9" is a reminder that happens to contain the verb
    # "call". Checked before COMMS, otherwise it routed to comms, whose allowlist
    # has no remind/task_create, and the reminder simply never existed.
    if REMIND.search(text):
        return "scheduler"
    if COMMS.search(text):
        return "comms"
    if EXECUTE.search(text):
        return "executor"
    if RESEARCH.search(text):
        return "researcher"
    if SCHEDULE.search(text):
        return "scheduler"
    return "scheduler"


def pick_model(kind: ModelKind, strong: str, cheap: str) -> str:
    """Voice turns get the cheap model: PLANBOOK §10.2 budgets 600 ms to first token."""
    if kind == "voice":
        return cheap
    if kind == "route":
        return cheap
    return strong
