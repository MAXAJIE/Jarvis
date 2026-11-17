import { money, relativeTime, type Overview } from "../../lib/overview";

export function SystemView({ overview }: { overview: Overview }) {
  const { health, budget, counters, llm } = overview;
  const ready = health.components.filter((part) => part.ok).length;

  return (
    <div className="grid min-h-0 flex-1 grid-cols-1 gap-3 overflow-y-auto pr-1 xl:grid-cols-3">
      <section className="panel xl:col-span-2">
        <div className="panel-head">
          <span className="flex-1">Subsystem Readiness</span>
          <span>
            {ready}/{health.components.length} ready · app_env {health.app_env}
          </span>
        </div>
        <div className="p-3">
          <table className="w-full text-left text-[0.72rem]">
            <thead className="text-[0.68rem] uppercase tracking-[0.14em] text-[var(--color-mute)]">
              <tr>
                <th className="pb-1.5">Component</th>
                <th className="pb-1.5">State</th>
                <th className="pb-1.5">Detail</th>
              </tr>
            </thead>
            <tbody>
              {health.components.map((part) => (
                <tr key={part.component} className="border-t border-[var(--color-line)]">
                  <td className="py-1.5 capitalize">{part.component.replace("_", " ")}</td>
                  <td className="py-1.5">
                    <span className={part.ok ? "text-emerald-300" : "text-amber-300"}>
                      {part.ok ? "ready" : "missing"}
                    </span>
                  </td>
                  <td className="py-1.5 text-[var(--color-mute)]">{part.detail}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-3 text-[0.62rem] leading-relaxed text-[var(--color-mute)]">
            Health is 503 while any component is missing, by design: a green dashboard with an empty
            key is the silent degradation the plan forbids. Nothing here degrades quietly — a tool
            without its key refuses with <code>NotConfigured</code>.
          </p>
        </div>
      </section>

      <section className="panel">
        <div className="panel-head">
          <span className="flex-1">Budget</span>
          <span>{overview.period_start}</span>
        </div>
        <div className="space-y-1.5 p-3 text-[0.72rem]">
          {[
            ["Spend (all-in)", money(budget.spend_usd)],
            ["Ceiling", money(budget.ceiling_usd)],
            ["Left for usage", money(budget.remaining_usd)],
            ["Fixed floor", money(budget.fixed_usd)],
            ["Metered usage", money(budget.usage_usd)],
            ["LLM calls", String(counters.api_calls)],
            ["Tokens", counters.tokens_used.toLocaleString()],
            ["Voice minutes", counters.voice_minutes.toFixed(2)],
            ["Tool runs", String(counters.tool_runs_month)],
            ["Failures", String(counters.failures)],
          ].map(([label, value]) => (
            <div key={label} className="flex items-center justify-between gap-2">
              <span className="text-[var(--color-mute)]">{label}</span>
              <span className="kpi text-[var(--color-ink)]">{value}</span>
            </div>
          ))}
          {budget.alarm ? (
            <div className="mt-2 rounded border border-rose-700/50 bg-rose-500/10 px-2 py-1 text-[0.68rem] text-rose-200">
              $15 alarm crossed. External tools stop at the ceiling.
            </div>
          ) : null}
          <p className="pt-1 text-[0.66rem] leading-relaxed text-[var(--color-mute)]">
            Fixed costs are a floor, not a ledger row: a partial ledger can never under-report spend.
          </p>
        </div>
      </section>

      <section className="panel xl:col-span-3">
        <div className="panel-head">
          <span className="flex-1">Model</span>
          <span>{llm.configured ? "live" : "stub"}</span>
        </div>
        <div className="grid grid-cols-2 gap-2 p-3 text-[0.72rem] md:grid-cols-4">
          <div>
            <div className="text-[0.68rem] tracking-[0.14em] text-[var(--color-mute)]">PROVIDER</div>
            <div>{llm.provider}</div>
          </div>
          <div>
            <div className="text-[0.68rem] tracking-[0.14em] text-[var(--color-mute)]">MODEL</div>
            <div>{llm.model}</div>
          </div>
          <div>
            <div className="text-[0.68rem] tracking-[0.14em] text-[var(--color-mute)]">VOICE STT</div>
            <div>{overview.voice.stt || "not configured"}</div>
          </div>
          <div>
            <div className="text-[0.68rem] tracking-[0.14em] text-[var(--color-mute)]">VOICE TTS</div>
            <div>{overview.voice.tts || "not configured"}</div>
          </div>
        </div>
        {!llm.configured ? (
          <p className="px-3 pb-3 text-[0.62rem] leading-relaxed text-amber-200/80">
            Stub mode: routing, policy, approvals, ledger and audit are real; the prose is
            templated. Set <code>OPENAI_API_KEY</code> and <code>LLM_PROVIDER=openai</code> for a real
            model.
          </p>
        ) : null}
        <p className="px-3 pb-3 text-[0.66rem] text-[var(--color-mute)]">
          Snapshot {relativeTime(overview.now)} · refreshed every 12 s
        </p>
      </section>
    </div>
  );
}
