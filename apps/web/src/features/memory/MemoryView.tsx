import { relativeTime, type Overview } from "../../lib/overview";

export function MemoryView({ overview, onOpenChat }: { overview: Overview; onOpenChat: () => void }) {
  const { counters, conversations, specialists } = overview;

  return (
    <div className="grid min-h-0 flex-1 grid-cols-1 gap-3 overflow-y-auto pr-1 xl:grid-cols-3">
      <section className="panel xl:col-span-2">
        <div className="panel-head">
          <span className="flex-1">Recent Conversations</span>
          <span>{counters.conversations} total</span>
        </div>
        <div className="p-2.5">
          <ul className="space-y-1">
            {conversations.map((row) => (
              <li
                key={row.id}
                className="flex items-center gap-2 rounded border border-[var(--color-line)] bg-[rgba(8,25,40,0.5)] px-2 py-1.5 text-[0.7rem]"
              >
                <span className="kpi text-[0.62rem] text-[var(--color-mute)]">
                  {relativeTime(row.started_at)}
                </span>
                <span className="flex-1 truncate font-mono text-[0.68rem] text-cyan-100/80">
                  {row.id.slice(0, 8)}
                </span>
                <span className="text-[0.66rem] text-[var(--color-mute)]">{row.transport}</span>
                <span className="tag bg-cyan-500/10 text-cyan-200">{row.lang}</span>
                <span className="text-[0.66rem] text-[var(--color-mute)]">
                  {row.messages} msg
                </span>
              </li>
            ))}
            {conversations.length === 0 ? (
              <li className="text-[0.72rem] text-[var(--color-mute)]">No conversations yet.</li>
            ) : null}
          </ul>
          <button type="button" className="btn mt-2" onClick={onOpenChat}>
            Open the live conversation
          </button>
        </div>
      </section>

      <section className="panel">
        <div className="panel-head">
          <span className="flex-1">Memory Tiers</span>
          <span>tier 1 only</span>
        </div>
        <div className="space-y-2 p-3 text-[0.7rem]">
          {[
            ["Facts", counters.facts],
            ["Messages", counters.messages],
            ["Open tasks", counters.open_tasks],
            ["Tool runs this month", counters.tool_runs_month],
          ].map(([label, value]) => (
            <div key={String(label)} className="flex items-baseline justify-between gap-2">
              <span className="text-[var(--color-mute)]">{label}</span>
              <span className="kpi text-base text-cyan-100">{value}</span>
            </div>
          ))}
          <p className="pt-1 text-[0.66rem] leading-relaxed text-[var(--color-mute)]">
            Vector recall over notes and mail is parked in Phase 2. Facts written by the agent stay
            unconfirmed until you say so, and a tainted turn may not write at all.
          </p>
          <div className="pt-2">
            <div className="text-[0.68rem] tracking-[0.14em] text-[var(--color-mute)]">
              SPECIALISTS
            </div>
            <div className="mt-1 flex flex-wrap gap-1">
              {specialists.map((agent) => (
                <span key={agent.name} className="tag bg-cyan-500/10 text-cyan-200">
                  {agent.label} · {agent.tools}
                </span>
              ))}
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}
