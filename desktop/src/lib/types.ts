/** Types mirrored from EnPu core /v1/recognize and /v1/export. */

export interface BoundingBox {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  score?: number | null;
}

export interface NoteHint {
  pitch?: string | null;
  text?: string | null;
  extra?: Record<string, unknown>;
}

/** EnPu Score v0.1 (subset used by UI). */
export type DurationName =
  | "whole"
  | "half"
  | "quarter"
  | "eighth"
  | "sixteenth"
  | "thirty_second";

export interface ScoreNote {
  pitch?: string | null;
  accidental?: string | null;
  octave?: number;
  duration?: DurationName | string;
  dots?: number;
  is_rest?: boolean;
  lyric?: string | null;
  tie?: string | null;
  extra?: Record<string, unknown>;
}

export interface ScoreMeasure {
  number: number;
  notes: ScoreNote[];
  extra?: Record<string, unknown>;
}

export interface ScorePart {
  id?: string;
  name?: string;
  measures: ScoreMeasure[];
  extra?: Record<string, unknown>;
}

export interface ScoreMeta {
  source_image?: string | null;
  engine?: string | null;
  created_by?: string | null;
  comments?: string | null;
  extra?: Record<string, unknown>;
}

export interface Score {
  schema_version: "0.1" | string;
  title?: string;
  key?: string;
  time_signature?: string;
  tempo_bpm?: number | null;
  parts: ScorePart[];
  meta?: ScoreMeta;
  extra?: Record<string, unknown>;
}

export interface RecognizeMeta {
  width: number;
  height: number;
  elapsed_ms: number;
  filename?: string | null;
  content_type?: string | null;
  mock: boolean;
  preprocess_steps?: string[];
  scale?: number;
  item_count?: number;
  parse_mode?: "score" | "hints" | "ocr_only" | null;
  parse_warnings?: string[];
}

export interface RecognizeResponse {
  ok: boolean;
  engine: string;
  texts: string[];
  boxes: BoundingBox[];
  notes: NoteHint[];
  score?: Score | null;
  meta: RecognizeMeta;
}

export interface HealthResponse {
  status: string;
  version?: string | null;
  engine?: string | null;
}

export interface ExportResponse {
  ok: boolean;
  format: "musicxml" | "midi";
  filename: string;
  media_type: string;
  content_base64: string;
  byte_length: number;
  warnings: string[];
}

/** Lightweight EnPu project file (Phase 2 MVP). */
export interface EnPuProject {
  project_version: "0.1";
  kind: "enpu-project";
  title?: string;
  score: Score;
  source_image?: string | null;
  updated_at?: string;
  notes?: string;
}

export type CoreConnectionState = "unknown" | "online" | "offline";

export const DURATION_OPTIONS: DurationName[] = [
  "whole",
  "half",
  "quarter",
  "eighth",
  "sixteenth",
  "thirty_second",
];

export const PITCH_OPTIONS = ["1", "2", "3", "4", "5", "6", "7"] as const;
