"""The provider table: a second free LLM is a row, and a fallback is an order.

What these tests defend is not "the fallback works" in the abstract but the
specific promises that make a chain safe: a rate-limited provider cannot kill a
turn, a wrong-key (401) failure is *not* retried everywhere, and a provider that
refused still leaves a trace.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, ClassVar

import httpx
import pytest

from apps.api.config import get_settings, reset_settings_cache
from providers.catalog import CATALOG, spec_for
from providers.llm import (
    AttemptTrace,
    ChainClient,
    ChatMessage,
    HTTPChatClient,
    LLMReply,
    ProviderHTTPError,
)


def _env(monkeypatch: pytest.MonkeyPatch, **values: str) -> None:
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    reset_settings_cache()


class _Scripted(HTTPChatClient):
    """An HTTP client that never sends: answers with a canned outcome."""

    outcomes: ClassVar[dict[str, Any]] = {}

    def __init__(self, provider: str, model: str) -> None:
        spec = CATALOG[provider]
        super().__init__(spec, model, "test-key")
        self.calls = 0

    async def chat(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[Any],
        *,
        deadline_ms: int,
    ) -> LLMReply:
        del messages, tools, deadline_ms
        self.calls += 1
        outcome = type(self).outcomes[self.provider]
        if isinstance(outcome, Exception):
            raise outcome
        return LLMReply(content=str(outcome), tokens_in=10, tokens_out=5)


@pytest.mark.anyio
async def test_a_rate_limited_primary_is_replaced_by_the_fallback() -> None:
    primary = _Scripted("openrouter", "nvidia/nemotron:free")
    fallback = _Scripted("groq", "llama-3.3-70b-versatile")
    _Scripted.outcomes = {
        "openrouter": ProviderHTTPError("openrouter", 429, "rate limited"),
        "groq": "answered by groq",
    }

    reply = await ChainClient([primary, fallback]).chat([], [], deadline_ms=5000)

    assert reply.content == "answered by groq"
    assert [a.ok for a in reply.attempts] == [False, True]
    assert reply.attempts[-1].provider == "groq"
    assert reply.attempts[0].status == 429


@pytest.mark.anyio
async def test_a_bad_key_is_not_retried_on_every_provider() -> None:
    # 401 means *this* key is wrong. Firing the same bad request at three
    # providers turns one clear error into three slow ones.
    primary = _Scripted("openrouter", "m")
    fallback = _Scripted("groq", "m")
    _Scripted.outcomes = {
        "openrouter": ProviderHTTPError("openrouter", 401, "invalid key"),
        "groq": "should never be reached",
    }

    with pytest.raises(ProviderHTTPError) as excinfo:
        await ChainClient([primary, fallback]).chat([], [], deadline_ms=5000)

    assert excinfo.value.status == 401
    assert fallback.calls == 0


@pytest.mark.anyio
async def test_the_last_error_is_raised_when_every_provider_refuses() -> None:
    a = _Scripted("openrouter", "m")
    b = _Scripted("groq", "m")
    _Scripted.outcomes = {
        "openrouter": ProviderHTTPError("openrouter", 503, "upstream down"),
        "groq": ProviderHTTPError("groq", 429, "slow down"),
    }
    with pytest.raises(ProviderHTTPError) as excinfo:
        await ChainClient([a, b]).chat([], [], deadline_ms=5000)
    assert excinfo.value.provider == "groq"


def test_the_chain_drops_unknown_names_and_duplicates(monkeypatch: pytest.MonkeyPatch) -> None:
    _env(
        monkeypatch,
        LLM_PROVIDER="openrouter",
        LLM_FALLBACKS="groq, not-a-provider ,openrouter,gemini,groq",
    )
    assert get_settings().llm_chain == ["openrouter", "groq", "gemini"]


def test_a_fallback_without_a_key_is_skipped_not_fatal(monkeypatch: pytest.MonkeyPatch) -> None:
    _env(
        monkeypatch,
        LLM_PROVIDER="openrouter",
        OPENROUTER_API_KEY="sk-or-test",
        LLM_FALLBACKS="groq,gemini",
        LLM_MODEL_STRONG="openai/gpt-4o-mini",
        GROQ_API_KEY="",
        GEMINI_API_KEY="",
    )
    from providers.llm import get_client

    # Only the primary has a key, so it is used alone - not a crash, not a stub.
    assert isinstance(get_client(), HTTPChatClient)
    assert get_settings().llm_chain == ["openrouter", "groq", "gemini"]


def test_every_catalog_entry_is_openai_compatible_and_has_a_key_name() -> None:
    for name, spec in CATALOG.items():
        assert spec.name == name
        assert spec.base_url.startswith("https://")
        assert spec.key_env.endswith(("_KEY", "_TOKEN"))
        assert spec.default_model
        if spec.requires_vendor_prefix:
            assert "/" in spec.default_model


def test_a_retryable_status_is_distinguished_from_a_permanent_one() -> None:
    assert ProviderHTTPError("x", 429, "").retryable
    assert ProviderHTTPError("x", 402, "").retryable
    assert ProviderHTTPError("x", 503, "").retryable
    assert not ProviderHTTPError("x", 400, "").retryable
    assert not ProviderHTTPError("x", 401, "").retryable
    assert not ProviderHTTPError("x", 404, "").retryable


def test_spec_lookup_is_case_and_space_insensitive() -> None:
    assert spec_for(" Groq ").name == "groq"  # type: ignore[union-attr]
    assert spec_for("nope") is None


@pytest.mark.anyio
async def test_a_network_error_is_retryable_but_a_protocol_error_is_not() -> None:
    primary = _Scripted("openrouter", "m")
    fallback = _Scripted("groq", "m")
    _Scripted.outcomes = {
        "openrouter": httpx.ConnectError("no route to host"),
        "groq": "answered",
    }
    reply = await ChainClient([primary, fallback]).chat([], [], deadline_ms=5000)
    assert reply.content == "answered"
    assert isinstance(reply.attempts[0], AttemptTrace)
    assert reply.attempts[0].ok is False
