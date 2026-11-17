# PLANBOOK — Personal AI Agent ("Jarvis")

| Field | Value |
|---|---|
| Version | 2.0 |
| Date | 2026-11-16 |
| Owner | Single operator (you) |
| Build window | 8 weeks × ~8 h/day ≈ 380 h |
| Jurisdiction | Malaysia (MY) |
| Budget tier | $20/month ceiling (Lean) |
| Status | Drafted — ready for implementation |

---

## 0. How to use this document

This is the **source of truth**. If code and this document disagree, one of them is a bug.

1. Every requirement here has a **testable acceptance criterion**. "It works" is not a criterion.
2. Anything marked **`VERIFY`** is an assumption that has **not** been confirmed. It must be confirmed by an experiment in Week 1 and the result written into `DECISIONS.md` **before** dependent code is written.
3. Anything marked **`VERIFY-LIVE`** is a price or limit read from a provider's public pricing page on 2026-11-16. Re-read it before you trust a cost projection.
4. Anything marked **`LEGAL-REVIEW`** is an engineering reading of a regulation, not legal advice. Get a Malaysian lawyer to confirm before exposing this to third parties.
5. Changes to this document require an entry in `DECISIONS.md` with date, reason, and what it invalidates.

### Reading order for the coding agent

`DECISIONS.md` (bind these) → `SKILL.md` (how to work) → this file (what to build).

---

## 1. Charter

### 1.1 What this is

A **single-user, self-hosted, tool-using assistant** that lives on a cloud VPS, is reachable from a browser and Telegram, speaks English and Traditional Chinese, can place and receive real phone calls, executes tasks in a sandbox, and reports its own health and spend.

### 1.2 What this is not (non-goals — do not build these)

| Non-goal | Why |
|---|---|
| Artificial general intelligence | Does not exist. The success metric is *reliability on ~15 named tasks*, not intelligence. |
| Multi-user / SaaS | Adds auth, tenancy isolation, billing, rate limits: ~3 weeks. Single user only. |
| WhatsApp integration (phase 1) | Requires Meta Business verification + message template approval + per-conversation fees. Telegram first. |
| GUI control of the operator's Windows laptop | Mouse/keyboard/screenshot control via vision is the highest-risk, lowest-reliability component. Deferred. The agent's "PC" is the VPS container. |
| Realtime speech-to-speech (`gpt-realtime-2.x`) | Turn-based push-to-talk already meets the accepted latency target (p95 ≤ 3.0 s). Realtime audio is $32/1M input and $64/1M output tokens and roughly 5× the per-minute cost. |
| Caller-ID spoofing / "call from any number I type" | Presenting a number you do not control is fraud, is the technique used in Malaysian scam-syndicate cases, and gets the CPaaS account terminated. See §8.2. |
| Cold-calling / autodialing at volume | Regulatory exposure and account risk. Calls are user-initiated, one at a time. |
| An app-store mobile app | PWA over the existing web frontend is sufficient. |
| Self-hosting the LLM | A 4 GB VPS cannot run a useful model. Cloud APIs only. |

### 1.3 Definition of "done" (global)

The project is complete when one recorded session demonstrates, end to end, in one sitting:

1. Web app login → "plan my week" in **text** → plan persisted, approved, and tickable.
2. Toggle to **talking** → hold button, speak in English → spoken answer in < 3 s p95 → toggle back to typing.
3. Same, in Traditional Chinese, and the answer **never** mixes languages.
4. "Call +60XXXXXXXXX" → real phone rings → 2-way conversation → transcript, summary and USD cost appear on the dashboard.
5. A call **into** the provisioned MY number is answered by the agent.
6. Telegram message → task created → confirmation reply.
7. Gmail: "summarise unread" works without approval; "reply to X" pauses for approval.
8. A sandbox job (Playwright scrape → file written) runs with an audit trail and a hard 15-min timeout.
9. Dashboard shows all 5 metrics and total spend; total monthly spend is under the alarm threshold.

---

## 2. Capability matrix

Legend: **MVP** = must ship in week N. **P1** = ships if schedule holds. **Deferred** = explicitly out of scope.

| # | Capability (operator's words) | Scope | Ships | Acceptance criterion (testable) |
|---|---|---|---|---|
| C1 | "Talk and receive messages, switch by clicking a switcher" | Text chat + push-to-talk voice, one switcher | W5 | Switcher persists per session; a voice turn produces STT text visible in the same thread as typed messages; p95 turn latency ≤ 3.0 s measured over ≥ 50 turns. |
| C2 | "Able to make a phone call" | Outbound to any E.164 number via an owned PhoneLine, two-way audio | W6 | Call to a real MY mobile connects; the callee hears the AI disclosure line; the agent transcribes both sides; `calls` row has non-null `duration_s`, `transcript`, `summary`, `cost_usd`. |
| C2b | "Able to call me" | Outbound briefing call to the operator's own number | W6 | Scheduled job triggers a call; operator answers; agent delivers the daily brief. |
| C2c | Receive a call | Inbound on a provisioned MY number | W6 | Inbound call answered by the agent; only works for `provisioned` lines. |
| C3 | "Have its own PC and run on that" | Docker sandbox on VPS: allowlisted shell, scoped workspace, Playwright | W7 | 5 real tasks executed; each has a `tool_runs` audit row; a deliberately slow job is killed at 900 s. |
| C4 | "Help arrange my job, to-do list" | Tasks, recurring jobs, week planner, reminders | W3 | "Plan my week" produces ≥ 5 dated subtasks; operator can approve/edit/complete; a recurring task fires twice in a 2-day test. |
| C5 | "Let me monitor stats" | 5 dashboard metrics | W8 | Tasks completed, failures, API usage, voice minutes, $ spend — all read from `cost_ledger`/`tasks`, nothing hardcoded; values match the equivalent SQL query within 1 %. |
| C6 | "Send message, etc." | Telegram transport + Gmail read/draft/send | W6 | Telegram inbound creates a task; Gmail send happens only when an approval row exists. |
| C7 | "Access tasks given and done it" | Durable agent runs with checkpoints + resumability | W2 | Kill the API process mid-run; on restart the run resumes from the last checkpoint, not from step 1. |
| C8 | Memory | 3 tiers: session, durable facts, RAG | W2 (tiers 1–2), P1 (tier 3) | After 3 separate sessions the agent recalls a fact stated in session 1 without being told again. RAG: answers a question whose answer exists only in an ingested note, citing the source. |
| C9 | Bilingual EN / zh-TW, never mixed | Explicit language toggle drives STT locale + TTS voice + system prompt | W5 | 20/20 turns in each language contain zero characters from the other script (automated check). |
| C10 | WhatsApp | — | Deferred | — |
| C11 | GUI/vision desktop control | — | Deferred | — |
| C12 | Mobile native app | PWA only | P1 | Add-to-home-screen works; usable at 390 px width. |

