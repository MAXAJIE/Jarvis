---
name: jarvis-builder
description: >
  Build and extend the "Jarvis" personal AI agent — a single-user, self-hosted
  assistant on a cloud VPS with React+Tailwind frontend and Python/FastAPI
  backend, LangGraph orchestration, Deepgram STT, Azure TTS, Twilio telephony
  for Malaysia, Telegram and Gmail transports, and a Docker sandbox for code
  execution. Use when implementing, reviewing, or debugging any part of this
  repository, or when adding a new tool/capability to the agent.
  Trigger words: jarvis, planbook, tool registry, taint, approval gate,
  phone line, push-to-talk, sandbox runner.
license: private
---

# Jarvis Builder

You are the implementation agent for a **single-user self-hosted personal AI assistant**.
The authoritative specification is `PLANBOOK.md` in the repo root. The binding
decisions are in `DECISIONS.md`.

**Read in this order before writing code:** `DECISIONS.md` → this file → `PLANBOOK.md` §3 and §7.

The spec outranks your instincts. If the spec is wrong, say so and propose a change —
do not silently build something different.

---

## 1. Prime directives

These are not preferences. Violating any of them is a defect, regardless of whether
the feature "works".

| # | Directive |
|---|---|
| **P1** | **No secrets in code, tests, fixtures, logs, prompts, or the sandbox.** All secrets come from `os.environ` inside `apps/api` only. |
| **P2** | **Every capability is a registered `Tool`** with a Pydantic input model, a Pydantic output model, a `RiskLevel`, and an `idempotent` flag. No ad-hoc capability functions reachable by the model. |
| **P3** | **Enforce policy in code, never in prompts.** The approval gate and the taint rule filter the tool list before the model sees it. A prompt saying "please don't email anyone" is not a control. |
| **P4** | **Every billable provider call writes a `cost_ledger` row** — including failures, which still bill. |
| **P5** | **No numeric claim without a source.** Prices, limits, latencies go in code/comments with the provider page and the date read. If unverified, mark `VERIFY` and add an experiment. |
| **P6** | **Fail closed.** Unknown tool, unknown risk, missing approval, missing phone-line verification, exceeded budget → refuse and log. Never "assume allowed". |
| **P7** | **Never widen a blast radius to save a week.** No host shell, no docker socket in the sandbox, no `privileged`, no secrets in the sandbox, no arbitrary `callerId`. |
| **P8** | **The agent graph is transport-agnostic.** If you find `if transport == "voice"` inside `agent/`, the design has been broken — fix it with an adapter in `media/` or `transports/`. |
| **P9** | **No unrequested scope.** WhatsApp, GUI/vision control, multi-user, and realtime speech-to-speech are frozen non-goals. Do not build stubs for them. |
| **P10** | **One migration per schema change, forward-only, with a backup step documented.** |

---

## 2. Repository layout

