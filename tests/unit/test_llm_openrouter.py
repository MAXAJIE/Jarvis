"""OpenRouter is OpenAI-compatible, so only three things differ: base URL, key,
and the cost the response reports. These tests pin exactly those three, offline.
"""

from __future__ import annotations

import asyncio
from typing import Any, ClassVar

import pytest

from agent.runtime import settings_guard
from apps.api.config import get_settings
from providers import llm as llm_module
from providers.llm import ChatMessage, HTTPChatClient, LLMNotConfigured, LLMReply, get_client


def _use(monkeypatch: pytest.MonkeyPatch, provider: str, key: str, model: str) -> None:
    monkeypatch.setenv("LLM_PROVIDER", provider)
    monkeypatch.setenv("OPENROUTER_API_KEY", key if provider == "openrouter" else "")
    monkeypatch.setenv("OPENAI_API_KEY", key if provider == "openai" else "")
    monkeypatch.setenv("LLM_MODEL_STRONG", model)
    from apps.api.config import reset_settings_cache

    reset_settings_cache()


def test_openrouter_builds_a_client_pointed_at_its_own_base_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use(monkeypatch, "openrouter", "sk-or-v1-test", "openai/gpt-4o-mini")
    client = get_client()
    assert isinstance(client, HTTPChatClient)
    assert client.provider == "openrouter"
    assert get_settings().llm_base_url == "https://openrouter.ai/api/v1"


def test_the_same_build_serves_openai_without_a_second_class(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use(monkeypatch, "openai", "sk-test", "gpt-4o-mini")
    client = get_client()
    assert client.provider == "openai"
    assert get_settings().llm_base_url == "https://api.openai.com/v1"


def test_openrouter_without_a_key_boots_but_refuses_to_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Booting matters: health and the chat both need a process in which to say
    # "OPENROUTER_API_KEY is empty". Answering would be worse than refusing.
    _use(monkeypatch, "openrouter", "", "openai/gpt-4o-mini")
    client = get_client()
    assert client.provider == "openrouter"
    with pytest.raises(LLMNotConfigured, match="OPENROUTER_API_KEY is empty"):
        asyncio.run(client.chat([ChatMessage(role="user", content="hi")], [], deadline_ms=1000))


def test_production_still_refuses_to_start_without_a_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use(monkeypatch, "openrouter", "", "openai/gpt-4o-mini")
    monkeypatch.setenv("APP_ENV", "prod")
    from apps.api.config import reset_settings_cache

    reset_settings_cache()
    with pytest.raises(SystemExit, match="OPENROUTER_API_KEY is empty"):
        settings_guard()
    monkeypatch.setenv("APP_ENV", "dev")
    reset_settings_cache()


def test_a_bare_model_name_is_refused_before_it_404s_mid_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # OpenRouter addresses models as vendor/model. Failing here is a startup
    # error; failing at request time would be a half-executed turn.
    _use(monkeypatch, "openrouter", "sk-or-v1-test", "gpt-4o-mini")
    with pytest.raises(RuntimeError, match="vendor-prefixed model"):
        get_client()


def test_openrouter_stays_unconfigured_for_health_until_the_key_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use(monkeypatch, "openrouter", "", "openai/gpt-4o-mini")
    assert get_settings().llm_configured is False
    assert get_settings().llm_key_env_name == "OPENROUTER_API_KEY"
    _use(monkeypatch, "openrouter", "sk-or-v1-test", "openai/gpt-4o-mini")
    assert get_settings().llm_configured is True


class _FakeResponse:
    def __init__(self, body: dict[str, Any]) -> None:
        self.status_code = 200
        self._body = body

    def json(self) -> dict[str, Any]:
        return self._body


class _FakeHTTP:
    """Captures the request instead of sending it."""

    sent: ClassVar[dict[str, Any]] = {}

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    async def __aenter__(self) -> _FakeHTTP:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def post(
        self, url: str, *, json: dict[str, Any], headers: dict[str, str]
    ) -> _FakeResponse:
        type(self).sent = {"url": url, "json": json, "headers": headers}
        return _FakeResponse(
            {
                "choices": [{"message": {"content": "hello"}}],
                "usage": {"prompt_tokens": 120, "completion_tokens": 30, "cost": 0.000042},
            }
        )


@pytest.mark.anyio
async def test_the_request_carries_openrouter_headers_and_asks_for_the_cost(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use(monkeypatch, "openrouter", "sk-or-v1-test", "openai/gpt-4o-mini")
    monkeypatch.setattr(llm_module.httpx, "AsyncClient", _FakeHTTP)
    reply = await get_client().chat([ChatMessage(role="user", content="hi")], [], deadline_ms=5000)

    sent = _FakeHTTP.sent
    assert sent["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert sent["headers"]["Authorization"] == "Bearer sk-or-v1-test"
    assert sent["headers"]["X-Title"] == "Jarvis"
    assert sent["json"]["usage"] == {"include": True}
    assert sent["json"]["model"] == "openai/gpt-4o-mini"
    assert reply.content == "hello"
    assert (reply.tokens_in, reply.tokens_out) == (120, 30)
    assert reply.cost_usd == pytest.approx(0.000042)


@pytest.mark.anyio
async def test_a_response_without_a_cost_leaves_it_unset_rather_than_inventing_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use(monkeypatch, "openai", "sk-test", "gpt-4o-mini")

    class _NoCost(_FakeHTTP):
        async def post(self, url: str, *, json: dict[str, Any], headers: dict[str, str]) -> Any:
            return _FakeResponse(
                {
                    "choices": [{"message": {"content": "ok"}}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5},
                }
            )

    monkeypatch.setattr(llm_module.httpx, "AsyncClient", _NoCost)
    reply = await get_client().chat([ChatMessage(role="user", content="hi")], [], deadline_ms=5000)
    assert reply.cost_usd is None
    assert reply == LLMReply(content="ok", tokens_in=10, tokens_out=5, cost_usd=None)
