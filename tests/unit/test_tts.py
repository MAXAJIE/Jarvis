"""TTS request shape, without a network and without a key.

The live ElevenLabs call is unverified until a key exists; what *is* verifiable is
that the request is well formed, that a missing key refuses instead of returning
silence, and that the UI is never told the voice loop is ready.
"""

from __future__ import annotations

from typing import Any, ClassVar

import pytest

from apps.api.config import get_settings, reset_settings_cache
from media import tts as tts_module
from media.tts import speak, voice_status
from packages.contracts.errors import NotConfigured


def _env(monkeypatch: pytest.MonkeyPatch, **values: str) -> None:
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    reset_settings_cache()


class _Resp:
    def __init__(self, status: int, payload: Any, content: bytes = b"") -> None:
        self.status_code = status
        self._payload = payload
        self.content = content
        self.text = str(payload)

    def json(self) -> Any:
        return self._payload


class _FakeClient:
    sent: ClassVar[list[dict[str, Any]]] = []

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    async def __aenter__(self) -> _FakeClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def get(self, url: str, *, headers: dict[str, str]) -> _Resp:
        type(self).sent.append({"method": "GET", "url": url, "headers": headers})
        return _Resp(
            200,
            {
                "voices": [
                    {"voice_id": "voice-en", "labels": {"language": "en"}},
                    {"voice_id": "voice-zh", "labels": {"language": "zh"}},
                ]
            },
        )

    async def post(self, url: str, *, json: dict[str, Any], headers: dict[str, str]) -> _Resp:
        type(self).sent.append({"method": "POST", "url": url, "json": json, "headers": headers})
        return _Resp(200, {}, content=b"ID3fake-mp3-bytes")


@pytest.mark.anyio
async def test_a_missing_key_refuses_instead_of_returning_silence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _env(monkeypatch, TTS_PROVIDER="elevenlabs", ELEVENLABS_API_KEY="")
    with pytest.raises(NotConfigured, match="ELEVENLABS_API_KEY is empty"):
        await speak("hello")


