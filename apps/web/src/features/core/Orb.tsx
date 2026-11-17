import { useMemo } from "react";

export type VoiceState = "live" | "idle" | "blocked";

/**
 * The core orb.
 *
 * It animates only when the system is genuinely listening. Today that is never:
 * the streaming voice turn ships in W5, and DEEPGRAM_API_KEY / AZURE_SPEECH_KEY
 * are empty, so the orb sits dormant and says why. An orb that pulses to look
 * alive would be the same lie as a green health check with no keys configured.
 */
export function Orb({
  state,
  subtitle,
  onClick,
  size = 168,
}: {
  state: VoiceState;
  subtitle: string;
  onClick?: () => void;
  size?: number;
}) {
  const live = state === "live";
  return (
    <div className={`orb-stage ${live ? "orb-live" : "orb-dormant"}`}>
      <button
        type="button"
        onClick={onClick}
        title={subtitle}
        aria-label={`Jarvis core: ${state}. ${subtitle}`}
        className="relative grid place-items-center rounded-full focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300"
        style={{ width: size, height: size }}
      >
        <span className="orb" style={{ width: size, height: size }}>
          <span className="orb-grid" />
        </span>
        <span className="orb-core-label">
          <span className="text-[1.35rem] font-semibold tracking-[0.35em] text-cyan-100 drop-shadow-[0_0_10px_rgba(34,211,238,0.8)]">
            JARVIS
          </span>
          <span className="mt-1 text-[0.68rem] tracking-[0.3em] text-cyan-300/80">AI CORE</span>
        </span>
      </button>
    </div>
  );
}

export function Waveform({ state, bars = 34 }: { state: "live" | "idle"; bars?: number }) {
  const delays = useMemo(
    () =>
      Array.from({ length: bars }, (_, index) => ({
        delay: `${(index % 9) * 0.09}s`,
        height: `${35 + ((index * 37) % 60)}%`,
      })),
    [bars],
  );
  return (
    <div className="wave" data-state={state} aria-hidden="true">
      {delays.map((bar, index) => (
        <span key={index} style={{ animationDelay: bar.delay, height: bar.height }} />
      ))}
    </div>
  );
}

export function StatusDot({ level }: { level: "ok" | "warn" | "bad" }) {
  const color =
    level === "ok" ? "text-emerald-400" : level === "warn" ? "text-amber-400" : "text-rose-400";
  return (
    <span className={`inline-flex items-center gap-1.5 ${color}`}>
      <span className="pulse-dot" />
    </span>
  );
}
