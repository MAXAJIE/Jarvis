# Jarvis

A single-user, self-hosted personal assistant. This repository implements the
**chassis** described in `PLANBOOK.md`: one agent graph, 28 registered tools, a
policy engine that decides what the model may see, an approval gate, a budget
guard, and an audit trail. `DECISIONS.md` is binding; `SKILL.md` is the working
rule book.

## What runs today

| Works, verified by a test | Not implemented or unverified |
|---|---|
| Tool registry (28 tools), risk levels, taint, approval rules | Real phone calls (needs Twilio + a verified line) |
| LangGraph turn loop with approval `interrupt()` + resume across processes | Gmail read/send (needs OAuth) |
| Budget guard on total spend, incl. fixed-cost floor | Telegram (needs a bot token) |
| TOTP + password login, signed session cookie, rate limit | Voice push-to-talk (needs Deepgram + Azure) |
| Tasks, memory facts, workspace files, dashboard metrics | Sandbox runner (week 7; tools refuse) |
| WebSocket chat + React UI | Vector RAG (needs pgvector) |
| Alembic migration that applies from empty | `docker compose` and Caddy (no Docker here) |

`/api/health` returns **503** and names every missing component. That is the
designed behaviour, not a fault: this build has no provider keys.

## Run it

```bash
uv sync --all-groups
cp .env.example .env                 # leave keys blank; fill what you have
python scripts/setup_operator.py     # writes the password hash + TOTP secret to .env
uv run uvicorn apps.api.main:app --port 8000
```

Open <http://127.0.0.1:8000>. For the Vite dev server instead:

```bash
cd apps/web && npm install && npm run dev    # http://127.0.0.1:5173
```

Without an LLM key the app runs on the **stub provider**: it plans real tool
calls (so approvals, taint, budget and audit all behave), but its prose is
templated. Set `LLM_PROVIDER=openai` and `OPENAI_API_KEY` to get real answers;
`APP_ENV=prod` with the stub refuses to start.

## Gates

```bash
uv run ruff check . && uv run ruff format --check .
uv run mypy agent tools packages          # --strict is configured in pyproject
uv run pytest -q                          # 42 tests
uv run pytest tests/unit/test_policy.py --cov=agent.policy   # 100 % required
uv run alembic upgrade head
```

## Layout

`packages/contracts` (Tool, RiskLevel) · `tools/` (one module per capability) ·
`agent/` (policy, graph, runtime, prompts) · `apps/api` (FastAPI, auth, routes,
services) · `apps/web` (React) · `alembic/` (migrations) · `tests/`.

Two invariants worth knowing before editing:

1. **The registry is the only path to a capability.** A tool that is not in
   `tools/registry.py` and in a specialist allowlist cannot be called.
2. **Policy is code, not prompt text.** `agent/policy.py` filters the tool list
   before the model sees it; `tests/unit/test_policy.py` is the gate.
