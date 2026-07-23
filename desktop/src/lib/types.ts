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
}

export interface RecognizeResponse {
  ok: boolean;
  engine: string;
  texts: string[];
  boxes: BoundingBox[];
  notes: NoteHint[];
  meta: RecognizeMeta;
}

export interface HealthResponse {
  status: string;
  version?: string | null;
  engine?: string | null;
}

export type CoreConnectionState = "unknown" | "online" | "offline";
