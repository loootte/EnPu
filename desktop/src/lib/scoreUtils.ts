/** Score helpers: clone, empty template, project I/O shapes. */

import type { EnPuProject, Score, ScoreNote } from "./types";

export function emptyScore(title = ""): Score {
  return {
    schema_version: "0.1",
    title,
    key: "C",
    time_signature: "4/4",
    tempo_bpm: 80,
    parts: [
      {
        id: "P1",
        name: "melody",
        measures: [
          {
            number: 1,
            notes: [
              {
                pitch: "1",
                octave: 0,
                duration: "quarter",
                dots: 0,
                is_rest: false,
                lyric: "",
              },
            ],
          },
        ],
      },
    ],
    meta: {
      created_by: "enpu-desktop",
      comments: "Created in UI editor",
    },
  };
}

export function cloneScore(score: Score): Score {
  return JSON.parse(JSON.stringify(score)) as Score;
}

export function scoreFromRecognize(
  score: Score | null | undefined,
  filename?: string | null,
): Score | null {
  if (!score) return null;
  const s = cloneScore(score);
  if (!s.meta) s.meta = {};
  if (filename && !s.meta.source_image) {
    s.meta.source_image = filename;
  }
  if (!s.parts?.length) {
    s.parts = emptyScore(s.title || "").parts;
  }
  return s;
}

export function defaultNote(): ScoreNote {
  return {
    pitch: "1",
    octave: 0,
    duration: "quarter",
    dots: 0,
    is_rest: false,
    lyric: "",
  };
}

export function toProject(score: Score, sourceImage?: string | null): EnPuProject {
  return {
    project_version: "0.1",
    kind: "enpu-project",
    title: score.title || "untitled",
    score: cloneScore(score),
    source_image: sourceImage ?? score.meta?.source_image ?? null,
    updated_at: new Date().toISOString(),
  };
}

export function parseProjectJson(raw: unknown): EnPuProject {
  if (!raw || typeof raw !== "object") {
    throw new Error("工程文件不是对象");
  }
  const o = raw as Record<string, unknown>;
  // Accept full Score as project for convenience
  if (o.kind === "enpu-project" && o.score && typeof o.score === "object") {
    return o as unknown as EnPuProject;
  }
  if (o.schema_version && o.parts) {
    const score = o as unknown as Score;
    return toProject(score);
  }
  throw new Error("无法识别的工程/Score JSON");
}

/** Jianpu degree → MIDI (C major movable-do; key letter shifts tonic). */
const DEGREE_SEMI: Record<string, number> = {
  "1": 0,
  "2": 2,
  "3": 4,
  "4": 5,
  "5": 7,
  "6": 9,
  "7": 11,
};

const PC_MIDI: Record<string, number> = {
  C: 60,
  D: 62,
  E: 64,
  F: 65,
  G: 67,
  A: 69,
  B: 71,
};

export function parseKeyTonicMidi(key: string | undefined): number {
  const raw = (key || "C").trim();
  const m =
    raw.match(/1\s*=\s*([A-Ga-g][b#]?)/) ||
    raw.match(/^([A-Ga-g])([b#]?)/);
  if (!m) return 60;
  const letter = (m[1] || "C").toUpperCase();
  const acc = m[2] || "";
  let base = PC_MIDI[letter] ?? 60;
  if (acc === "b") base -= 1;
  if (acc === "#") base += 1;
  return base;
}

export function noteToMidi(
  pitch: string | null | undefined,
  octave: number | undefined,
  key: string | undefined,
): number | null {
  if (!pitch || !(pitch in DEGREE_SEMI)) return null;
  const midi =
    parseKeyTonicMidi(key) +
    DEGREE_SEMI[pitch] +
    (octave ?? 0) * 12;
  return Math.max(0, Math.min(127, midi));
}

export function midiToHz(midi: number): number {
  return 440 * Math.pow(2, (midi - 69) / 12);
}

const DUR_BEATS: Record<string, number> = {
  whole: 4,
  half: 2,
  quarter: 1,
  eighth: 0.5,
  sixteenth: 0.25,
  thirty_second: 0.125,
};

export function noteBeats(note: ScoreNote): number {
  const base = DUR_BEATS[note.duration || "quarter"] ?? 1;
  const dots = Math.max(0, Math.min(2, note.dots ?? 0));
  if (dots === 0) return base;
  return base * (2 - Math.pow(0.5, dots));
}

export function tempoToBeatMs(bpm: number | null | undefined): number {
  const t = bpm && bpm > 0 ? bpm : 80;
  return 60000 / t;
}

export function flattenMelody(score: Score): ScoreNote[] {
  const part = score.parts?.[0];
  if (!part) return [];
  return part.measures.flatMap((m) => m.notes || []);
}

export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.rel = "noopener";
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export function downloadText(
  text: string,
  filename: string,
  mime = "application/json",
): void {
  downloadBlob(new Blob([text], { type: `${mime};charset=utf-8` }), filename);
}

export function downloadBase64(
  b64: string,
  filename: string,
  mime: string,
): void {
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  downloadBlob(new Blob([bytes], { type: mime }), filename);
}

export function safeFilename(name: string, ext: string): string {
  const base = (name || "enpu-score")
    .replace(/[^\w\u4e00-\u9fff\-]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 48);
  const e = ext.startsWith(".") ? ext : `.${ext}`;
  return `${base || "enpu-score"}${e}`;
}
