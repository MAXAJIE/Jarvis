"""Probe every configured provider for real: model, tool call, price, latency.

Written because a catalog default model was shipped that the account did not have
(`llama-3.3-70b-versatile` on Groq), and it was only found when a live turn failed
halfway. A default is a claim; this is the check.

One request per provider, using two real tool specs from the registry - not a toy
schema, because providers differ in how strictly they validate the schemas pydantic
actually emits.

    uv run python -m scripts.check_providers

Exit code 0 when every provider that has a key answered, 1 otherwise. Providers
without a key are reported as skipped, never as passing.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time

import httpx

from apps.api.config import get_settings
from providers.catalog import CATALOG, spec_for
from tools.registry import build_registry

TOOL_NAMES = ("task_list", "calendar_read")
TIMEOUT_S = 90


def _tool_specs() -> list[dict[str, object]]:
    registry = build_registry()
    by_name = {tool.name: tool for tool in registry.all()}
    specs: list[dict[str, object]] = []
    for name in TOOL_NAMES:
        tool = by_name.get(name)
        if tool is None:
            continue
        specs.append(
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.input_model.model_json_schema(),
                },
            }
        )
    return specs


async def _probe(client: httpx.AsyncClient, provider: str, key: str, model: str) -> bool:
    spec = spec_for(provider)
    if spec is None:
        print(f"FAIL {provider:11} not in providers/catalog.py")
        return False
    payload: dict[str, object] = {
        "model": model,
        "messages": [{"role": "user", "content": "what is on my calendar next week?"}],
        "temperature": 0.2,
        "tools": _tool_specs(),
        "max_tokens": get_settings().llm_max_tokens,
    }
    if provider == "openrouter":
        payload["usage"] = {"include": True}
    headers = {"Authorization": f"Bearer {key}"}
    started = time.monotonic()
    try:
        response = await client.post(
            f"{spec.base_url.rstrip('/')}/chat/completions", json=payload, headers=headers
        )
    except httpx.HTTPError as exc:
        print(f"FAIL {provider:11} {model:34} transport: {type(exc).__name__}")
        return False
    ms = int((time.monotonic() - started) * 1000)

    if response.status_code != 200:
        detail = response.text.strip().replace("\n", " ")[:120]
        print(f"FAIL {provider:11} {model:34} http {response.status_code} in {ms} ms: {detail}")
        return False

    body = response.json()
    message = (body.get("choices") or [{}])[0].get("message") or {}
    calls = message.get("tool_calls") or []
    names = [((call.get("function") or {}).get("name")) for call in calls]
    usage = body.get("usage") or {}
    cost = usage.get("cost")
    price = f"cost={cost}" if cost is not None else "cost=NOT REPORTED (ledger records $0)"
    ok = bool(calls) and all(name in set(TOOL_NAMES) for name in names)
    label = "PASS" if ok else "WARN"
    tool_text = json.dumps(names) if names else "no tool call"
    print(f"{label} {provider:11} {model:34} {tool_text} {price} in {ms} ms")
    return ok


async def main() -> int:
    settings = get_settings()
    chain = settings.llm_chain
    if not chain:
        print("no provider configured: LLM_PROVIDER is stub or names an unknown provider")
        print("skipped:", ", ".join(sorted(CATALOG)))
        return 1

    failures = 0
    print(f"chain: {' -> '.join(chain)}")
    async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
        for provider in chain:
            key = settings.key_for(provider)
            if not key:
                spec = spec_for(provider)
                variable = spec.key_env if spec else "?"
                print(f"SKIP {provider:11} {variable} is empty (unverified, not passing)")
                continue
            model = settings.model_for(provider)
            if not await _probe(client, provider, key, model):
                failures += 1
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
