# DECISIONS — binding log

**Rule:** this file wins over `PLANBOOK.md` and over any agent's instinct. Every decision
below is dated and has a revisit trigger. Changing one requires a new entry that says
what it supersedes, what it invalidates, and what must be re-tested.

Companion documents: `PLANBOOK.md` (what to build), `SKILL.md` (how to work).

---

## A. Operator answers (2026-11-16) — the raw inputs

| Q | Asked | Answer |
|---|---|---|
| A1 | One demoable thing in 8 weeks | "8 weeks should done the whole project" |
| A2 | Hours/week + skill | 8 h/day consistently; upper-B to C |
| A3 | Monthly API/infra ceiling | **A — under $20** |
| A4 | Jurisdiction | **Malaysia** |
| B1 | Agent shape | **C — multi-agent with specialists** |
| B2 | Models | **B — cheap router + strong model** |
| B3 | Memory depth | **C — profile facts + RAG over notes/docs/emails** |
| B4 | Autonomy | **B — act on low risk, ask on irreversible** |
| C1 | Wake word vs push-to-talk | **Push-to-talk** |
| C2 | Voice latency tolerance | **2–3 s is fine** |
| C3 | Languages | **English + Chinese — never mix** (later: **Traditional**, English default) |
| C4 | Voice quality | **B — good (not cloned, not free/robotic)** |
| D1 | "Make a phone call" means | **A — real external number, and B — it can call me** |
| D2 | Inbound number now? | No for this phase |
| D3 | Chat channel | **Telegram now, WhatsApp later** |
| D4 | Email/calendar | **Gmail now** |
| E1 | Where it lives | Cloud server (localhost *or* online, planned cloud) |
| E2 | PC powers | **B — shell + browser automation; no GUI/vision** |
| E3 | OS | Windows (dev machine) |
| F1 | Users | Just me |
| F2 | Mobile | Web page is good |
| F3 | Dashboard numbers | tasks completed, failures, API usage, + 2 reserve |
| F4 | Must stay local | Nothing |
| F5 | Deadline | Open-ended, wants a few weeks |

Follow-up correction (same day): **Traditional Chinese, English default** · **Gmail** ·
cuts approved.

---

## B. Binding decisions

### D-01 — Budget is the primary design constraint
**Decided:** architecture is shaped by the $20/month ceiling, not by ambition.
**Consequence:** no realtime speech-to-speech, no managed voice-agent platform, no self-hosted LLM, no multi-user. Every phase proves its expensive part on Twilio's ~$15 trial credit first.
**Because:** a per-minute voice stack at ~$0.10/min against $8.20 of usable budget is ~40–60 call minutes/month. Anything more expensive cannot be used daily.
**Revisit if:** the ceiling moves to $50+ (see PLANBOOK §6.3), which widens calls to ~200–300 min/mo.

### D-02 — Voice is turn-based, not realtime
**Decided:** push-to-talk → STT → LLM → TTS → playback. No `gpt-realtime-*`.
**Supersedes:** the instinct to build a live duplex voice loop.
**Because:** operator accepted 2–3 s latency (C2 = A); realtime audio is $32/1M input and $64/1M output tokens versus ~$0.10/min for the turn-based stack, and requires a different, harder state machine.
**Invalidates:** nothing. Leaves the door open later — the transport adapter boundary is where a realtime pipeline would slot in.
**Revisit if:** measured p95 exceeds 5 s after both latency fixes in PLANBOOK §10.2.

### D-03 — One agent graph, four transports
**Decided:** chat, voice, Telegram, PSTN are adapters over the same LangGraph graph.
**Because:** four separate agent loops means four divergent behaviours and four places to fix a policy bug. Also means the taint rule is enforced once.
**Enforced by:** SKILL.md P8; `if transport ==` inside `agent/` is a defect.

