/**
 * HTTP client for EnPu core (FastAPI).
 * Dual-process integration (#5 UI + #6 scripts/docs).
 * Base URL: VITE_ENPU_CORE_URL or http://127.0.0.1:8765
 */

import type {
  CropRecognizeResponse,
  CropRect,
  ExportResponse,
  HealthResponse,
  PreprocessOptions,
  PreprocessResponse,
  RecognizeResponse,
  SampleMetrics,
  Score,
  StructureBoxEdit,
  StructureDebug,
  StructureRerunResponse,
  TuneParamResult,
} from "./types";

export const DEFAULT_CORE_BASE_URL = "http://127.0.0.1:8765";

export function getCoreBaseUrl(): string {
  const fromEnv = import.meta.env.VITE_ENPU_CORE_URL as string | undefined;
  return (fromEnv && fromEnv.replace(/\/$/, "")) || DEFAULT_CORE_BASE_URL;
}

export class CoreApiError extends Error {
  readonly status?: number;
  readonly kind: "network" | "http" | "parse";

  constructor(
    message: string,
    opts?: { status?: number; kind?: "network" | "http" | "parse" },
  ) {
    super(message);
    this.name = "CoreApiError";
    this.status = opts?.status;
    this.kind = opts?.kind ?? "http";
  }
}

function friendlyNetworkError(err: unknown, baseUrl: string): CoreApiError {
  const msg = err instanceof Error ? err.message : String(err);
  if (
    msg.includes("Failed to fetch") ||
    msg.includes("NetworkError") ||
    msg.includes("fetch")
  ) {
    return new CoreApiError(
      `无法连接识别核心（${baseUrl}）。请先启动：.\\scripts\\start.ps1 或 .\\scripts\\dev-core.ps1（Git Bash: ./scripts/start.sh）`,
      { kind: "network" },
    );
  }
  return new CoreApiError(msg, { kind: "network" });
}

export async function healthCheck(
  baseUrl: string = getCoreBaseUrl(),
  signal?: AbortSignal,
): Promise<HealthResponse> {
  let res: Response;
  try {
    res = await fetch(`${baseUrl}/health`, { signal });
  } catch (err) {
    throw friendlyNetworkError(err, baseUrl);
  }
  if (!res.ok) {
    throw new CoreApiError(`健康检查失败：HTTP ${res.status}`, {
      status: res.status,
      kind: "http",
    });
  }
  try {
    return (await res.json()) as HealthResponse;
  } catch {
    throw new CoreApiError("健康检查响应不是合法 JSON", { kind: "parse" });
  }
}

function appendPreprocessForm(
  form: FormData,
  opts?: Partial<PreprocessOptions> | null,
  crop?: CropRect | null,
) {
  if (!opts) return;
  form.append("denoise", opts.denoise ? "true" : "false");
  form.append("deskew", opts.deskew ? "true" : "false");
  form.append("clahe", opts.clahe ? "true" : "false");
  form.append("shadow_remove", opts.shadow_remove ? "true" : "false");
  form.append("adaptive_binary", opts.adaptive_binary ? "true" : "false");
  if (opts.brightness != null) form.append("brightness", String(opts.brightness));
  if (opts.contrast != null) form.append("contrast", String(opts.contrast));
  if (opts.max_side != null) form.append("max_side", String(opts.max_side));
  if (opts.use_selection_crop && crop) {
    form.append("crop_x1", String(crop.x1));
    form.append("crop_y1", String(crop.y1));
    form.append("crop_x2", String(crop.x2));
    form.append("crop_y2", String(crop.y2));
  }
}

/**
 * Upload an image file to POST /v1/recognize.
 */
export async function recognizeImage(
  file: File,
  baseUrl: string = getCoreBaseUrl(),
  signal?: AbortSignal,
  preprocess?: Partial<PreprocessOptions> | null,
  crop?: CropRect | null,
): Promise<RecognizeResponse> {
  const form = new FormData();
  form.append("file", file, file.name || "upload.png");
  appendPreprocessForm(form, preprocess, crop);

  let res: Response;
  try {
    res = await fetch(`${baseUrl}/v1/recognize`, {
      method: "POST",
      body: form,
      signal,
    });
  } catch (err) {
    throw friendlyNetworkError(err, baseUrl);
  }

  if (!res.ok) {
    let detail = `识别失败：HTTP ${res.status}`;
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (typeof body.detail === "string") {
        detail = body.detail;
      } else if (body.detail != null) {
        detail = JSON.stringify(body.detail);
      }
    } catch {
      // ignore body parse errors
    }
    throw new CoreApiError(detail, { status: res.status, kind: "http" });
  }

  try {
    return (await res.json()) as RecognizeResponse;
  } catch {
    throw new CoreApiError("识别响应不是合法 JSON", { kind: "parse" });
  }
}

