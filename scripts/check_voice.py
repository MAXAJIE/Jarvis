"""Render one sentence to mp3 and report what happened.

    python -m scripts.check_voice
    python -m scripts.check_voice "Jarvis online. 我而家可以講嘢。"

The point is to prove the TTS half of the voice loop against the real API before
the streaming turn exists. It writes var/voice-sample.mp3 and prints the size, so
"voice works" is a file you can play, not a claim in a README.
"""

from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

from apps.api.config import get_settings
from media.tts import speak, voice_status
from packages.contracts.errors import NotConfigured

OUT = Path("var/voice-sample.mp3")

# A Windows console defaults to a legacy code page; printing a zh-TW sentence to
# it raises UnicodeEncodeError instead of speaking. Text is data here, not ANSI.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def detect_lang(text: str) -> str:
    """Any CJK in the sentence means it is not English.

    Hardcoding lang="en" here let a Chinese sentence through an English voice in
    the first run of this script: audible proof that "voice works" can be a lie
    if the language never travels with the text.
    """
    return "zh-TW" if re.search(r"[\u3400-\u9fff]", text) else "en"


async def main(argv: list[str]) -> int:
    settings = get_settings()
    status = voice_status()
    print(f"tts provider : {settings.tts_provider}")
    print(f"key          : {status['tts_key_env']} ({'set' if status['tts_ready'] else 'EMPTY'})")
    if status["free_chars_per_month"]:
        print(f"free tier    : {status['free_chars_per_month']} characters/month")
    print(f"stt          : {'deepgram' if status['stt_ready'] else 'not configured'}")
    print("transport    : streaming turn NOT implemented (W5)")

    text = argv[0] if argv else "Jarvis online. All systems nominal."
    lang = detect_lang(text)
    print(f"text         : {text!r} ({lang})")
    try:
        speech = await speak(text, lang=lang)
    except NotConfigured as exc:
        print(f"\nBLOCKED: {exc}")
        print("         nothing was synthesized, and nothing will pretend otherwise")
        return 2
    except Exception as exc:  # noqa: BLE001 - report, do not traceback at the operator
        print(f"\nFAIL: {exc}")
        return 1

    OUT.parent.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(OUT.write_bytes, speech.audio)
    print(f"\nPASS wrote {OUT} · {len(speech.audio)} bytes · {speech.mime} · voice {speech.voice}")
    expected = len(text)
    print(f"     spent {expected} characters of the monthly allowance")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1:])))
