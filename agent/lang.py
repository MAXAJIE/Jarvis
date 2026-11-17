"""Language: one prompt file per language, and a script-purity check (C9, D-12).

The check is a heuristic over a curated set of simplified-only glyphs. It is
deliberately conservative: it can miss a simplified character it does not know,
so it is a regression guard for the strings this repository emits, not a
general-purpose converter.
"""

from __future__ import annotations

import re
from pathlib import Path

from packages.contracts.tool import Lang

PROMPT_DIR = Path(__file__).resolve().parent / "prompts"

# Simplified-only forms whose traditional counterpart is a different character.
SIMPLIFIED_ONLY: frozenset[str] = frozenset(
    "这说时间电话为个们对开关门问长马鸟车东业头应现战语读写认识让议论试该请谢谁变单双"
    "边过运动员团场备复吗学习国来会无与从见爱师归张陈队阶阳阴际随难鸡鱼龙"
)

CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")


def violations(text: str, lang: Lang) -> list[str]:
    """Characters in ``text`` that belong to the wrong script for ``lang``."""
    if lang is Lang.ZH_TW:
        return sorted({ch for ch in text if ch in SIMPLIFIED_ONLY})
    return sorted(set(CJK.findall(text)))


def is_pure(text: str, lang: Lang) -> bool:
    return not violations(text, lang)


def load_prompt(lang: Lang) -> str:
    path = PROMPT_DIR / f"{lang.value}.md"
    if not path.exists():
        raise FileNotFoundError(f"missing prompt file {path.name}")
    return path.read_text(encoding="utf-8").strip()
