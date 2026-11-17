/**
 * One utterance per turn: press, speak, release.
 *
 * The server does the listening (Deepgram) and the speaking (Aura); this file only
 * moves bytes and plays the mp3 that comes back. It deliberately does not fake a
 * live waveform from the microphone: the bars you see while recording are real
 * recorder state, not an animation pretending to hear you.
 */

export type VoiceFrame =
  | { type: "ready"; conversation_id: string; lang: string }
  | { type: "listening" }
  | { type: "transcript"; text: string; confidence: number; seconds: number }
  | {
      type: "turn";
      answer: string;
      events: { type: string; name?: string; ok?: boolean; detail?: unknown }[];
      approval: unknown;
      tainted: boolean;
      stopped: string;
    }
  | { type: "speech"; mime: string; data: string; chars: number }
  | { type: "error"; message: string; stage?: string };

export type VoiceState = "idle" | "connecting" | "recording" | "thinking" | "speaking";

function socketUrl(resumeId: string | null): string {
  const scheme = window.location.protocol === "https:" ? "wss" : "ws";
  const base = `${scheme}://${window.location.host}/ws/voice`;
  return resumeId ? `${base}?conversation_id=${encodeURIComponent(resumeId)}` : base;
}

export class VoiceSession {
  private ws: WebSocket | null = null;
  private recorder: MediaRecorder | null = null;
  private stream: MediaStream | null = null;
  private audio: HTMLAudioElement | null = null;
  private chunks: Blob[] = [];
  private ready: Promise<void> | null = null;

  constructor(
    private readonly resumeId: () => string | null,
    private readonly onFrame: (frame: VoiceFrame) => void,
    private readonly onState: (state: VoiceState) => void,
    private readonly onError: (message: string) => void,
  ) {}

  open(): Promise<void> {
    if (this.ready) return this.ready;
    this.onState("connecting");
    this.ready = new Promise<void>((resolve, reject) => {
      const ws = new WebSocket(socketUrl(this.resumeId()));
      ws.binaryType = "arraybuffer";
      this.ws = ws;
      ws.onmessage = (event) => {
        let frame: VoiceFrame;
        try {
          frame = JSON.parse(event.data as string) as VoiceFrame;
        } catch {
          this.onError("voice: unreadable frame from server");
          return;
        }
        if (frame.type === "ready") {
          resolve();
          this.onState("idle");
        } else if (frame.type === "error") {
          this.onError(frame.message);
          this.onState("idle");
        } else if (frame.type === "transcript") {
          this.onState("thinking");
        } else if (frame.type === "speech") {
          this.play(frame.data, frame.mime);
        }
        this.onFrame(frame);
      };
      ws.onerror = () => {
        reject(new Error("voice socket failed"));
        this.onError("Voice connection failed. Typing still works.");
        this.onState("idle");
      };
      ws.onclose = () => {
        this.ready = null;
        this.onState("idle");
      };
    });
    return this.ready;
  }

  /** Records one utterance. Throws with a readable message if the mic is denied. */
  async record(): Promise<void> {
    await this.open();
    if (!navigator.mediaDevices?.getUserMedia) {
      throw new Error("This browser has no microphone access (needs https or localhost).");
    }
    this.stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const mime = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
      ? "audio/webm;codecs=opus"
      : "audio/webm";
    this.chunks = [];
    this.recorder = new MediaRecorder(this.stream, { mimeType: mime });
    this.recorder.ondataavailable = (event) => {
      if (event.data.size > 0) {
        this.chunks.push(event.data);
        this.ws?.send(event.data);
      }
    };
    this.ws?.send(JSON.stringify({ type: "audio_start", mime }));
    this.recorder.start(250);
    this.onState("recording");
  }

  /** Stops recording and hands the utterance to the server. */
  stop(): void {
    const recorder = this.recorder;
    if (!recorder || recorder.state === "inactive") return;
    recorder.addEventListener("stop", () => {
      this.ws?.send(JSON.stringify({ type: "audio_end" }));
      this.onState("thinking");
      this.releaseMic();
    });
    recorder.stop();
  }

  private releaseMic(): void {
    this.stream?.getTracks().forEach((track) => track.stop());
    this.stream = null;
    this.recorder = null;
  }

  private play(base64: string, mime: string): void {
    try {
      const bytes = Uint8Array.from(atob(base64), (char) => char.charCodeAt(0));
      const url = URL.createObjectURL(new Blob([bytes], { type: mime }));
      this.audio?.pause();
      this.audio = new Audio(url);
      this.onState("speaking");
      this.audio.onended = () => {
        URL.revokeObjectURL(url);
        this.onState("idle");
      };
      this.audio.onerror = () => {
        URL.revokeObjectURL(url);
        this.onError("Voice reply arrived but the browser could not play it.");
        this.onState("idle");
      };
      void this.audio.play().catch(() => {
        // Autoplay policy: a click started this turn, so playback usually works;
        // when it does not, say so instead of pretending the reply was spoken.
        this.onError("Tap once more to allow audio playback in this tab.");
        this.onState("idle");
      });
    } catch {
      this.onError("Voice reply could not be decoded.");
      this.onState("idle");
    }
  }

  close(): void {
    this.releaseMic();
    this.audio?.pause();
    this.audio = null;
    this.ws?.close();
    this.ws = null;
    this.ready = null;
  }
}
