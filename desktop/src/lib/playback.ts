/** Simple WebAudio melody playback for Score (issue #12). */

import {
  flattenMelody,
  midiToHz,
  noteBeats,
  noteToMidi,
  tempoToBeatMs,
} from "./scoreUtils";
import type { Score } from "./types";

export type PlayState = "idle" | "playing" | "paused";

export interface PlaybackHandle {
  stop: () => void;
}

/**
 * Play score melody with a soft square/sine hybrid.
 * Returns a handle to stop early.
 */
export function playScore(
  score: Score,
  opts?: {
    onEnd?: () => void;
    onNote?: (index: number) => void;
  },
): PlaybackHandle {
  const AudioCtx =
    window.AudioContext ||
    (window as unknown as { webkitAudioContext?: typeof AudioContext })
      .webkitAudioContext;
  if (!AudioCtx) {
    throw new Error("当前环境不支持 Web Audio");
  }

  const ctx = new AudioCtx();
  const master = ctx.createGain();
  master.gain.value = 0.18;
  master.connect(ctx.destination);

  const notes = flattenMelody(score);
  const beatMs = tempoToBeatMs(score.tempo_bpm);
  let cancelled = false;
  const timers: number[] = [];
  let t = 0;

  notes.forEach((note, index) => {
    const beats = noteBeats(note);
    const durMs = Math.max(80, beats * beatMs);
    const startMs = t;
    t += durMs;

    if (note.is_rest || !note.pitch) {
      return;
    }
    const midi = noteToMidi(note.pitch, note.octave, score.key);
    if (midi == null) return;
    const hz = midiToHz(midi);

    const id = window.setTimeout(() => {
      if (cancelled) return;
      opts?.onNote?.(index);
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = "triangle";
      osc.frequency.value = hz;
      const now = ctx.currentTime;
      const durSec = durMs / 1000;
      gain.gain.setValueAtTime(0.0001, now);
      gain.gain.exponentialRampToValueAtTime(0.9, now + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, now + Math.max(0.05, durSec * 0.95));
      osc.connect(gain);
      gain.connect(master);
      osc.start(now);
      osc.stop(now + durSec);
    }, startMs);
    timers.push(id);
  });

  const endId = window.setTimeout(() => {
    if (cancelled) return;
    void ctx.close();
    opts?.onEnd?.();
  }, t + 50);
  timers.push(endId);

  return {
    stop: () => {
      cancelled = true;
      for (const id of timers) window.clearTimeout(id);
      void ctx.close();
    },
  };
}
