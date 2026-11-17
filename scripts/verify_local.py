"""Local verification recipe (SKILL §7 in spirit): prove the loop, not the vibes.

Run against a server started with `uv run uvicorn apps.api.main:app`:

    JARVIS_PASSWORD=... uv run python -m scripts.verify_local

Prints one PASS/FAIL line per claim and exits non-zero on any failure.
"""

from __future__ import annotations

import asyncio
import json
import os

import httpx
import pyotp

BASE = os.environ.get("JARVIS_BASE", "http://127.0.0.1:8000")


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
    password = os.environ.get("JARVIS_PASSWORD", "")
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
        return frame


async def main() -> int:
    failures = 0
    async with _client() as client:
        if not await check_health(client):
            failures += 1
        if not await login(client):
            return 1

        cookie = f"jarvis_session={client.cookies.get('jarvis_session')}"
        turn = await ws_turn("plan my week", cookie)
        tools = [e for e in turn["events"] if e["type"] == "tool"]  # type: ignore[union-attr]
        ok = len(tools) == 5 and all(e["ok"] for e in tools)
        print(f"{'PASS' if ok else 'FAIL'} ws turn 'plan my week': {len(tools)} tool events")
        failures += 0 if ok else 1

        created = await client.post("/api/tasks", json={"title": "verify: delete me"})
        task_id = created.json()["id"]
        turn = await ws_turn(f"delete task {task_id}", cookie)
        approval = turn["approval"]
        ok = isinstance(approval, dict) and approval.get("tool_name") == "task_delete"
        print(f"{'PASS' if ok else 'FAIL'} destructive action paused for approval")
        failures += 0 if ok else 1
        if ok:
            decided = await client.post(
                f"/api/approvals/{approval['id']}/decide", json={"decision": "rejected"}
            )
            still_there = await client.get("/api/tasks")
            ok = decided.status_code == 200 and any(t["id"] == task_id for t in still_there.json())
            print(f"{'PASS' if ok else 'FAIL'} rejected approval executed nothing")
            failures += 0 if ok else 1

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
