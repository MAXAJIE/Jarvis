"""Text to speech. This is the half of the voice loop that can exist before the
transport does: text in, mp3 bytes out, no streaming, no session state.

What is NOT here, and must not be pretended: the streaming voice turn (audio in
over a WebSocket, μ-law framing, barge-in). That is W5 work. ``speak()`` gives the
turn a mouth; it does not give Jarvis ears.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from apps.api.config import get_settings
from packages.contracts.errors import NotConfigured

ELEVENLABS_BASE = "https://api.elevenlabs.io/v1"
DEEPGRAM_SPEAK = "https://api.deepgram.com/v1/speak"

# Free tier: 10k characters/month, attribution required, non-commercial. Told
# here so the ceiling is visible at the point of spend, not discovered later.
ELEVENLABS_FREE_CHARS_PER_MONTH = 10_000

# VERIFY: Aura pricing, USD per 1000 characters, from memory. Deepgram reports
# no per-request cost, so every tts row carries meta.unverified_price.
TTS_USD_PER_1K_CHARS = 0.030


@dataclass(frozen=True)
class Speech:
    audio: bytes
    mime: str
    provider: str
    voice: str


async def list_elevenlabs_voices(api_key: str) -> list[dict[str, object]]:
    """The account's own voices, rather than a hardcoded id that may not exist."""
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(f"{ELEVENLABS_BASE}/voices", headers={"xi-api-key": api_key})
    if response.status_code != 200:
        raise RuntimeError(f"elevenlabs voices http {response.status_code}: {response.text[:200]}")
    body = response.json()
    voices = body.get("voices")
    return [v for v in voices if isinstance(v, dict)] if isinstance(voices, list) else []


def _pick_voice(voices: list[dict[str, object]], lang: str) -> str:
    """Prefer an exact language match, else the first voice on the account."""
    wanted = lang.lower()
    for voice in voices:
        labels = voice.get("labels")
        if isinstance(labels, dict) and str(labels.get("language", "")).lower() == wanted:
            return str(voice.get("voice_id"))
    for voice in voices:
        if str(voice.get("voice_id")):
            return str(voice["voice_id"])
    raise NotConfigured("elevenlabs account has no voices")


async def speak(text: str, lang: str = "en") -> Speech:
    """Render one sentence. Refuses rather than returns silence when unconfigured."""
    settings = get_settings()
    if not text.strip():
        raise ValueError("nothing to say")
    if settings.tts_provider == "elevenlabs":
        return await _elevenlabs(text, lang, settings.elevenlabs_api_key)
    if settings.tts_provider == "deepgram":
        return await _deepgram(text, lang, settings.deepgram_api_key)
    raise NotConfigured(
        f"tts: unknown TTS_PROVIDER={settings.tts_provider!r}; use deepgram or elevenlabs"
    )


async def _deepgram(text: str, lang: str, api_key: str) -> Speech:
    """Aura, on the same key as STT: one signup covers ears and mouth in English.

    Aura has no Cantonese or Mandarin voice. Reading a zh-TW answer in an English
    voice is worse than not speaking, so that is a refusal, not a silent fallback.
    """
    if not api_key:
        raise NotConfigured("tts: DEEPGRAM_API_KEY is empty")
    if not lang.lower().startswith("en"):
        raise NotConfigured(
            f"tts: deepgram Aura has no {lang} voice; set TTS_PROVIDER=elevenlabs "
            "(multilingual) to speak Chinese"
        )
    settings = get_settings()
    model = settings.deepgram_tts_model_en
    async with httpx.AsyncClient(timeout=45.0) as client:
        response = await client.post(
            DEEPGRAM_SPEAK,
            params={"model": model},
            json={"text": text},
            headers={"Authorization": f"Token {api_key}"},
        )
    if response.status_code != 200:
        raise RuntimeError(f"deepgram tts http {response.status_code}: {response.text[:200]}")
    return Speech(audio=response.content, mime="audio/mpeg", provider="deepgram", voice=model)


async def _elevenlabs(text: str, lang: str, api_key: str) -> Speech:
    if not api_key:
        raise NotConfigured("tts: ELEVENLABS_API_KEY is empty")
    settings = get_settings()
    voice_id = settings.elevenlabs_voice_id
    if not voice_id:
        voices = await list_elevenlabs_voices(api_key)
        voice_id = _pick_voice(voices, lang)
    payload = {
        "text": text,
        "model_id": settings.elevenlabs_model,
        "voice_settings": {"stability": 0.4, "similarity_boost": 0.75},
    }
    async with httpx.AsyncClient(timeout=45.0) as client:
        response = await client.post(
            f"{ELEVENLABS_BASE}/text-to-speech/{voice_id}",
            json=payload,
            headers={"xi-api-key": api_key, "Accept": "audio/mpeg"},
        )
    if response.status_code != 200:
        raise RuntimeError(f"elevenlabs tts http {response.status_code}: {response.text[:200]}")
    return Speech(
        audio=response.content,
        mime="audio/mpeg",
        provider="elevenlabs",
        voice=voice_id,
    )


def voice_status() -> dict[str, object]:
    """What the UI may claim. transport_ready stays False until W5 ships."""
    settings = get_settings()
    voice = (
        settings.elevenlabs_voice_id
        if settings.tts_provider == "elevenlabs"
        else settings.deepgram_tts_model_en
    )
    return {
        "stt": "deepgram" if settings.deepgram_api_key else "",
        "stt_ready": bool(settings.deepgram_api_key),
        "tts": settings.tts_provider,
        "tts_ready": bool(settings.tts_configured),
        "tts_voice": voice,
        "tts_key_env": settings.tts_key_env_name,
        "free_chars_per_month": (
            ELEVENLABS_FREE_CHARS_PER_MONTH
            if settings.tts_provider == "elevenlabs"
            else None  # deepgram bills against its credit, not a character allowance
        ),
        # True only because /ws/voice exists and both halves are configured.
        # It said False for weeks while the route did not exist; that flag is a
        # statement about this process, not about the operator's keys.
        "transport_ready": bool(settings.deepgram_api_key) and bool(settings.tts_configured),
    }
