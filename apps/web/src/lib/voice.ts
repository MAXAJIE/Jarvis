/**
 * Voice transport: socket, microphone, and playback.
 *
 * Two shapes, one protocol.
 *
 * - **Continuous listening** (the default): the microphone stays open while the
 *   toggle is on. A local energy VAD (`vad.ts`) cuts each utterance at a pause, the
 *   frames are wrapped as a WAV (`wav.ts`) and sent as one turn. After the reply is
 *   played, listening resumes by itself, so a conversation needs no clicking.
 * - **Press to talk** (`record()` / `stop()`): kept for browsers where the capture
 *   graph cannot be built, and used by nothing else.
 *
 * What this file will not do is pretend. If the microphone is denied, playback is
 * blocked, or the graph cannot be created, the caller gets a sentence it can show
 * the operator instead of a silent no-op.
 */

import { EnergyVad } from "./vad";
import { Utterance } from "./wav";

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
      latency_ms?: number;
    }
  | { type: "speech"; mime: string; data: string; chars: number }
  | { type: "error"; message: string; stage?: string };

/**
 * `listening` means the microphone is open and the gate is closed: the operator is
 * mid-conversation but not currently speaking.
 */
export type VoiceState = "idle" | "connecting" | "listening" | "recording" | "thinking" | "speaking";

const TARGET_RATE = 16000;
/** After playback, ignore the room for a moment so the tail of the reply is not heard
 * as an utterance. Echo cancellation helps; this does not depend on it working. */
const ECHO_GUARD_MS = 350;

function socketUrl(resumeId: string | null): string {
  const scheme = window.location.protocol === "https:" ? "wss" : "ws";
  const base = `${scheme}://${window.location.host}/ws/voice`;
  return resumeId ? `${base}?conversation_id=${encodeURIComponent(resumeId)}` : base;
}

interface Capture {
  context: AudioContext;
  stream: MediaStream;
  dispose: () => void;
}

export class VoiceSession {
  private ws: WebSocket | null = null;
  private recorder: MediaRecorder | null = null;
  private capture: Capture | null = null;
  private audio: HTMLAudioElement | null = null;
  private chunks: Blob[] = [];
  private ready: Promise<void> | null = null;

  private vad = new EnergyVad();
  private utterance: Utterance | null = null;
  private continuous = false;
  private suspended = false;
  private sentForThisUtterance = false;
  private mutedUntil = 0;

  constructor(
    private readonly resumeId: () => string | null,
    private readonly onFrame: (frame: VoiceFrame) => void,
    private readonly onState: (state: VoiceState) => void,
    private readonly onError: (message: string) => void,
  ) {}