---

## 3. Architecture

### 3.1 Shape

The single most important structural decision: **voice, chat, Telegram and phone are four transports over one agent graph.** Nothing in the agent knows what transport it is on.

```
                 ┌─────────────── TRANSPORTS ────────────────┐
  Browser (React)│  WS /ws/chat    (text)                    │
                 │  WS /ws/voice   (PCM audio, push-to-talk) │
  Telegram ──────┼─ POST /webhooks/telegram                  │
  PSTN  ─────────┼─ POST /webhooks/twilio/voice → WS media   │
                 └────────────────────┬──────────────────────┘
                                      │  Envelope
                                      ▼
                       ┌──────────────────────────────┐
                       │  FastAPI  (apps/api)         │
                       │  auth · rate limit · redact  │
                       └──────────────┬───────────────┘
                                      ▼
                       ┌──────────────────────────────┐
                       │  Agent runtime (LangGraph)   │
                       │  supervisor + 4 specialists  │
                       │  Postgres checkpointer       │
                       │  interrupt() approval gates  │
                       └──┬────────┬────────┬─────────┘
                          │        │        │
              ┌───────────┘        │        └────────────┐
              ▼                    ▼                     ▼
      ┌──────────────┐    ┌────────────────┐    ┌────────────────┐
      │ Tool registry│    │ Model router   │    │ Media pipeline │
      │ Pydantic     │    │ cheap / strong │    │ STT · TTS      │
      │ schemas      │    └────────────────┘    └────────────────┘
      └──────┬───────┘
             │
   ┌─────────┼──────────┬───────────┬──────────┬────────────┐
   ▼         ▼          ▼           ▼          ▼            ▼
 Tasks    Memory    PhoneLine    Gmail      Sandbox     Telegram
 (SQL)   (pgvector)  (Twilio)   (OAuth)   (Docker)      (Bot API)
```

### 3.2 Component contracts

| Component | Responsibility | Must not |
|---|---|---|
| `apps/web` | React SPA: chat, voice, tasks, dashboard, approvals | Hold provider secrets; call providers directly |
| `apps/api` | HTTP/WS surface, auth, redaction, validation | Contain agent policy logic |
| `agent/` | Graph, prompts, router, tool dispatch, checkpointer | Perform I/O directly — only via tools |
| `tools/` | One module per capability, Pydantic in/out | Read env secrets; be called outside the registry |
| `media/` | STT/TTS adapters, audio framing, VAD | Talk to the DB |
| `providers/` | Thin clients: Twilio, Deepgram, Azure, Google, Telegram | Leak provider errors verbatim to the UI |
| `infra/` | docker-compose, Caddy, migrations, backup scripts | — |

**Hard interface rule:** every capability is a `Tool` object with a Pydantic input model, a Pydantic output model, and `RiskLevel`. The LLM sees `model_json_schema()`. The backend validates before dispatch. Fail closed.

```python
# packages/contracts/tool.py  (canonical shape — implement exactly this)
class RiskLevel(StrEnum):
    READ = "read"  # no side effects
    WRITE = "write"  # reversible state change
    EXTERNAL = "external"  # leaves the system (email, call, message)
    IRREVERSIBLE = "irreversible"  # delete, spend, overwrite


class Tool(Protocol):
    name: str
    description: str  # one sentence, written for the model
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    risk: RiskLevel
    taints: bool  # output comes from outside our system

    # D-33: arguments are part of the decision (a shell command is approved by content).
    def requires_approval(self, args: BaseModel, ctx: ToolContext) -> bool: ...

    idempotent: bool
    timeout_s: float

    async def run(self, args: BaseModel, ctx: ToolContext) -> BaseModel: ...
```

### 3.3 Data model

PostgreSQL 16 + `pgvector`. Migrations via Alembic. The shape is binding; column names are not sacred.

