/**
 * Energy-based voice activity detection, one 20 ms frame at a time.
 *
 * The job is small and specific: decide when an utterance *starts* and when the
 * operator has *finished talking*, so continuous listening can send one turn
 * without anyone clicking. No model, no library, no server round trip — a pause
 * is a pause.
 *
 * Kept free of DOM types so it can be exercised outside a browser.
 *
 * The threshold adapts instead of being a constant. A fixed RMS threshold is either
 * deaf in a quiet room or always-on next to a fan; this tracks a noise floor from
 * the frames that are *not* speech and opens the gate at a multiple of it.
 */

export interface VadOptions {
  /** How far above the noise floor counts as speech. */
  ratio?: number;
  /** Never open below this RMS, so a silent room does not self-trigger on hiss. */
  floorRms?: number;
  /** Silence after speech that ends the utterance. */
  hangoverMs?: number;
  /** Frames above threshold needed before calling it speech, rejecting clicks. */
  attackMs?: number;
  /** Utterances shorter than this are noise, not a turn. */
  minSpeechMs?: number;
  /** Hard stop, so a stuck gate cannot record forever. */
  maxUtteranceMs?: number;
}

export type VadEvent =
  | { type: "start" }
  | { type: "end"; reason: "silence" | "max" | "too-short"; durationMs: number };

const DEFAULTS: Required<VadOptions> = {
  ratio: 3,
  floorRms: 0.006,
  hangoverMs: 900,
  attackMs: 60,
  minSpeechMs: 300,
  maxUtteranceMs: 20000,
};

export function rms(frame: Float32Array): number {
  if (frame.length === 0) return 0;
  let sum = 0;
  for (let i = 0; i < frame.length; i += 1) sum += frame[i] * frame[i];
  return Math.sqrt(sum / frame.length);
}

export class EnergyVad {
  private readonly opts: Required<VadOptions>;
  private floor = 0.002;
  private speaking = false;
  private aboveMs = 0;
  private quietMs = 0;
  private speechMs = 0;
  private startedAt = 0;

  constructor(options: VadOptions = {}) {
    this.opts = { ...DEFAULTS, ...options };
  }

  get isSpeaking(): boolean {
    return this.speaking;
  }

  /** Current gate level, for a real level meter rather than a fake animation. */
  get threshold(): number {
    return Math.max(this.floor * this.opts.ratio, this.opts.floorRms);
  }

  /**
   * Feed one frame; returns an event when the state changes.
   * `frameMs` is passed rather than assumed so the caller's buffer size is honest.
   */
  push(frame: Float32Array, frameMs: number): VadEvent | null {
    const level = rms(frame);
    const threshold = this.threshold;

    if (!this.speaking) {
      // Track the floor only while listening, so the operator's own voice never
      // raises the bar they have to clear.
      this.floor = this.floor * 0.95 + level * 0.05;
      if (level > threshold) {
        this.aboveMs += frameMs;
        if (this.aboveMs >= this.opts.attackMs) {
          this.speaking = true;
          this.speechMs = this.aboveMs;
          this.quietMs = 0;
          this.startedAt = this.speechMs;
          return { type: "start" };
        }
      } else {
        this.aboveMs = 0;
      }
      return null;
    }

    this.speechMs += frameMs;
    if (level > threshold) {
      this.quietMs = 0;
    } else {
      this.quietMs += frameMs;
    }

    if (this.speechMs >= this.opts.maxUtteranceMs) {
      return this.finish("max");
    }
    if (this.quietMs >= this.opts.hangoverMs) {
      return this.speechMs - this.quietMs < this.opts.minSpeechMs
        ? this.finish("too-short")
        : this.finish("silence");
    }
    return null;
  }

  private finish(reason: "silence" | "max" | "too-short"): VadEvent {
    const durationMs = this.speechMs;
    this.speaking = false;
    this.aboveMs = 0;
    this.quietMs = 0;
    this.speechMs = 0;
    this.startedAt = 0;
    return { type: "end", reason, durationMs };
  }

  /** Length of the utterance so far, for the "listening" indicator. */
  get elapsedMs(): number {
    return this.speaking ? this.speechMs - this.startedAt : 0;
  }
}
