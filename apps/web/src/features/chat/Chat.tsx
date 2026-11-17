import { useEffect, useRef, useState } from "react";

import { api, type ApprovalRequest, type Turn } from "../../lib/api";
import { ChatSocket, type ServerFrame } from "../../lib/ws";

type Lang = "en" | "zh-TW";

interface Bubble {
  id: number;
  role: "user" | "assistant" | "system";
  text: string;
  events?: { name: string; ok: boolean }[];
  approval?: ApprovalRequest | null;
  tainted?: boolean;
}

let nextId = 1;

/** The last conversation this browser talked in; the server owns the transcript. */
const CONVERSATION_KEY = "jarvis.conversation";
const LANG_KEY = "jarvis.lang";

function storedConversation(): string | null {
  try {
    return window.localStorage.getItem(CONVERSATION_KEY);
  } catch {
    return null;
  }
}

export default function Chat({ onDecided }: { onDecided: () => void }) {
  const [bubbles, setBubbles] = useState<Bubble[]>([]);
  const [draft, setDraft] = useState("");
  const [status, setStatus] = useState<"connecting" | "open" | "closed">("connecting");
  const [lang, setLang] = useState<Lang>(() => {
    try {
      return window.localStorage.getItem(LANG_KEY) === "zh-TW" ? "zh-TW" : "en";
    } catch {
      return "en";
    }
  });
  const [mode, setMode] = useState<"typing" | "talking">("typing");
  const [provider, setProvider] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const socketRef = useRef<ChatSocket | null>(null);
  const langRef = useRef<Lang>(lang);
  langRef.current = lang;

  useEffect(() => {
    const socket = new ChatSocket((frame: ServerFrame) => {
      if (frame.type === "ready") {
        setProvider(frame.provider);
        const resumed = frame.lang === "zh-TW" ? "zh-TW" : "en";
        setLang(resumed);
        try {
          window.localStorage.setItem(CONVERSATION_KEY, frame.conversation_id);
          window.localStorage.setItem(LANG_KEY, resumed);
        } catch {
          /* storage can be unavailable; the transcript still loads below */
        }
        void loadHistory(frame.conversation_id);
        return;
      }
      if (frame.type === "error") {
        setBubbles((current) => [
          ...current,
          { id: nextId++, role: "system", text: frame.message },
        ]);
        return;
      }
      if (frame.type === "turn") {
        setBusy(false);
        setBubbles((current) => [
          ...current,
          {
            id: nextId++,
            role: "assistant",
            text:
              frame.answer ||
              (frame.approval
                ? langRef.current === "zh-TW"
                  ? "等你批准先做。"
                  : "Waiting for your approval."
                : "(no answer)"),
            events: frame.events.map((event) => ({ name: event.name, ok: event.ok })),
            approval: frame.approval,
            tainted: frame.tainted,
          },
        ]);
      }
    }, setStatus, storedConversation);
    socketRef.current = socket;
    socket.connect();
    return () => socket.close();
  }, []);

  async function loadHistory(conversationId: string) {
    try {
      const body = await api<{ messages: { role: string; content: string }[] }>(
        `/api/chat/history?conversation_id=${encodeURIComponent(conversationId)}`,
      );
      if (!body.messages.length) return;
      setBubbles((current) =>
        current.length
          ? current
          : body.messages.map((message) => ({
              id: nextId++,
              role: message.role === "user" ? ("user" as const) : ("assistant" as const),
              text: message.content,
            })),
      );
    } catch {
      /* an empty transcript is a fine fallback; do not block the socket */
    }
  }

  function send() {
    const text = draft.trim();
    if (!text || !socketRef.current || busy) return;
    setBubbles((current) => [...current, { id: nextId++, role: "user", text }]);
    setDraft("");
    setBusy(true);
    socketRef.current.send({ type: "user_message", text });
  }

  function changeLang(next: Lang) {
    setLang(next);
    try {
      window.localStorage.setItem(LANG_KEY, next);
    } catch {
      /* ignore */
    }
    socketRef.current?.send({ type: "set_lang", lang: next });
  }

  async function decide(id: string, decision: "approved" | "rejected") {
    const body = await api<{ decision: string; turn: Turn | null }>(
      `/api/approvals/${id}/decide`,
      { method: "POST", body: JSON.stringify({ decision }) },
    );
    setBubbles((current) => [
      ...current,
      { id: nextId++, role: "system", text: `approval ${body.decision}` },
      ...(body.turn
        ? [
            {
              id: nextId++,
              role: "assistant" as const,
              text: body.turn.answer || "(no answer)",
              events: body.turn.events.map((event) => ({ name: event.name, ok: event.ok })),
            },
          ]
        : []),
    ]);
    onDecided();
  }

  return (
    <div className="card flex h-[calc(100vh-7rem)] flex-col">
      <div className="flex flex-wrap items-center gap-2 border-b border-[var(--color-line)] p-3">
        <div className="flex overflow-hidden rounded-lg border border-[var(--color-line)]">
          {(["typing", "talking"] as const).map((value) => (
            <button
              key={value}
              type="button"
              className={`px-3 py-1.5 text-sm ${mode === value ? "bg-blue-600 text-white" : ""}`}
              onClick={() => setMode(value)}
              disabled={value === "talking"}
              title={value === "talking" ? "needs DEEPGRAM_API_KEY + AZURE_SPEECH_KEY" : undefined}
            >
              {value === "typing" ? "Typing" : "Talking"}
            </button>
          ))}
        </div>
        <div className="flex overflow-hidden rounded-lg border border-[var(--color-line)]">
          {(["en", "zh-TW"] as const).map((value) => (
            <button
              key={value}
              type="button"
              className={`px-3 py-1.5 text-sm ${lang === value ? "bg-slate-700" : ""}`}
              onClick={() => changeLang(value)}
            >
              {value === "en" ? "English" : "繁體中文"}
            </button>
          ))}
        </div>
        <span className="ml-auto text-xs text-slate-500">
          ws:{status}
          {provider ? ` · model:${provider}` : ""}
        </span>
      </div>

      <div className="flex-1 space-y-3 overflow-y-auto p-4">
        {bubbles.length === 0 ? (
          <p className="text-sm text-slate-500">
            Try: “plan my week”, “add task buy milk”, “list my tasks”, “remember that I live in
            Kuala Lumpur”.
          </p>
        ) : null}
        {bubbles.map((bubble) => (
          <div key={bubble.id} className={bubble.role === "user" ? "text-right" : ""}>
            <div
              className={`inline-block max-w-[46rem] whitespace-pre-wrap rounded-xl px-3 py-2 text-sm ${
                bubble.role === "user"
                  ? "bg-blue-600 text-white"
                  : bubble.role === "system"
                    ? "bg-slate-800 text-slate-300"
                    : "bg-[#0e1626]"
              }`}
            >
              {bubble.tainted ? (
                <div className="mb-1 text-xs text-amber-400">
                  this turn contained outside content
                </div>
              ) : null}
              {bubble.text}
              {bubble.events?.length ? (
                <div className="mt-2 flex flex-wrap gap-1">
                  {bubble.events.map((event, index) => (
                    <span
                      key={`${event.name}-${index}`}
                      className={`rounded px-1.5 py-0.5 text-xs ${
                        event.ok ? "bg-emerald-900 text-emerald-200" : "bg-red-900 text-red-200"
                      }`}
                    >
                      {event.name}
                      {event.ok ? "" : " ✕"}
                    </span>
                  ))}
                </div>
              ) : null}
              {bubble.approval ? (
                <div className="mt-2 rounded-lg border border-amber-700 bg-amber-950/40 p-2 text-xs">
                  <div className="font-semibold text-amber-200">
                    {bubble.approval.tool_name} · {bubble.approval.risk}
                  </div>
                  <div className="mt-1 whitespace-pre-wrap text-amber-100">
                    {bubble.approval.summary}
                  </div>
                  <div className="mt-2 flex gap-2">
                    <button
                      className="btn btn-primary"
                      type="button"
                      onClick={() => void decide(bubble.approval!.id, "approved")}
                    >
                      Approve
                    </button>
                    <button
                      className="btn btn-danger"
                      type="button"
                      onClick={() => void decide(bubble.approval!.id, "rejected")}
                    >
                      Reject
                    </button>
                  </div>
                </div>
              ) : null}
            </div>
          </div>
        ))}
        {busy ? <p className="text-xs text-slate-500">thinking…</p> : null}
      </div>

      <form
        className="flex gap-2 border-t border-[var(--color-line)] p-3"
        onSubmit={(event) => {
          event.preventDefault();
          send();
        }}
      >
        <input
          className="field"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          placeholder={lang === "zh-TW" ? "講嘢或者打字…" : "Type a message…"}
        />
        <button className="btn btn-primary" type="submit" disabled={busy || status !== "open"}>
          Send
        </button>
      </form>
    </div>
  );
}