```sql
CREATE TABLE users (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  email         text UNIQUE NOT NULL,
  totp_secret   text,                          -- encrypted at rest
  lang_default  text NOT NULL DEFAULT 'en',    -- 'en' | 'zh-TW'
  created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE conversations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id),
  transport text NOT NULL,                     -- 'web' | 'voice' | 'telegram' | 'pstn'
  lang text NOT NULL DEFAULT 'en',
  mode text NOT NULL DEFAULT 'text',           -- 'text' | 'voice'
  started_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE messages (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  conversation_id uuid NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  role text NOT NULL,                          -- 'user' | 'assistant' | 'tool' | 'system'
  content text NOT NULL,
  tainted boolean NOT NULL DEFAULT false,      -- true if derived from untrusted external content
  tokens_in int, tokens_out int,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE tasks (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id),
  title text NOT NULL,
  detail text,
  status text NOT NULL DEFAULT 'open',         -- open|in_progress|blocked|done|cancelled
  priority smallint NOT NULL DEFAULT 3,        -- 1 highest
  due_at timestamptz,
  parent_id uuid REFERENCES tasks(id) ON DELETE CASCADE,
  source text NOT NULL DEFAULT 'user',         -- user|agent|telegram|call
  recurrence text,                             -- iCal RRULE, null = one-shot
  created_at timestamptz NOT NULL DEFAULT now(),
  completed_at timestamptz
);
CREATE INDEX ON tasks (user_id, status, due_at);

CREATE TABLE task_events (
  id bigserial PRIMARY KEY,
  task_id uuid NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  event text NOT NULL, payload jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

-- Memory tier 2: durable facts. Provenance is mandatory — no fact without a source.
CREATE TABLE memory_facts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id),
  subject text NOT NULL, predicate text NOT NULL, object text NOT NULL,
  confidence real NOT NULL DEFAULT 0.8,
  source_message_id uuid REFERENCES messages(id) ON DELETE SET NULL,
  confirmed boolean NOT NULL DEFAULT false,    -- operator explicitly confirmed
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (user_id, subject, predicate, object)
);

-- Memory tier 3: RAG
CREATE TABLE memory_chunks (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id),
  source text NOT NULL,                        -- 'note:file.md' | 'email:<id>' | 'call:<id>'
  content text NOT NULL,
  embedding vector(1536),
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON memory_chunks USING hnsw (embedding vector_cosine_ops);

CREATE TABLE phone_lines (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id),
  e164 text NOT NULL,
  mode text NOT NULL,                          -- 'provisioned' | 'verified_caller_id'
  twilio_sid text,
  capability_voice_in boolean NOT NULL DEFAULT false,
  verified_at timestamptz,                     -- MUST be non-null to be usable as callerId
  monthly_cost_usd numeric(8,4) NOT NULL DEFAULT 0,
  status text NOT NULL DEFAULT 'active',       -- active|suspended|released
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (user_id, e164)
);

CREATE TABLE calls (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  phone_line_id uuid NOT NULL REFERENCES phone_lines(id),
  direction text NOT NULL,                     -- 'outbound' | 'inbound'
  remote_e164 text NOT NULL,
  twilio_call_sid text UNIQUE,
  status text NOT NULL,                        -- queued|ringing|in_progress|completed|failed|no_answer
  started_at timestamptz, ended_at timestamptz,
  duration_s int,
  transcript jsonb,                            -- [{"role":"agent"|"human","text":"...","ts_ms":int}]
  summary text,
  recording_uri text,                          -- NULL by default; recording disabled in phase 1
  cost_usd numeric(10,4) NOT NULL DEFAULT 0
);

-- Every billable unit of work. Single source for the dashboard and the budget guard.
CREATE TABLE cost_ledger (
  id bigserial PRIMARY KEY,
  ts timestamptz NOT NULL DEFAULT now(),
  kind text NOT NULL CHECK (kind IN ('llm','stt','tts','telephony','other')),
                                               -- NOT 'infra': fixed costs live in
                                               -- infra_costs so they cannot be counted twice (D-35)
  provider text NOT NULL,
  model text,
  units numeric(12,4) NOT NULL,                -- tokens|minutes|characters
  unit_name text NOT NULL,
  unit_price_usd numeric(12,8) NOT NULL,
  usd numeric(12,6) NOT NULL,
  conversation_id uuid REFERENCES conversations(id) ON DELETE SET NULL,
  call_id uuid REFERENCES calls(id) ON DELETE SET NULL,
  meta jsonb
);
CREATE INDEX ON cost_ledger (ts);

CREATE TABLE approvals (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  thread_id text NOT NULL,                     -- LangGraph thread id
  tool_name text NOT NULL,
  args jsonb NOT NULL,
  risk text NOT NULL,
  decision text,                               -- approved|edited|rejected|expired
  decided_at timestamptz,
  expires_at timestamptz NOT NULL DEFAULT now() + interval '30 minutes'
);

CREATE TABLE tool_runs (                       -- append-only audit trail
  id bigserial PRIMARY KEY,
  tool_name text NOT NULL,
  args jsonb, result jsonb,
  ok boolean NOT NULL,
  error text,
  ms int,
  conversation_id uuid,
  ts timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE voice_latency (
  id bigserial PRIMARY KEY,
  ts timestamptz NOT NULL DEFAULT now(),
  lang text NOT NULL,
  capture_ms int, network_ms int, stt_ms int,
  llm_first_token_ms int, llm_total_ms int,
  tts_first_byte_ms int, playback_ms int, total_ms int
);
```

### 3.4 Agent topology (this is what "multi-agent" means here — no more)

```
supervisor (router + planner)
├── executor    tools: shell, fs, code, browser          ← sandbox only
├── researcher  tools: web_fetch, rag_search             ← read-only, tainted output
├── scheduler   tools: task_*, calendar_*, remind        ← writes tasks/calendar
└── comms       tools: send_telegram, email_*, place_call ← always approval-gated
```

Rules:
- All four share **one** tool registry. No specialist may invent a tool.
- The supervisor may delegate at most **2 hops** deep. No agent-to-agent chatter.
- Every delegation is recorded in `tool_runs` as `tool_name='delegate:<specialist>'`.
- Output from `researcher` is marked `tainted=true` and can never directly trigger an `EXTERNAL` or `IRREVERSIBLE` tool (§7.2).
- **Kill gate at week 4** (§9.4): if the supervisor costs > 1 s p95 latency or > 30 % relative failure increase versus a single-agent baseline on the 30-case eval set, the supervisor is removed and the graph collapses to one agent with the same tools. Recorded in `DECISIONS.md`.

### 3.5 Where it runs

| Thing | Region | Why |
|---|---|---|
| VPS (2 vCPU / 4 GB) | **Singapore** (or Kuala Lumpur if available) | RTT to MY mobile networks and to Deepgram/Azure SG endpoints; target < 60 ms from Malaysia |
| Postgres | same VPS, `pgvector`, bound to 127.0.0.1 only | Data residency in-region |
| Caddy | same VPS, automatic TLS | Single public surface, HTTPS + WSS only |
| Sandbox container | same VPS, no published ports, egress-filtered | See §7.4 |

**Deployment:** `docker compose` (api, web-static via Caddy, postgres, sandbox-runner). No Kubernetes. No managed PaaS.

---

## 4. Locked stack

