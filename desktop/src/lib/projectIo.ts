/**
 * EnPu project save / open helpers (.enpu.json).
 * Embeds score + optional image + structure for full session restore.
 */

import type {
  BoundingBox,
  EnPuProject,
  LayoutRegion,
  Score,
  StructureDebug,
} from "./types";
import { cloneScore, downloadText, parseProjectJson, safeFilename } from "./scoreUtils";

export const PROJECT_EXT = ".enpu.json";
export const PROJECT_ACCEPT = ".enpu.json,.json,application/json";

export interface ProjectSnapshot {
  score: Score;
  sourceImageName?: string | null;
  sourceImageDataUrl?: string | null;
  structure?: StructureDebug | null;
  boxes?: BoundingBox[] | null;
  regions?: LayoutRegion[] | null;
  engine?: string | null;
  notes?: string | null;
}

/** Build a v0.2 project document from the current session. */
export function buildProject(snap: ProjectSnapshot): EnPuProject {
  const score = cloneScore(snap.score);
  const title = score.title || "untitled";
  if (!score.meta) score.meta = {};
  if (snap.sourceImageName && !score.meta.source_image) {
    score.meta.source_image = snap.sourceImageName;
  }
  return {
    project_version: "0.2",
    kind: "enpu-project",
    title,
    score,
    source_image: snap.sourceImageName ?? score.meta?.source_image ?? null,
    source_image_data_url: snap.sourceImageDataUrl ?? null,
    structure: snap.structure ?? null,
    boxes: snap.boxes ?? null,
    regions: snap.regions ?? null,
    updated_at: new Date().toISOString(),
    created_at: new Date().toISOString(),
    notes: snap.notes ?? undefined,
    meta: {
      engine: snap.engine ?? score.meta?.engine ?? null,
      enpu_desktop: "0.1.0",
      pipeline_mode: snap.structure ? "structure" : null,
    },
  };
}

/** Download project as .enpu.json */
export function saveProjectFile(project: EnPuProject, filenameHint?: string): string {
  const name = safeFilename(
    filenameHint || project.title || "enpu-project",
    PROJECT_EXT,
  );
  downloadText(JSON.stringify(project, null, 2), name, "application/json");
  return name;
}

/** Read File → EnPuProject (supports v0.1 project, v0.2, or bare Score JSON). */
export async function loadProjectFromFile(file: File): Promise<EnPuProject> {
  const text = await file.text();
  let raw: unknown;
  try {
    raw = JSON.parse(text);
  } catch {
    throw new Error("工程文件不是合法 JSON");
  }
  return normalizeProject(raw);
}

export function normalizeProject(raw: unknown): EnPuProject {
  const base = parseProjectJson(raw);
  const o = raw as Record<string, unknown>;
  // parseProjectJson already handles kind + bare Score
  const proj: EnPuProject = {
    ...base,
    project_version:
      typeof o.project_version === "string" ? o.project_version : base.project_version,
    source_image_data_url:
      typeof o.source_image_data_url === "string"
        ? o.source_image_data_url
        : base.source_image_data_url ?? null,
    structure:
      o.structure && typeof o.structure === "object"
        ? (o.structure as StructureDebug)
        : base.structure ?? null,
    boxes: Array.isArray(o.boxes) ? (o.boxes as BoundingBox[]) : base.boxes ?? null,
    regions: Array.isArray(o.regions)
      ? (o.regions as LayoutRegion[])
      : base.regions ?? null,
    meta:
      o.meta && typeof o.meta === "object"
        ? (o.meta as EnPuProject["meta"])
        : base.meta,
  };
  return proj;
}

/** File → data URL (for embedding in project). */
export function fileToDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      if (typeof reader.result === "string") resolve(reader.result);
      else reject(new Error("无法读取图片"));
    };
    reader.onerror = () => reject(reader.error ?? new Error("读取图片失败"));
    reader.readAsDataURL(file);
  });
}

/** data URL → File (so re-recognize still works after open project). */
export async function dataUrlToFile(
  dataUrl: string,
  filename = "restored.png",
): Promise<File> {
  const res = await fetch(dataUrl);
  const blob = await res.blob();
  const type = blob.type || "image/png";
  const name =
    filename.includes(".") ? filename : `${filename}.png`;
  return new File([blob], name, { type });
}

/** Object URL from data URL for preview. */
export function dataUrlToObjectUrl(dataUrl: string): string {
  // Prefer keeping data URL as img src directly — works without revoke issues
  return dataUrl;
}