  get isListening(): boolean {
    return this.continuous && this.capture !== null;
  }

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
          this.onState(this.isListening ? "listening" : "idle");
        } else if (frame.type === "error") {
          this.onError(frame.message);
          this.suspended = false;
          this.onState(this.isListening ? "listening" : "idle");
        } else if (frame.type === "transcript") {
          this.onState("thinking");
        } else if (frame.type === "speech") {
          this.play(frame.data, frame.mime);
        } else if (frame.type === "turn" && !frame.answer) {
          // Nothing to say: no speech frame is coming, so waiting for playback would
          // leave continuous listening suspended forever.
          this.resumeListening();
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
        this.continuous = false;
      };
    });
    return this.ready;
  }

  // --- continuous listening ------------------------------------------------

  /**
   * Opens the microphone and keeps it open until `stopListening()`.
   *
   * Returns only once the capture graph is running, so a permission failure
   * surfaces to the caller instead of leaving a toggle that looks on.
   */
  async startListening(): Promise<void> {
    if (this.capture) return;
    await this.open();
    if (!navigator.mediaDevices?.getUserMedia) {
      throw new Error("This browser has no microphone access (needs https or localhost).");
    }
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
    });
    // A 16 kHz context is what the recogniser wants; browsers resample the device.
    // If the platform refuses that rate, keep the device rate rather than failing.
    let context: AudioContext;
    try {
      context = new AudioContext({ sampleRate: TARGET_RATE });
    } catch {
      context = new AudioContext();
    }
    if (context.state === "suspended") await context.resume();
    const rate = context.sampleRate;
    this.vad = new EnergyVad();
    this.utterance = new Utterance(rate, Math.round(rate * 0.02));
    this.continuous = true;
    this.suspended = false;
    this.sentForThisUtterance = false;

    const handleFrame = (frame: Float32Array, frameMs: number) => this.onAudioFrame(frame, frameMs);
    const source = context.createMediaStreamSource(stream);
    let dispose: () => void;

    try {
      dispose = await this.attachWorklet(context, source, handleFrame);
    } catch {
      // Safari and older Chromium: no AudioWorklet. The deprecated but universal
      // ScriptProcessor still delivers the same frames.
      dispose = this.attachScriptProcessor(context, source, handleFrame);
    }

    this.capture = {
      context,
      stream,
      dispose: () => {
        dispose();
        stream.getTracks().forEach((track) => track.stop());
        void context.close();
      },
    };
    this.onState("listening");
  }

  private async attachWorklet(
    context: AudioContext,
    source: MediaStreamAudioSourceNode,
    onFrame: (frame: Float32Array, frameMs: number) => void,
  ): Promise<() => void> {
    const code = `
      class Capture extends AudioWorkletProcessor {
        process(inputs) {
          const channel = inputs[0] && inputs[0][0];
          if (channel) this.port.postMessage(channel.slice(0));
          return true;
        }
      }
      registerProcessor("jarvis-capture", Capture);
    `;
    const url = URL.createObjectURL(new Blob([code], { type: "application/javascript" }));
    try {
      await context.audioWorklet.addModule(url);
    } finally {
      URL.revokeObjectURL(url);
    }
    const node = new AudioWorkletNode(context, "jarvis-capture");
    const rate = context.sampleRate;
    node.port.onmessage = (event: MessageEvent<Float32Array>) => {
      onFrame(event.data, (event.data.length / rate) * 1000);
    };
    source.connect(node);
    // A worklet with no destination is not pulled in some browsers; a zero gain
    // keeps the graph alive without echoing the microphone into the speakers.
    const sink = context.createGain();
    sink.gain.value = 0;
    node.connect(sink).connect(context.destination);
    return () => {
      node.port.onmessage = null;
      node.disconnect();
      sink.disconnect();
    };
  }

  private attachScriptProcessor(
    context: AudioContext,
    source: MediaStreamAudioSourceNode,
    onFrame: (frame: Float32Array, frameMs: number) => void,
  ): () => void {
    const size = 2048;
    const processor = context.createScriptProcessor(size, 1, 1);
    const rate = context.sampleRate;
    processor.onaudioprocess = (event) => {
      onFrame(new Float32Array(event.inputBuffer.getChannelData(0)), (size / rate) * 1000);
    };
    const sink = context.createGain();
    sink.gain.value = 0;
    source.connect(processor);
    processor.connect(sink).connect(context.destination);
    return () => {
      processor.onaudioprocess = null;
      processor.disconnect();
      sink.disconnect();
    };
  }

  /** One captured block: gate, collect, and send the utterance when it ends. */
  private onAudioFrame(frame: Float32Array, frameMs: number): void {
    if (!this.continuous || this.suspended) return;
    if (performance.now() < this.mutedUntil) return;
    const utterance = this.utterance;
    if (!utterance) return;

    const event = this.vad.push(frame, frameMs);
    utterance.offer(frame, this.vad.isSpeaking);

    if (event?.type === "start") {
      this.sentForThisUtterance = false;
      this.onState("recording");
      return;
    }
    if (event?.type === "end") {
      if (event.reason === "too-short") {
        // A door closing is not a turn. Drop it and keep listening.
        utterance.reset();
        this.onState("listening");
        return;
      }
      this.sendUtterance();
    }
  }

  /** Back to the microphone after a turn, with a short guard against the tail of
   * the reply being heard as speech. */
  private resumeListening(): void {
    this.suspended = false;
    this.mutedUntil = performance.now() + ECHO_GUARD_MS;
    this.sentForThisUtterance = false;
    this.vad = new EnergyVad();
    this.utterance?.reset();
    this.onState(this.isListening ? "listening" : "idle");
  }

  /** Ends the utterance now, without waiting for a pause. */
  flush(): void {
    if (this.utterance?.hasAudio) this.sendUtterance();
  }

  private sendUtterance(): void {
    const utterance = this.utterance;
    if (!utterance || !utterance.hasAudio || this.sentForThisUtterance) return;
    this.sentForThisUtterance = true;
    this.suspended = true;
    const blob = utterance.toWav();
    utterance.reset();
    this.ws?.send(JSON.stringify({ type: "audio_start", mime: "audio/wav" }));
    this.ws?.send(blob);
    this.ws?.send(JSON.stringify({ type: "audio_end" }));
    this.onState("thinking");
  }

  stopListening(): void {
    this.continuous = false;
    this.capture?.dispose();
    this.capture = null;
    this.utterance = null;
    this.vad = new EnergyVad();
    this.suspended = false;
    this.audio?.pause();
    this.onState("idle");
  }

  // --- press to talk (fallback) -------------------------------------------

  async record(): Promise<void> {
    await this.open();
    if (!navigator.mediaDevices?.getUserMedia) {
      throw new Error("This browser has no microphone access (needs https or localhost).");
    }
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const mime = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
      ? "audio/webm;codecs=opus"
      : "audio/webm";
    this.chunks = [];
    this.recorder = new MediaRecorder(stream, { mimeType: mime });
    this.recorder.ondataavailable = (event) => {
      if (event.data.size > 0) {
        this.chunks.push(event.data);
        this.ws?.send(event.data);
      }
    };
    this.ws?.send(JSON.stringify({ type: "audio_start", mime }));
    this.recorder.start(250);
    const context = new AudioContext();
    this.capture = {
      context,
      stream,
      dispose: () => {
        stream.getTracks().forEach((track) => track.stop());
        void context.close();
      },
    };
    this.onState("recording");
  }

  stop(): void {
    const recorder = this.recorder;
    if (!recorder || recorder.state === "inactive") return;
    recorder.addEventListener("stop", () => {
      this.ws?.send(JSON.stringify({ type: "audio_end" }));
      this.onState("thinking");
      this.capture?.dispose();
      this.capture = null;
      this.recorder = null;
    });
    recorder.stop();
  }

  // --- playback ------------------------------------------------------------

  private play(base64: string, mime: string): void {
    try {
      const bytes = Uint8Array.from(atob(base64), (char) => char.charCodeAt(0));
      const url = URL.createObjectURL(new Blob([bytes], { type: mime }));
      this.audio?.pause();
      this.audio = new Audio(url);
      this.onState("speaking");
      const resume = () => {
        URL.revokeObjectURL(url);
        // Listening resumes on its own: that is the whole point of the toggle.
        this.resumeListening();
      };
      this.audio.onended = resume;
      this.audio.onerror = () => {
        resume();
        this.onError("Voice reply arrived but the browser could not play it.");
      };
      void this.audio.play().catch(() => {
        // Autoplay policy: without a gesture the reply cannot be spoken. Say so
        // rather than pretending it was, and keep listening.
        resume();
        this.onError("Tap once to allow audio playback in this tab.");
      });
    } catch {
      this.onError("Voice reply could not be decoded.");
      this.resumeListening();
    }
  }

  close(): void {
    this.continuous = false;
    this.capture?.dispose();
    this.capture = null;
    this.recorder = null;
    this.audio?.pause();
    this.audio = null;
    this.ws?.close();
    this.ws = null;
    this.ready = null;
  }
}
