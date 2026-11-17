export type ServerFrame =
  | { type: "ready"; conversation_id: string; lang: string; provider: string }
  | { type: "lang"; lang: string }
  | { type: "turn"; answer: string; events: ToolEventFrame[]; approval: ApprovalFrame | null; tainted: boolean; stopped: string }
  | { type: "error"; message: string };

export interface ToolEventFrame {
  type: "tool";
  name: string;
  ok: boolean;
  detail: unknown;
}

export interface ApprovalFrame {
  id: string;
  thread_id: string;
  tool_name: string;
  risk: string;
  summary: string;
  expires_at: string;
}

type Handler = (frame: ServerFrame) => void;
type StatusHandler = (status: "connecting" | "open" | "closed") => void;

export class ChatSocket {
  private ws: WebSocket | null = null;
  private attempt = 0;
  private closedByCaller = false;

  constructor(
    private readonly onFrame: Handler,
    private readonly onStatus: StatusHandler,
    /** Which conversation to reattach to, so a reconnect resumes the transcript. */
    private readonly resumeId: () => string | null = () => null,
  ) {}

  connect(): void {
    this.closedByCaller = false;
    const scheme = location.protocol === "https:" ? "wss" : "ws";
    this.onStatus("connecting");
    const id = this.resumeId();
    const query = id ? `?conversation_id=${encodeURIComponent(id)}` : "";
    const ws = new WebSocket(`${scheme}://${location.host}/ws/chat${query}`);
    this.ws = ws;

    ws.onopen = () => {
      this.attempt = 0;
      this.onStatus("open");
    };
    ws.onmessage = (event: MessageEvent<string>) => {
      this.onFrame(JSON.parse(event.data) as ServerFrame);
    };
    ws.onclose = () => {
      this.onStatus("closed");
      if (this.closedByCaller) return;
      const delay = Math.min(8000, 400 * 2 ** this.attempt);
      this.attempt += 1;
      window.setTimeout(() => this.connect(), delay);
    };
  }

  send(payload: Record<string, unknown>): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(payload));
    }
  }

  close(): void {
    this.closedByCaller = true;
    this.ws?.close();
    this.ws = null;
  }
}
