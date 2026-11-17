import type { Overview } from "../../lib/overview";
import { clockTime, money } from "../../lib/overview";
import { Waveform } from "../core/Orb";

/**
 * The bottom strip. The reference shows weather and a live "I am listening"
 * meter; we have neither a weather source nor a voice loop, so this bar reports
 * what is actually measurable: the clock, the timezone, disk headroom, and
 * whether the operator can speak right now.
 */
export function BottomBar({
  overview,
  listening,
  onTalk,
  onType,
}: {
  overview: Overview | undefined;
  listening: boolean;
  onTalk: () => void;
  onType: () => void;
}) {
  const disk = overview?.health.components.find((part) => part.component === "disk");
  const voiceReady = Boolean(overview?.voice.transport_ready);
  const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;

  return (
    <footer className="flex h-16 shrink-0 items-center gap-4 border-t border-[var(--color-line)] bg-[rgba(4,14,24,0.9)] px-4">
      <div className="hidden items-center gap-3 text-[0.68rem] text-[var(--color-mute)] lg:flex">
        <div>
          <div className="tracking-[0.18em]">STATION</div>
          <div className="text-[var(--color-ink)]">{timezone}</div>
        </div>
        <div className="h-7 w-px bg-[var(--color-line)]" />
        <div>
          <div className="tracking-[0.18em]">DISK</div>
          <div className="text-[var(--color-ink)]">{disk?.detail ?? "unknown"}</div>
        </div>
        <div className="h-7 w-px bg-[var(--color-line)]" />
        <div>
          <div className="tracking-[0.18em]">NETWORK</div>
          <div className="text-[var(--color-ink)]">loopback only</div>
        </div>
      </div>

      <div className="mx-auto flex w-full max-w-xl items-center gap-3">
        <button
          type="button"
          onClick={onTalk}
          className="panel panel-hot flex flex-1 items-center gap-3 px-4 py-1.5 text-left"
          title={voiceReady ? "Voice loop ships in W5" : "Speech keys are not configured"}
        >
          <Waveform state={listening ? "live" : "idle"} bars={18} />
          <span className="flex-1 leading-tight">
            <span className="block text-[0.72rem] font-semibold tracking-[0.22em] text-cyan-100">
              TALK TO JARVIS
            </span>
            <span className="block text-[0.68rem] text-[var(--color-mute)]">
              {listening
                ? "listening…"
                : voiceReady
                  ? "voice loop lands in W5 — click to type"
                  : "voice offline — click to type instead"}
            </span>
          </span>
        </button>
        <button type="button" className="btn" onClick={onType}>
          Type
        </button>
      </div>

      <div className="hidden items-center gap-3 text-[0.68rem] text-[var(--color-mute)] xl:flex">
        <div className="text-right">
          <div className="tracking-[0.18em]">LEFT THIS MONTH</div>
          <div className="kpi text-[var(--color-ink)]">
            {overview ? money(overview.budget.remaining_usd) : "—"} of{" "}
            {overview ? money(overview.budget.ceiling_usd) : "—"}
          </div>
        </div>
        <div className="h-7 w-px bg-[var(--color-line)]" />
        <div className="text-right">
          <div className="tracking-[0.18em]">SNAPSHOT</div>
          <div className="text-[var(--color-ink)]">{clockTime(overview?.now ?? null)}</div>
        </div>
      </div>
    </footer>
  );
}