@pytest.mark.anyio
async def test_the_request_names_the_key_header_and_asks_for_mp3(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _env(
        monkeypatch,
        TTS_PROVIDER="elevenlabs",
        ELEVENLABS_API_KEY="el-test",
        ELEVENLABS_VOICE_ID="voice-en",
        ELEVENLABS_MODEL="eleven_turbo_v2_5",
    )
    monkeypatch.setattr(tts_module.httpx, "AsyncClient", _FakeClient)
    _FakeClient.sent = []

    speech = await speak("Jarvis online.")

    post = next(entry for entry in _FakeClient.sent if entry["method"] == "POST")
    assert post["url"].endswith("/text-to-speech/voice-en")
    assert post["headers"]["xi-api-key"] == "el-test"
    assert post["headers"]["Accept"] == "audio/mpeg"
    assert post["json"]["text"] == "Jarvis online."
    assert post["json"]["model_id"] == "eleven_turbo_v2_5"
    assert speech.audio == b"ID3fake-mp3-bytes"
    assert speech.mime == "audio/mpeg"
    assert speech.voice == "voice-en"


@pytest.mark.anyio
async def test_a_blank_voice_id_is_resolved_from_the_account_not_invented(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _env(
        monkeypatch,
        TTS_PROVIDER="elevenlabs",
        ELEVENLABS_API_KEY="el-test",
        ELEVENLABS_VOICE_ID="",
    )
    monkeypatch.setattr(tts_module.httpx, "AsyncClient", _FakeClient)
    _FakeClient.sent = []

    speech = await speak("hello", lang="zh")

    assert any(
        entry["method"] == "GET" and entry["url"].endswith("/voices") for entry in _FakeClient.sent
    )
    assert speech.voice == "voice-zh"


@pytest.mark.anyio
async def test_an_http_error_carries_the_provider_explanation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _env(
        monkeypatch,
        TTS_PROVIDER="elevenlabs",
        ELEVENLABS_API_KEY="el-test",
        ELEVENLABS_VOICE_ID="v",
    )

    class _Broken(_FakeClient):
        async def post(self, url: str, *, json: dict[str, Any], headers: dict[str, str]) -> _Resp:
            return _Resp(401, "invalid api key")

    monkeypatch.setattr(tts_module.httpx, "AsyncClient", _Broken)
    with pytest.raises(RuntimeError, match="invalid api key"):
        await speak("hello")


def test_the_ui_is_never_told_the_voice_loop_is_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    _env(
        monkeypatch,
        TTS_PROVIDER="elevenlabs",
        ELEVENLABS_API_KEY="el-test",
        DEEPGRAM_API_KEY="dg-test",
    )
    status = voice_status()
    assert status["tts_ready"] is True
    assert status["stt_ready"] is True
    assert status["free_chars_per_month"] == 10_000
    # Both halves configured still does not make the streaming turn exist.
    assert status["transport_ready"] is False
    assert get_settings().tts_configured is True


def test_the_missing_key_is_named_per_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    _env(monkeypatch, TTS_PROVIDER="elevenlabs", ELEVENLABS_API_KEY="")
    assert get_settings().tts_key_env_name == "ELEVENLABS_API_KEY"
    _env(monkeypatch, TTS_PROVIDER="azure", AZURE_SPEECH_KEY="")
    assert get_settings().tts_key_env_name == "AZURE_SPEECH_KEY"


class _FakeDeepgram:
    sent: ClassVar[list[dict[str, Any]]] = []

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    async def __aenter__(self) -> _FakeDeepgram:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def post(
        self,
        url: str,
        *,
        params: dict[str, str],
        json: dict[str, Any],
        headers: dict[str, str],
    ) -> _Resp:
        type(self).sent.append({"url": url, "params": params, "json": json, "headers": headers})
        return _Resp(200, {}, content=b"ID3deepgram")


@pytest.mark.anyio
async def test_deepgram_speaks_english_on_the_stt_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # One key for ears and mouth is the whole reason deepgram is the default: no
    # second signup before the first sentence can be heard.
    _env(
        monkeypatch,
        TTS_PROVIDER="deepgram",
        DEEPGRAM_API_KEY="dg-test",
        DEEPGRAM_TTS_MODEL_EN="aura-2-thalia-en",
    )
    monkeypatch.setattr(tts_module.httpx, "AsyncClient", _FakeDeepgram)
    _FakeDeepgram.sent = []

    speech = await speak("Jarvis online.", lang="en")

    sent = _FakeDeepgram.sent[0]
    assert sent["url"] == "https://api.deepgram.com/v1/speak"
    assert sent["params"] == {"model": "aura-2-thalia-en"}
    assert sent["headers"]["Authorization"] == "Token dg-test"
    assert sent["json"] == {"text": "Jarvis online."}
    assert speech.audio == b"ID3deepgram"
    assert speech.provider == "deepgram"


@pytest.mark.anyio
async def test_a_chinese_sentence_is_refused_rather_than_read_in_english(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _env(monkeypatch, TTS_PROVIDER="deepgram", DEEPGRAM_API_KEY="dg-test")
    monkeypatch.setattr(tts_module.httpx, "AsyncClient", _FakeDeepgram)
    _FakeDeepgram.sent = []

    with pytest.raises(NotConfigured, match="no zh-TW voice") as excinfo:
        await speak("我而家可以講嘢。", lang="zh-TW")

    assert "elevenlabs" in str(excinfo.value)
    assert _FakeDeepgram.sent == []  # nothing was sent: no audio was made


def test_deepgram_tts_counts_as_configured_from_the_shared_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _env(monkeypatch, TTS_PROVIDER="deepgram", DEEPGRAM_API_KEY="dg-test")
    settings = get_settings()
    assert settings.tts_configured is True
    assert settings.tts_key_env_name == "DEEPGRAM_API_KEY"