### D-04 — LangGraph 1.2.x as the orchestrator
**Decided:** LangGraph OSS, Postgres checkpointer.
**Because:** durable checkpoint/resume and `interrupt()` for human approval are first-class and are exactly capabilities C7 and B4. 1.2.0 shipped 2026-05-11 and hardened persistence and streaming.
**Rejected:** CrewAI (weaker durability), OpenAI Agents SDK (provider lock-in), Pydantic AI (great types, weaker long-running resume), hand-rolled loop (you rebuild checkpointing badly).
**Revisit if:** LangGraph's token overhead shows up as > 40 % of turn cost in `cost_ledger`.

### D-05 — Multi-agent is capped at 1 supervisor + 4 specialists
**Decided:** executor, researcher, scheduler, comms — sharing **one** tool registry, max 2 delegation hops.
**Because:** operator chose C (multi-agent), but an unbounded agent swarm at 8 weeks and $20/mo is how this project dies. The cap preserves the intent (separation of concerns) without the failure modes (routing errors, token multiplication).
**Enforced by:** the week-4 kill gate (D-06). All delegation logged to `tool_runs`.

### D-06 — The multi-agent kill gate is binding
**Decided:** at week 4, compare supervisor+specialists against a single agent on the 30-case eval set. Collapse to single agent if **any** of: p95 latency delta > 1000 ms · pass-rate delta < −30 % relative · mean tokens > 2× · > 3 cases where a specialist mis-routed and a single agent got it right.
**Because:** multi-agent architectures frequently lose to single agents on small tool sets, and the operator's choice was made before measurement existed.
**Invalidates:** D-05's topology only — the tool registry and prompts survive.
**Revisit:** never relitigate after the gate result is written.

### D-07 — Malaysia telephony via Twilio
**Decided:** Twilio Programmable Voice + bidirectional Media Streams; **not** ConversationRelay.
**Because:** MY numbers exist at $4.00/mo; outbound → MY mobile is $0.0800/min and inbound $0.0318/min; ConversationRelay adds $0.07/min for glue we are building anyway, which is ~70 % overhead on the telephony line at our volume.
**Rejected:** Telnyx/Plivo (comparable MY KYC, less mature docs).