| Layer | Choice | Version target | Why this | Rejected, and why |
|---|---|---|---|---|
| Frontend | React + Vite + TypeScript + Tailwind | React 19 / Tailwind v4 | Operator's requirement; fastest path to a PWA | Next.js — SSR adds a server we don't need for one user |
| UI state | TanStack Query + Zustand | current | Server state vs local state separation | Redux — ceremony for one user |
| Backend | FastAPI + uvicorn | Python 3.12 | Async, typed, OpenAPI for free | Django — ORM/admin overhead we don't need; Flask — no async story |
| Deps | `uv` | current | Fast, lockfile-native | pip-tools |
| Lint/format | Ruff + `mypy --strict` on `agent/`,`tools/` | current | One tool, no debate | flake8+black+isort |
| Orchestration | **LangGraph** (OSS) | 1.2.x | Durable checkpointing + `interrupt()` for human approval, both first-class. 1.2.0 shipped 2026-05-11 and hardened persistence/streaming | CrewAI — role-play ergonomics, weaker durability; OpenAI Agents SDK — provider lock-in; Pydantic AI — excellent types, weaker long-running checkpoint/resume story; hand-rolled loop — you will rebuild checkpointing badly |
| Checkpointer | `langgraph-checkpoint-postgres` | current | Survives process death (capability C7) | InMemorySaver — loses runs; SQLite — single-writer contention |
| HTTP client | `httpx` | current | Async, timeouts, retries | requests |
| Validation | Pydantic v2 | current | Tool schemas ARE Pydantic models | dataclasses — no JSON Schema |
| DB | PostgreSQL 16 + pgvector | 16.x | One store for relational + vector; `hnsw` index | Chroma — a second database for no gain; Pinecone — cost + network hop |
| Migrations | Alembic | current | — | — |
| Scheduler | APScheduler (in-process, Postgres jobstore) | 3.x | One process, one user. Redis is not justified yet | Celery — needs broker + worker for zero benefit at this scale |
| STT | **Deepgram Nova-3** streaming, explicit `language=en` or `zh-TW` | — | $0.0048/min monolingual, 150–300 ms transcription latency; best cost/latency for phone audio | OpenAI Whisper API — not streaming, $0.006/min, higher latency; faster-whisper self-hosted — 1–3 s latency, no GPU on a $6 VPS |
| TTS | **Azure Speech** neural, `en-MY`/`en-US` + `zh-TW` | — | $15/1M chars with a monthly free allowance; strong zh-TW voice set; same vendor as the STT fallback | ElevenLabs — best quality, worst cost at this budget; Piper — free but robotic and weak zh-TW |
| Telephony | **Twilio Programmable Voice** + Media Streams (ConversationRelay *not* used) | — | MY numbers exist; documented per-minute rates; bidirectional media streams let us run our own pipeline | ConversationRelay — +$0.07/min for glue we're building anyway; Telnyx/Plivo — viable, comparable MY KYC, but Twilio's docs are better |
| Messaging | Telegram Bot API | — | Free, no approval, instant | WhatsApp Cloud API — deferred (business verification + templates + fees) |
| Email | Gmail API via Google OAuth | — | Operator's requirement | IMAP — worse auth model, no send-as hygiene |
| Sandbox | Docker, rootless, read-only rootfs, no docker socket | — | Blast-radius control is the whole point | Firecracker/gVisor — heavier ops; bare shell on the host — unacceptable risk |
| Browser automation | Playwright (Python) in its own container | current | Real Chromium, reliable | Selenium — slower, flakier |
| Egress control | iptables in the sandbox netns, allowlist | — | Prompt-injected code cannot exfiltrate | None |

**Version policy:** pin exactly, commit the lockfiles, bump only with a green eval run.

---

## 5. Integrations and credentials

### 5.1 Accounts to create (Week 1)

| # | Provider | Purpose | Free allowance / trial | KYC needed | Blocking? |
|---|---|---|---|---|---|
| 1 | Twilio | Voice | ~$15 trial credit (`VERIFY-LIVE` at signup) | **MY regulatory bundle: passport/ID + MY address proof** | **YES — start day 1, 1–3 day queue** |
| 2 | Deepgram | STT | credit on signup (`VERIFY-LIVE`) | email | no |
| 3 | Azure (Speech) | TTS + STT fallback | monthly free character allowance (`VERIFY-LIVE`) | card | no |
| 4 | OpenAI (or OpenRouter) | LLM | none | card | no |
| 5 | Google Cloud | Gmail + Calendar OAuth | free quota | OAuth consent screen; testing-mode refresh tokens expire in ~7 days (`VERIFY`) | no |
| 6 | Telegram | Bot | free | none | no |
| 7 | VPS provider | Hosting | — | card | no |
| 8 | Domain registrar | TLS + stable origin | — | — | no |
| 9 | S3-compatible (B2/Wasabi) | Backups | — | card | no |

### 5.2 Environment variables

`.env` on the VPS, `chmod 600`, owned by the service user, **never** committed, **never** passed into the agent context or the sandbox.

```dotenv
# --- core ---
APP_ENV=prod
APP_BASE_URL=https://jarvis.example.my
SECRET_KEY=                       # 32+ random bytes, signs sessions
DATABASE_URL=postgresql+psycopg://jarvis:***@127.0.0.1:5432/jarvis
OPERATOR_EMAIL=you@example.com

# --- models ---
OPENAI_API_KEY=
LLM_MODEL_STRONG=                 # planning + tool use
LLM_MODEL_CHEAP=                  # classification, formatting, summarisation
EMBEDDING_MODEL=

# --- speech ---
DEEPGRAM_API_KEY=
DEEPGRAM_LANG_EN=en
DEEPGRAM_LANG_ZH=zh-TW            # VERIFY: confirm Nova-3 zh-TW support (Spike B)
AZURE_SPEECH_KEY=
AZURE_SPEECH_REGION=southeastasia
AZURE_VOICE_EN=                   # VERIFY-LIVE: real voice id from the voice list
AZURE_VOICE_ZH=zh-TW-HsiaoChenNeural

# --- telephony ---
TWILIO_ACCOUNT_SID=
TWILIO_AUTH_TOKEN=
TWILIO_WEBHOOK_BASE=https://jarvis.example.my/webhooks/twilio
TWILIO_DEFAULT_LINE_E164=

# --- messaging / mail ---
TELEGRAM_BOT_TOKEN=
TELEGRAM_ALLOWED_CHAT_ID=         # hard allowlist — bot ignores every other chat
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GOOGLE_REFRESH_TOKEN=

# --- safety ---
SANDBOX_IMAGE=jarvis-sandbox:latest
SANDBOX_EGRESS_ALLOWLIST=api.twilio.com,api.deepgram.com,*.openai.com,*.microsoft.com
MONTHLY_BUDGET_USD=20
BUDGET_ALARM_USD=15
CALL_MAX_DURATION_S=600
```