```
.
├── PLANBOOK.md                  # spec (source of truth)
├── SKILL.md                     # this file
├── DECISIONS.md                 # binding decision log
├── docker-compose.yml
├── .env.example                 # every key, no values
├── apps/
│   ├── api/                     # FastAPI
│   │   ├── main.py
│   │   ├── auth.py              # password + TOTP, session cookie
│   │   ├── routes/
│   │   │   ├── chat.py          # WS /ws/chat
│   │   │   ├── voice.py         # WS /ws/voice
│   │   │   ├── tasks.py
│   │   │   ├── phone_lines.py
│   │   │   ├── approvals.py
│   │   │   ├── metrics.py
│   │   │   ├── health.py
│   │   │   └── webhooks/
│   │   │       ├── telegram.py
│   │   │       └── twilio.py
│   │   ├── db/
│   │   │   ├── models.py        # SQLAlchemy 2.0 typed
│   │   │   └── migrations/      # alembic
│   │   └── jobs/                # APScheduler: reminders, briefs, rollups
│   └── web/                     # React + Vite + TS + Tailwind
│       └── src/
│           ├── features/shell/  # top bar, left rail, bottom talk bar, icons
│           ├── features/core/   # command center panels, orb, waveform, system view
│           ├── features/chat/   # voice-first conversation: orb, transcript, composer
│           ├── features/tasks/  # task ledger
│           ├── features/approvals/
│           ├── features/tools/  # registered tool inventory, filter by risk
│           ├── features/memory/ # recent conversations, tier-1 counters
│           └── lib/api.ts, lib/ws.ts, lib/overview.ts, lib/approvals.ts
├── agent/
│   ├── graph.py                 # supervisor + specialists, compiled
│   ├── router.py                # model tier selection
│   ├── policy.py                # taint rule + approval decisions  ← highest test coverage
│   ├── prompts/                 # en.md, zh-TW.md  (one file per language)
│   └── checkpointer.py          # postgres saver wiring
├── tools/
│   ├── registry.py              # single source of registered tools
│   ├── tasks.py
│   ├── memory.py
│   ├── mail.py
│   ├── telegram.py
│   ├── phone.py                 # place_call — enforces phone_lines verification
│   ├── sandbox.py               # shell, python_run, browser (Docker exec)
│   └── web.py                   # web_fetch → always tainted
├── media/
│   ├── audio.py                 # framing, μ-law ↔ PCM for Twilio
│   ├── stt.py                   # Deepgram nova-3, one utterance in, one sentence out
│   └── tts.py                   # one sentence → mp3: Deepgram Aura (en), ElevenLabs (multilingual)
├── providers/
│   ├── catalog.py               # provider table: base_url, key_env, default model (adding one = a row)
│   ├── llm.py                   # HTTPChatClient (OpenAI-compatible) + ChainClient fallbacks
│   └── clients.py               # Twilio, Deepgram, Google OAuth, Azure speech
├── packages/
│   └── contracts/               # Tool protocol, RiskLevel, shared Pydantic models
├── sandbox/
│   ├── Dockerfile
│   └── egress.sh                # iptables allowlist
├── infra/
│   ├── Caddyfile
│   └── backup.sh
└── tests/
    ├── unit/, contract/, integration/, e2e/
    └── evals/cases.yaml         # 30-case set
```

---

## 3. Commands

```bash
# setup
uv sync --all-extras
docker compose up -d postgres
uv run alembic upgrade head

# dev
uv run uvicorn apps.api.main:app --reload --port 8000
cd apps/web && npm run dev     # pnpm is not installed on the dev machine (D-31 note)

# quality gates — all must pass before you claim a task is done
uv run ruff check . --fix
uv run ruff format .
uv run mypy agent tools packages --strict
uv run pytest -m "not live"          # default suite
uv run pytest -m live                # real provider calls, uses credit
uv run pytest tests/unit/test_policy.py -q   # must be 100% green always

# evals (weekly from week 4)
uv run python -m tests.evals.run --topology=supervisor
uv run python -m tests.evals.run --topology=single

# sandbox
docker build -t jarvis-sandbox:latest sandbox/
docker run --rm -it --network jarvis-sbx jarvis-sandbox:latest bash

# deploy
docker compose up -d --build
curl -fsS https://$APP_BASE_URL/api/health | jq
```

---

## 4. The Tool contract

Implement exactly this shape in `packages/contracts/tool.py`. Do not extend it
without a `DECISIONS.md` entry.

```python
from enum import StrEnum
from typing import Protocol
from pydantic import BaseModel


class RiskLevel(StrEnum):
    READ = "read"  # no side effects anywhere
    WRITE = "write"  # reversible state change inside our system
    EXTERNAL = "external"  # leaves our system: email, call, message
    IRREVERSIBLE = "irreversible"  # delete, overwrite, spend


class ToolContext(BaseModel):
    user_id: str
    conversation_id: str
    thread_id: str
    lang: str  # 'en' | 'zh-TW'
    transport: str  # 'web' | 'voice' | 'telegram' | 'pstn'
    turn_tainted: bool
    deadline_ms: int


class Tool(Protocol):
    name: str  # snake_case, verb_noun
    description: str  # ONE sentence, written for the model
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    risk: RiskLevel
    idempotent: bool
    timeout_s: float

    taints: bool  # output originates outside our system -> taints the turn

    # D-33: approval depends on the arguments, not just the context
    # (PLANBOOK §7.3 approves a shell call by inspecting its command).
    def requires_approval(self, args: BaseModel, ctx: ToolContext) -> bool: ...
    async def run(self, args: BaseModel, ctx: ToolContext) -> BaseModel: ...
```

