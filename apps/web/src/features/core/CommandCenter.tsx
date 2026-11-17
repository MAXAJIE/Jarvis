import type { CSSProperties } from "react";

import { money, relativeTime, type Overview } from "../../lib/overview";
import { Orb, Waveform } from "./Orb";

function Meter({
  value,
  label,
  caption,
  color,
}: {
  value: number;
  label: string;
  caption: string;
  color: string;
}) {
  const clamped = Math.max(0, Math.min(100, value));
  return (
    <div className="flex flex-col items-center gap-1">
      <div
        className="meter"
        style={{ "--meter-value": clamped, "--meter-color": color } as CSSProperties}
      >
        <div className="text-center leading-none">
          <div className="kpi text-base font-semibold">{Math.round(clamped)}%</div>
          <div className="text-[0.66rem] tracking-[0.16em] text-[var(--color-mute)]">{label}</div>
        </div>
      </div>
      <div className="text-center text-[0.66rem] text-[var(--color-mute)]">{caption}</div>
    </div>
  );
}

function Panel({
  title,
  right,
  children,
  className = "",
}: {
  title: string;
  right?: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section className={`panel flex min-h-0 flex-col ${className}`}>
      <div className="panel-head">
        <span className="flex-1">{title}</span>
        {right ? <span className="text-[0.66rem] text-[var(--color-mute)]">{right}</span> : null}
      </div>
      <div className="panel-body min-h-0 flex-1">{children}</div>
    </section>
  );
}

