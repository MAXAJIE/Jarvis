"""Speech to text, prerecorded path. Deepgram only for this phase (English).

The browser sends one utterance - press to talk, release to send - which keeps the
first working voice loop to one HTTP call instead of a duplex protocol. Streaming
STT is what W5's latency target wants; this is what works today, and the shape
here does not have to change to add it.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from apps.api.config import get_settings
from packages.contracts.errors import NotConfigured

DEEPGRAM_LISTEN = "https://api.deepgram.com/v1/listen"

# VERIFY: prerecorded nova pricing, USD per minute, read from Deepgram's pricing
# page from memory. Deepgram does not report a per-request cost, so every stt row
# carries meta.unverified_price until an invoice confirms this number.
STT_USD_PER_MINUTE = 0.0043


@dataclass(frozen=True)
class Transcript:
    text: str
    confidence: float
    seconds: float
    provider: str
    model: str


async def transcribe(audio: bytes, mime: str = "audio/webm", lang: str = "en") -> Transcript:
    """One utterance in, one sentence out. Refuses if no key, or if empty audio."""
    settings = get_settings()
    if not settings.deepgram_api_key:
        raise NotConfigured("stt: DEEPGRAM_API_KEY is empty")
    if not audio:
        raise ValueError("no audio")
    params = {
        "model": settings.deepgram_stt_model,
        "language": lang,
        "smart_format": "true",
        "punctuate": "true",
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            DEEPGRAM_LISTEN,
            params=params,
            content=audio,
            headers={
                "Authorization": f"Token {settings.deepgram_api_key}",
                "Content-Type": mime,
            },
        )
    if response.status_code != 200:
        raise RuntimeError(f"deepgram stt http {response.status_code}: {response.text[:200]}")
    body = response.json()
    try:
        alternative = body["results"]["channels"][0]["alternatives"][0]
    except (KeyError, IndexError) as exc:
        raise RuntimeError(f"deepgram stt: unexpected body {str(body)[:200]}") from exc
    return Transcript(
        text=str(alternative.get("transcript") or "").strip(),
        confidence=float(alternative.get("confidence") or 0.0),
        seconds=float((body.get("metadata") or {}).get("duration") or 0.0),
        provider="deepgram",
        model=settings.deepgram_stt_model,
    )
