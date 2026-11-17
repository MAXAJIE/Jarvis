/**
 * Mono 16-bit PCM in a WAV container.
 *
 * Continuous listening needs to stop an utterance at a silence boundary. MediaRecorder
 * cannot do that: it produces webm/opus, and cutting a webm stream at an arbitrary
 * byte leaves a file no decoder will accept. Raw PCM cut at a frame boundary is
 * still valid audio, so the browser sends float frames here and this wraps them.
 *
 * 16 kHz mono is what speech recognition wants and a 20 s utterance stays under
 * 640 kB.
 */

/** Collects frames and keeps a short pre-roll so the first syllable is not clipped. */
export class Utterance {
  private frames: Float32Array[] = [];
  private preRoll: Float32Array[] = [];
  private preRollFrames: number;
  private total = 0;

  constructor(
    private readonly sampleRate: number,
    frameSamples: number,
    preRollMs = 300,
  ) {
    this.preRollFrames = Math.max(1, Math.round(preRollMs / (1000 * (frameSamples / sampleRate))));
  }

  /** Always call this: frames that arrive before speech starts become pre-roll. */
  offer(frame: Float32Array, speaking: boolean): void {
    if (!speaking) {
      this.preRoll.push(frame);
      if (this.preRoll.length > this.preRollFrames) this.preRoll.shift();
      return;
    }
    if (this.frames.length === 0) {
      // The pre-roll is part of the utterance: without it the first consonant of
      // whatever triggered the gate is missing.
      for (const pre of this.preRoll) this.total += pre.length;
      this.frames.push(...this.preRoll);
      this.preRoll = [];
    }
    this.frames.push(frame);
    this.total += frame.length;
  }

  get durationMs(): number {
    return (this.total / this.sampleRate) * 1000;
  }

  reset(): void {
    this.frames = [];
    this.preRoll = [];
    this.total = 0;
  }

  /** True once there is enough audio to be worth transcribing. */
  get hasAudio(): boolean {
    return this.total > 0;
  }

  toWav(): Blob {
    const bytes = this.total * 2;
    const buffer = new ArrayBuffer(44 + bytes);
    const view = new DataView(buffer);
    const write = (offset: number, text: string) => {
      for (let i = 0; i < text.length; i += 1) view.setUint8(offset + i, text.charCodeAt(i));
    };

    write(0, "RIFF");
    view.setUint32(4, 36 + bytes, true);
    write(8, "WAVE");
    write(12, "fmt ");
    view.setUint32(16, 16, true); // PCM chunk size
    view.setUint16(20, 1, true); // PCM
    view.setUint16(22, 1, true); // mono
    view.setUint32(24, this.sampleRate, true);
    view.setUint32(28, this.sampleRate * 2, true); // byte rate
    view.setUint16(32, 2, true); // block align
    view.setUint16(34, 16, true); // bits per sample
    write(36, "data");
    view.setUint32(40, bytes, true);

    let offset = 44;
    for (const frame of this.frames) {
      for (let i = 0; i < frame.length; i += 1) {
        const clamped = Math.max(-1, Math.min(1, frame[i]));
        view.setInt16(offset, clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff, true);
        offset += 2;
      }
    }
    return new Blob([buffer], { type: "audio/wav" });
  }
}
