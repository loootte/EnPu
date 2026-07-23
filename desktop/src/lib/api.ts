/**
 * HTTP client for EnPu core (FastAPI).
 * Dual-process integration (#5 UI + #6 scripts/docs).
 * Base URL: VITE_ENPU_CORE_URL or http://127.0.0.1:8765
 */

import type { HealthResponse, RecognizeResponse } from "./types";

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

/**
 * Upload an image file to POST /v1/recognize.
 */
export async function recognizeImage(
  file: File,
  baseUrl: string = getCoreBaseUrl(),
  signal?: AbortSignal,
): Promise<RecognizeResponse> {
  const form = new FormData();
  form.append("file", file, file.name || "upload.png");

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
