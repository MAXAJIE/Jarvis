import { useEffect, useState } from "react";

import type { Identity } from "../../lib/api";
import type { Overview } from "../../lib/overview";

function useClock() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(timer);
  }, []);
  return now;
}

export function TopBar({
  identity,
  overview,
  query,
  onQuery,
  onSignOut,
}: {
  identity: Identity;
  overview: Overview | undefined;
  query: string;
  onQuery: (value: string) => void;
  onSignOut: () => void;
}) {
  const now = useClock();
  const healthy = overview?.health.status === "ok";
  const missing = overview?.health.missing.length ?? 0;

  return (
    <header className="flex h-14 shrink-0 items-center gap-4 border-b border-[var(--color-line)] bg-[rgba(4,14,24,0.85)] px-4">
      <div className="flex items-center gap-3">
        <div className="grid h-9 w-9 place-items-center rounded-md border border-cyan-500/60 bg-cyan-500/10 text-cyan-300 shadow-[0_0_18px_rgba(34,211,238,0.35)]">
          <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="1.6">
            <circle cx="12" cy="12" r="7.5" />
            <ellipse cx="12" cy="12" rx="10" ry="4" />
            <circle cx="12" cy="12" r="2" />
          </svg>
        </div>
        <div className="leading-tight">
          <div className="text-sm font-semibold tracking-[0.32em] text-cyan-100">JARVIS</div>
          <div className="text-[0.62rem] tracking-[0.28em] text-[var(--color-mute)]">
            COMMAND CENTER
          </div>
        </div>
      </div>

      <div className="ml-2 hidden items-center gap-2 rounded-md border border-[var(--color-line)] bg-[rgba(8,25,40,0.7)] px-3 py-1.5 lg:flex">
        <span className="text-[0.62rem] tracking-[0.18em] text-[var(--color-mute)]">
          SYSTEM STATUS
        </span>
        <span
          className={`flex items-center gap-1.5 text-[0.68rem] font-semibold tracking-[0.14em] ${
            healthy ? "text-emerald-300" : "text-amber-300"
          }`}
        >
          <span className="pulse-dot" />
          {healthy ? "OPTIMAL" : "DEGRADED"}
        </span>
        {!healthy && missing > 0 ? (
          <span className="text-[0.62rem] text-[var(--color-mute)]">
            {missing} provider{missing === 1 ? "" : "s"} unconfigured
          </span>
        ) : null}
      </div>

      <div className="ml-auto hidden text-center leading-tight lg:block">
        <div className="text-[0.66rem] tracking-[0.22em] text-[var(--color-mute)]">
          {now.toLocaleDateString(undefined, {
            weekday: "long",
            day: "2-digit",
            month: "long",
            year: "numeric",
          })}
        </div>
        <div className="kpi text-sm font-semibold text-cyan-100">
          {now.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
        </div>
      </div>

      <label className="ml-auto hidden w-40 items-center gap-2 md:flex lg:w-56 rounded-md border border-[var(--color-line)] bg-[rgba(3,12,20,0.8)] px-2.5 py-1.5">
        <svg viewBox="0 0 24 24" className="h-4 w-4 text-[var(--color-mute)]" fill="none" stroke="currentColor" strokeWidth="1.6">
          <circle cx="11" cy="11" r="6.5" />
          <path d="m16 16 4 4" />
        </svg>
        <input
          value={query}
          onChange={(event) => onQuery(event.target.value)}
          placeholder="Search this view…"
          aria-label="Search"
          className="w-full bg-transparent text-xs text-[var(--color-ink)] placeholder:text-[#48768c] focus:outline-none"
        />
      </label>

      <div className="hidden items-center gap-2 rounded-md border border-[var(--color-line)] px-2.5 py-1.5 sm:flex">
        <div className="grid h-6 w-6 place-items-center rounded-full bg-cyan-500/15 text-[0.66rem] font-semibold text-cyan-200">
          {identity.email.slice(0, 2).toUpperCase()}
        </div>
        <div className="leading-tight">
          <div className="text-[0.7rem] text-cyan-50">Operator</div>
          <div className="text-[0.62rem] tracking-[0.16em] text-[var(--color-mute)]">COMMANDER</div>
        </div>
      </div>

      <button type="button" className="btn" onClick={onSignOut}>
        Sign out
      </button>
    </header>
  );
}