/** POST /v1/preprocess — preview toolbox result without OCR (#47). */
export async function preprocessImage(
  file: File,
  opts: Partial<PreprocessOptions>,
  crop?: CropRect | null,
  baseUrl: string = getCoreBaseUrl(),
  signal?: AbortSignal,
): Promise<PreprocessResponse> {
  const form = new FormData();
  form.append("file", file, file.name || "upload.png");
  appendPreprocessForm(form, opts, crop);

  let res: Response;
  try {
    res = await fetch(`${baseUrl}/v1/preprocess`, {
      method: "POST",
      body: form,
      signal,
    });
  } catch (err) {
    throw friendlyNetworkError(err, baseUrl);
  }
  if (!res.ok) {
    let detail = `预处理失败：HTTP ${res.status}`;
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      /* ignore */
    }
    throw new CoreApiError(detail, { status: res.status, kind: "http" });
  }
  try {
    return (await res.json()) as PreprocessResponse;
  } catch {
    throw new CoreApiError("预处理响应不是合法 JSON", { kind: "parse" });
  }
}

export const ALLOWED_IMAGE_TYPES = new Set([
  "image/png",
  "image/jpeg",
  "image/jpg",
]);

export const ALLOWED_EXTENSIONS = new Set([".png", ".jpg", ".jpeg"]);

export function isAllowedImageFile(file: File): boolean {
  const type = (file.type || "").toLowerCase();
  if (type && ALLOWED_IMAGE_TYPES.has(type)) {
    return true;
  }
  const name = file.name.toLowerCase();
  const dot = name.lastIndexOf(".");
  if (dot < 0) return false;
  return ALLOWED_EXTENSIONS.has(name.slice(dot));
}

/**
 * POST /v1/recognize/crop — rectangle ROI re-recognize + optional Score merge (#49).
 */
export async function recognizeCrop(
  file: File,
  crop: CropRect,
  opts?: {
    baseScore?: Score | null;
    measureFrom?: number | null;
    measureTo?: number | null;
    baseUrl?: string;
    signal?: AbortSignal;
  },
): Promise<CropRecognizeResponse> {
  const baseUrl = opts?.baseUrl ?? getCoreBaseUrl();
  const form = new FormData();
  form.append("file", file, file.name || "upload.png");
  form.append("x1", String(crop.x1));
  form.append("y1", String(crop.y1));
  form.append("x2", String(crop.x2));
  form.append("y2", String(crop.y2));
  if (opts?.baseScore) {
    form.append("base_score", JSON.stringify(opts.baseScore));
  }
  if (opts?.measureFrom != null) {
    form.append("measure_from", String(opts.measureFrom));
  }
  if (opts?.measureTo != null) {
    form.append("measure_to", String(opts.measureTo));
  }

  let res: Response;
  try {
    res = await fetch(`${baseUrl}/v1/recognize/crop`, {
      method: "POST",
      body: form,
      signal: opts?.signal,
    });
  } catch (err) {
    throw friendlyNetworkError(err, baseUrl);
  }

  if (!res.ok) {
    let detail = `局部识别失败：HTTP ${res.status}`;
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (typeof body.detail === "string") {
        detail = body.detail;
      } else if (body.detail != null) {
        detail = JSON.stringify(body.detail);
      }
    } catch {
      // ignore
    }
    throw new CoreApiError(detail, { status: res.status, kind: "http" });
  }

  try {
    return (await res.json()) as CropRecognizeResponse;
  } catch {
    throw new CoreApiError("局部识别响应不是合法 JSON", { kind: "parse" });
  }
}

/**
 * POST /v1/recognize/structure/rerun — re-run from an edited structure layer (#78).
 */
export async function recognizeStructureRerun(
  file: File,
  opts: {
    fromLayer: "L1" | "L2" | "L3" | "L4" | "L5";
    baseStructure: StructureDebug;
    edits?: StructureBoxEdit[];
    key?: string | null;
    timeSignature?: string | null;
    title?: string | null;
    baseUrl?: string;
    signal?: AbortSignal;
  },
): Promise<StructureRerunResponse> {
  const baseUrl = opts.baseUrl ?? getCoreBaseUrl();
  const form = new FormData();
  form.append("file", file, file.name || "upload.png");
  form.append("from_layer", opts.fromLayer);
  form.append("base_structure", JSON.stringify(opts.baseStructure));
  if (opts.edits?.length) {
    form.append("edits", JSON.stringify(opts.edits));
  }
  if (opts.key) form.append("key", opts.key);
  if (opts.timeSignature) form.append("time_signature", opts.timeSignature);
  if (opts.title) form.append("title", opts.title);

  let res: Response;
  try {
    res = await fetch(`${baseUrl}/v1/recognize/structure/rerun`, {
      method: "POST",
      body: form,
      signal: opts.signal,
    });
  } catch (err) {
    throw friendlyNetworkError(err, baseUrl);
  }

  if (!res.ok) {
    let detail = `结构层重识别失败：HTTP ${res.status}`;
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
      else if (body.detail != null) detail = JSON.stringify(body.detail);
    } catch {
      /* ignore */
    }
    throw new CoreApiError(detail, { status: res.status, kind: "http" });
  }

  try {
    return (await res.json()) as StructureRerunResponse;
  } catch {
    throw new CoreApiError("结构层重识别响应不是合法 JSON", { kind: "parse" });
  }
}

