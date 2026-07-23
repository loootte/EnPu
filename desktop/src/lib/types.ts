/** Types mirrored from EnPu core /v1/recognize response. */

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
export interface ScoreNote {
  pitch?: string | null;
  duration?: string;
  dots?: number;
  is_rest?: boolean;
  lyric?: string | null;
  octave?: number;
}

export interface ScoreMeasure {
  number: number;
  notes: ScoreNote[];
}

export interface ScorePart {
  id?: string;
  name?: string;
  measures: ScoreMeasure[];
}

export interface Score {
  schema_version: string;
  title?: string;
  key?: string;
  time_signature?: string;
  tempo_bpm?: number | null;
  parts: ScorePart[];
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

export type CoreConnectionState = "unknown" | "online" | "offline";
