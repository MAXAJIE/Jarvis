# Jarvis

A single-user, self-hosted personal assistant. One agent graph, 22 runnable tools,
a policy engine that decides what the model may see, an approval gate, a budget
guard, and an audit trail. `PLANBOOK.md` is the spec, `DECISIONS.md` is binding,
`SKILL.md` is the working rule book.

Nothing here degrades quietly. A missing key makes the tool that needs it refuse
with `NotConfigured`; `/api/health` stays **503** and names what is absent; a
capability that does not exist is withheld from the model instead of being offered
and failing.

---

## Status

| Works, covered by a test | Not built |
|---|---|
| Tool registry: 22 tools with risk levels, taint and approval rules | Sandbox runner — **6 tools withheld**, not registered (needs Docker) |
| LangGraph turn loop, approval `interrupt()` + resume across restarts | Scheduled delivery: RRULE is stored, nothing fires it yet |
| Budget guard on **total** spend, including a fixed-cost floor | Inbound calls, `POST /webhooks/twilio/voice` |
| Password + TOTP login, signed cookie, login rate limit | Telegram **inbound** (outbound send works) |
| Tasks, memory facts, workspace files, keyword memory search | Gmail/Calendar: coded, but the OAuth exchange script is missing |
| WebSocket chat, and voice in and out (`/ws/voice`) | Vector RAG: no ingestion, keyword search only |
| Provider chain with fallbacks, per-call cost ledger | PWA, `/api/export`, `/api/erase` |
| React command-center UI that states what is off | Docker/compose, Caddy — this build targets a bare host |

---

## Requirements

