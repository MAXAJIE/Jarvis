"""Which providers this build can talk to, as data.

Adding a provider is a row here plus a key in the environment - not another
branch in the client. Every entry below speaks the OpenAI chat-completions
protocol, which is the only reason one client class can serve them all.

Free tiers are noted because they are the reason to switch, and because their
limits are the reason a fallback chain exists at all. Nothing here is a promise:
a free tier can rate-limit, and the ledger records what actually happened.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderSpec:
    name: str
    base_url: str
    key_env: str
    default_model: str
    note: str
    requires_vendor_prefix: bool = False


CATALOG: dict[str, ProviderSpec] = {
    "openai": ProviderSpec(
        name="openai",
        base_url="https://api.openai.com/v1",
        key_env="OPENAI_API_KEY",
        default_model="gpt-4o-mini",
        note="paid, no free tier",
    ),
    "openrouter": ProviderSpec(
        name="openrouter",
        base_url="https://openrouter.ai/api/v1",
        key_env="OPENROUTER_API_KEY",
        default_model="openai/gpt-4o-mini",
        note="one key for many vendors; ':free' models bill 0",
        requires_vendor_prefix=True,
    ),
    "groq": ProviderSpec(
        name="groq",
        base_url="https://api.groq.com/openai/v1",
        key_env="GROQ_API_KEY",
        default_model="llama-3.3-70b-versatile",
        note="free tier, very fast, supports tool calling",
    ),
    "gemini": ProviderSpec(
        name="gemini",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        key_env="GEMINI_API_KEY",
        default_model="gemini-2.0-flash",
        note="free tier via AI Studio, OpenAI-compatible endpoint",
    ),
    "cerebras": ProviderSpec(
        name="cerebras",
        base_url="https://api.cerebras.ai/v1",
        key_env="CEREBRAS_API_KEY",
        default_model="llama-3.3-70b",
        note="free tier, very fast",
    ),
}


def spec_for(name: str) -> ProviderSpec | None:
    return CATALOG.get(name.strip().lower())
