export type Role = "user" | "assistant";

export interface ToolEvent {
  type: "tool";
  name: string;
  ok: boolean;
  detail: unknown;
}

export interface ApprovalRequest {
  id: string;
  thread_id: string;
  tool_name: string;
  risk: string;
  summary: string;
  expires_at: string;
}

export interface Turn {
  answer: string;
  events: ToolEvent[];
  approval: ApprovalRequest | null;
  tainted: boolean;
  stopped: string;
}

export interface Task {
  id: string;
  title: string;
  detail: string | null;
  status: string;
  priority: number;
  due_at: string | null;
  completed_at: string | null;
  source: string;
}

export interface Dashboard {
  tasks_completed: number;
  failures: number;
  api_calls: number;
  tokens_used: number;
  voice_minutes: number;
  spend_usd: number;
  usage_usd: number;
  fixed_usd: number;
  ceiling_usd: number;
  remaining_usd: number;
  alarm: boolean;
  period_start: string;
}

export interface Identity {
  user_id: string;
  email: string;
  lang_default: string;
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    credentials: "same-origin",
    headers: { "content-type": "application/json", ...(init?.headers ?? {}) },
    ...init,
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = (await response.json()) as { detail?: string };
      detail = body.detail ?? detail;
    } catch {
      /* the body was not JSON; keep the status text */
    }
    throw new ApiError(response.status, detail);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}
