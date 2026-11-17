import { useState } from "react";

import type { Overview } from "../../lib/overview";

const RISK_COLOR: Record<string, string> = {
  read: "text-emerald-300",
  write: "text-cyan-300",
  external: "text-amber-300",
  irreversible: "text-rose-300",
};

export function ToolsView({ overview, query }: { overview: Overview; query: string }) {
  const [risk, setRisk] = useState<string>("all");
  const needle = query.trim().toLowerCase();
  const rows = overview.tools.filter(
    (tool) =>
      (risk === "all" || tool.risk === risk) &&
      (!needle ||
        tool.name.toLowerCase().includes(needle) ||
        tool.description.toLowerCase().includes(needle)),
  );

  return (
    <div className="panel flex min-h-0 flex-1 flex-col">
      <div className="panel-head">
        <span className="flex-1">Tools &amp; Skills</span>
        <span>
          {overview.tools.length} registered ·{" "}
          {Object.entries(overview.tools_by_risk)
            .map(([name, count]) => `${count} ${name}`)
            .join(" · ")}
        </span>
      </div>

      <div className="flex shrink-0 flex-wrap gap-1.5 border-b border-[var(--color-line)] p-2.5">
        {["all", "read", "write", "external", "irreversible"].map((value) => (
          <button
            key={value}
            type="button"
            onClick={() => setRisk(value)}
            className={`rounded border px-2 py-0.5 text-[0.62rem] tracking-[0.08em] ${
              risk === value
                ? "border-cyan-400/60 bg-cyan-500/15 text-cyan-100"
                : "border-[var(--color-line)] text-[var(--color-mute)]"
            }`}
          >
            {value.toUpperCase()}
          </button>
        ))}
        <span className="ml-auto text-[0.66rem] text-[var(--color-mute)]">
          every capability is a registered tool; policy lives in code, not in a prompt
        </span>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-2.5">
        <ul className="space-y-1">
          {rows.map((tool) => (
            <li key={tool.name} className="rounded border border-[var(--color-line)] bg-[rgba(8,25,40,0.5)] px-2 py-1.5">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-mono text-[0.74rem] text-cyan-100">{tool.name}</span>
                <span className={`text-[0.68rem] uppercase tracking-[0.12em] ${RISK_COLOR[tool.risk] ?? ""}`}>
                  {tool.risk}
                </span>
                {tool.taints ? (
                  <span className="tag bg-amber-500/15 text-amber-200">taints</span>
                ) : null}
                {tool.idempotent ? (
                  <span className="tag bg-cyan-500/10 text-cyan-200">idempotent</span>
                ) : null}
              </div>
              <div className="mt-0.5 truncate text-[0.68rem] text-[var(--color-mute)]">
                {tool.description}
              </div>
            </li>
          ))}
        </ul>
        {rows.length === 0 ? (
          <p className="text-[0.72rem] text-[var(--color-mute)]">No tool matches that filter.</p>
        ) : null}
      </div>
    </div>
  );
}