Rules for a new tool:

1. Name it `verb_noun` (`task_create`, `email_send`, `call_place`). Never `do_stuff`.
2. `description` is one sentence and states the *effect*, not the implementation.
3. Both models are Pydantic and fully typed. No `dict` payloads, no `Any`.
4. `requires_approval(args, ctx)` is the **only** approval authority (D-33). It is derived
   from `risk`, the arguments, and the target (e.g. the Telegram chat id). `policy.py` must
   not hold a second risk table.
5. `run()` must:
   - raise `BudgetExceeded` if `ctx.turn_tainted` and `risk ∈ {EXTERNAL, IRREVERSIBLE}`;
   - write a `tool_runs` row in a `finally` block (success **and** failure);
   - write a `cost_ledger` row in a `finally` block **if it spends money**;
   - never log secrets, and never return a provider error message verbatim to the model.
6. Add it to `tools/registry.py` and to the correct specialist's allowlist.
7. Add one unit test (happy path), one refusal test (policy), one contract test (fixture).

### Tool inventory for v1 (do not exceed this)

| Tool | Risk | Approval | Notes |
|---|---|---|---|
| `task_list`, `task_get` | READ | auto | |
| `task_create`, `task_update`, `task_complete` | WRITE | auto | `task_update` may not change `status` to `done` without `completed_at` |
| `task_delete` | IRREVERSIBLE | **always** | |
| `memory_write_fact`, `memory_search` | WRITE / READ | auto | fact requires `source_message_id` |
| `web_fetch` | READ | auto | output `tainted=true`; robots.txt respected; 10 s timeout |
| `mail_read`, `mail_search` | READ | auto | output `tainted=true` |
| `mail_draft` | WRITE | auto | drafts only, never sends |
| `mail_send` | EXTERNAL | **always** | must reference an existing draft id |
| `telegram_send` | EXTERNAL | auto only to `TELEGRAM_ALLOWED_CHAT_ID`; otherwise **always** | |
| `call_place` | EXTERNAL | **always** | `callerId` must exist in `phone_lines` with `verified_at NOT NULL` |
| `shell` | WRITE | auto if binary allowlisted, else **always** | sandbox only |
| `python_run` | WRITE | auto | sandbox only |
| `browser_open`, `browser_click`, `browser_extract` | READ | auto | sandbox only, egress allowlisted |
| `fs_read` | READ | auto | workspace only (`var/workspace`) |
| `fs_write` | WRITE | auto | workspace only |
| `fs_delete` | IRREVERSIBLE | **always** | workspace only, single file (D-37) |
| `rag_search` | READ | auto | output `tainted=true`; keyword mode on SQLite |
| `calendar_read` | READ | auto | Google OAuth |
| `remind` | WRITE | auto | a dated task, not a second scheduler |
| `memory_fact_confirm` | WRITE | auto | implements T8's "confirmed" column |
| `delegate` | READ | auto | registered Tool; propagates taint (D-37) |

Total: **28 tools**. The eight rows above were required by PLANBOOK §3.4/§7.3 but absent
from the original inventory; D-37 records the change.

---

## 5. Policy engine (`agent/policy.py`) — the two rules that matter

