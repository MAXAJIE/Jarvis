import type { ReactElement } from "react";

import type { Overview } from "../../lib/overview";
import { Waveform } from "../core/Orb";
import { IconChat, IconCommand, IconCore, IconMemory, IconMic, IconShield, IconTasks, IconTools } from "./icons";

export type Section = "command" | "chat" | "tasks" | "approvals" | "core" | "tools" | "memory";

const ENTRIES: { id: Section; label: string; icon: () => ReactElement; countKey?: string }[] = [
  { id: "command", label: "Command Center", icon: IconCommand },
  { id: "chat", label: "Conversations", icon: IconChat, countKey: "conversations" },
  { id: "tasks", label: "Tasks", icon: IconTasks, countKey: "open_tasks" },
  { id: "approvals", label: "Approvals", icon: IconShield, countKey: "approvals_pending" },
  { id: "core", label: "AI Core", icon: IconCore },
  { id: "tools", label: "Tools & Skills", icon: IconTools },
  { id: "memory", label: "Memory", icon: IconMemory, countKey: "facts" },
];

export function Sidebar({
  section,
  onSection,
  overview,
}: {
  section: Section;
  onSection: (value: Section) => void;
  overview: Overview | undefined;
}) {
  const counters = overview?.counters as Record<string, number> | undefined;
  const voiceReady = Boolean(overview?.voice.transport_ready);

  return (
    <aside className="hidden w-60 shrink-0 flex-col gap-3 border-r border-[var(--color-line)] bg-[rgba(4,12,20,0.6)] p-3 md:flex">
      <nav className="flex flex-col gap-1">
        {ENTRIES.map((entry) => {
          const count = entry.countKey ? counters?.[entry.countKey] : undefined;
          return (
            <button
              key={entry.id}
              type="button"
              className="rail-item"
              data-active={section === entry.id}
              onClick={() => onSection(entry.id)}
            >
              <entry.icon />
              <span className="flex-1">{entry.label}</span>
              {count ? (
                <span className="rounded bg-cyan-500/15 px-1.5 py-0.5 text-[0.62rem] text-cyan-200">
                  {count}
                </span>
              ) : null}
            </button>
          );
        })}
      </nav>

      <div className="panel mt-auto">
        <div className="panel-head">
          <IconMic />
          <span className="flex-1">Voice Status</span>
          <span className={voiceReady ? "text-emerald-300" : "text-amber-300"}>
            {voiceReady ? "READY" : "OFFLINE"}
          </span>
        </div>
        <div className="panel-body space-y-2">
          <Waveform state="idle" bars={26} />
          <p className="text-[0.68rem] leading-relaxed text-[var(--color-mute)]">
            {voiceReady ? (
              "Speech keys present. The streaming turn lands in W5."
            ) : (
              <>
                Speech is not configured: <code className="text-cyan-200">DEEPGRAM_API_KEY</code>{" "}
                and <code className="text-cyan-200">AZURE_SPEECH_KEY</code> are empty. Typing works
                now; the orb stays dormant until the loop exists.
              </>
            )}
          </p>
          <button type="button" className="btn w-full" onClick={() => onSection("chat")}>
            Open conversation
          </button>
        </div>
      </div>
    </aside>
  );
}

/** The rail is hidden below md, so small screens get a scrollable strip instead. */
export function MobileNav({
  section,
  onSection,
}: {
  section: Section;
  onSection: (value: Section) => void;
}) {
  return (
    <nav className="flex w-full min-w-0 max-w-full gap-1 overflow-x-auto pb-1 md:hidden">
      {ENTRIES.map((entry) => (
        <button
          key={entry.id}
          type="button"
          onClick={() => onSection(entry.id)}
          className={`flex shrink-0 items-center gap-1.5 rounded border px-2.5 py-1.5 text-[0.7rem] ${
            section === entry.id
              ? "border-cyan-400/60 bg-cyan-500/15 text-cyan-100"
              : "border-[var(--color-line)] text-[var(--color-mute)]"
          }`}
        >
          <entry.icon />
          {entry.label}
        </button>
      ))}
    </nav>
  );
}
