"""Local verification recipe (SKILL §7 in spirit): prove the loop, not the vibes.

Run against a server started with `uv run uvicorn apps.api.main:app`:

    JARVIS_PASSWORD=... uv run python -m scripts.verify_local

Prints one PASS/FAIL line per claim and exits non-zero on any failure.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path

import httpx
import pyotp

BASE = os.environ.get("JARVIS_BASE", "http://127.0.0.1:8000")


def _operator_password() -> str:
    """JARVIS_PASSWORD first, then the gitignored dev credential record.

    Refusing to guess is the point: an empty password makes the login endpoint
    return 422 and the recipe must say why rather than look like a broken app.
    """
    password = os.environ.get("JARVIS_PASSWORD", "")
    if password:
        return password
    record = Path("var/DEV_CREDENTIALS.txt")
    if not record.exists():
        return ""
    for line in record.read_text(encoding="utf-8").splitlines():
        if line.lower().startswith("password:"):
            return line.split(":", 1)[1].strip()
    return ""


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=BASE, timeout=30.0)


async def check_health(client: httpx.AsyncClient) -> bool:
    response = await client.get("/api/health")
    body = response.json()
    ok = response.status_code == 503 and body["status"] == "degraded"
    missing = ", ".join(body["missing"])
    print(f"{'PASS' if ok else 'FAIL'} health: {response.status_code} degraded, missing: {missing}")
    return ok


async def login(client: httpx.AsyncClient) -> bool:
    from apps.api.config import get_settings

    settings = get_settings()
    password = _operator_password()
    if not password:
        print(
            "FAIL login: no operator password. Set JARVIS_PASSWORD or run "
            "python scripts/setup_operator.py first."
        )
        return False
    code = pyotp.TOTP(settings.operator_totp_secret).now()
    response = await client.post(
        "/api/auth/login",
        json={"email": settings.operator_email, "password": password, "totp": code},
    )
    ok = response.status_code == 200 and "jarvis_session" in response.cookies
    print(f"{'PASS' if ok else 'FAIL'} login: {response.status_code}")
    if ok:
        client.cookies.update(response.cookies)
    return ok


class TurnError(RuntimeError):
    """The server answered the turn with an error frame instead of a result."""


async def ws_turn(text: str, cookie: str, lang: str | None = None) -> dict[str, object]:
    from websockets.asyncio.client import connect

    scheme = "wss" if BASE.startswith("https") else "ws"
    host = BASE.split("://", 1)[1]
    async with connect(
        f"{scheme}://{host}/ws/chat", additional_headers={"cookie": cookie}
    ) as socket:
        ready = json.loads(await socket.recv())
        assert ready["type"] == "ready", ready
        if lang:
            await socket.send(json.dumps({"type": "set_lang", "lang": lang}))
            assert json.loads(await socket.recv())["type"] == "lang"
        await socket.send(json.dumps({"type": "user_message", "text": text}))
        frame: dict[str, object] = json.loads(await socket.recv())
        if frame.get("type") == "error":
            raise TurnError(str(frame.get("message")))
        return frame


PACE_S = float(os.environ.get("JARVIS_VERIFY_PACE_S", "0"))


async def _pace() -> None:
    """Space turns out when asked.

    A free tier meters tokens per minute (Groq: 7000) and an agent turn costs about
    1800 of them, so four turns back to back *cannot* pass on that plan - the script
    would report a product defect where the product is fine and the quota is small.
    Pacing is stated on stdout rather than hidden, and it is opt-in: an unpaced run
    still fails, which is the honest result for that plan.
    """
    if PACE_S > 0:
        await asyncio.sleep(PACE_S)


async def main() -> int:
    failures = 0
    if PACE_S > 0:
        print(f"NOTE pacing turns {PACE_S:.0f}s apart (free-tier token quota)")
    async with _client() as client:
        if not await check_health(client):
            failures += 1
        if not await login(client):
            return 1

        cookie = f"jarvis_session={client.cookies.get('jarvis_session')}"
        try:
            turn = await ws_turn("plan my week", cookie)
        except TurnError as exc:
            # Every check below needs a working model. Saying so beats five
            # misleading FAILs caused by one missing key.
            print(f"FAIL model call: {exc}")
            print("      nothing below this line was verified: no model, no turn")
            return 1
        events: list[dict[str, object]] = list(turn.get("events") or [])  # type: ignore[call-overload]
        tools = [e for e in events if e.get("type") == "tool"]
        # Two things must hold with any planner: the loop dispatched real tools,
        # and the turn came back with words. What must NOT be asserted is the tool
        # count or every tool succeeding: "plan my week" legitimately reaches for
        # the calendar, which is entitled to refuse when GOOGLE_* is empty. That
        # refusal is correct behaviour, and the approval checks below cover tool
        # execution deterministically.
        answer = str(turn.get("answer") or "")
        ok = bool(tools) and bool(answer.strip())
        summary = ", ".join(f"{e.get('name')}{'=' if e.get('ok') else '!'}" for e in tools)
        label = "PASS" if ok else "FAIL"
        print(f"{label} ws turn 'plan my week': {len(tools)} tool event(s) [{summary}]")
        failures += 0 if ok else 1

        # A unique title, and the id in the instruction: earlier runs left several
        # tasks literally called "verify: delete me", and a small planner asked
        # "which one?" instead of deleting - a verifier defect reported as a product
        # defect. Leftovers from the previous run are cleared first.
        for stale in (await client.get("/api/tasks")).json():
            if str(stale["title"]).startswith("verify: delete me"):
                await client.delete(f"/api/tasks/{stale['id']}")
        title = f"verify: delete me {time.strftime('%H%M%S')}"
        created = await client.post("/api/tasks", json={"title": title})
        task_id = created.json()["id"]
        print(f"NOTE created one task to delete: {title}")
        await _pace()
        turn = await ws_turn(f"delete the task with id {task_id}", cookie)
        approval = turn.get("approval")
        approval_id = approval["id"] if isinstance(approval, dict) else None
        ok = isinstance(approval, dict) and approval.get("tool_name") == "task_delete"
        print(f"{'PASS' if ok else 'FAIL'} destructive action paused for approval")
        failures += 0 if ok else 1
        if ok:
            decided = await client.post(
                f"/api/approvals/{approval_id}/decide", json={"decision": "rejected"}
            )
            still_there = await client.get("/api/tasks")
            ok = decided.status_code == 200 and any(t["id"] == task_id for t in still_there.json())
            print(f"{'PASS' if ok else 'FAIL'} rejected approval executed nothing")
            failures += 0 if ok else 1

        await _pace()
        turn = await ws_turn("記住我住在吉隆坡", cookie, lang="zh-TW")
        from agent.lang import is_pure
        from packages.contracts.tool import Lang

        answer = str(turn["answer"])
        ok = is_pure(answer, Lang.ZH_TW)
        print(f"{'PASS' if ok else 'FAIL'} zh-TW turn is script-pure")

        metrics = (await client.get("/api/metrics/dashboard")).json()
        ok = {"spend_usd", "remaining_usd", "ceiling_usd"} <= set(metrics)
        print(
            f"{'PASS' if ok else 'FAIL'} dashboard: spend ${metrics['spend_usd']:.2f} "
            f"of ${metrics['ceiling_usd']:.2f}, left ${metrics['remaining_usd']:.2f}"
        )
        failures += 0 if ok else 1

    print("\nRESULT:", "PASS" if failures == 0 else f"{failures} FAILED")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