```python
# Amended by D-33/D-34. The original sketch left WRITE untouched on a tainted turn,
# which let memory_write_fact persist injected content, and whitelisted a tool by name
# instead of by target. Both are closed below.
TAINT_BLOCKED_WRITE = frozenset({"memory_write_fact"})  # D-34


def filter_tools(tools: list[Tool], ctx: ToolContext) -> list[Tool]:
    """Called BEFORE the model chooses. The model must never see a tool it may not use."""
    out = []
    for t in tools:
        validate_tool(t)  # P6: unknown risk -> refused
        if not ctx.turn_tainted or t.risk in (RiskLevel.READ, RiskLevel.WRITE):
            if t.name in TAINT_BLOCKED_WRITE and ctx.turn_tainted:
                continue
            out.append(t)
    return out


def needs_approval(tool: Tool, args: BaseModel, ctx: ToolContext) -> bool:
    if ctx.turn_tainted and tool.risk in (RiskLevel.EXTERNAL, RiskLevel.IRREVERSIBLE):
        raise TaintedRefused(tool.name)  # defence in depth, never "ask"
    return tool.requires_approval(args, ctx)  # single authority (D-33)
```

**`turn_tainted` computation:** after every `READ` tool whose output originates outside our
system (`web_fetch`, `mail_read`, `mail_search`, `browser_extract`, inbound call audio
transcript), set `turn_tainted = True` for the remainder of the turn. Reset at turn start.

Untested policy = no policy. `tests/unit/test_policy.py` must cover: tainted + `mail_send`
→ filtered out; tainted + `call_place` → filtered out; tainted + `task_create` → allowed;
untainted + `mail_send` → present but approval required; unknown risk value → refused.

---

## 6. Definition-of-Done gates

Do not report a task complete until every applicable gate passes. Report the gate
results, not a summary sentence.

| Gate | Check | Evidence |
|---|---|---|
| G1 | `ruff check` and `ruff format --check` clean | command output |
| G2 | `mypy --strict` clean on `agent/`, `tools/`, `packages/` | command output |
| G3 | `pytest -m "not live"` green; `test_policy.py` at 100 % | pytest summary line |
| G4 | New tool: schema test + refusal test + contract fixture exist | file paths |
| G5 | If it spends money: `cost_ledger` row appears, verified with a SQL query | query + row |
| G6 | If it has side effects: `tool_runs` row appears on success **and** on forced failure | two rows |
| G7 | If it is user-visible: driven once in a real browser (login, every tab, one approval approve **and** one reject), or a Playwright E2E when one exists | screenshot / recorded clicks + the defects it found |
| G8 | If it changes schema: Alembic migration exists, upgrades from empty, and downgrade path documented | migration id |
| G9 | If it changes the agent graph: eval set re-run, numbers recorded in `DECISIONS.md` | eval table |
| G10 | `PLANBOOK.md` updated if behaviour deviates from spec | diff |

---

## 7. Verification recipes

"Works on my machine" is not evidence. Each integration has one canonical proof.

**Twilio outbound call**
```bash
uv run python -m scripts.verify_call --to +60XXXXXXXXX
# PASS iff: calls.status='completed', duration_s>0, cost_usd>0,
#           transcript has >=1 'agent' and >=1 'human' turn,
#           the first agent utterance contains the AI disclosure string.
# AND you listened to the call yourself.
```

**Twilio inbound**
Call the provisioned number from your mobile. PASS iff `calls` gains an `inbound` row with
`capability_voice_in=true` on the line, and the agent speaks first.

**Caller-ID guard (must fail)**
```bash
uv run python -m scripts.verify_call --to +60123456789 --caller-id +60199999999
# PASS iff it raises CallerIdNotOwned and writes NO ledger row and NO outbound call.
```

**STT**
```bash
uv run python -m scripts.verify_stt --lang zh-TW --file tests/fixtures/zh_tw_30s.wav
# PASS iff transcript is Traditional Chinese, contains no Simplified-only glyphs,
#       and reported latency < 400 ms p95 over 10 runs.
```

**TTS**
```bash
uv run python -m scripts.verify_tts --lang zh-TW --text "你好，我而家幫你安排行程。"
# PASS iff audio duration > 0, voice id is a zh-TW voice, and the ledger row shows
#       characters billed = 2x code points (per Microsoft billing rule).
```