### 5.3 Startup self-check

`apps/api` must, on boot, log and expose at `/api/health` a check of: DB reachable + migrations current, all required env vars present and non-empty, Twilio credentials valid (`GET /Accounts/{sid}`), Deepgram key valid, Azure key valid, sandbox image present, Telegram webhook registered, disk > 10 % free. Any failure → `/api/health` returns 503 naming the failing component. **No silent degradation.**

---

## 6. Cost model

All provider prices below were read from public pricing pages on **2026-11-16**. Re-verify before quoting them to anyone.

### 6.1 Unit prices (verified)

| Item | Price | Source note |
|---|---|---|
| Twilio MY local number | **$4.00 / month** | twilio.com voice pricing MY |
| Twilio outbound → MY **mobile** | **$0.0800 / min** | same |
| Twilio outbound → MY **landline** | $0.0555 / min | same |
| Twilio inbound to MY number | $0.0318 / min | same |
| Twilio toll-free MY number | $25.00 / month (inbound $0.1872/min) | same |
| Twilio browser/app call leg | $0.0040 / min | same |
| Twilio ConversationRelay | +$0.0700 / min | twilio.com (region availability `VERIFY`) |
| Deepgram Nova-3 streaming | $0.0048 / min (multilingual $0.0058) | deepgram.com/pricing |
| Azure neural TTS | $15 / 1M characters; **each Chinese character bills as 2** | Microsoft docs |
| OpenAI Whisper | $0.006 / min | OpenAI docs |
| OpenAI `gpt-4o-mini-transcribe` | ~$0.003 / min | third-party estimate — `VERIFY` |
| Realtime speech-to-speech (`gpt-realtime-2.1`) | $32 / 1M audio input tokens, $64 / 1M audio output tokens | OpenAI docs — **not used**, listed to show what we avoided |
| Twilio US local number | $1.15 / month | reference only |

### 6.2 Per-minute cost of a phone call (self-built pipeline)

| Component | USD / min |
|---|---|
| Telephony, outbound → MY mobile | 0.0800 |
| STT, Deepgram Nova-3 | 0.0048 |
| TTS, Azure (effectively $0 inside the monthly free allowance) | ≈ 0.0000 |
| LLM conversation (rough, mid-tier model, ~4 turns/min) | 0.0100 – 0.0250 |
| **Total** | **≈ $0.095 – $0.110 / min → ~$6 / hour** |

A 3-minute call ≈ **$0.30**. ConversationRelay would make it ≈ $0.15/min — that is why §4 rejects it.

### 6.3 Monthly envelopes

| Line | Lean ($20 ceiling) | Comfortable ($50) | Notes |
|---|---|---|---|
| VPS 2 vCPU / 4 GB SG | 6.00 | 12.00 | |
| Domain (amortised) | 1.20 | 1.20 | ~$14/yr |
| Backup object storage | 0.60 | 0.60 | |
| Twilio MY number | 4.00 | 4.00 | 1 line, `provisioned` |
| **Fixed subtotal** | **11.80** | **17.80** | |
| Left for usage | **8.20** | **32.20** | |
| TTS | 0.00 | 0.00 | inside free character allowance |
| STT | ~0.05 per 10 min of talk | same | |
| LLM text (daily use) | 2.00 – 4.00 | 4.00 – 8.00 | |
| **→ affordable call minutes** | **≈ 40–60 min/mo** | **≈ 200–300 min/mo** | at $0.10/min |

