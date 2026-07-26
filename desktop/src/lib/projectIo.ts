/**
 * EnPu project save / open helpers (.enpu.json).
 * Embeds score + optional image + structure for full session restore.
 *
 * Prefer the File System Access API (Save / Open dialogs in WebView2 & Chrome)
 * so users pick a folder. Fall back to download + file input when unavailable.
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

export type SaveProjectResult = {
  filename: string;
  /** full path when known (rarely available in browser) */
  path?: string | null;
  method: "picker" | "download";
  message: string;
};

export type OpenProjectResult = {
  project: EnPuProject;
  filename: string;
  method: "picker" | "input";
};

function hasSavePicker(): boolean {
  return typeof window !== "undefined" && "showSaveFilePicker" in window;
}

function hasOpenPicker(): boolean {
  return typeof window !== "undefined" && "showOpenFilePicker" in window;
}

const PROJECT_PICKER_TYPES = [
  {
    description: "EnPu 工程 (.enpu.json)",
    accept: {
      "application/json": [".json", ".enpu.json"],
    },
  },
] as const;

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

/**
 * Save project with system "Save As" dialog when available.
 * Otherwise downloads to the browser Downloads folder and explains where.
 */
export async function saveProjectFile(
  project: EnPuProject,
  filenameHint?: string,
): Promise<SaveProjectResult> {
  const suggested = safeFilename(
    stripProjectExt(filenameHint || project.title || "enpu-project"),
    PROJECT_EXT,
  );
  const text = JSON.stringify(project, null, 2);

  if (hasSavePicker()) {
    try {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const handle = await (window as any).showSaveFilePicker({
        suggestedName: suggested,
        types: PROJECT_PICKER_TYPES,
        excludeAcceptAllOption: false,
      });
      const writable = await handle.createWritable();
      await writable.write(text);
      await writable.close();
      const name = handle.name || suggested;
      return {
        filename: name,
        path: null,
        method: "picker",
        message: `已保存工程到：${name}（请在刚才选择的文件夹中查看）`,
      };
    } catch (err) {
      // User cancelled
      if (err && typeof err === "object" && (err as { name?: string }).name === "AbortError") {
        throw new Error("已取消保存");
      }
      // Fall through to download
      console.warn("showSaveFilePicker failed, fallback to download", err);
    }
  }

  downloadText(text, suggested, "application/json");
  return {
    filename: suggested,
    method: "download",
    message:
      `已下载工程文件「${suggested}」。` +
      `请到系统「下载」文件夹查找（不是打开对话框的默认目录）。` +
      `若要用「打开工程」，请先在下载文件夹中找到该文件。`,
  };
}

/** Open project via system file picker when available. */
export async function openProjectWithPicker(): Promise<OpenProjectResult | null> {
  if (!hasOpenPicker()) return null;
  try {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const handles = await (window as any).showOpenFilePicker({
      multiple: false,
      types: PROJECT_PICKER_TYPES,
      excludeAcceptAllOption: false,
    });
    const handle = handles?.[0];
    if (!handle) return null;
    const file = (await handle.getFile()) as File;
    const project = await loadProjectFromFile(file);
    return {
      project,
      filename: file.name || handle.name || "project.enpu.json",
      method: "picker",
    };
  } catch (err) {
    if (err && typeof err === "object" && (err as { name?: string }).name === "AbortError") {
      return null; // cancelled
    }
    throw err;
  }
}

function stripProjectExt(name: string): string {
  return name
    .replace(/\.enpu\.json$/i, "")
    .replace(/\.json$/i, "")
    .trim() || "enpu-project";
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
