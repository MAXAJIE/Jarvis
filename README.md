# Jarvis

A single-user, self-hosted personal assistant. This repository implements the
**chassis** described in `PLANBOOK.md`: one agent graph, 28 registered tools, a
policy engine that decides what the model may see, an approval gate, a budget
guard, and an audit trail. `DECISIONS.md` is binding; `SKILL.md` is the working
rule book.

## What runs today

| Works, verified by a test | Not implemented |
|---|---|
| Tool registry: 22 runnable tools, risk levels, taint, approval rules | Sandbox runner — **6 tools withheld**, not registered (needs Docker) |
| LangGraph turn loop with approval `interrupt()` + resume across processes | Outbound phone calls — `call_place` withheld (no TwiML handler) |
| Budget guard on total spend, incl. fixed-cost floor | Inbound calls and `POST /webhooks/twilio/voice` |
| TOTP + password login, signed session cookie, rate limit | Telegram **inbound** (`POST /webhooks/telegram`); outbound works |
| Tasks, memory facts (router now reaches the supervisor), workspace files | Scheduled delivery: RRULE is stored, nothing fires it |
| WebSocket chat **and voice** (`/ws/voice`, Deepgram STT + TTS) | Gmail/Calendar: needs an OAuth token exchange (`scripts/google_auth.py`) |
| Provider table with fallback chain (OpenRouter, Groq, Gemini, …) | Vector RAG: no ingestion, keyword only (needs pgvector) |
| React command-center UI, honest about what is off | PWA, `/api/export`, `/api/erase` (§8.1) |
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
templated. `APP_ENV=prod` with the stub refuses to start.

**OpenRouter** (one key, many vendors' models): in `.env`

```
LLM_PROVIDER=openrouter
OPENROUTER_API_KEY=sk-or-v1-...
LLM_MODEL_STRONG=openai/gpt-4o-mini   # vendor/model slug, required
LLM_MODEL_CHEAP=openai/gpt-4o-mini
```

OpenRouter is OpenAI-compatible, so the same client serves every provider in
`providers/catalog.py` (`openai`, `openrouter`, `groq`, `gemini`, `cerebras`).
The request asks for `usage.include`, and the provider's reported cost is what
lands in `cost_ledger` (`price_source: provider`); a bad key boots into a client
that refuses and names the variable instead of killing the process.

**Fallbacks.** `LLM_FALLBACKS=groq,gemini` is tried in order when the primary
rate-limits (429), is out of credit (402) or fails upstream (5xx). A 400/401 is
never retried elsewhere — it would fail the same way everywhere. Each failed
attempt lands in `cost_ledger` at $0 with `meta.failed`, so a silently degrading
chain is visible.

**Voice.** `TTS_PROVIDER=deepgram` (default) uses `DEEPGRAM_API_KEY` for both
speech-to-text and speech, Aura voices, English only. `TTS_PROVIDER=elevenlabs`
with `ELEVENLABS_API_KEY` adds multilingual voices for Chinese (free tier: 10k
characters/month). Check it for real:

```bash
python -m scripts.check_voice "Jarvis online."      # writes var/voice-sample.mp3
python -m scripts.check_voice "我而家可以講嘢。"     # refuses until ElevenLabs is set
```

### Talking to it

The conversation view opens in voice mode. Press **Talk**, speak, press again: one
utterance per turn, English, Deepgram listening (nova-3) and Deepgram speaking
(Aura). The reply is played back in the browser.

```bash
python -m scripts.check_voice_loop "list my tasks"
```

That drives `/ws/voice` for real — synthesize an utterance, push it through the
socket the way the browser does, and check that a transcript, an agent turn and
spoken audio all come back. It writes `var/voice-reply.mp3`.

Not built yet: streaming input and barge-in (the current loop records a whole
utterance before sending it). The turn latency is reported on the wire as
`latency_ms`; a free model lands around 8 s against the 3 s target, which is why
the number is measured rather than claimed.
`,
## Gates

```bash
uv run ruff check . && uv run ruff format --check .
uv run mypy agent tools packages          # --strict is configured in pyproject
uv run pytest -q                          # 86 tests
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