**Voice latency**
```bash
uv run python -m scripts.verify_latency --runs 50
# PASS iff p95(end_of_speech → first_audio) <= 3000 ms and every stage is under
#       the PLANBOOK §10.2 budget; prints a per-stage table.
```

**Sandbox**
```bash
uv run python -m scripts.verify_sandbox
# PASS iff: allowlisted command runs; `rm -rf /` refused; `curl https://example.com`
#           refused by egress; sleep 901 killed at 900 s; no env secret visible in `env`.
```

**Budget guard**
```bash
uv run python -m scripts.verify_budget --force-spend 25
# PASS iff subsequent EXTERNAL tools raise BudgetExceeded and READ tools still work.
```

**Checkpoint resume**
```bash
uv run python -m scripts.verify_resume
# PASS iff a run interrupted mid-tool resumes at the interrupted step (proved by
#          counting tool_runs rows: no duplicate completed steps).
```

---

## 8. Failure playbook

| Symptom | First check | Then |
|---|---|---|
| Agent loops | `tool_runs` for repeated identical args | add dedupe + lower max iterations; check the tool returns a *stable* error, not a novel one each retry |
| Latency regression | `voice_latency` per-stage table | isolate the stage; do not "optimise the LLM prompt" before measuring |
| Cost spike | `cost_ledger` grouped by `provider, kind` | find the retry storm; check for a stuck call with no `maxDuration` |
| Tool refuses unexpectedly | `turn_tainted` value for that turn | confirm a `READ` tool didn't poison the turn; that is by design |
| Approval prompt never appears | is `requires_approval` on the *instance* or the *class*? | policy must be evaluated per call with `ctx` |
| Twilio call connects but no audio | μ-law vs PCM framing in `media/audio.py` | Twilio Media Streams are 8 kHz μ-law base64; Deepgram wants linear16 — convert exactly once |
| Chinese answer contains Simplified glyphs | prompt file selection | `prompts/zh-TW.md` must be loaded, and the system message must forbid mixed output |
| Alembic "relation already exists" | stray migration | never edit an applied migration; add a new one |
| `/api/health` 503 | the named component | do not paper over it with a try/except |

---

## 9. Banned

- `eval`, `exec`, or `pickle` on model output.
- `shell=True` outside the sandbox container.
- Passing any `os.environ` value into a prompt or a tool result.
- `# type: ignore` without a comment explaining why.
- `except Exception: pass`.
- Storing a phone number as a `callerId` that is not in `phone_lines`.
- Calling Twilio `Calls.create` without `maxDuration`/`TimeLimit`.
- Enabling call recording without an approval row and an announcement.
- Adding a tool directly to the LLM's tool list — the registry is the only path.
- Committing `.env`, `*.pem`, or any fixture containing a real phone number or email.
- Writing a "TODO: add approval later" on an `EXTERNAL` tool.
- Mocking the policy engine in a test that claims to prove safety.

---

## 10. When to stop and ask

Stop and ask the operator — do not guess — if:

1. A spec requirement is impossible or contradictory (e.g. Spike A proves `verified_caller_id` cannot be presented).
2. A change would require a new provider, a new paid service, or would raise the monthly ceiling.
3. A change would require loosening a Prime Directive (P1–P10).
4. The eval set disagrees with the spec's architecture choice (report numbers, propose the kill).
5. Legal/compliance ambiguity in §8 (caller ID, recording, retention) becomes a design decision.

Otherwise: proceed, implement, verify with the recipe in §7, and report gate results.

---

## 11. Reporting format

End every implementation turn with:

```
CHANGE:   <one line>
FILES:    <paths touched>
GATES:    G1 ✅  G2 ✅  G3 ✅  G4 ✅  G5 ✅  G6 n/a  G7 ✅  G8 ✅  G9 n/a  G10 n/a
EVIDENCE: <the actual command output / row counts / latency numbers>
RISK:     <what could break, or "none identified">
NEXT:     <the next DoD item, or a question>
```

No gate may be marked ✅ without pasted evidence. "Should work" is not evidence.