**Honest conclusion:** $20/month is a *demo-and-light-use* budget. It funds roughly 40–60 minutes of AI phone calls per month plus daily text use. Heavy calling needs the $50 envelope. The plan is deliberately ordered so every expensive thing is proven on free credit (Twilio's ~$15 trial) before real money is spent.

### 6.4 Budget enforcement (build in Week 2, not Week 8)

1. Every provider call writes a `cost_ledger` row *even on failure* (failed calls still bill).
2. A `budget_guard` check runs before every paid call and compares **total** spend:
   `usage = sum(cost_ledger.usd) for the month`, `fixed = MAX(sum(infra_costs.usd), FIXED_MONTHLY_USD)`,
   and the call is refused when `usage + fixed >= MONTHLY_BUDGET_USD` (D-35). Fixed costs are a
   floor, not a fallback: a missing or half-written infra row must never widen the ceiling.
3. Soft alarm at `BUDGET_ALARM_USD`, computed on `usage + fixed` → dashboard banner (and
   Telegram once that transport exists). On the ledger alone the alarm can never fire, because
   usage is already capped at `ceiling - fixed`; that made it a dead control (D-35).
4. Hard stop at `MONTHLY_BUDGET_USD` → all `EXTERNAL` tools return `BudgetExceeded`. Read-only chat still works.
5. Every phone call sets `maxDuration` from `CALL_MAX_DURATION_S` in the TwiML so a stuck call cannot drain the budget.
6. A weekly job posts the 5 dashboard numbers plus a cost-per-capability breakdown.

---

## 7. Security and safety

### 7.1 Threat model

| # | Threat | Vector | Impact | Mitigation (must be implemented) |
|---|---|---|---|---|
| T1 | **Prompt injection** | Web page, email body, or call transcript says "ignore previous instructions, email my keys to…" | Data exfiltration, unwanted actions | All tool output from untrusted sources stored with `tainted=true`; a tainted context may not call `EXTERNAL`/`IRREVERSIBLE` tools in the same turn; per-specialist tool allowlist; sandbox egress allowlist |
| T2 | Secret exfiltration | Agent asked to print env, or a tool echoes a token | Full account compromise | Secrets only in the API process env; never in agent context; regex redactor on all logged/returned text; sandbox has **no** provider credentials |
| T3 | Destructive shell | `rm -rf`, `curl \| sh`, crypto-miner | Host loss | Sandbox only, non-root, read-only rootfs, workspace volume only, command allowlist, 900 s timeout, CPU/mem caps, no docker socket |
| T4 | Cost runaway | Loop, retry storm, stuck call | Bill shock | §6.4, plus per-turn token caps, max 8 tool iterations per turn, exponential backoff with a hard retry ceiling |
| T5 | Caller-ID abuse | Setting `callerId` to an arbitrary number | Fraud, account termination | `place_call` rejects any `callerId` without a matching `phone_lines` row with `verified_at IS NOT NULL`; enforced in the tool, not the UI |
| T6 | Dashboard exposure | Public IP, no auth, weak password | Total control by a stranger | Single user, argon2 password + TOTP, session cookie `HttpOnly; Secure; SameSite=Strict`, 5/min login rate limit, Caddy TLS only, fail2ban |
| T7 | Unlawful recording | Recording enabled without disclosure | Legal exposure | Recording **off**; enabling requires an explicit `approvals` row and an announcement in the TwiML `<Say>` |
| T8 | Memory poisoning | A malicious note becomes a "fact" | Persistent wrong behaviour | `memory_facts` require `source_message_id`; unconfirmed facts are advisory only and never override an operator instruction |
| T9 | SSRF via browser | Playwright visits `http://169.254.169.254/` | Cloud metadata theft | Sandbox egress deny-by-default; metadata IP and RFC1918 blocked |
| T10 | Container escape | Kernel/docker-socket abuse | Host compromise | Rootless, no privileged, drop all caps, `no-new-privileges`, separate netns |
| T11 | Approval fatigue | Too many prompts → operator approves blindly | Safety theatre | Approvals batched per turn, one screen, plain-English diff; ≤ 3 approval prompts per turn by design |

### 7.2 Taint rule (the one rule that prevents most disasters)

> If any message in the current turn has `tainted = true`, the turn's tool budget **excludes** every tool with `risk ∈ {EXTERNAL, IRREVERSIBLE}`, and also `memory_write_fact` (D-34). There is no same-turn override: the operator re-asks in a new turn (D-19, D-40).

Implementation: the router computes `turn_tainted` before selecting tools and hard-filters the tool list passed to the model. Enforced in code, not in the prompt.

### 7.3 Approval policy

| Tool class | Examples | Risk | Approval |
|---|---|---|---|
| Read local | `task_list`, `rag_search`, `fs_read` (workspace) | READ | auto |
| Read remote | `web_fetch`, `gmail_read`, `calendar_read` | READ | auto; output marked `tainted` |
| Write local | `task_create`, `task_update`, `fs_write` (workspace) | WRITE | auto + audit row |
| Code execution | `shell` (allowlisted), `python_run` | WRITE | auto, sandbox only |
| Code execution | `shell` with a non-allowlisted binary | WRITE | **approval**, shows full command |
| Outbound comms | `send_telegram` to the allowlisted chat | EXTERNAL | auto |
| Outbound comms | `telegram_send` to any other chat | EXTERNAL | **ignored** (D-13: the bot only talks to `TELEGRAM_ALLOWED_CHAT_ID`) |
| Outbound comms | `mail_send`, `call_place` | EXTERNAL | **approval always** |
| Destructive | `fs_delete`, `task_delete`, `drop`, `truncate` | IRREVERSIBLE | **approval always** |
| Money | anything that can spend | IRREVERSIBLE | **approval always**, hard-capped |
| Credentials | any tool that would read a secret | — | **does not exist** |

Approval UX: the graph calls `interrupt({tool, args, human_summary, risk})`; the web app renders it; the decision resumes the same `thread_id`. Unanswered approvals expire in 30 minutes and default to **reject**.

### 7.4 Sandbox specification

```
image:             python:3.12-slim + playwright chromium + common CLIs
user:              uid 10001, non-root, no shell login
rootfs:            read-only; /workspace rw (bind-mounted, per-task dir)
capabilities:      drop ALL
no-new-privileges: true
network:           dedicated bridge; egress deny-by-default, allowlist only
dns:               filtered
limits:            --cpus=1 --memory=1g --pids-limit=256
timeout:           900 s hard kill (SIGTERM → SIGKILL)
secrets:           NONE. Ever. No provider keys, no DB URL.
audit:             every exec recorded to tool_runs with full argv
```

---

## 8. Compliance (Malaysia)

### 8.1 Data protection

- **PDPA 2010** applies to personal data processed in commercial transactions. A purely personal, single-user assistant sits at the low end of exposure, but `memory_facts`, `memory_chunks` and `calls.transcript` will contain third-party personal data (names, phone numbers, what they said). `LEGAL-REVIEW`.
- Engineering obligations adopted regardless: collect only what a feature needs; retention policy (default: transcripts 180 d, `tool_runs` 90 d, `cost_ledger` 24 mo); `/api/export` and `/api/erase` endpoints; encryption at rest for `users.totp_secret`; TLS everywhere; single-user access by construction.

### 8.2 Caller ID — the hard rules

Quoted from Twilio's documentation on 2026-11-16:

- Malaysia voice guidelines: **"Malaysian verified caller-IDs are not supported for outbound calls to Malaysia."**
- Verified Caller ID help article: *"For upgraded accounts we allow verified phone numbers to be used as a caller ID on outbound calls"* … *"you will not be able to receive inbound calls to Twilio over this number."*
- Trial accounts: outbound calls **only** to verified numbers, and a trial message plays before your TwiML executes.
- Non-US numbers require compliance registration **before** purchase.

Therefore:

1. Two line modes only: `provisioned` (Twilio-owned MY number, $4/mo, full duplex, KYC) and `verified_caller_id` (operator's own number, outbound-only, no monthly fee, may be silently dropped on MY→MY — **Spike A decides**).
2. **A third-party number you do not own can never be a caller ID.** Enforced in `place_call` (§7.1 T5). Presenting one is what Malaysian scam syndicates do; it is fraud and it ends the account.
3. The UI states the mode and its limits next to the number. No silent failures.

### 8.3 Calling conduct

- Calls are **operator-initiated**, one at a time, with a `maxDuration` cap. No dialers, no lists, no retry-until-answered.
- Every call opens with an **AI disclosure**: e.g. *"Hi, this is an AI assistant calling on behalf of <name>."* Non-negotiable, in the TwiML, before any other speech.
- **Recording off.** If enabled: announcement first, `approvals` row required, retention limit set.
- Network misuse: Communications and Multimedia Act 1998 s.233 covers improper use of network facilities/services, including communications made with intent to annoy, abuse, threaten or harass. Our use is consensual and identified — keep it that way. `LEGAL-REVIEW`.
- Do not call scraped numbers. Do not call at antisocial hours. Do not impersonate a person or an institution.

### 8.4 Language

English is the default. Traditional Chinese (`zh-TW`) is opt-in via the toggle. Auto-detect is **disabled by design** — operator requirement: never mix. STT locale and TTS voice move together with the toggle, atomically, and the system prompt is rewritten to instruct output in that language only.

---

## 9. Phase plan

Calendar assumes a start of **Mon 2026-11-16**. Shift the whole table if you start later. **Note:** weeks 6–8 land on the year-end holidays; if you observe them, either accept one week of slippage or start on 2027-01-04.

| Week | Dates | Phase | Deliverable | Definition of Done |
|---|---|---|---|---|
| 1 | Nov 16–22 | De-risk + spine | Accounts, KYC submitted, 2 spikes run, repo skeleton, DB migrated, auth working | Spikes A & B written up in `DECISIONS.md`; `/api/health` green; login works with TOTP |
| 2 | Nov 23–29 | Spine | LangGraph supervisor + 4 specialists + tool registry + Postgres checkpointer + chat WS + streaming UI + `cost_ledger` + budget guard | Tool-using text chat in the browser; killing the API mid-run resumes from checkpoint; every LLM call has a cost row; hard stop fires when the budget is faked to 0 |
| 3 | Nov 30–Dec 6 | Tasks & scheduling | `tasks` CRUD, RRULE recurrence, APScheduler, week planner, reminders | "Plan my week" yields ≥ 5 dated subtasks, editable and completable; a recurring task fires twice in a 2-day window |
| 4 | Dec 7–13 | **Kill gate** + memory | 30-case eval set; baseline vs supervisor; memory tiers 1–2; taint rule + approval UI | Eval run produces a table with p95 latency and pass rate for both topologies; written go/no-go in `DECISIONS.md`; taint rule demonstrably blocks an email |
| 5 | Dec 14–20 | Voice | Push-to-talk, STT, TTS, language toggle, typing⇄talking switcher, latency instrumentation | p95 end-of-speech→first-audio ≤ 3.0 s over 50 turns with per-stage timings stored; 20/20 turns per language pass the no-mixing check |
| 6 | Dec 21–27 | Phone + Telegram + Gmail | `PhoneLine` service, outbound + inbound calls, Telegram transport, Gmail read/draft/send | Real call to a real MY mobile with transcript + summary + cost; one inbound call answered; Telegram creates a task; Gmail send blocked without an approval row |
| 7 | Dec 28–Jan 3 | Sandbox | Docker sandbox, allowlisted shell, Playwright, egress allowlist, audits | 5 real tasks executed end-to-end with audit rows; a slow job killed at 900 s; a blocked egress attempt logged and refused |
| 8 | Jan 4–10 | Dashboard + ship | 5 metrics, PWA, backups, alarms, eval re-run, doc update | All 9 items in §1.3 demonstrated in one session; §6.3 replaced with measured numbers |

### 9.1 Weekly ritual (protect this)

Monday: pick the week's 3 DoD items. Friday: run the eval set, write to `DECISIONS.md` what changed and what slipped. No week ends without a green-or-red eval number.

### 9.2 Week-1 spikes (each ≤ 2 h, before dependent code)

**Spike A — Malaysian verified caller ID.** Add your own MY mobile as a Verified Caller ID on an upgraded Twilio account. Place an outbound call to another MY mobile. Record: was the call presented, was your verified number shown, or was it replaced/dropped? *Outcome decides whether `verified_caller_id` mode ships or is removed in favour of `provisioned` only.*

**Spike B — `zh-TW` STT.** Send a 30-second Traditional-Chinese audio file to Deepgram Nova-3 with `language=zh-TW`. Record accuracy by eye and latency. *If unsupported or poor, switch STT to Azure Speech (same vendor as TTS) and update §4.*

### 9.3 Things that must not be deferred past their week

- Budget guard (week 2) — before any calling exists.
- Taint rule (week 4) — before any email/browser tool exists.
- Sandbox egress allowlist (week 7) — must exist the moment Playwright does.
- AI disclosure in TwiML (week 6) — must exist the moment outbound calling does.

### 9.4 The multi-agent kill gate (week 4, formal)

Run the 32-case eval set (31 runnable at this point; D-39) twice: (a) supervisor + 4 specialists,
(b) single agent with the same tool registry. Measure pass@1, p95 turn latency, mean tokens,
mean tool calls.

**Collapse to single agent if any of:** p95 latency delta > 1000 ms · pass-rate delta < −30 % relative · mean tokens > 2× · more than 3 cases where a specialist produced a wrong routing decision that a single agent got right.

Write the numbers, the decision, and the evidence into `DECISIONS.md`. Do not relitigate for the rest of the project.

---

## 10. Test and evaluation plan

### 10.1 Layers

| Layer | Tool | Gate |
|---|---|---|
| Unit | pytest | ≥ 80 % on `agent/` and `tools/`; 100 % on the approval policy and the taint rule |
| Contract | pytest + recorded fixtures | Every provider client has one recorded-response test and one live smoke test behind `@pytest.mark.live` |
| Integration | pytest + test DB | Task lifecycle, checkpoint resume, budget guard trips |
| E2E | Playwright | Login → chat → task → approval → dashboard reflects the change |
| Voice | timing harness | Replays WAV fixtures through the real pipeline, asserts per-stage budget |
| Eval | 30-case set | Run weekly from week 4; pass@1 recorded |
| Chaos | manual script | Kill DB mid-task; revoke a token; fill the disk; expire the OAuth token |

### 10.2 Voice latency budget (p95, from end-of-speech to first audio)

| Stage | Target | Measurement |
|---|---|---|
| Browser capture stop → WS frame | 30 ms | client timestamp |
| Network MY → VPS (SG) | 60 ms | WS ping |
| Deepgram final transcript | 250 ms | `speech_final` event timestamp |
| LLM first token | 600 ms | provider stream header |
| LLM complete response (short) | 900 ms | last token |
| Azure TTS first byte | 350 ms | response header |
| Client playback start | 80 ms | `AudioContext` timestamp |
| **Total budget** | **≈ 2.27 s typical / 3.0 s p95** | `voice_latency` table |

The 2.27 s figure adds overlapping stages (LLM first token 600 ms *and* LLM complete 900 ms
cannot both sit on one path), so the real path is ≈1.37 s with streaming TTS and ≈1.67 s
waiting for the full completion (D-40). The acceptance value is the measured p95 of
`voice_latency.total_ms`, not this arithmetic. `capture_ms`, `network_ms` and `playback_ms`
can only be measured in the browser and must be posted by the client; when absent they are
NULL, never 0.

Failure policy: if p95 > 3.0 s, first fix is to stream TTS sentence-by-sentence instead of waiting for the full completion; second is a smaller/faster LLM for voice turns specifically.

### 10.3 The 32-case eval set (build in week 4; these are the seed cases)

Ten task-creation · five scheduling/conflict · five memory recall · three email send (must
require approval) · three call placement (must require approval) · two shell (one allowlisted,
one that must be refused) · two prompt-injection attempts that must be blocked · plus three
added by D-39: bilingual purity, budget guard, caller-ID guard. The allowlisted-shell case is
marked `requires_sandbox` and is skipped (visibly) until week 7, which makes the set 32 cases
with 31 runnable at the week-4 gate. Each case = input, expected tool sequence, forbidden tool sequence, expected final-answer shape.

---

## 11. Operations

| Concern | Decision |
|---|---|
| Deploy | `docker compose up -d --build` from the repo on the VPS; Caddy terminates TLS |
| Migrations | `alembic upgrade head` as a pre-start step; never auto-run in prod without a backup |
| Backups | Nightly `pg_dump`, monthly restore test, to S3-compatible storage, 14-day rotation |
| Logs | JSON to stdout → docker json-file driver with `max-size=50m, max-file=5`; no PII at info level |
| Metrics | `/metrics` (Prometheus format); the 5 business metrics come from SQL, not statsd |
| Uptime | External monitor hitting `/api/health` every 5 min → Telegram alert after 2 consecutive failures |
| Restart | `restart: unless-stopped`; agent runs resume from the checkpointer |
| Secrets rotation | Twilio/Deepgram/Azure/OpenAI quarterly or on suspected leak: new key → deploy → verify health → revoke old |
| Incident runbook | 1) `/api/health` 2) last 200 log lines 3) `cost_ledger` spike check 4) `tool_runs` for the failing tool 5) if unsure, stop the api container — the checkpointer makes this safe |
| Data retention | transcripts 180 d · `tool_runs` 90 d · `cost_ledger` 24 mo · `messages` 180 d |

