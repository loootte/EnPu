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

/** Recognition problem tag (#46 / P4-G). */
export type ScoreProblemKind =
  | "low_confidence"
  | "meter_over"
  | "meter_under"
  | "empty_measure"
  | "layout_pollution"
  | "geometry_pitch"
  | "other";

export type ScoreProblemSeverity = "error" | "warning" | "info";

export interface ScoreProblem {
  id: string;
  kind: ScoreProblemKind | string;
  severity?: ScoreProblemSeverity | string;
  message: string;
  measure?: number | null;
  note_index?: number | null;
  confidence?: number | null;
  source?: string | null;
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

/** OCR region with layout class (#34/#45) in input-image pixels. */
export interface LayoutRegion {
  text: string;
  box: BoundingBox;
  kind: "title" | "meta" | "pitch" | "lyrics" | "footer" | "annotation" | "other" | string;
  score?: number | null;
}

/** One drawable structure element from L1–L5 (#58). */
export interface StructureBox {
  layer: "L1" | "L2" | "L3" | "L4" | "L5";
  id: string;
  label: string;
  box: BoundingBox;
  kind?: string;
  pitch?: string | null;
  duration?: string | null;
  underlines?: number | null;
  octave?: number | null;
  confidence?: number | null;
}

export interface StructureBarline {
  system: number;
  x: number;
  y1: number;
  y2: number;
  /** #85 split id for drag/delete */
  id?: string;
  source?: string;
  confidence?: number | null;
  editable?: boolean;
}

export interface StructureDebug {
  pipeline: string;
  summary?: Record<string, unknown>;
  items: StructureBox[];
  barlines?: StructureBarline[];
}

export interface RecognizeResponse {
  ok: boolean;
  engine: string;
  texts: string[];
  boxes: BoundingBox[];
  /** Paired text+box+kind; use pitch regions for dual-view measure map. */
  regions?: LayoutRegion[];
  notes: NoteHint[];
  score?: Score | null;
  /** Present when ENPU_PIPELINE_MODE=structure (#58). */
  structure?: StructureDebug | null;
  meta: RecognizeMeta;
}

/** Full-image pixel crop ROI (#49). */
export interface CropRect {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
}

export interface CropMergeInfo {
  replaced_measure_from?: number | null;
  replaced_measure_to?: number | null;
  inserted_measure_count: number;
  crop: CropRect;
  preserved_outside: boolean;
}

/** POST /v1/recognize/crop response (#49). */
export interface CropRecognizeResponse extends RecognizeResponse {
  crop: CropRect;
  merged_score?: Score | null;
  merge?: CropMergeInfo | null;
}

/** User-edited structure box for layer re-run (#78). */
export interface StructureBoxEdit {
  id: string;
  layer?: StructureBox["layer"];
  label?: string;
  box: BoundingBox;
}

/** POST /v1/recognize/structure/rerun (#78). */
export interface StructureRerunResponse extends RecognizeResponse {
  from_layer: StructureBox["layer"];
  edited_item_count: number;
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

/** Layered evaluation metrics (#86). */
export interface LayerMetric {
  layer: string;
  precision: number;
  recall: number;
  f1: number;
  tp: number;
  fp: number;
  fn: number;
  mean_iou: number;
  mode: string;
  extra?: Record<string, unknown>;
  errors?: MetricErrorBox[];
}

export interface MetricErrorBox {
  kind: "tp" | "fp" | "fn";
  box: BoundingBox;
  iou?: number | null;
}

export interface SampleMetrics {
  sample_id: string;
  layers: Record<string, LayerMetric>;
  warnings: string[];
  meta?: Record<string, unknown>;
}

export interface TuneParamResult {
  param: string;
  layer: string;
  points: Array<{
    param: string;
    value: number | boolean | string;
    f1: number;
    precision: number;
    recall: number;
    extra?: Record<string, unknown>;
  }>;
  best_value: number | boolean | string | null;
  best_f1: number;
  elapsed_sec: number;
  n_runs: number;
  warnings: string[];
}

/** Full layer auto-tune result (#89). */
export interface TuneLayerResult {
  layer: string;
  best_params: Record<string, unknown>;
  best_loss: number;
  best_score: number;
  baseline_loss: number;
  baseline_score: number;
  improved: boolean;
  n_trials: number;
  seed: number;
  elapsed_sec: number;
  warnings: string[];
  trials?: Array<Record<string, unknown>>;
}

/** OpenCV preprocess toolbox options (#47). */
export interface PreprocessOptions {
  denoise: boolean;
  deskew: boolean;
  clahe: boolean;
  shadow_remove: boolean;
  adaptive_binary: boolean;
  brightness: number;
  contrast: number;
  max_side: number;
  /** Use current selection as crop (applied on recognize / preview). */
  use_selection_crop: boolean;
}

export const defaultPreprocessOptions = (): PreprocessOptions => ({
  denoise: true,
  deskew: false,
  clahe: false,
  shadow_remove: false,
  adaptive_binary: false,
  brightness: 0,
  contrast: 1,
  max_side: 2000,
  use_selection_crop: false,
});

export interface PreprocessResponse {
  ok: boolean;
  steps: string[];
  width: number;
  height: number;
  out_width: number;
  out_height: number;
  scale: number;
  image_png_base64: string;
  options: Record<string, unknown>;
  elapsed_ms: number;
}

/**
 * EnPu project file (.enpu.json).
 * v0.1: score + optional source_image name
 * v0.2: + embedded image, structure overlays, session notes
 */
export interface EnPuProject {
  project_version: "0.1" | "0.2" | string;
  kind: "enpu-project";
  title?: string;
  score: Score;
  /** Original image file name (display / re-open hint). */
  source_image?: string | null;
  /**
   * Optional embedded image as data URL (`data:image/png;base64,...`)
   * so 打开工程 can restore the dual-view original.
   */
  source_image_data_url?: string | null;
  /** Structure L1–L5 overlay from last recognition (#58/#78). */
  structure?: StructureDebug | null;
  /** OCR boxes from last recognition (optional dual-view). */
  boxes?: BoundingBox[] | null;
  regions?: LayoutRegion[] | null;
  updated_at?: string;
  created_at?: string;
  notes?: string;
  /** App / pipeline metadata */
  meta?: {
    engine?: string | null;
    pipeline_mode?: string | null;
    enpu_desktop?: string;
    extra?: Record<string, unknown>;
  };
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