| Need | Version | Why |
|---|---|---|
| Python | 3.12 (pinned `==3.12.*`) | `uv` installs it for you |
| [uv](https://docs.astral.sh/uv/) | current | dependency and venv manager |
| Node.js | 20 or newer | builds the UI once; not needed at runtime |
| Disk | ~200 MB + database | `/api/health` fails below 10 % free space |
| Optional | PostgreSQL 15+ / Supabase | otherwise SQLite (default) |

No Docker, no WSL, no Redis, no Postgres required. Windows, Linux and macOS all
work; the examples use Windows paths.

---

## Quick start

```bash
git clone <this repo> jarvis && cd jarvis

uv sync --all-groups                  # creates .venv and installs everything
cp .env.example .env                  # Windows: copy .env.example .env
#   edit .env: OPERATOR_EMAIL you@example.com, and LLM_PROVIDER / keys (see below)

uv run python scripts/setup_operator.py    # asks for a password (12+ chars)
cd apps/web && npm install && npm run build && cd ../..
uv run uvicorn apps.api.main:app --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000>. `setup_operator.py` writes `OPERATOR_PASSWORD_HASH`,
`OPERATOR_TOTP_SECRET` and `SECRET_KEY` into `.env` and prints a provisioning URI;
`var/DEV_CREDENTIALS.txt` (gitignored) keeps a copy for this machine.

Rebuild the UI only when `apps/web` changes. For UI work, run the dev server
instead — it proxies `/api` and `/ws` to port 8000:

```bash
cd apps/web && npm run dev            # http://127.0.0.1:5173
```

---

## First login: password + 6-digit code

The form asks for three things. The third one trips people up.

| Field | Value | Where it comes from |
|---|---|---|
| Email | `OPERATOR_EMAIL` from `.env` | you set it |
| Password | the one you typed into `setup_operator.py` | argon2 hash in `.env` |
| 6-digit code | **computed from** `OPERATOR_TOTP_SECRET` | changes every 30 s |

The code is not stored anywhere — it is derived from the secret plus the current
30-second window. Three ways to get it:

```bash
uv run python -m scripts.totp           # prints e.g.  934822   (18s left)
uv run python -m scripts.totp --watch   # refreshes until you log in
uv run python -m scripts.totp --uri     # otpauth:// URI for an authenticator app
```

For an authenticator app (Google Authenticator, Authy, 1Password) choose "enter
setup key" and paste the 32-character secret from `OPERATOR_TOTP_SECRET`, or import
the `--uri` string. After that the code lives on your phone and rotates itself.

**The commonest mistake:** typing the first few characters of the *secret* into the
code box. `6UVD2H` is not a code, and the server answers `invalid credentials`.
Codes are 6 **digits**.

Details that matter when it goes wrong:

- Attempts are limited to **5 per minute per IP**; the sixth returns `429 too many
  attempts, wait a minute`. Restarting the server clears the counter.
- The code must come from the secret **currently in `.env`**. If you re-ran
  `setup_operator.py`, an app set up earlier holds a stale secret: re-import the URI.
- TOTP is clock-based. A host whose clock is more than ~30 s off will fail
  consistently — let it sync (`w32tm /resync` on Windows, `timedatectl` on Linux).
- Sessions last **7 days** (`jarvis_session` cookie). The cookie is `Secure`
  automatically when `APP_BASE_URL` starts with `https://`, so set that behind TLS.

---

## Configuration

Every secret is read by `apps/api/config.py` from `.env` only (P1). Blank means
"not configured", never "use a default that pretends". The app boots with
everything blank: the tools that need a key refuse, and `/api/health` says so.

### Core

| Variable | Default | Notes |
|---|---|---|
| `APP_ENV` | `dev` | `prod` removes `/docs`, requires Alembic, and refuses the stub |
| `APP_BASE_URL` | `http://127.0.0.1:8000` | must be `https://…` in production for Secure cookies |
| `SECRET_KEY` | generated | signs session cookies; written to `.env` on first boot |
| `DATABASE_URL` | `sqlite+aiosqlite:///./var/jarvis.db` | or `postgresql+asyncpg://…` |
| `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` | `5` / `2` | Postgres only |
| `OPERATOR_EMAIL` | `operator@localhost` | the only account that can exist |

### Models

| Variable | Default | Notes |
|---|---|---|
| `LLM_PROVIDER` | `stub` | `openai`, `openrouter`, `groq`, `gemini`, `cerebras` |
| `LLM_MODEL_STRONG` | `gpt-4o-mini` | tools/typing turns |
| `LLM_MODEL_CHEAP` | `gpt-4o-mini` | routing and voice turns |
| `LLM_MAX_TOKENS` | `800` | always sent; Groq rejects the absence against its 1000/min cap |
| `LLM_FALLBACKS` | empty | comma-separated, tried in order, e.g. `groq,gemini` |
| `OPENROUTER_API_KEY` etc. | empty | one per provider in `providers/catalog.py` |
| `OPENROUTER_MODEL`, `GROQ_MODEL`, `GEMINI_MODEL`, `CEREBRAS_MODEL`, `OPENAI_MODEL` | empty | per-provider override; blank uses the catalog default |

### Speech

| Variable | Default | Notes |
|---|---|---|
| `TTS_PROVIDER` | `deepgram` | `deepgram` (English), `elevenlabs` (adds Chinese), `azure` |
| `DEEPGRAM_API_KEY` | empty | covers speech-to-text **and** English speech |
| `DEEPGRAM_STT_MODEL` | `nova-3` | |
| `DEEPGRAM_TTS_MODEL_EN` | `aura-2-thalia-en` | |
| `ELEVENLABS_API_KEY` / `ELEVENLABS_VOICE_ID` | empty | needed for a Chinese voice |

### Safety and budget

| Variable | Default | Notes |
|---|---|---|
| `MONTHLY_BUDGET_USD` | `20` | hard stop on **total** spend |
| `BUDGET_ALARM_USD` | `15` | alarm banner in the UI |
| `FIXED_MONTHLY_USD` | `11.80` | floor for costs the app cannot meter (host, domain) |
| `APPROVAL_TTL_MINUTES` | `30` | an unanswered approval expires |
| `CALL_MAX_DURATION_S` | `600` | telephony cap |

The remaining groups (Twilio, Telegram, Google, sandbox) are listed in
`.env.example`; each one is verified by `/api/health` and refuses individually.

---

## Models and fallbacks

OpenRouter, Groq, Gemini, Cerebras and OpenAI all speak the same
`/chat/completions` wire format, so one client serves all of them; a provider is a
row in `providers/catalog.py` plus an env key. OpenRouter is the primary in the
reference setup because one key reaches many vendors:

```bash
LLM_PROVIDER=openrouter
OPENROUTER_API_KEY=sk-or-v1-...
LLM_MODEL_STRONG=nvidia/nemotron-3.5-lightning:free
LLM_MODEL_CHEAP=inclusionai/ling-3.2-flash:free
LLM_FALLBACKS=groq
GROQ_API_KEY=gsk_...
GROQ_MODEL=qwen/qwen3.8-27b
```

Behaviour worth knowing before you pick a plan:

- **Model names must be slugs.** OpenRouter wants `vendor/model`; a bare
  `gpt-4o-mini` is refused at startup instead of 404-ing mid-turn.
- **Retries are deliberate.** The chain moves on for 402/408/429/5xx and transport
  errors, never for 401/403/404 — a wrong key fails the same way everywhere. One
  exception: a 400 saying the *model* wrote invalid tool arguments is re-sampled,
  because the request was fine and the model's JSON was not.
- **A short rate limit is waited out** when the failing provider is the last one in
  the chain: a 429 `Retry-After` up to 10 s, never beyond the caller's own
  deadline, so a 3 s voice turn never blocks. Every attempt is written to
  `cost_ledger` at $0 with `meta.failed`.
- **Free tiers are small.** Groq allows ~7 000 tokens/minute and an agent turn
  costs ~1 800, so about 3–4 turns a minute. OpenRouter's free tier is 50
  requests/day until the account holds $10 of credit. Neither is a bug; both are
  visible in the error text the chain surfaces.
- **Unpriced calls are counted, not hidden.** Groq reports tokens but no price, so
  those rows record $0 with `unverified_price`. The System panel shows
  `Unpriced calls`, because a $20 ceiling cannot stop what it cannot see.
- `scripts/check_providers.py` is the probe to re-run after changing a model —
  a catalog default is only as good as its last verification.
- **In prod (`APP_ENV=prod`) the primary must be `openai` or `openrouter` with a
  real key**; the process exits otherwise. Others are fine as fallbacks.
- Without any key the app runs on the **stub**: real tool calls, real approvals and
  real budget rows, but templated prose. The stub never answers as if it knew
  something, and prod refuses to run on it.

---

## Voice

One utterance per turn: press Talk, speak, press again. Deepgram transcribes
(nova-3), the agent runs one turn, Deepgram speaks the answer (Aura), the browser
plays it. Approval requests are spoken aloud, because a silent gate on a voice
channel is the same as no gate.

```bash
uv run python -m scripts.check_voice "Jarvis online."   # → var/voice-sample.mp3
uv run python -m scripts.check_voice_loop "list my tasks"  # drives /ws/voice end to end
```

- English is the verified path. A Chinese voice needs `ELEVENLABS_API_KEY`; with
  Deepgram selected the app **refuses** zh-TW rather than reading Chinese in an
  English voice.
- Each stage bills independently (STT seconds, TTS characters) and each reports its
  own failure, so a failed transcription never becomes an empty turn.
- `latency_ms` is measured and returned on the wire. A free model currently lands
  around 8 s against the 3 s target — reported, not hidden.
- Not built: streaming input, barge-in. The browser needs microphone permission;
  without it the UI says "Microphone blocked" rather than appearing to listen.

---

## Database

SQLite by default: no server, no Docker, and the profile the test suite runs on.
For a durable store, use **Supabase** (Project → Connect → Session pooler):

```bash
DATABASE_URL=postgresql+asyncpg://postgres.<project-ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres
```

Then create the schema once — in `APP_ENV=prod` this is mandatory, because prod
does not call `create_all`:

```bash
uv run alembic upgrade head
```

- **Port 5432** is the session pooler and works as-is. **6543** is the transaction
  pooler; the app turns off asyncpg's prepared-statement cache for it, because each
  transaction lands on a different backend.
- The URL holds the database password: `.env` only, gitignored, never logged.
  `/api/health` reports the database *name* ("postgres jarvis"), never the DSN.
- Every table gets row level security with no policies. Supabase exposes PostgREST
  behind a public anon key; without RLS every row here would be readable and
  writable through an API Jarvis never uses. The app connects as the owner role,
  which RLS does not restrict.
- **Conversation checkpoints stay local** (`var/checkpoints.sqlite`). Resume
  survives restarts but not a move to another machine — see D-46.
- **Back up before anything destructive:** `uv run python -m scripts.backup_db`
  (SQLite copy verified by re-reading it, or `pg_dump` when on Postgres; refuses
  loudly if `pg_dump` is absent).
- **Rehearse migrations on a copy:** `uv run python -m scripts.db_migrate_check`
  runs up → down → up against a throwaway database. Never point it at the live one.
- **Live parity is a separate gate**, skipped unless you supply a real URL:

```bash
JARVIS_TEST_POSTGRES_URL='postgresql+asyncpg://…' uv run pytest tests/integration/test_postgres_parity.py -q
```

Until that passes on your instance, Postgres is *implemented and schema-verified*
(DDL renders with JSONB, BIGSERIAL, timestamptz, 14 RLS statements) but not
*proven live*. `/api/health` reports which database answered, so a silent fallback
to SQLite is visible.

---

## Deploy for real

Checklist, in order:

1. **Build the UI once** — `cd apps/web && npm ci && npm run build`. FastAPI serves
   `apps/web/dist` at `/`, so no Node process runs in production.
2. **Set `APP_ENV=prod` and `APP_BASE_URL=https://your.domain`** so cookies become
   `Secure`. `LLM_PROVIDER` must be `openai` or `openrouter` with a real key or the
   process exits on purpose.
3. **Migrate, then back up on a schedule.**
   `uv run alembic upgrade head` → `uv run python -m scripts.backup_db` (cron or
   Task Scheduler; keep 5 copies by default, `--keep N` to change).
4. **Bind to loopback and put TLS in front.** The app has no TLS of its own:

```bash
uv run uvicorn apps.api.main:app --host 127.0.0.1 --port 8000 --workers 1
```

   Keep **one worker**: the agent runtime, approval interrupt and rate limiter are
   in-process, and two workers would mean two agents on one conversation.

5. **Reverse proxy** (Caddy example — `caddy` terminates TLS and forwards both the
   API and the WebSocket):

```caddyfile
jarvis.example.com {
    reverse_proxy 127.0.0.1:8000
}
```

   For nginx, remember `proxy_set_header Upgrade $http_upgrade;` and
   `proxy_set_header Connection "upgrade";` on `/ws/`, or voice and chat silently
   fail to connect.

6. **Run it as a service.** Linux:

```ini
# /etc/systemd/system/jarvis.service
[Unit]
Description=Jarvis
After=network-online.target

[Service]
WorkingDirectory=/opt/jarvis
Environment=APP_ENV=prod
ExecStart=/opt/jarvis/.venv/bin/python -m uvicorn apps.api.main:app \
          --host 127.0.0.1 --port 8000 --workers 1
Restart=always
RestartSec=3
# the only writable paths the app needs
ReadWritePaths=/opt/jarvis/var

[Install]
WantedBy=multi-user.target
```

   Windows: `nssm install Jarvis "C:\path\jarvis\.venv\Scripts\python.exe" -m uvicorn apps.api.main:app --host 127.0.0.1 --port 8000`,
   or a Task Scheduler entry at logon. (Both patterns are standard; this repository
   develops on Windows and does not exercise them in its gates.)

7. **Expose nothing else.** Twilio, Telegram and Google callbacks need
   `TWILIO_WEBHOOK_BASE` / `APP_BASE_URL` to be publicly reachable; everything else
   can stay behind the proxy. The admin surface (`/docs`) is disabled in prod.

---

## Operating it

```bash
uv run python -m scripts.verify_local        # health, login, one real turn, approval, zh purity, budget
uv run python -m scripts.totp                # current login code
uv run python -m scripts.backup_db --keep 7  # timestamped copy of the database
uv run python -m scripts.db_migrate_check    # migration chain on a throwaway DB
uv run python -m scripts.check_voice "hi"    # one synthesized sentence
```

`verify_local` sends four turns back to back. On a free tier that exceeds the
per-minute token quota, which is a *plan* limit rather than a defect — pace it:

```bash
JARVIS_VERIFY_PACE_S=25 uv run python -m scripts.verify_local     # RESULT: PASS
```

Health and gates:

- `GET /api/health` → `200` only when every component is ready; otherwise `503`
  listing `missing`. It is unauthenticated on purpose, for uptime probes.
  `telegram`, `google`, `sandbox` and `disk` are routinely missing in a minimal
  install, and `disk` fails below 10 % free space.
- `GET /api/metrics/dashboard` (authenticated) → spend, ceiling, calls,
  `unpriced_calls`, failures, voice minutes.

```bash
uv run ruff check . && uv run ruff format --check .
uv run mypy agent tools packages apps providers media scripts
uv run pytest -q                                   # 113 passed, 3 skipped
cd apps/web && npx tsc --noEmit && npm run build
```

The 3 skips are the live-Postgres parity tests, which only run with
`JARVIS_TEST_POSTGRES_URL` set. A skip is not a pass, and the build never presents
it as one.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `invalid credentials` at login | typed a prefix of the **secret** instead of a 6-digit code; stale secret after re-running setup; clock skew | `uv run python -m scripts.totp`; re-import the `--uri` in your authenticator |
| `429 too many attempts` | 5 login attempts in a minute | wait 60 s, or restart the server to clear the counter |
| `503` on login | `OPERATOR_PASSWORD_HASH` is empty | run `scripts/setup_operator.py` |
| Turn fails: `… is empty` naming a variable | that provider has no key | fill it, or pick a provider you have |
| `groq http 429: Rate limit reached … ITPM` | free-tier token quota | add a fallback provider, buy credits, or pace turns (`JARVIS_VERIFY_PACE_S`) |
| `Request too large … OTPM` | `LLM_MAX_TOKENS` above the plan's output cap | lower `LLM_MAX_TOKENS` |
| `tool call validation failed` | the model wrote `"7"` where the schema says integer | automatic: the turn is re-sampled once |
| Health `503` naming `telegram`/`google`/`sandbox`/`disk` | those features are unconfigured | expected; fill the keys if you want them |
| Health `503` naming `db` | database unreachable or wrong URL scheme | check `DATABASE_URL`; URL must start `sqlite+aiosqlite:///` or `postgresql+asyncpg://` |
| Health says `sqlite` but you configured Supabase | the URL did not parse as Postgres | the DSN must start `postgresql+asyncpg://` (not `postgres://`) |
| `relation "…" does not exist` on Postgres | prod skips `create_all` | `uv run alembic upgrade head` |
| Voice says "Microphone blocked" | browser permission | allow the mic for the origin; needs HTTPS (or `localhost`) |
| Chinese voice refuses | Deepgram has no zh-TW voice | set `ELEVENLABS_API_KEY` and `TTS_PROVIDER=elevenlabs` |
| WebSocket drops on every turn behind a proxy | proxy is not forwarding upgrades | add the `Upgrade`/`Connection` headers on `/ws/` |
| `var/jarvis.db` looks empty | someone ran `alembic downgrade` on it | restore from `var/backups/`; use `scripts.db_migrate_check` for rehearsals |

---

## Layout and invariants

`packages/contracts` (Tool, RiskLevel, errors) · `tools/` (one module per
capability) · `agent/` (policy, router, graph, runtime, prompts) · `apps/api`
(FastAPI, auth, routes, services) · `apps/web` (React + Tailwind) · `alembic/`
(migrations) · `media/` (speech, audio) · `providers/` (catalog, LLM clients) ·
`scripts/` (operator and verification) · `tests/`.

Four invariants to keep before editing:

1. **The registry is the only path to a capability.** A tool missing from
   `tools/registry.py` or from every specialist allowlist cannot be called; a tool
   that can only fail is withheld rather than offered.
2. **Policy is code, not prompt text.** `agent/policy.py` filters the tool list
   before the model sees it, and `requires_approval()` is the single authority.
   Prompts describe the interface; they never enforce anything.
3. **Every billable call writes a ledger row**, including failures and unpriced
   ones. The ceiling is on total spend and fixed costs are a floor.
4. **No secrets in code, tests or logs.** Configuration comes from `.env` through
   `apps/api/config.py`; tests point `JARVIS_ENV_FILE` at a nonexistent file so a
   developer's keys never reach a test run.

Where to read next: `DECISIONS.md` for why each of these is the way it is (D-31 to
D-47), `PLANBOOK.md` for the spec, `SKILL.md` for the operating rules.