export function CommandCenter({
  overview,
  onPrompt,
  onSection,
}: {
  overview: Overview;
  onPrompt: (text: string) => void;
  onSection: (value: "chat" | "tasks" | "approvals" | "core" | "tools") => void;
}) {
  const { counters, budget, health } = overview;
  const missing = health.components.filter((part) => !part.ok);
  const disk = health.components.find((part) => part.component === "disk");
  const diskFree = disk ? Number.parseFloat(disk.detail) || 0 : 0;
  const voiceReady = Boolean(overview.voice.transport_ready);
  const spendPct = budget.ceiling_usd > 0 ? (budget.spend_usd / budget.ceiling_usd) * 100 : 0;
  const failurePct = counters.tool_runs_month
    ? (counters.failures / counters.tool_runs_month) * 100
    : 0;

  return (
    <div className="grid min-h-0 flex-1 auto-rows-max grid-cols-1 gap-3 overflow-y-auto pr-1 xl:grid-cols-4">
      {/* hero */}
      <section className="panel panel-hot min-h-[420px] xl:col-span-2">
        <div className="flex h-full flex-col items-center justify-center gap-2 p-3">
          <Orb
            state={voiceReady ? "idle" : "blocked"}
            subtitle={
              voiceReady
                ? "Press to talk — one utterance per turn, English for now"
                : "Voice offline: DEEPGRAM_API_KEY and AZURE_SPEECH_KEY are empty"
            }
            onClick={() => onSection("chat")}
            size={190}
          />
          <div className="text-center">
            <div className="text-[0.68rem] tracking-[0.3em] text-cyan-200/80">
              {overview.llm.configured ? "CORE ONLINE" : "CORE IN STUB MODE"}
            </div>
            <div className="mt-1 text-[0.62rem] text-[var(--color-mute)]">
              {overview.llm.configured
                ? `${overview.llm.provider} · ${overview.llm.model}`
                : "no model key: orchestration is real, prose is templated"}
            </div>
          </div>
          <Waveform state="idle" bars={40} />
          <div className="flex flex-wrap justify-center gap-2">
            <button type="button" className="btn btn-primary" onClick={() => onSection("chat")}>
              Open conversation
            </button>
            <button type="button" className="btn" onClick={() => onPrompt("plan my week")}>
              Plan my week
            </button>
          </div>
        </div>
      </section>

      {/* core overview */}
      <Panel title="AI Core" right={`${health.components.length} subsystems`}>
        <ul className="space-y-1.5">
          {health.components.map((part) => (
            <li key={part.component} className="flex items-center gap-2 text-[0.72rem]">
              <span
                className={`h-1.5 w-1.5 rounded-full ${
                  part.ok ? "bg-emerald-400 shadow-[0_0_8px_#34d399]" : "bg-amber-400 shadow-[0_0_8px_#fbbf24]"
                }`}
              />
              <span className="w-24 shrink-0 capitalize text-[var(--color-ink)]">
                {part.component.replace("_", " ")}
              </span>
              <span className="truncate text-[var(--color-mute)]" title={part.detail}>
                {part.detail}
              </span>
            </li>
          ))}
        </ul>
      </Panel>

      {/* feed */}
      <Panel title="Intel Feed" right={health.status.toUpperCase()}>
        <ul className="max-h-[340px] space-y-1.5 overflow-y-auto pr-1">
          {overview.feed.length === 0 ? (
            <li className="text-[0.72rem] text-[var(--color-mute)]">
              Nothing yet. Tool runs and approvals appear here.
            </li>
          ) : null}
          {overview.feed.map((item, index) => (
            <li key={`${item.ts}-${index}`} className="feed-item" data-level={item.level}>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="truncate text-[0.7rem] font-semibold text-cyan-100">
                    {item.title}
                  </span>
                  <span className="ml-auto shrink-0 text-[0.68rem] text-[var(--color-mute)]">
                    {relativeTime(item.ts)}
                  </span>
                </div>
                <div className="truncate text-[0.68rem] text-[var(--color-mute)]" title={item.detail}>
                  {item.detail}
                </div>
              </div>
            </li>
          ))}
        </ul>
      </Panel>

      {/* agents */}
      <Panel title="Agents" right={`${overview.specialists.length} routed`} className="xl:col-span-2">
        <ul className="grid grid-cols-1 gap-1.5">
          {overview.specialists.map((agent) => (
            <li
              key={agent.name}
              className="flex items-center gap-2 rounded border border-[var(--color-line)] bg-[rgba(8,25,40,0.55)] px-2 py-1.5"
            >
              <div className="grid h-6 w-6 place-items-center rounded bg-cyan-500/10 text-[0.66rem] text-cyan-200">
                {agent.label.slice(0, 2).toUpperCase()}
              </div>
              <div className="min-w-0 flex-1">
                <div className="text-[0.7rem] text-[var(--color-ink)]">{agent.label}</div>
                <div className="truncate text-[0.68rem] text-[var(--color-mute)]" title={agent.tool_names.join(", ")}>
                  {agent.tools} tools · {agent.tool_names.slice(0, 3).join(", ")}
                  {agent.tools > 3 ? "…" : ""}
                </div>
              </div>
              <span className="text-[0.62rem] tracking-[0.14em] text-[var(--color-mute)]">STANDBY</span>
            </li>
          ))}
        </ul>
      </Panel>

      {/* timeline */}
      <Panel title="Timeline" right="next 14 days">
        {overview.timeline.length === 0 ? (
          <p className="text-[0.72rem] text-[var(--color-mute)]">
            No dated tasks. Say “plan my week” to generate one.
          </p>
        ) : (
          <ul className="space-y-1">
            {overview.timeline.map((task) => (
              <li key={task.id} className="flex items-center gap-2 text-[0.7rem]">
                <span
                  className={`kpi w-14 shrink-0 text-[0.62rem] ${
                    task.overdue ? "text-rose-300" : "text-[var(--color-mute)]"
                  }`}
                >
                  {relativeTime(task.due_at)}
                </span>
                <span className="flex-1 truncate text-[var(--color-ink)]" title={task.title}>
                  {task.title}
                </span>
                <span className="shrink-0 rounded bg-cyan-500/10 px-1 text-[0.62rem] text-cyan-200">
                  P{task.priority}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Panel>

      {/* quick commands */}
      <Panel title="Commands" right="real prompts">
        <div className="grid grid-cols-2 gap-1.5">
          {[
            "plan my week",
            "list my tasks",
            "add task buy milk",
            "remember that I live in Kuala Lumpur",
          ].map((command) => (
            <button
              key={command}
              type="button"
              className="btn justify-start truncate !text-[0.68rem]"
              onClick={() => onPrompt(command)}
              title={command}
            >
              {command}
            </button>
          ))}
          <button
            type="button"
            className="btn justify-start !text-[0.68rem]"
            onClick={() => onSection("approvals")}
          >
            Review approvals
          </button>
          <button
            type="button"
            className="btn justify-start !text-[0.68rem]"
            onClick={() => onSection("tools")}
          >
            Tools inventory
          </button>
        </div>
      </Panel>

      {/* monitor */}
      <Panel title="Monitor" right={`${overview.period_start}`}>
        <div className="flex items-start justify-around gap-2">
          <Meter
            value={spendPct}
            label="SPEND"
            caption={`${money(budget.spend_usd)} / ${money(budget.ceiling_usd)}`}
            color={budget.alarm ? "var(--color-rose)" : "var(--color-cyan)"}
          />
          <Meter
            value={failurePct}
            label="FAIL"
            caption={`${counters.failures} of ${counters.tool_runs_month} runs`}
            color={failurePct > 25 ? "var(--color-amber)" : "var(--color-mint)"}
          />
          <Meter
            value={diskFree}
            label="DISK"
            caption="free"
            color={diskFree < 10 ? "var(--color-rose)" : "var(--color-cyan)"}
          />
        </div>
        <p className="mt-2 text-[0.66rem] leading-relaxed text-[var(--color-mute)]">
          No CPU/RAM gauges: this app cannot measure them without a system agent, and a fabricated
          gauge is indistinguishable from a broken one.
        </p>
      </Panel>

      {/* memory */}
      <Panel title="Memory" right={`${counters.facts} facts`}>
        <div className="grid grid-cols-2 gap-2 text-center">
          {[
            { label: "facts", value: counters.facts },
            { label: "conversations", value: counters.conversations },
            { label: "messages", value: counters.messages },
            { label: "open tasks", value: counters.open_tasks },
          ].map((stat) => (
            <div key={stat.label} className="rounded border border-[var(--color-line)] py-1.5">
              <div className="kpi text-lg text-cyan-100">{stat.value}</div>
              <div className="text-[0.62rem] tracking-[0.14em] text-[var(--color-mute)]">
                {stat.label.toUpperCase()}
              </div>
            </div>
          ))}
        </div>
        <p className="mt-2 text-[0.66rem] text-[var(--color-mute)]">
          Tier-1 facts only. Vector recall over your notes is parked in the Phase 2 backlog.
        </p>
      </Panel>

      {/* llm + providers */}
      <Panel title="Model" right={overview.llm.configured ? "LIVE" : "STUB"} className="xl:col-span-2">
        <div className="space-y-1.5 text-[0.7rem]">
          <div className="flex items-center justify-between">
            <span className="text-[var(--color-mute)]">Provider</span>
            <span className="text-[var(--color-ink)]">{overview.llm.provider}</span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-[var(--color-mute)]">Model</span>
            <span className="text-[var(--color-ink)]">{overview.llm.model}</span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-[var(--color-mute)]">LLM calls this month</span>
            <span className="kpi text-[var(--color-ink)]">{counters.api_calls}</span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-[var(--color-mute)]">Tokens</span>
            <span className="kpi text-[var(--color-ink)]">{counters.tokens_used.toLocaleString()}</span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-[var(--color-mute)]">Voice minutes</span>
            <span className="kpi text-[var(--color-ink)]">{counters.voice_minutes.toFixed(2)}</span>
          </div>
          {missing.length ? (
            <div className="mt-1 rounded border border-amber-700/40 bg-amber-500/5 px-2 py-1 text-[0.62rem] text-amber-200">
              Unconfigured: {missing.map((part) => part.component).join(", ")}
            </div>
          ) : null}
        </div>
      </Panel>
    </div>
  );
}