/**
 * Export Score via POST /v1/export (issue #11 / UI #12).
 */
export async function exportScore(
  score: Score,
  format: "musicxml" | "midi",
  baseUrl: string = getCoreBaseUrl(),
  signal?: AbortSignal,
): Promise<ExportResponse> {
  const qs = new URLSearchParams({ format });
  let res: Response;
  try {
    res = await fetch(`${baseUrl}/v1/export?${qs.toString()}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(score),
      signal,
    });
  } catch (err) {
    throw friendlyNetworkError(err, baseUrl);
  }

  if (!res.ok) {
    let detail = `导出失败：HTTP ${res.status}`;
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (typeof body.detail === "string") {
        detail = body.detail;
      } else if (body.detail != null) {
        detail = JSON.stringify(body.detail);
      }
    } catch {
      // ignore
    }
    throw new CoreApiError(detail, { status: res.status, kind: "http" });
  }

  try {
    return (await res.json()) as ExportResponse;
  } catch {
    throw new CoreApiError("导出响应不是合法 JSON", { kind: "parse" });
  }
}

/** POST /v1/evaluation/compare — layered metrics vs GT (#86). */
export async function evaluateCompare(
  body: {
    sample_id?: string;
    gt: Record<string, unknown>;
    score?: Score | Record<string, unknown> | null;
    structure?: StructureDebug | Record<string, unknown> | null;
    iou_threshold?: number;
    include_errors?: boolean;
  },
  baseUrl: string = getCoreBaseUrl(),
  signal?: AbortSignal,
): Promise<SampleMetrics> {
  let res: Response;
  try {
    res = await fetch(`${baseUrl}/v1/evaluation/compare`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        sample_id: body.sample_id ?? "sample",
        gt: body.gt,
        score: body.score ?? null,
        structure: body.structure ?? null,
        iou_threshold: body.iou_threshold ?? 0.5,
        include_errors: body.include_errors ?? true,
      }),
      signal,
    });
  } catch (err) {
    throw friendlyNetworkError(err, baseUrl);
  }
  if (!res.ok) {
    let detail = `评测对比失败：HTTP ${res.status}`;
    try {
      const j = (await res.json()) as { detail?: unknown };
      if (typeof j.detail === "string") detail = j.detail;
    } catch {
      /* ignore */
    }
    throw new CoreApiError(detail, { status: res.status, kind: "http" });
  }
  const data = (await res.json()) as { metrics: SampleMetrics };
  return data.metrics;
}

/** POST /v1/evaluation/tune-param/upload — L3 param grid search (#86). */
export async function evaluateTuneParamUpload(
  file: File,
  opts: {
    gt: Record<string, unknown>;
    param?: string;
    start?: number;
    stop?: number;
    step?: number;
    layer?: string;
    sample_id?: string;
    baseUrl?: string;
    signal?: AbortSignal;
  },
): Promise<TuneParamResult> {
  const baseUrl = opts.baseUrl ?? getCoreBaseUrl();
  const form = new FormData();
  form.append("file", file, file.name || "score.png");
  form.append("gt_json", JSON.stringify(opts.gt));
  form.append("param", opts.param ?? "l3_min_measure_width");
  form.append("start", String(opts.start ?? 16));
  form.append("stop", String(opts.stop ?? 64));
  form.append("step", String(opts.step ?? 8));
  form.append("layer", opts.layer ?? "L3");
  form.append("sample_id", opts.sample_id ?? "tune");

  let res: Response;
  try {
    res = await fetch(`${baseUrl}/v1/evaluation/tune-param/upload`, {
      method: "POST",
      body: form,
      signal: opts.signal,
    });
  } catch (err) {
    throw friendlyNetworkError(err, baseUrl);
  }
  if (!res.ok) {
    let detail = `参数扫描失败：HTTP ${res.status}`;
    try {
      const j = (await res.json()) as { detail?: unknown };
      if (typeof j.detail === "string") detail = j.detail;
    } catch {
      /* ignore */
    }
    throw new CoreApiError(detail, { status: res.status, kind: "http" });
  }
  const data = (await res.json()) as { result: TuneParamResult };
  return data.result;
}
