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


def route_specialist(text: str) -> str:
    if CALL_NUMBER.search(text):
        return "comms"
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