---

## 12. Risk register

| # | Risk | Likelihood | Impact | Mitigation | **Kill criterion** |
|---|---|---|---|---|---|
| R1 | MY KYC rejects or stalls | Medium | Blocks week 6 | Submit day 1; fallback = Twilio US number ($1.15/mo) for outbound, accept foreign caller ID in testing | Not approved by end of week 3 → outbound via verified caller ID / US number; inbound marked deferred |
| R2 | Verified MY caller ID dropped on MY→MY | Medium | One mode unusable | Spike A in week 1 | Documented limitation; mode hidden in the UI |
| R3 | Multi-agent overhead outweighs benefit | **High** | +1–2 weeks | Kill gate week 4 | Collapse to single agent, keep the tools |
| R4 | Voice latency misses 3.0 s p95 | Medium | Poor UX | Streaming TTS, faster model for voice | p95 > 5 s after two fixes → ship typing-first, voice as P1 |
| R5 | Cost overruns the $20 envelope | **High** | Project paused | Budget guard + hard stop + max-call duration | A normal week costs > $8 → text-only, calls 2×/week |
| R6 | Prompt injection succeeds | Medium | Severe | Taint rule, sandbox egress, no secrets in sandbox | Any successful injection in the eval set is a **release blocker** |
| R7 | zh-TW STT quality poor | Medium | Bilingual feature weak | Spike B; Azure STT fallback | WER unusable → zh-TW moves to text-only, voice stays English |
| R8 | Scope creep (WhatsApp, GUI control, multi-user) | **High** | Never ships | §1.2 non-goals are frozen | Any new capability goes to a "phase 2" list; it does not enter week 8 |
| R9 | Solo-dev burnout at 8 h/day | Medium | Slips a week | Weekly ritual; holiday buffer noted in §9 | Take the buffer; don't compress the kill gate |

---

## 13. Open items

| # | Item | Owner | Needed by |
|---|---|---|---|
| O1 | Spike A result → `verified_caller_id` in or out | you | end W1 |
| O2 | Spike B result → STT vendor confirmed | you | end W1 |
| O3 | Real Azure voice ids for `en-MY` and `zh-TW` | you | W5 |
| O4 | Google OAuth testing-mode refresh-token expiry — publish the app or re-auth monthly | you | W6 |
| O5 | Retention periods confirmed (§8.1) | you | W8 |
| O6 | Legal review of §8 before any third-party calling at scale | you | before scale |

---

## 14. Glossary

| Term | Meaning |
|---|---|
| **Envelope** | The transport-neutral message the agent receives (covers text, audio transcript, Telegram message, phone transcript) |
| **Tainted** | Derived from content the operator did not author — web, email, call audio. Blocks external/irreversible tools |
| **PhoneLine** | A row describing a number the operator may use as caller ID, plus its mode and limits |
| **Kill gate** | A scheduled decision point with pre-agreed numeric thresholds that can remove an architecture choice |
| **Spike** | A ≤ 2 h experiment that resolves a `VERIFY` before dependent code is written |
| **DoD** | Definition of Done — the testable condition for a phase being complete |
