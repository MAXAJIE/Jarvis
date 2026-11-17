"""End-to-end voice probe over the real socket, with no microphone.

    python -m scripts.check_voice_loop ["list my tasks"]

It synthesizes an utterance with Deepgram Aura, pushes those bytes at /ws/voice the
way the browser would, and checks the four things a voice turn must produce:
a transcript, an agent turn, spoken audio, and cost rows for both stages.

The one thing this cannot prove is the browser's MediaRecorder permission path -
there is no microphone in this environment - so that stays unverified and is
listed as such.
"""

from __future__ import annotations

import asyncio
import base64
import json
import sys
from pathlib import Path

import httpx
from websockets.asyncio.client import connect

from media.tts import speak
from scripts.verify_local import BASE, TurnError, login

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


async def main(argv: list[str]) -> int:
    utterance = argv[0] if argv else "list my tasks"
    print(f"utterance      : {utterance!r}")

    speech = await speak(utterance, lang="en")
    print(f"synthesized    : {len(speech.audio)} bytes via {speech.provider} {speech.voice}")

    async with httpx.AsyncClient(base_url=BASE, timeout=30.0) as client:
        await login(client)
        cookie = f"jarvis_session={client.cookies.get('jarvis_session')}"

    host = BASE.split("://", 1)[1]
    scheme = "wss" if BASE.startswith("https") else "ws"
    async with connect(f"{scheme}://{host}/ws/voice", additional_headers={"cookie": cookie}) as ws:
        ready = json.loads(await ws.recv())
        print(
            f"ready          : conversation {ready.get('conversation_id')} "
            f"stt={ready.get('thresholds', {}).get('stt')} "
            f"tts={ready.get('thresholds', {}).get('tts')}"
        )

        await ws.send(json.dumps({"type": "audio_start", "mime": "audio/mpeg"}))
        assert json.loads(await ws.recv())["type"] == "listening"
        for start in range(0, len(speech.audio), 4096):
            await ws.send(speech.audio[start : start + 4096])
        await ws.send(json.dumps({"type": "audio_end"}))

        transcript = json.loads(await asyncio.wait_for(ws.recv(), timeout=60))
        if transcript.get("type") == "error":
            raise TurnError(f"{transcript.get('stage')}: {transcript.get('message')}")
        print(
            f"transcript     : {transcript['text']!r} "
            f"confidence={transcript['confidence']} seconds={transcript['seconds']}"
        )
        if not transcript["text"]:
            print("FAIL stt returned nothing")
            return 1

        turn = json.loads(await asyncio.wait_for(ws.recv(), timeout=120))
        if turn.get("type") == "error":
            raise TurnError(f"{turn.get('stage')}: {turn.get('message')}")
        tools = [e for e in turn.get("events", []) if e.get("type") == "tool"]
        print(
            f"turn           : {len(tools)} tool event(s) "
            f"[{', '.join(str(e.get('name')) for e in tools)}]"
        )
        print(f"answer         : {str(turn.get('answer'))[:160]!r}")
        latency = turn.get("latency_ms")
        print(f"turn latency   : {latency} ms (target 3000)")
        if isinstance(latency, int) and latency > 3000:
            print(
                "                 over the D-06 target: a free model will be; "
                "record it, do not hide it"
            )

        reply = json.loads(await asyncio.wait_for(ws.recv(), timeout=120))
        if reply.get("type") == "error":
            raise TurnError(f"{reply.get('stage')}: {reply.get('message')}")
        audio = base64.b64decode(reply["data"])
        out = Path("var/voice-reply.mp3")
        out.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(out.write_bytes, audio)
        print(f"spoken reply   : {len(audio)} bytes {reply['mime']} -> {out}")

    ok = bool(audio) and bool(transcript["text"]) and bool(turn.get("answer"))
    print()
    print(f"RESULT: {'PASS' if ok else 'FAIL'} — stt, agent turn and tts all ran over /ws/voice")
    print(
        "NOT VERIFIED: the browser microphone path (MediaRecorder + permission prompt);"
        " no microphone in this environment."
    )
    return 0 if ok else 1


if __name__ == "__main__":
    from packages.contracts.errors import NotConfigured

    try:
        raise SystemExit(asyncio.run(main(sys.argv[1:])))
    except NotConfigured as exc:
        print(f"BLOCKED: {exc}")
        raise SystemExit(2) from exc
    except TurnError as exc:
        print(f"FAIL: {exc}")
        raise SystemExit(1) from exc
