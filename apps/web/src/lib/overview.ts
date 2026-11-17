import { useQuery } from "@tanstack/react-query";

import { api } from "./api";

export interface HealthComponent {
  component: string;
  ok: boolean;
  detail: string;
}

export interface FeedItem {
  kind: string;
  level: "info" | "warn" | "tip";
  title: string;
  detail: string;
  ts: string;
  pending: boolean;
}

export interface TimelineItem {
  id: string;
  title: string;
  due_at: string | null;
  priority: number;
  status: string;
  overdue: boolean;
}

export interface ConversationRow {
  id: string;
  started_at: string;
  lang: string;
  transport: string;
  messages: number;
}

export interface SpecialistRow {
  name: string;
  label: string;
  tools: number;
  tool_names: string[];
}

export interface ToolRow {
  name: string;
  description: string;
  risk: string;
  taints: boolean;
  idempotent: boolean;
}

export interface Overview {
  now: string;
  period_start: string;
  health: {
    status: string;
    components: HealthComponent[];
    missing: string[];
    app_env: string;
  };
  budget: {
    spend_usd: number;
    usage_usd: number;
    fixed_usd: number;
    ceiling_usd: number;
    remaining_usd: number;
    alarm: boolean;
  };
  counters: {
    open_tasks: number;
    facts: number;
    conversations: number;
    messages: number;
    tool_runs_month: number;
    approvals_pending: number;
    tasks_completed: number;
    failures: number;
    api_calls: number;
    tokens_used: number;
    voice_minutes: number;
    cost_cents: number;
  };
  feed: FeedItem[];
  timeline: TimelineItem[];
  conversations: ConversationRow[];
  specialists: SpecialistRow[];
  tools: ToolRow[];
  tools_by_risk: Record<string, number>;
  /** Named in this build's design but not implemented: shown, never offered. */
  withheld_tools: { name: string; reason: string }[];
  llm: { provider: string; configured: boolean; model: string };
  voice: {
    stt: string;
    stt_ready: boolean;
    tts: string;
    tts_ready: boolean;
    tts_voice: string;
    tts_key_env: string;
    free_chars_per_month: number | null;
    transport_ready: boolean;
  };
}

/**
 * One payload for the whole landing screen, polled once.
 *
 * Eleven panels reading eleven endpoints would drift apart by milliseconds and
 * disagree about the month boundary; this keeps every number on screen from the
 * same snapshot.
 */
export function useOverview(enabled = true) {
  return useQuery<Overview>({
    queryKey: ["overview"],
    queryFn: () => api<Overview>("/api/system/overview"),
    enabled,
    refetchInterval: enabled ? 12_000 : false,
  });
}

export function money(value: number): string {
  return `$${value.toFixed(2)}`;
}

export function relativeTime(iso: string | null): string {
  if (!iso) return "no date";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "no date";
  const diffMinutes = Math.round((then - Date.now()) / 60_000);
  const abs = Math.abs(diffMinutes);
  const suffix = diffMinutes < 0 ? "ago" : "in";
  if (abs < 1) return "now";
  if (abs < 60) return `${abs} m ${suffix}`;
  if (abs < 60 * 24) return `${Math.round(abs / 60)} h ${suffix}`;
  return `${Math.round(abs / 1400)} d ${suffix}`;
}

export function clockTime(iso: string | null): string {
  if (!iso) return "--:--";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "--:--";
  return date.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}