### D-08 — Two phone-line modes, and no third
**Decided:** `provisioned` (Twilio-owned MY number: inbound + outbound, KYC, $4/mo) and `verified_caller_id` (operator's own number: outbound only, no inbound, no monthly fee).
**Hard rule:** a number not present in `phone_lines` with `verified_at IS NOT NULL` can never be a `callerId`. Enforced inside `call_place`, not the UI.
**Because:** Twilio permits verified *owned* numbers as outbound caller ID, explicitly does not support inbound on them, and its Malaysia guidelines state: *"Malaysian verified caller-IDs are not supported for outbound calls to Malaysia."* Presenting a number you do not control is the technique used in Malaysian scam-syndicate cases and is fraud.
**Supersedes:** operator request (2026-11-16) "I just input a Malaysian number and it straight away uses it to call." The *intent* is implemented (type a number → it works); the *spoofing variant* is refused.
**Revisit if:** Spike A shows verified MY caller IDs present correctly.

### D-09 — Inbound calling deferred behind KYC
**Decided:** no inbound number in phase 1 until the MY regulatory bundle is approved; inbound ships in week 6 only if approved.
**Because:** Twilio requires compliance registration *before* a non-US number can be purchased; the MY bundle needs a passport/ID plus Malaysian address proof and takes days.
**Kill criterion (PLANBOOK R1):** not approved by end of week 3 → outbound-only via verified caller ID / US number, inbound marked deferred.

### D-10 — Deepgram Nova-3 for STT with an explicit language, never auto-detect
**Decided:** `language=en` or `language=zh-TW` chosen by the UI toggle.
**Because:** $0.0048/min and 150–300 ms transcription latency; auto-detect is the single most common cause of language mixing, which is an explicit operator prohibition.
**`VERIFY`:** Nova-3 `zh-TW` locale support (Spike B). If weak → Azure Speech STT (same vendor as TTS).

### D-11 — Azure Speech for TTS
**Decided:** Azure neural voices, `en-MY`/`en-US` + `zh-TW`.
**Because:** $15/1M characters with a monthly free allowance that covers personal volume → effectively $0 in the Lean envelope; strong zh-TW voice set. Note Microsoft bills **each Chinese character as 2**, so budget accordingly.
**Rejected:** ElevenLabs (best quality, wrong cost tier), Piper (robotic, weak zh-TW).

### D-12 — Traditional Chinese, English default, no auto-detect
**Decided:** `zh-TW` throughout; prompt files are per-language (`prompts/en.md`, `prompts/zh-TW.md`); the toggle moves STT locale, TTS voice and system prompt atomically.
**Because:** operator corrected "Chinese" to Traditional and set English as default; mixed-language output is prohibited.
**Acceptance:** 20/20 turns per language contain zero characters from the other script (automated check).

### D-13 — Telegram first, WhatsApp deferred
**Decided:** Telegram Bot API as the messaging transport, hard-allowlisted to one chat id.
**Because:** free, no approval process, instant. WhatsApp Cloud API needs Meta business verification, message template approval, and per-conversation fees — none of which buys anything in phase 1.
**Deferred to phase 2**, not stubbed.

### D-14 — Gmail over Google OAuth
**Decided:** Gmail API (`mail_read`, `mail_search` tainted; `mail_draft`; `mail_send` always approval-gated).
**Because:** operator's answer (D4). Calendar is read-only and optional.
**`VERIFY`:** testing-mode OAuth refresh tokens expire in ~7 days; decide publish-the-app vs monthly re-auth (Open item O4).

### D-15 — Single store: PostgreSQL 16 + pgvector
**Decided:** one database for relational data, durable agent checkpoints, and vector memory (`hnsw` cosine index).
**Because:** a second database (Chroma/Pinecone) adds a network hop, a bill, and a backup problem for zero benefit at this scale.

### D-16 — APScheduler in-process, not Celery
**Decided:** APScheduler with a Postgres jobstore inside the API process.
**Because:** one process, one user, no throughput requirement. Celery would add a broker and a worker to operate.
**Revisit if:** a job must survive at a scale where the API is horizontally scaled — which is out of scope by D-17.

### D-17 — Single user, no tenancy
**Decided:** one `users` row. Password (argon2) + TOTP. No registration, no invites, no roles.
**Because:** multi-user was never requested and would cost ~3 weeks (auth, isolation, rate limits, billing).

### D-18 — The agent's "PC" is a Docker sandbox on the VPS, never the Windows laptop
**Decided:** shell + Playwright inside a rootless, read-only, egress-filtered container with a per-task workspace.
**Because:** operator asked for shell + browser automation only (no GUI/vision), and controlling their real desktop is the single largest security liability in the project. It also decouples the agent from whether their laptop is awake.
**Limits:** 900 s timeout, 1 CPU, 1 GB, pids 256, capabilities dropped, no docker socket, no secrets in the container.

### D-19 — The taint rule is enforced in code
**Decided:** any turn containing output from a non-operator-authored source sets `turn_tainted`, and the tool list handed to the model **excludes** `EXTERNAL` and `IRREVERSIBLE` tools for the rest of that turn.
**Because:** prompt injection via a web page, email, or phone transcript is the highest-severity realistic attack; instructions in a prompt are not a control.
**Consequence:** sometimes the agent will refuse a legitimate follow-up ("now email that summary") — by design, the operator re-asks in a fresh turn.

### D-20 — Approval policy is fixed by risk class
**Decided:** READ and sandboxed WRITE auto · `EXTERNAL` and `IRREVERSIBLE` require approval · `mail_send`, `call_place`, `task_delete`, anything spending money, and non-allowlisted shell are **always** approval-gated · approvals expire in 30 minutes and default to reject.
**Because:** operator chose B4 (act on low risk, ask on irreversible) — this is that answer as an enforceable table.

### D-21 — Budget guard ships in week 2, before any calling exists
**Decided:** `cost_ledger` written on every billable call (including failures); soft alarm at $15; hard stop at the monthly ceiling; `maxDuration` on every call.
**Because:** the ceiling is $20 and telephony is ~$0.10/min. A retry storm or a stuck call can consume the month in an hour.

### D-22 — Recording off by default
**Decided:** `calls.recording_uri` is NULL; enabling recording requires an `approvals` row and an announcement in the TwiML before any capture.
**Because:** recording consent law and PDPA exposure, and nothing in phase 1 needs recordings (transcripts suffice).

### D-23 — AI disclosure on every call
**Decided:** the first agent utterance on any call states that it is an AI assistant calling on the operator's behalf.
**Because:** calling conduct (§8.3), and because a deceived callee is a real person taking a real action.

### D-24 — Hosting region: Singapore
**Decided:** VPS in Singapore (or Kuala Lumpur if offered).
**Because:** the latency budget in PLANBOOK §10.2 allocates 60 ms to network between Malaysia and the VPS; a US or EU instance breaks the 3.0 s p95 target before any code runs.

### D-25 — Deployment is docker compose on one VPS
**Decided:** compose + Caddy. No Kubernetes, no managed PaaS, no CI/CD pipeline beyond a deploy script.
**Because:** one host, one user, 8 weeks. CI is `ruff`/`mypy`/`pytest` run locally and on a pre-push hook.

### D-26 — Prices are cited, never remembered
**Decided:** every price in code or docs carries its source and the date read (2026-11-16 baseline). Unverified figures are marked `VERIFY` and get an experiment.
**Because:** the entire plan's feasibility rests on the cost model; a stale price silently invalidates D-01 and D-07.

### D-27 — The 5 dashboard metrics are derived, never hardcoded
**Decided:** tasks completed, failures, API usage (tokens + calls), voice minutes, USD spend this month — all from SQL over `tasks`, `tool_runs`, `cost_ledger`.
**Because:** operator asked for 2 reserve slots; these two (voice minutes, spend) are already in the ledger, so they cost nothing to add and are the ones that predict a budget breach.
**Revisit:** swap either reserve slot for a metric you actually look at.

### D-28 — Non-goals are frozen
**Decided:** WhatsApp, GUI/vision control, multi-user/SaaS, native mobile app, self-hosted LLM, realtime speech-to-speech, caller-ID spoofing, autodialing, and "AGI" are out of scope for this build.
**Because:** each is a project on its own; scope creep is the highest-likelihood failure mode in the risk register (R8). New capability requests go to a phase-2 list and do not enter week 8.

### D-29 — Eighth-week honesty
**Decided:** the 8 weeks deliver a *scoped* v1 (capabilities C1–C9 minus P1 items), not "the whole project" as originally phrased.
**Because:** "whole project" in the original brief included WhatsApp, GUI control, and open-ended AGI-like behaviour. At 8 h/day × 8 weeks ≈ 380 h with a single developer, this scope is already tight.
**Consequence:** P1 items (RAG tier 3, PWA polish) may slip; deferred items are scheduled into a phase 2 that starts only after all 9 items in PLANBOOK §1.3 pass in one session.

### D-30 — Malaysian KYC starts on day 1
**Decided:** submit the MY regulatory bundle (passport/ID + Malaysian address proof) in the first 24 hours, before any code.
**Because:** it is a human queue with reject-and-resubmit cycles, and it gates both inbound calling (D-09) and the `provisioned` mode (D-08). It is the only external dependency that can block a week.

---


### D-31 — Dev runs on SQLite; PostgreSQL is the production path only
**Decided:** `DATABASE_URL` defaults to `sqlite+aiosqlite`, and the dev profile uses
`langgraph-checkpoint-sqlite`. The Alembic migration is portable and applies from empty on
SQLite; PostgreSQL-specific objects (pgvector `vector(1536)`, HNSW index) are not created.
**Because:** the build machine has no Docker and no PostgreSQL. Refusing to build was the
alternative, and it would have proved nothing.
**Consequence, stated plainly:** memory tier 3 (vector RAG) is **unverified** in this profile,
and G8's "upgrades from empty" evidence is SQLite-only. C7 resume *is* verified, including
across a fresh process. Anything unverified is reported as unverified.
**Revisit if:** Postgres becomes available; then run `alembic upgrade head` and add migration
0002 with the vector column and HNSW index.

### D-32 — The stub model is a dev-only provider that fails closed outside dev
**Decided:** `LLM_PROVIDER=stub` is the default. `APP_ENV=prod` with any non-openai provider
makes the process exit at startup, and `/api/health` reports `llm` as a degraded component
(503) whenever the stub is in use.
**Because:** auto-switching to a real model when a key appears is silent degradation (P6's
opposite). A stub that masquerades as an assistant is worse than one that announces itself.
**Consequence:** in the stub profile `/api/health` is **expected** to be 503. The week-1 DoD
"health green" is deferred until real keys exist, and that deferral is recorded in section E.

### D-33 — Tool contract v2: `requires_approval(args, ctx)` and `taints`
**Supersedes:** PLANBOOK §3.2 (`requires_approval: bool`) and SKILL §4 (`requires_approval(self, ctx)`).
**Because:** (1) PLANBOOK §7.3 requires approval to depend on the *command* ("shell with a
non-allowlisted binary"), which a context-only signature cannot express; (2) three different
authorities for approval existed (the `bool` attribute, the tool method, and a second risk
table inside `policy.needs_approval`). Now there is one: the tool instance. `taints` moves the
"output is from outside our system" fact onto the tool, so the taint set has a single source
of truth instead of a name list that drifts.
**Invalidates:** SKILL's `ALWAYS_ALLOWED_EXTERNAL` sketch — it is gone. `telegram_send` now
checks its target inside the tool, which is what "target-checked separately" was supposed to mean.

### D-34 — Tainted turns lose `memory_write_fact`, and nothing else extra
**Decided:** on a tainted turn the model may still use `shell`, `python_run`, `mail_draft`,
`fs_write` and the rest of WRITE; it may **not** use `memory_write_fact`.
**Because:** SKILL §5 removed every tool that is EXTERNAL/IRREVERSIBLE and left WRITE wide
open, which made prompt-injection to durable memory to execution a complete chain. T8's
`source_message_id` cannot stop it: a poisoned message has an id. Durable memory is the one
write that outlives the taint, so it is the one write removed. `mail_draft` and `shell` stay
because C3 ("scrape then write a file") and §1.3-7's read-then-draft flow need them, and their
damage is bounded by approval on the send/execute step.
**Test:** `tests/unit/test_policy.py::test_tainted_turn_hides_memory_write_fact` and
`::test_tainted_turn_keeps_shell_python_and_draft`.

### D-35 — Budget ceiling is total spend; fixed costs are a floor in their own table
**Supersedes:** the implicit reading of §6.4 that only `cost_ledger` counts.
**Decided:** fixed monthly costs (VPS, domain, Twilio number) live in `infra_costs`
(PK `(period_start, line)`), never in `cost_ledger` (whose `kind` CHECK excludes `'infra'`).
The guard uses `fixed = MAX(sum(infra_costs for month), FIXED_MONTHLY_USD)` and stops
spend-capable tools at `ledger + fixed >= MONTHLY_BUDGET_USD`. The $15 alarm is computed on
the same total.
**Because:** §6.3's arithmetic only balances as total spend ($11.80 + $8.20 = $20). With the
ledger alone, real spend could reach $31.80, and the $15 alarm could never fire because usage
is capped at $8.20 — a dead control. MAX, not a zero-check, so a half-written ledger cannot
make the ceiling look generous.
**Test:** `tests/unit/test_policy.py` budget cases and
`tests/api/test_api.py::test_task_lifecycle_and_dashboard`.

### D-36 — Mail drafts are files, not a table
**Decided:** `mail_draft` writes `var/drafts/<id>.json`; `mail_send` refuses an id with no file,
and the approval screen renders the body (and flags drafts written in a tainted turn).
**Because:** PLANBOOK §3.3 has no drafts table, and inventing one is a schema change whose only
benefit is a query nobody needs. The rule that matters — "send may only reference something
that was drafted and shown" — is enforced either way.
**Revisit if:** drafts need to survive a volume wipe or be listed in the UI.

### D-37 — The eight tools the spec referenced but never specified
**Decided:** `fs_read`, `fs_write`, `fs_delete`, `rag_search`, `calendar_read`, `remind`,
`memory_fact_confirm`, `delegate` are registered with named risk levels, taking the inventory
from 20 to **28**. `fs_delete` is IRREVERSIBLE (always approved) and confined to
`var/workspace` by resolved path. `delegate` is a registered READ tool whose output propagates
taint, so the supervisor's one capability is no longer a bare `tool_runs` string
(`delegate:<specialist>`, which violated P2 and could not be filtered).
**Because:** SKILL's inventory said "do not exceed this", while §3.4 and §7.3 required tools
that were not in it. Either the inventory grows or the graph silently calls unregistered
capabilities; the second option is how P2 dies.

### D-38 — Frontend state: TanStack Query only, no Zustand
**Decided:** server state via TanStack Query; local UI state via `useState`.
**Because:** one screen, one user. A second store would hold a string and a tab index.
**Revisit if:** offline queueing or cross-tab sync is added.

### D-39 — The eval set becomes 32 cases, and one case is marked `requires_sandbox`
**Supersedes:** D-06's "30-case" denominator.
**Decided:** 30 - 1 (the allowlisted-shell case needs the week-7 sandbox) + 3 (C9 language
purity, budget guard, caller-ID guard) = **32** cases; the sandbox case is skipped at gate time
and the skip is printed, not hidden.
**Because:** the kill gate was scheduled to run cases for tools that ship two weeks later, and
would have produced a "never relitigate" verdict from an incomplete set.

### D-40 — Mismatches between binding documents, resolved in one direction
For the record, because each one would otherwise be re-litigated mid-build: §7.2's
"unless the operator explicitly re-authorises in the same turn" is deleted (D-19 and SKILL are
absolute; a same-turn escape hatch is the injection path). §7.3's "send to another chat, ask"
is replaced by D-13's "ignore every other chat" — ignoring is safer than asking. §10.2's
"about 2.27 s typical" was the sum of overlapping stages (first-token 600 and complete 900
cannot both be on one path); the real path is about 1.37-1.67 s, so the 3.0 s p95 target has
more headroom than the document claims, and `voice_latency.total_ms` is the acceptance value,
not the document's arithmetic.
**Invalidates:** the latency table's total row only.

## C. Spike results (fill in during week 1)

### Spike A — Malaysian verified caller ID
| Field | Value |
|---|---|
| Date run | *(todo)* |
| Account state | *(trial / upgraded)* |
| Verified number | *(E.164)* |
| Called number | *(E.164)* |
| `callerId` presented to callee? | *(yes / replaced / dropped)* |
| Trial message played? | *(yes / no)* |
| **Outcome** | *(todo)* |
| **Decision** | *(keep `verified_caller_id` mode / remove it, `provisioned` only)* |
| Supersedes | D-08 partially |

### Spike B — Deepgram `zh-TW`
| Field | Value |
|---|---|
| Date run | *(todo)* |
| Fixture | *(path, duration, content)* |
| `language` param accepted? | *(yes / no / error message)* |
| Accuracy (eyeball, 10 utterances) | *(x/10 correct)* |
| Traditional glyphs preserved? | *(yes / Simplified substituted)* |
| Latency p95 | *(ms)* |
| **Decision** | *(Deepgram `zh-TW` / switch STT to Azure Speech)* |
| Supersedes | D-10 |

---

## D. Kill-gate result (fill in during week 4)

| Metric | Supervisor + 4 specialists | Single agent | Delta |
|---|---|---|---|
| pass@1 (of 30) | | | |
| p95 turn latency (ms) | | | |
| mean tokens / turn | | | |
| mean tool calls / turn | | | |
| mis-routes (of 30) | | | |

**Decision:** *(keep supervisor / collapse to single agent)*
**Rule applied:** collapse if p95 delta > 1000 ms, or relative pass-rate delta < −30 %, or tokens > 2×, or > 3 mis-routes.
**Evidence location:** *(path to the eval output)*

---

## E. Change log

| Date | Change | Supersedes | Invalidates | Re-test required |
|---|---|---|---|---|
| 2026-11-16 | Initial decision set D-01…D-30 from operator answers | — | — | — |
| 2026-11-17 | D-31...D-40 added from the pre-build review: contract v2, taint tightening, budget table split, inventory 20 to 28, eval set 30 to 32 | D-06 (denominator), §3.2 signature, §7.2 escape hatch, §7.3 telegram row | SKILL §4/§5, PLANBOOK §3.2/§3.3/§6.4/§7.2/§7.3/§9/§10.2 | policy tests, runtime tests, API tests, migration from empty |
| 2026-11-17 | Week-1 DoD "health green" deferred: no provider keys exist, so `/api/health` is 503 by design (D-32) | none | W1 DoD | re-check when keys are present |
| 2026-11-17 | D-41: the operator asked for the command-center look (dark deck, left rail, orb hero, bottom talk bar) with **voice as the default mode**. Built as a shell over one read-only endpoint (`GET /api/system/overview`) so every panel reads the same snapshot. Refused to fabricate the mockup's fake telemetry: no CPU/RAM gauges (no source), no weather (no source), no "4 connected" LLMs (7 of 9 components are unconfigured), no "agents running" (no such process). The voice orb stays dormant and states the missing keys, because the streaming voice turn ships in W5 and is not built; typing is one click away. Sections: Command Center, Conversations, Tasks, Approvals, AI Core, Tools & Skills, Memory | none | SKILL §5 tree; the old 4-tab layout | browser pass on all 7 sections + the new API test |
| 2026-11-17 | G7 browser pass found five defects the API recipe could not see, all fixed: (1) 422 validation errors rendered `[object Object]`; (2) every socket connect opened a new conversation, so switching tabs wiped the transcript and the language; (3) the specialist was sticky per thread, so a turn routed to `executor` kept the executor tool list and `task_delete` vanished for later turns; (4) the nav badge and the Approvals page shared query key `["approvals"]` with different shapes; (5) a paused approval said `(no answer)`. Also: stub replies now summarise tool results instead of dumping JSON, and the stub's "tool unavailable" refusal no longer blames taint when the cause is scope | none | none | browser pass re-run, runtime tests (`test_second_turn_in_a_thread_reroutes_to_the_right_specialist` added) |

| 2026-11-17 | D-42: the operator uses **OpenRouter**, not OpenAI directly. OpenRouter is OpenAI-compatible, so one `HTTPChatClient` serves both and the provider only moves the base URL, the key, and two attribution headers; a second client class would duplicate the wire format and drift. Model names must be `vendor/model` slugs and are rejected at startup otherwise, because a bare `gpt-4o-mini` 404s halfway through a turn. Cost: the request sets `usage.include` and the provider's reported `usage.cost` goes into `cost_ledger` verbatim (`meta.price_source = provider`); the local price table is consulted only when nothing is reported and is then labelled a guess (`table`), because a guessed price and a billed price are indistinguishable once they are a row. Two gaps this exposed and closed: a selected provider with an empty key used to kill the process at boot (now boots with a client that refuses every call, naming the variable, while prod still exits in `settings_guard`), and a provider HTTP fault used to drop the WebSocket mid-turn (now an error frame that releases the composer). | D-32 (stub is dev-only); no fallback from a real provider to the stub under any circumstance | §3.2 provider list; README models block; `.env.example` | `tests/unit/test_llm_openrouter.py`, `tests/integration/test_llm_cost.py`, health output naming `OPENROUTER_API_KEY` |

---

## F. Phase 2 backlog (explicitly parked, do not build)

| Item | Why parked | Prerequisite |
|---|---|---|
| WhatsApp Cloud API | Meta verification + template approval + per-conversation fees | Telegram transport proven |
| GUI / vision desktop control | Highest risk, lowest reliability | Sandbox proven, budget ≥ $50 |
| Inbound calling | Blocked on MY KYC | Bundle approved |
| Realtime speech-to-speech | 5× cost, needs latency mandate | p95 > 5 s persists after both fixes |
| RAG tier 3 (notes/email corpus) | P1, not MVP | Memory tiers 1–2 stable |
| Multi-user | Never requested | — |
| Self-hosted LLM | No GPU at this budget | Budget ≥ $50 + GPU host |
| "AGI" behaviour / self-authored skills | Not a real engineering target | — |
