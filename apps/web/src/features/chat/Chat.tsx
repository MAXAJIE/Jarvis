import { useEffect, useRef, useState } from "react";

import { api, type ApprovalRequest, type Turn } from "../../lib/api";
import { VoiceSession, type VoiceFrame, type VoiceState } from "../../lib/voice";
import { ChatSocket, type ServerFrame } from "../../lib/ws";
import { Orb, Waveform } from "../core/Orb";

type Lang = "en" | "zh-TW";
type Mode = "talking" | "typing";

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
const MODE_KEY = "jarvis.mode";

function stored(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

export default function Chat({
  onDecided,
  voiceReady,
  voiceHint,
  prompt,
  onPromptConsumed,
}: {
  onDecided: () => void;
  voiceReady: boolean;
  voiceHint: string;
  prompt: string | null;
  onPromptConsumed: () => void;
}) {
  const [bubbles, setBubbles] = useState<Bubble[]>([]);
  const [draft, setDraft] = useState("");
  const [status, setStatus] = useState<"connecting" | "open" | "closed">("connecting");
  const [lang, setLang] = useState<Lang>(() => (stored(LANG_KEY) === "zh-TW" ? "zh-TW" : "en"));
  const [mode, setMode] = useState<Mode>(() => (stored(MODE_KEY) === "typing" ? "typing" : "talking"));
  const [provider, setProvider] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [voiceState, setVoiceState] = useState<VoiceState>("idle");
  // The microphone toggle, not a per-utterance button: once on, it stays on and the
  // local VAD decides when an utterance ended.
  const [listening, setListening] = useState(false);
  const voiceRef = useRef<VoiceSession | null>(null);
  const socketRef = useRef<ChatSocket | null>(null);
  const langRef = useRef<Lang>(lang);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const transcriptRef = useRef<HTMLDivElement | null>(null);
  langRef.current = lang;

  useEffect(() => {
    const socket = new ChatSocket(
      (frame: ServerFrame) => {
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
          // A failed turn must release the composer: a provider error that leaves
          // the UI stuck on "thinking…" is indistinguishable from a hang.
          setBusy(false);
          setBubbles((current) => [...current, { id: nextId++, role: "system", text: frame.message }]);
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
      },
      setStatus,
      () => stored(CONVERSATION_KEY),
    );
    socketRef.current = socket;
    socket.connect();
    return () => socket.close();
  }, []);

  // The voice socket is created once and kept: reconnecting per utterance would
  // re-open the conversation on every press, which is the bug the typed socket
  // already had to fix.
  useEffect(() => {
    const session = new VoiceSession(
      () => stored(CONVERSATION_KEY),
      (frame: VoiceFrame) => {
        if (frame.type === "transcript") {
          if (!frame.text) return;
          setBubbles((current) => [
            ...current,
            { id: nextId++, role: "user", text: frame.text },
          ]);
          return;
        }
        if (frame.type === "turn") {
          setBubbles((current) => [
            ...current,
            {
              id: nextId++,
              role: "assistant",
              text: frame.answer || (frame.approval ? "Waiting for your approval." : "(no answer)"),
              events: frame.events.map((event) => ({ name: event.name ?? "", ok: event.ok ?? false })),
              approval: frame.approval as ApprovalRequest | null,
              tainted: frame.tainted,
            },
          ]);
          if (frame.approval) onDecided();
          return;
        }
        if (frame.type === "speech") setNotice(null);
      },
      setVoiceState,
      (message) => {
        setVoiceState("idle");
        setBubbles((current) => [...current, { id: nextId++, role: "system", text: message }]);
      },
    );
    voiceRef.current = session;
    return () => {
      session.close();
      voiceRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const node = transcriptRef.current;
    if (node) node.scrollTop = node.scrollHeight;
  }, [bubbles, busy]);

  // A quick command from the command center arrives as a prompt.
  useEffect(() => {
    if (!prompt) return;
    if (status !== "open") return;
    dispatch(prompt);
    onPromptConsumed();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [prompt, status]);

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

  function dispatch(text: string) {
    const body = text.trim();
    if (!body || !socketRef.current || busy) return;
    setBubbles((current) => [...current, { id: nextId++, role: "user", text: body }]);
    setDraft("");
    setBusy(true);
    socketRef.current.send({ type: "user_message", text: body });
  }

  function send() {
    dispatch(draft);
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

  function changeMode(next: Mode) {
    setMode(next);
    try {
      window.localStorage.setItem(MODE_KEY, next);
    } catch {
      /* ignore */
    }
    if (next === "typing") {
      // Leaving voice must release the microphone. A toggle that keeps recording in
      // a mode the operator cannot see is the worst of both.
      voiceRef.current?.stopListening();
      setListening(false);
      window.setTimeout(() => inputRef.current?.focus(), 0);
    }
  }

  function micMessage(error: unknown): string {
    // A denied microphone is a permission problem the operator can fix, not a
    // silent no-op: say so, and leave typing available.
    const blocked =
      error instanceof DOMException &&
      (error.name === "NotAllowedError" || error.name === "SecurityError");
    if (blocked) return "Microphone blocked. Allow mic access for this site, or type instead.";
    if (error instanceof Error) return `Microphone unavailable: ${error.message}`;
    return "Microphone unavailable.";
  }

  async function toggleListening(): Promise<void> {
    if (!voiceReady || !voiceRef.current) {
      setNotice(voiceHint);
      changeMode("typing");
      return;
    }
    setNotice(null);
    const session = voiceRef.current;
    if (listening) {
      session.stopListening();
      setListening(false);
      return;
    }
    try {
      await session.startListening();
      setListening(true);
    } catch (error) {
      setBubbles((current) => [
        ...current,
        { id: nextId++, role: "system", text: micMessage(error) },
      ]);
      setVoiceState("idle");
    }
  }

  function sendNow(): void {
    voiceRef.current?.flush();
  }

  const talkLabel = !listening
    ? "MICROPHONE OFF · TAP TO START"
    : voiceState === "recording"
      ? "HEARING YOU"
      : voiceState === "thinking"
        ? "THINKING"
        : voiceState === "speaking"
          ? "SPEAKING"
          : voiceState === "connecting"
            ? "CONNECTING"
            : "LISTENING · SPEAK, THEN PAUSE";

  async function decide(id: string, decision: "approved" | "rejected") {
    const body = await api<{ decision: string; turn: Turn | null }>(`/api/approvals/${id}/decide`, {
      method: "POST",
      body: JSON.stringify({ decision }),
    });
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
    <div className="panel flex min-h-0 flex-1 flex-col">
      <div className="panel-head">
        <span className="flex-1">Conversation</span>
        <div className="flex overflow-hidden rounded border border-[var(--color-line)]">
          {(["talking", "typing"] as const).map((value) => (
            <button
              key={value}
              type="button"
              onClick={() => changeMode(value)}
              className={`px-2 py-0.5 text-[0.62rem] tracking-[0.12em] ${
                mode === value ? "bg-cyan-500/20 text-cyan-100" : "text-[var(--color-mute)]"
              }`}
            >
              {value === "talking" ? "VOICE" : "TYPING"}
            </button>
          ))}
        </div>
        <div className="flex overflow-hidden rounded border border-[var(--color-line)]">
          {(["en", "zh-TW"] as const).map((value) => (
            <button
              key={value}
              type="button"
              onClick={() => changeLang(value)}
              className={`px-2 py-0.5 text-[0.62rem] ${
                lang === value ? "bg-cyan-500/20 text-cyan-100" : "text-[var(--color-mute)]"
              }`}
            >
              {value === "en" ? "EN" : "繁中"}
            </button>
          ))}
        </div>
        <span className="text-[0.66rem] text-[var(--color-mute)]">
          ws:{status}
          {provider ? ` · ${provider}` : ""}
        </span>
      </div>

      {mode === "talking" ? (
        <div className="flex shrink-0 flex-col items-center gap-2 border-b border-[var(--color-line)] bg-[radial-gradient(600px_200px_at_50%_0%,rgba(34,211,238,0.12),transparent)] px-4 py-4">
          <Orb
            state={!voiceReady ? "blocked" : listening ? "live" : "idle"}
            subtitle={
              !voiceReady
                ? voiceHint
                : !listening
                  ? "Microphone off"
                  : voiceState === "recording"
                    ? "Hearing you"
                    : voiceState === "speaking"
                      ? "Speaking through Deepgram Aura"
                      : voiceState === "thinking"
                        ? "Working on it"
                        : "Listening for speech"
            }
            onClick={() => void toggleListening()}
            size={132}
          />
          <div className="text-center text-[0.66rem] leading-relaxed text-[var(--color-mute)]">
            <div className="tracking-[0.24em] text-cyan-100">
              {voiceReady ? talkLabel : "VOICE OFFLINE"}
            </div>
            <div className="mt-0.5 max-w-md">
              {voiceReady
                ? listening
                  ? "Speak, then pause. It answers and keeps listening until you switch this off."
                  : "Switch the microphone on once, then just talk. English only for now."
                : voiceHint}
            </div>
          </div>
          <Waveform state={!voiceReady || !listening ? "idle" : "live"} bars={44} />
          <div className="flex items-center gap-2">
            <button
              type="button"
              className="btn"
              aria-pressed={listening}
              onClick={() => void toggleListening()}
            >
              {listening ? "Stop listening" : "Start listening"}
            </button>
            {listening && voiceState === "recording" ? (
              <button type="button" className="btn" onClick={sendNow}>
                Send now
              </button>
            ) : null}
            <button type="button" className="btn" onClick={() => changeMode("typing")}>
              Type instead
            </button>
          </div>
        </div>
      ) : null}

      {notice ? (
        <div className="shrink-0 border-b border-amber-700/40 bg-amber-500/10 px-3 py-1.5 text-[0.66rem] text-amber-200">
          {notice}
        </div>
      ) : null}

      <div ref={transcriptRef} className="mx-auto min-h-0 w-full max-w-3xl flex-1 space-y-2 overflow-y-auto p-3">
        {bubbles.length === 0 ? (
          <p className="text-[0.72rem] leading-relaxed text-[var(--color-mute)]">
            Say “plan my week”, “add task buy milk”, “list my tasks”, or “remember that I live in
            Kuala Lumpur”. Writes to memory wait for your confirmation; anything external or
            destructive stops for approval.
          </p>
        ) : null}
        {bubbles.map((bubble) => (
          <div key={bubble.id} className={bubble.role === "user" ? "flex justify-end" : "flex justify-start"}>
            <div
              className={`bubble ${
                bubble.role === "user" ? "bubble-user" : bubble.role === "system" ? "bubble-system" : ""
              }`}
            >
              {bubble.tainted ? (
                <div className="mb-1 text-[0.62rem] text-amber-300">
                  this turn contained outside content
                </div>
              ) : null}
              {bubble.text}
              {bubble.events?.length ? (
                <div className="mt-2 flex flex-wrap gap-1">
                  {bubble.events.map((event, index) => (
                    <span
                      key={`${event.name}-${index}`}
                      className={`tag ${event.ok ? "tag-ok" : "tag-bad"}`}
                    >
                      {event.name}
                      {event.ok ? "" : " ✕"}
                    </span>
                  ))}
                </div>
              ) : null}
              {bubble.approval ? (
                <div className="mt-2 rounded border border-amber-700/60 bg-amber-500/5 p-2 text-[0.68rem]">
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
        {busy ? <p className="text-[0.66rem] text-[var(--color-mute)]">thinking…</p> : null}
      </div>

      <form
        className="flex shrink-0 items-center gap-2 border-t border-[var(--color-line)] p-2.5"
        onSubmit={(event) => {
          event.preventDefault();
          send();
        }}
      >
        <input
          ref={inputRef}
          className="field"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          placeholder={
            mode === "talking"
              ? "Type your message (voice is one tap away)"
              : lang === "zh-TW"
                ? "打字或者講嘢…"
                : "Type a message…"
          }
        />
        <button className="btn btn-primary" type="submit" disabled={busy || status !== "open"}>
          Send
        </button>
      </form>
    </div>
  );
}
