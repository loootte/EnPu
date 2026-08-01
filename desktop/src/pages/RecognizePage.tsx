import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ImagePicker } from "../components/ImagePicker";
import {
  ImagePreview,
  type ImageOverlayMode,
} from "../components/ImagePreview";
import { ResultPanel } from "../components/ResultPanel";
import { StatusBanner } from "../components/StatusBanner";
import { PreprocessPanel } from "../components/PreprocessPanel";
import { ProblemNavPanel } from "../components/ProblemNavPanel";
import {
  StructureLayerPanel,
  defaultStructureLayersEnabled,
  type StructureLayerId,
} from "../components/StructureLayerPanel";
import { LayerMetricsPanel } from "../components/LayerMetricsPanel";
import type { MetricErrorBox, StructureBarline } from "../lib/types";
import { rederiveMeasuresFromSplits } from "../lib/structureGt";
import {
  problemMeasureNumbers,
  problemsFromScore,
} from "../lib/problems";
import {
  AppMenuBar,
  type MenuAction,
} from "../components/AppMenuBar";
import {
  CoreApiError,
  exportScore,
  getCoreBaseUrl,
  healthCheck,
  preprocessImage,
  recognizeCrop,
  recognizeImage,
  recognizeStructureRerun,
} from "../lib/api";
import {
  buildProject,
  dataUrlToFile,
  fileToDataUrl,
  loadProjectFromFile,
  openProjectWithPicker,
  PROJECT_ACCEPT,
  saveProjectFile,
} from "../lib/projectIo";
import {
  buildMeasureRects,
  measureRectsFromStructure,
  isLargeStaffRoi,
  pointToMeasureIndex,
  rectToMeasureRange,
} from "../lib/measureLayout";
import {
  downloadText,
  emptyScore,
  safeFilename,
  scoreFromRecognize,
} from "../lib/scoreUtils";
import type {
  BoundingBox,
  CoreConnectionState,
  CropRect,
  HealthResponse,
  PreprocessOptions,
  RecognizeResponse,
  Score,
  StructureBoxEdit,
  StructureDebug,
} from "../lib/types";
import { defaultPreprocessOptions } from "../lib/types";

const LAYER_RANK: Record<StructureLayerId, number> = {
  L1: 1,
  L2: 2,
  L3: 3,
  L4: 4,
  L5: 5,
};

function boxChanged(a: BoundingBox, b: BoundingBox, eps = 0.5): boolean {
  return (
    Math.abs(a.x1 - b.x1) > eps ||
    Math.abs(a.y1 - b.y1) > eps ||
    Math.abs(a.x2 - b.x2) > eps ||
    Math.abs(a.y2 - b.y2) > eps
  );
}

function collectStructureEdits(
  base: StructureDebug | null | undefined,
  draft: StructureDebug | null | undefined,
): StructureBoxEdit[] {
  if (!base?.items?.length || !draft?.items?.length) return [];
  const byId = new Map(base.items.map((it) => [it.id || `${it.layer}-${it.label}`, it]));
  const edits: StructureBoxEdit[] = [];
  for (const it of draft.items) {
    const id = it.id || `${it.layer}-${it.label}`;
    const prev = byId.get(id);
    if (!prev || boxChanged(prev.box, it.box)) {
      edits.push({ id, layer: it.layer, label: it.label, box: { ...it.box } });
    }
  }
  return edits;
}

/** Map L4 id `l4-m{g}-pitch{i}` → key used by L5 `l5-m{g}-n{i}`. */
function l4ToL5Key(id: string): string | null {
  const m = id.match(/^l4-m(\d+)-(?:pitch|chord|lyric)?(\d+)$/i);
  if (!m) return null;
  return `l5-m${m[1]}-n${m[2]}`;
}

function boxCenter(b: BoundingBox): { cx: number; cy: number } {
  return { cx: (b.x1 + b.x2) / 2, cy: (b.y1 + b.y2) / 2 };
}

/**
 * After L3 re-run the backend already:
 *  - assigned measures to systems by geometry
 *  - sorted by center (reading order)
 *  - renumbered m1..n
 * Do **not** reattach draft boxes by id (l3-m1 was detection order; after
 * sort it points at a different physical box → 1↔3 / 2↔4 swaps).
 *
 * For L3: trust response order & labels; only overlay draft geometry via
 * nearest-center match (1:1, no id).
 * For other layers: pin draft geometry by id as before.
 */
function mergePinnedLayerBoxes(
  draft: StructureDebug | null | undefined,
  response: StructureDebug | null | undefined,
  fromLayer: StructureLayerId,
): StructureDebug | null {
  if (!response?.items?.length) return response ?? null;
  if (!draft?.items?.length) return response;

  // L3 re-run: response is authoritative for order; match draft boxes by center only
  if (fromLayer === "L3") {
    return mergeL3RerunStructure(draft, response);
  }

  const pinRank = LAYER_RANK[fromLayer];
  const draftById = new Map(
    draft.items.map((it) => [it.id || `${it.layer}-${it.label}`, it]),
  );

  const l4BoxByL5Id = new Map<string, BoundingBox>();
  for (const p of draft.items) {
    if (p.layer !== "L4" || LAYER_RANK[p.layer] > pinRank) continue;
    const l5id = l4ToL5Key(p.id || "");
    if (l5id) l4BoxByL5Id.set(l5id, { ...p.box });
  }

  let below = response.items.filter((it) => LAYER_RANK[it.layer] > pinRank);
  if (fromLayer === "L4" || fromLayer === "L5") {
    below = below.map((it) => {
      if (it.layer !== "L5") return it;
      const id = it.id || `${it.layer}-${it.label}`;
      const box = l4BoxByL5Id.get(id);
      return box ? { ...it, box: { ...box } } : it;
    });
  }

  const aboveFromResponse = response.items.filter(
    (it) => LAYER_RANK[it.layer] <= pinRank,
  );
  const mergedAbove = aboveFromResponse.map((resp) => {
    const id = resp.id || `${resp.layer}-${resp.label}`;
    const d = draftById.get(id);
    if (!d) return resp;
    return {
      ...resp,
      box: { ...d.box },
      id: d.id || resp.id,
      label: d.label || resp.label,
      kind: d.kind ?? resp.kind,
    };
  });

  return {
    ...response,
    items: [...mergedAbove, ...below],
    barlines: response.barlines,
    summary: response.summary,
  };
}

/** L3-specific merge: reading order = response; boxes from draft by nearest center. */
function mergeL3RerunStructure(
  draft: StructureDebug,
  response: StructureDebug,
): StructureDebug {
  const draftL3 = draft.items.filter((it) => it.layer === "L3");
  const used = new Set<number>();

  const matchDraftBox = (respBox: BoundingBox): BoundingBox => {
    const rc = boxCenter(respBox);
    let bestI = -1;
    let bestD = Infinity;
    for (let i = 0; i < draftL3.length; i++) {
      if (used.has(i)) continue;
      const dc = boxCenter(draftL3[i].box);
      const dist = (dc.cx - rc.cx) ** 2 + (dc.cy - rc.cy) ** 2;
      if (dist < bestD) {
        bestD = dist;
        bestI = i;
      }
    }
    // Generous threshold: whole page may be large; prefer any unused nearest
    if (bestI >= 0) {
      used.add(bestI);
      return { ...draftL3[bestI].box };
    }
    return { ...respBox };
  };

  // L1/L2: prefer draft geometry by id (stable)
  const draftById = new Map(
    draft.items.map((it) => [it.id || `${it.layer}-${it.label}`, it]),
  );

  const items = response.items.map((resp) => {
    if (resp.layer === "L3") {
      // Keep response id/label (m1, m2… reading order); box from draft geometry
      return {
        ...resp,
        box: matchDraftBox(resp.box),
      };
    }
    if (resp.layer === "L1" || resp.layer === "L2") {
      const id = resp.id || `${resp.layer}-${resp.label}`;
      const d = draftById.get(id);
      if (d) return { ...resp, box: { ...d.box } };
    }
    return resp;
  });

  // Any draft L3 not matched (user-added, missing from response): insert by geometry
  if (used.size < draftL3.length) {
    const orphans = draftL3.filter((_, i) => !used.has(i));
    const l3Only = items.filter((it) => it.layer === "L3");
    const nonL3 = items.filter((it) => it.layer !== "L3");
    const mergedL3 = [
      ...l3Only,
      ...orphans.map((d, i) => ({
        layer: "L3" as const,
        id: d.id || `user-l3-orphan-${i}`,
        label: "新小节",
        kind: "measure",
        box: { ...d.box },
        confidence: d.confidence,
      })),
    ].sort((a, b) => {
      const ac = boxCenter(a.box);
      const bc = boxCenter(b.box);
      return ac.cy - bc.cy || ac.cx - bc.cx;
    });
    mergedL3.forEach((it, i) => {
      it.label = `m${i + 1}`;
      it.id = `l3-m${i + 1}`;
    });
    return {
      ...response,
      items: [...nonL3, ...mergedL3],
    };
  }

  return { ...response, items };
}

export function RecognizePage() {
  const baseUrl = useMemo(() => getCoreBaseUrl(), []);
  const [file, setFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  /** Object URL for preprocess preview (#47); overrides file preview when set. */
  const [preprocessPreviewUrl, setPreprocessPreviewUrl] = useState<string | null>(
    null,
  );
  const [preprocessOpts, setPreprocessOpts] = useState<PreprocessOptions>(() =>
    defaultPreprocessOptions(),
  );
  const [preprocessSteps, setPreprocessSteps] = useState<string[] | null>(null);
  const [previewingPp, setPreviewingPp] = useState(false);
  const [result, setResult] = useState<RecognizeResponse | null>(null);
  const [score, setScore] = useState<Score | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [coreState, setCoreState] = useState<CoreConnectionState>("unknown");
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [selection, setSelection] = useState<CropRect | null>(null);
  const [highlightMeasures, setHighlightMeasures] = useState<number[] | null>(
    null,
  );
  /** Dual-view (#45): shared hover measure (1-based). */
  const [hoverMeasure, setHoverMeasure] = useState<number | null>(null);
  /** Problem nav (#46): scroll ScoreEditor to this measure. */
  const [focusMeasure, setFocusMeasure] = useState<number | null>(null);
  const [activeProblemId, setActiveProblemId] = useState<string | null>(null);
  const [overlayMode, setOverlayMode] = useState<ImageOverlayMode>("boxes");
  const [structureLayers, setStructureLayers] = useState(
    defaultStructureLayersEnabled,
  );
  /** #78 structure box edit draft (session). */
  const [structureDraft, setStructureDraft] = useState<StructureDebug | null>(
    null,
  );
  const [structureEditMode, setStructureEditMode] = useState(false);
  const [selectedStructureId, setSelectedStructureId] = useState<string | null>(
    null,
  );
  const [structureFromLayer, setStructureFromLayer] =
    useState<StructureLayerId>("L2");
  const [structureRerunning, setStructureRerunning] = useState(false);
  const [structureAddMode, setStructureAddMode] = useState(false);
  /** #86 evaluation */
  const [metricErrors, setMetricErrors] = useState<MetricErrorBox[] | null>(
    null,
  );
  const [layerF1, setLayerF1] = useState<Partial<
    Record<StructureLayerId, number>
  > | null>(null);
  /** #85 selected L3 split line */
  const [selectedBarlineId, setSelectedBarlineId] = useState<string | null>(
    null,
  );

  // Edit mode / layer change: show edit layer (+ parent); clear off-layer selection
  useEffect(() => {
    if (!structureEditMode) return;
    setOverlayMode("structure");
    setStructureLayers((prev) => {
      const next = { ...prev, [structureFromLayer]: true };
      const parentOf: Record<StructureLayerId, StructureLayerId | null> = {
        L5: "L4",
        L4: "L3",
        L3: "L2",
        L2: "L1",
        L1: null,
      };
      const p = parentOf[structureFromLayer];
      if (p) next[p] = true;
      return next;
    });
    setSelectedStructureId((cur) => {
      if (!cur) return null;
      const items = (structureDraft ?? result?.structure)?.items ?? [];
      const it = items.find((x) => (x.id || `${x.layer}-${x.label}`) === cur);
      if (!it || it.layer !== structureFromLayer) return null;
      return cur;
    });
    // Only react to mode/layer changes — not every box drag
    // eslint-disable-next-line react-hooks/exhaustive-deps -- intentional
  }, [structureEditMode, structureFromLayer]);
  /**
   * Full-page layout from last whole-image recognize (natural pixels).
   * Crop only returns ROI boxes — keep full map for dual-view (#45).
   */
  const [layoutBoxes, setLayoutBoxes] = useState<
    import("../lib/types").BoundingBox[] | null
  >(null);
  const [layoutRegions, setLayoutRegions] = useState<
    import("../lib/types").LayoutRegion[] | null
  >(null);
  const projectInputRef = useRef<HTMLInputElement>(null);
  const imageInputRef = useRef<HTMLInputElement>(null);
  const [projectName, setProjectName] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);
  const [imageDataUrl, setImageDataUrl] = useState<string | null>(null);
  // Keep latest score for keyboard crop without stale closures.
  const scoreRef = useRef<Score | null>(null);
  scoreRef.current = score;
  const fileRef = useRef<File | null>(null);
  fileRef.current = file;
  const selectionRef = useRef<CropRect | null>(null);
  selectionRef.current = selection;
  const loadingRef = useRef(false);
  loadingRef.current = loading;
  const dirtyRef = useRef(false);
  dirtyRef.current = dirty;

  // Object URL lifecycle for original file preview
  useEffect(() => {
    if (!file) {
      setPreviewUrl(null);
      return;
    }
    const url = URL.createObjectURL(file);
    setPreviewUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  // Revoke preprocess preview URL on change/unmount
  useEffect(() => {
    return () => {
      if (preprocessPreviewUrl) URL.revokeObjectURL(preprocessPreviewUrl);
    };
  }, [preprocessPreviewUrl]);

  const refreshHealth = useCallback(async () => {
    try {
      const h = await healthCheck(baseUrl);
      setHealth(h);
      setCoreState(h.status === "ok" ? "online" : "offline");
    } catch {
      setHealth(null);
      setCoreState("offline");
    }
  }, [baseUrl]);

  useEffect(() => {
    void refreshHealth();
    const id = window.setInterval(() => void refreshHealth(), 15000);
    return () => window.clearInterval(id);
  }, [refreshHealth]);

  const onScoreChange = useCallback((s: Score) => {
    setScore(s);
    setDirty(true);
  }, []);

  const onFile = (f: File) => {
    setError(null);
    setInfo(null);
    setResult(null);
    setScore(null);
    setSelection(null);
    setHighlightMeasures(null);
    setStructureDraft(null);
    setStructureEditMode(false);
    setProjectName(null);
    setDirty(false);
    if (preprocessPreviewUrl) {
      URL.revokeObjectURL(preprocessPreviewUrl);
      setPreprocessPreviewUrl(null);
    }
    setPreprocessSteps(null);
    setHoverMeasure(null);
    setLayoutBoxes(null);
    setLayoutRegions(null);
    setFile(f);
    void fileToDataUrl(f)
      .then((url) => setImageDataUrl(url))
      .catch(() => setImageDataUrl(null));
    setInfo(`已选择：${f.name}（${Math.round(f.size / 1024)} KB）`);
  };

  const applyOpenedProject = useCallback(
    async (proj: Awaited<ReturnType<typeof loadProjectFromFile>>, name: string) => {
      setScore(proj.score);
      setProjectName(name);
      setDirty(false);
      setSelection(null);
      setHighlightMeasures(null);
      setHoverMeasure(null);
      setStructureEditMode(false);
      setSelectedStructureId(null);

      if (proj.structure) {
        setStructureDraft(structuredClone(proj.structure));
        setResult({
          ok: true,
          engine: proj.meta?.engine || "project",
          texts: [],
          boxes: proj.boxes ?? [],
          regions: proj.regions ?? [],
          notes: [],
          score: proj.score,
          structure: proj.structure,
          meta: {
            width: 0,
            height: 0,
            elapsed_ms: 0,
            filename: proj.source_image ?? name,
            mock: false,
            parse_mode: "score",
            parse_warnings: ["从工程文件恢复"],
          },
        });
        setLayoutBoxes(proj.boxes ?? null);
        setLayoutRegions(proj.regions ?? null);
        setOverlayMode("structure");
      } else {
        setResult(null);
        setStructureDraft(null);
        setLayoutBoxes(proj.boxes ?? null);
        setLayoutRegions(proj.regions ?? null);
      }

      if (proj.source_image_data_url) {
        setImageDataUrl(proj.source_image_data_url);
        const restored = await dataUrlToFile(
          proj.source_image_data_url,
          proj.source_image || "restored.png",
        );
        setFile(restored);
      } else {
        setFile(null);
        setImageDataUrl(null);
      }

      setInfo(
        `已打开工程：${name}` +
          (proj.title ? ` · ${proj.title}` : "") +
          (proj.structure ? " · 已恢复结构叠图" : "") +
          (proj.source_image_data_url ? " · 已恢复原图" : " · 无嵌入原图"),
      );
    },
    [],
  );

  const onSaveProject = useCallback(async () => {
    const sc = scoreRef.current;
    if (!sc) {
      setError("没有可保存的谱面，请先识别或新建谱");
      return;
    }
    try {
      let dataUrl = imageDataUrl;
      if (!dataUrl && fileRef.current) {
        dataUrl = await fileToDataUrl(fileRef.current);
        setImageDataUrl(dataUrl);
      }
      const proj = buildProject({
        score: sc,
        sourceImageName: fileRef.current?.name ?? sc.meta?.source_image ?? null,
        sourceImageDataUrl: dataUrl,
        structure: structureDraft ?? result?.structure ?? null,
        boxes: result?.boxes ?? layoutBoxes,
        regions: result?.regions ?? layoutRegions,
        engine: result?.engine ?? health?.engine ?? null,
      });
      const saved = await saveProjectFile(proj, projectName ?? proj.title);
      setProjectName(saved.filename);
      setDirty(false);
      setInfo(
        saved.message +
          (dataUrl ? " · 已嵌入原图与结构层" : " · 仅谱面（未嵌入原图）"),
      );
    } catch (err) {
      const msg = err instanceof Error ? err.message : "保存工程失败";
      if (msg.includes("取消")) {
        setInfo(msg);
        return;
      }
      setError(msg);
    }
  }, [
    health?.engine,
    imageDataUrl,
    layoutBoxes,
    layoutRegions,
    projectName,
    result?.boxes,
    result?.engine,
    result?.regions,
    result?.structure,
    structureDraft,
  ]);

  const onOpenProjectFile = useCallback(
    async (f: File) => {
      setError(null);
      setInfo(null);
      try {
        const proj = await loadProjectFromFile(f);
        await applyOpenedProject(proj, f.name);
      } catch (err) {
        setError(err instanceof Error ? err.message : "无法打开工程文件");
      }
    },
    [applyOpenedProject],
  );

  /** Prefer system open dialog; fall back to hidden file input. */
  const onOpenProjectDialog = useCallback(async () => {
    setError(null);
    try {
      const picked = await openProjectWithPicker();
      if (picked === null) {
        // cancelled or picker unavailable → try input
        if (!("showOpenFilePicker" in window)) {
          projectInputRef.current?.click();
        }
        return;
      }
      await applyOpenedProject(picked.project, picked.filename);
    } catch (err) {
      // Picker failed → fall back to classic file input
      console.warn("openProjectWithPicker failed", err);
      projectInputRef.current?.click();
    }
  }, [applyOpenedProject]);

  const onExportScoreJson = useCallback(() => {
    const sc = scoreRef.current;
    if (!sc) {
      setError("没有可导出的谱面");
      return;
    }
    const name = safeFilename(sc.title || "enpu-score", ".json");
    downloadText(JSON.stringify(sc, null, 2), name, "application/json");
    setInfo(`已导出 Score JSON：${name}`);
  }, []);

  const onExportBinary = useCallback(
    async (format: "musicxml" | "midi") => {
      const sc = scoreRef.current;
      if (!sc) {
        setError("没有可导出的谱面");
        return;
      }
      try {
        const res = await exportScore(sc, format, baseUrl);
        const { downloadBase64 } = await import("../lib/scoreUtils");
        downloadBase64(res.content_base64, res.filename, res.media_type);
        setInfo(`已导出 ${format.toUpperCase()}：${res.filename}`);
        setCoreState("online");
      } catch (err) {
        setError(
          err instanceof CoreApiError
            ? err.message
            : err instanceof Error
              ? err.message
              : String(err),
        );
      }
    },
    [baseUrl],
  );

  const onNewScore = useCallback(() => {
    if (dirtyRef.current) {
      const ok = window.confirm("当前工程有未保存更改，确定新建空白谱？");
      if (!ok) return;
    }
    setScore(emptyScore("未命名"));
    setResult(null);
    setFile(null);
    setImageDataUrl(null);
    setSelection(null);
    setHighlightMeasures(null);
    setHoverMeasure(null);
    setLayoutBoxes(null);
    setLayoutRegions(null);
    setStructureDraft(null);
    setProjectName(null);
    setDirty(true);
    setInfo("已新建空白 Score，可直接编辑后保存工程");
  }, []);

  const onClearWorkspace = useCallback(() => {
    if (dirtyRef.current) {
      const ok = window.confirm("当前工程有未保存更改，确定清空工作区？");
      if (!ok) return;
    }
    setFile(null);
    setResult(null);
    setScore(null);
    setImageDataUrl(null);
    setSelection(null);
    setHighlightMeasures(null);
    setHoverMeasure(null);
    setLayoutBoxes(null);
    setLayoutRegions(null);
    setStructureDraft(null);
    setProjectName(null);
    setDirty(false);
    setError(null);
    setInfo(null);
  }, []);

  const imageSize = useMemo(() => {
    // Prefer meta (original pixels after box unscale); 0 until recognize.
    const w = result?.meta.width ?? 0;
    const h = result?.meta.height ?? 0;
    return { w, h };
  }, [result?.meta.height, result?.meta.width]);

  const nMeasures = score?.parts?.[0]?.measures?.length ?? 0;

  const problemMeasures = useMemo(
    () => problemMeasureNumbers(problemsFromScore(score)),
    [score],
  );

  /** Crop selection highlights ∪ problem measures (red-ish via editor). */
  const editorHighlights = useMemo(() => {
    const set = new Set<number>();
    for (const m of highlightMeasures ?? []) set.add(m);
    for (const m of problemMeasures) set.add(m);
    return set.size ? [...set].sort((a, b) => a - b) : null;
  }, [highlightMeasures, problemMeasures]);

  const noteCounts = useMemo(() => {
    const measures = score?.parts?.[0]?.measures;
    if (!measures?.length) return null;
    return measures.map((m) => Math.max(1, m.notes?.length ?? 1));
  }, [score?.parts]);

  /**
   * Spatial map (#66/#85): prefer structure L3 / split-derived boxes
   * (including edit draft so highlights track dragged split lines);
   * else pitch-region row tiles.
   */
  const allMeasureRects = useMemo((): CropRect[] => {
    if (!nMeasures || !imageSize.w || !imageSize.h) return [];
    // Prefer live edit draft so dual-view tracks L3 split edits
    const fromL3 = measureRectsFromStructure(
      structureDraft ?? result?.structure,
    );
    if (fromL3 && fromL3.length > 0) {
      // #85: trust split-derived geometry; do not invent pad rects that
      // drift away from barlines. Truncate only if Score has fewer slots.
      if (fromL3.length > nMeasures) return fromL3.slice(0, nMeasures);
      return fromL3;
    }
    return buildMeasureRects(
      nMeasures,
      imageSize.w,
      imageSize.h,
      layoutBoxes,
      layoutRegions,
      noteCounts,
    );
  }, [
    imageSize.h,
    imageSize.w,
    layoutBoxes,
    layoutRegions,
    nMeasures,
    noteCounts,
    result?.structure,
    structureDraft,
  ]);

  const selectionPreviewRange = useMemo(() => {
    if (!selection || !nMeasures || !imageSize.w) return null;
    if (isLargeStaffRoi(selection, imageSize.w, imageSize.h)) {
      return { from: 1, to: nMeasures, large: true as const };
    }
    if (!allMeasureRects.length) return null;
    const r = rectToMeasureRange(selection, allMeasureRects);
    return { ...r, large: false as const };
  }, [allMeasureRects, imageSize.h, imageSize.w, nMeasures, selection]);

  const activeMeasureNumbers = useMemo(() => {
    const set = new Set<number>();
    if (hoverMeasure != null) set.add(hoverMeasure);
    if (highlightMeasures) {
      for (const m of highlightMeasures) set.add(m);
    }
    if (selectionPreviewRange && !highlightMeasures?.length) {
      for (
        let m = selectionPreviewRange.from;
        m <= selectionPreviewRange.to;
        m += 1
      ) {
        set.add(m);
      }
    }
    return set.size ? Array.from(set).sort((a, b) => a - b) : null;
  }, [highlightMeasures, hoverMeasure, selectionPreviewRange]);

  const onHoverImage = useCallback(
    (point: { x: number; y: number } | null) => {
      if (!point || !allMeasureRects.length) {
        setHoverMeasure(null);
        return;
      }
      const idx = pointToMeasureIndex(point.x, point.y, allMeasureRects, 20);
      setHoverMeasure(idx == null ? null : idx + 1);
    },
    [allMeasureRects],
  );

  const onPreprocessPreview = async () => {
    if (!file || previewingPp || loading) return;
    setPreviewingPp(true);
    setError(null);
    try {
      const res = await preprocessImage(
        file,
        preprocessOpts,
        preprocessOpts.use_selection_crop ? selection : null,
        baseUrl,
      );
      const bin = atob(res.image_png_base64);
      const bytes = new Uint8Array(bin.length);
      for (let i = 0; i < bin.length; i += 1) bytes[i] = bin.charCodeAt(i);
      const blob = new Blob([bytes], { type: "image/png" });
      const url = URL.createObjectURL(blob);
      if (preprocessPreviewUrl) URL.revokeObjectURL(preprocessPreviewUrl);
      setPreprocessPreviewUrl(url);
      setPreprocessSteps(res.steps);
      setInfo(
        `预处理预览 · ${res.out_width}×${res.out_height} · ${res.elapsed_ms} ms · 识别将使用相同参数`,
      );
      setCoreState("online");
    } catch (err) {
      setError(
        err instanceof CoreApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : String(err),
      );
    } finally {
      setPreviewingPp(false);
    }
  };

  const onRecognize = useCallback(async () => {
    const f = fileRef.current;
    if (!f || loadingRef.current) return;
    setError(null);
    setInfo(null);
    setLoading(true);
    setResult(null);
    setScore(null);
    setHighlightMeasures(null);
    setLayoutBoxes(null);
    setLayoutRegions(null);
    try {
      const res = await recognizeImage(
        f,
        baseUrl,
        undefined,
        preprocessOpts,
        preprocessOpts.use_selection_crop ? selectionRef.current : null,
      );
      setResult(res);
      setLayoutBoxes(res.boxes ?? null);
      setLayoutRegions(res.regions ?? null);
      setScore(scoreFromRecognize(res.score, res.meta.filename || f.name));
      setStructureDraft(
        res.structure ? structuredClone(res.structure) : null,
      );
      setSelectedStructureId(null);
      setStructureEditMode(false);
      setDirty(true);
      setCoreState("online");
      if (res.structure?.items?.length) {
        setOverlayMode("structure");
      }
      const structHint = res.structure?.items?.length
        ? ` · 结构分层 ${res.structure.items.length} 框（可改框重识别）`
        : "";
      const ppHint =
        res.meta.preprocess_steps && res.meta.preprocess_steps.length > 2
          ? ` · 预处理 ${res.meta.preprocess_steps.length} 步`
          : "";
      setInfo(
        `识别完成 · engine=${res.engine} · ${res.texts.length} 段文本 · ${res.meta.elapsed_ms} ms` +
          (res.score ? " · 可编辑 Score" : " · 未解析出 Score") +
          structHint +
          ppHint +
          " · 双视图可悬停联动 · 框选后局部重识别",
      );
      void refreshHealth();
    } catch (err) {
      const message =
        err instanceof CoreApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : String(err);
      setError(message);
      if (err instanceof CoreApiError && err.kind === "network") {
        setCoreState("offline");
      }
    } finally {
      setLoading(false);
    }
  }, [baseUrl, preprocessOpts, refreshHealth]);

  const onCropRecognize = useCallback(async () => {
    const f = fileRef.current;
    const sel = selectionRef.current;
    if (!f || !sel || loadingRef.current) return;
    setError(null);
    setInfo(null);
    setLoading(true);
    try {
      // Spatial measure range from OCR-box map (not page-grid) → explicit merge window.
      const base = scoreRef.current;
      const n = base?.parts?.[0]?.measures?.length ?? 0;
      const metaW = result?.meta.width ?? 0;
      const metaH = result?.meta.height ?? 0;
      let measureFrom: number | undefined;
      let measureTo: number | undefined;
      if (n > 0 && metaW > 0 && metaH > 0) {
        if (isLargeStaffRoi(sel, metaW, metaH)) {
          measureFrom = 1;
          measureTo = n;
        } else {
          const fromL3 = measureRectsFromStructure(
            structureDraft ?? result?.structure,
          );
          const counts =
            base?.parts?.[0]?.measures?.map((m) =>
              Math.max(1, m.notes?.length ?? 1),
            ) ?? null;
          const rects =
            fromL3 && fromL3.length > 0
              ? fromL3.length >= n
                ? fromL3.slice(0, n)
                : fromL3
              : buildMeasureRects(
                  n,
                  metaW,
                  metaH,
                  layoutBoxes,
                  layoutRegions,
                  counts,
                );
          const range = rectToMeasureRange(sel, rects);
          measureFrom = range.from;
          measureTo = range.to;
        }
      }

      const res = await recognizeCrop(f, sel, {
        baseScore: base,
        baseUrl,
        measureFrom: measureFrom ?? null,
        measureTo: measureTo ?? null,
      });
      // Keep full-page layout boxes for dual-view; only merge OCR boxes into display.
      setResult({
        ...res,
        boxes: layoutBoxes?.length
          ? [...layoutBoxes, ...(res.boxes ?? [])]
          : res.boxes,
      });
      const next =
        res.merged_score != null
          ? scoreFromRecognize(res.merged_score, res.meta.filename || f.name)
          : scoreFromRecognize(res.score, res.meta.filename || f.name);
      if (next) setScore(next);
      const from = res.merge?.replaced_measure_from;
      const to = res.merge?.replaced_measure_to;
      if (from != null && to != null) {
        const list: number[] = [];
        for (let nM = from; nM <= to; nM += 1) list.push(nM);
        setHighlightMeasures(list);
      } else {
        setHighlightMeasures(null);
      }
      setCoreState("online");
      const mergeHint =
        res.merge != null
          ? ` · 已合并小节 ${res.merge.replaced_measure_from ?? "?"}-${res.merge.replaced_measure_to ?? "?"}` +
            (measureFrom != null
              ? `（客户端定位 ${measureFrom}-${measureTo}）`
              : "（区外手改保留）")
          : res.score
            ? " · 无 base Score，仅返回选区识别"
            : " · 选区未解析出 Score";
      setInfo(
        `局部重识别完成 · ${res.meta.elapsed_ms} ms · crop ${Math.round(sel.x2 - sel.x1)}×${Math.round(sel.y2 - sel.y1)}${mergeHint}`,
      );
      void refreshHealth();
    } catch (err) {
      const message =
        err instanceof CoreApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : String(err);
      setError(message);
      if (err instanceof CoreApiError && err.kind === "network") {
        setCoreState("offline");
      }
    } finally {
      setLoading(false);
    }
  }, [
    baseUrl,
    layoutBoxes,
    layoutRegions,
    refreshHealth,
    result?.meta.height,
    result?.meta.width,
  ]);

  const structureEdits = useMemo(
    () => collectStructureEdits(result?.structure, structureDraft),
    [result?.structure, structureDraft],
  );
  const structureDirty = structureEdits.length > 0;

  const onStructureBoxChange = useCallback((id: string, box: BoundingBox) => {
    setStructureDraft((prev) => {
      if (!prev?.items?.length) return prev;
      return {
        ...prev,
        items: prev.items.map((it) => {
          const sid = it.id || `${it.layer}-${it.label}`;
          return sid === id ? { ...it, box: { ...box } } : it;
        }),
      };
    });
    setDirty(true);
  }, []);

  /** #85: drag L3 split line */
  const onBarlineMove = useCallback((id: string, x: number) => {
    setStructureDraft((prev) => {
      const base =
        prev ??
        (result?.structure ? structuredClone(result.structure) : null);
      if (!base?.barlines?.length) return prev;
      const nextBars = base.barlines.map((b, i) => {
        const bid = b.id || `bar-${b.system}-${i}`;
        return bid === id ? { ...b, x, source: "user" } : b;
      });
      const updated = { ...base, barlines: nextBars };
      return rederiveMeasuresFromSplits(updated);
    });
    setDirty(true);
  }, [result?.structure]);

  const onBarlineDelete = useCallback((id: string) => {
    setStructureDraft((prev) => {
      const base =
        prev ??
        (result?.structure ? structuredClone(result.structure) : null);
      if (!base?.barlines?.length) return prev;
      const nextBars = base.barlines.filter((b, i) => {
        const bid = b.id || `bar-${b.system}-${i}`;
        return bid !== id;
      });
      const updated = { ...base, barlines: nextBars };
      return rederiveMeasuresFromSplits(updated);
    });
    setSelectedBarlineId(null);
    setDirty(true);
  }, [result?.structure]);

  const onBarlineAdd = useCallback(
    (system: number, x: number, y1: number, y2: number) => {
      setStructureDraft((prev) => {
        const base =
          prev ??
          (result?.structure
            ? structuredClone(result.structure)
            : { pipeline: "structure", items: [], barlines: [], summary: {} });
        const id = `user-split-${Date.now().toString(36)}`;
        const bl: StructureBarline = {
          system,
          x,
          y1,
          y2,
          id,
          source: "user",
          editable: true,
        };
        const updated = {
          ...base,
          barlines: [...(base.barlines ?? []), bl],
        };
        return rederiveMeasuresFromSplits(updated);
      });
      setStructureAddMode(false);
      setDirty(true);
      setInfo("已插入 L3 分割线；小节框已按线重算");
    },
    [result?.structure],
  );

  const onResetStructureEdits = useCallback(() => {
    setStructureDraft(
      result?.structure ? structuredClone(result.structure) : null,
    );
    setSelectedStructureId(null);
    setSelectedBarlineId(null);
    setStructureAddMode(false);
  }, [result?.structure]);

  const onStructureBoxAdd = useCallback(
    (box: BoundingBox, layer: StructureLayerId) => {
      // #85: L3 "add" inserts a vertical split at the box center-x
      if (layer === "L3") {
        const cx = (box.x1 + box.x2) / 2;
        const systems =
          (structureDraft ?? result?.structure)?.items.filter(
            (it) => it.layer === "L2",
          ) ?? [];
        let sysIdx = 0;
        let y1 = box.y1;
        let y2 = box.y2;
        for (let i = 0; i < systems.length; i++) {
          const s = systems[i];
          if (
            cx >= s.box.x1 &&
            cx <= s.box.x2 &&
            (box.y1 + box.y2) / 2 >= s.box.y1 &&
            (box.y1 + box.y2) / 2 <= s.box.y2
          ) {
            sysIdx = i;
            y1 = s.box.y1;
            y2 = s.box.y2;
            break;
          }
        }
        onBarlineAdd(sysIdx, cx, y1, y2);
        return;
      }
      setStructureDraft((prev) => {
        const base =
          prev ??
          (result?.structure
            ? structuredClone(result.structure)
            : { pipeline: "structure", items: [], summary: {} });
        const id = `user-${layer.toLowerCase()}-${Date.now().toString(36)}`;
        const kindByLayer: Record<StructureLayerId, string> = {
          L1: "score",
          L2: "system",
          L3: "measure_derived",
          L4: "note_roi",
          L5: "glyph",
        };
        // Temporary label — L3 numbers are assigned by geometric order on re-run
        const labelByLayer: Record<StructureLayerId, string> = {
          L1: "自定义区域",
          L2: "新谱行",
          L3: "新小节",
          L4: "新音符",
          L5: "新字形",
        };
        const item = {
          layer,
          id,
          label: labelByLayer[layer],
          kind: kindByLayer[layer],
          box: { ...box },
          confidence: 1,
        };
        return { ...base, items: [...base.items, item] };
      });
      setStructureAddMode(false);
      setStructureFromLayer(layer);
      setOverlayMode("structure");
      setInfo(
        `已添加 ${layer} 区域 · 可继续拖拽调整，然后点「按 ${layer} 框重识别下层」`,
      );
    },
    [onBarlineAdd, result?.structure, structureDraft],
  );

  const onDeleteSelectedStructure = useCallback(() => {
    if (!selectedStructureId) return;
    setStructureDraft((prev) => {
      if (!prev?.items?.length) return prev;
      return {
        ...prev,
        items: prev.items.filter(
          (it) => (it.id || `${it.layer}-${it.label}`) !== selectedStructureId,
        ),
      };
    });
    setSelectedStructureId(null);
  }, [selectedStructureId]);

  const onStructureRerun = useCallback(
    async (fromLayerOverride?: StructureLayerId) => {
      const f = fileRef.current;
      const base = result?.structure;
      if (!f || !base || structureRerunning || loading) return;
      const fromLayer = fromLayerOverride ?? structureFromLayer;
      setError(null);
      setInfo(null);
      setStructureRerunning(true);
      setLoading(true);
      try {
        // Always use the UI edit layer. structureDraft already has user boxes;
        // do NOT re-detect that layer — only recompute layers below it.
        const draft = structureDraft ?? base;
        const edits = collectStructureEdits(base, draft);
        const res = await recognizeStructureRerun(f, {
          fromLayer,
          baseStructure: draft,
          edits,
          baseUrl,
        });
        // Keep pinned current-layer boxes from draft if response drifts
        const mergedStructure = mergePinnedLayerBoxes(
          draft,
          res.structure ?? null,
          fromLayer,
        );
        setResult({
          ...res,
          structure: mergedStructure ?? res.structure,
        });
        setLayoutBoxes(res.boxes ?? null);
        setLayoutRegions(res.regions ?? null);
        setScore(scoreFromRecognize(res.score, res.meta.filename || f.name));
        setStructureDraft(
          mergedStructure
            ? structuredClone(mergedStructure)
            : res.structure
              ? structuredClone(res.structure)
              : null,
        );
        setSelectedStructureId(null);
        setOverlayMode("structure");
        setStructureFromLayer(fromLayer);
        setStructureLayers((prev) => ({
          ...prev,
          [fromLayer]: true,
        }));
        setCoreState("online");
        setInfo(
          `已按编辑后的 ${fromLayer} 框重识别其下层 · from=${res.from_layer} · 改框 ${edits.length} · ${res.meta.elapsed_ms} ms`,
        );
        void refreshHealth();
      } catch (err) {
        const message =
          err instanceof CoreApiError
            ? err.message
            : err instanceof Error
              ? err.message
              : String(err);
        setError(message);
        if (err instanceof CoreApiError && err.kind === "network") {
          setCoreState("offline");
        }
      } finally {
        setStructureRerunning(false);
        setLoading(false);
      }
    },
    [
      baseUrl,
      loading,
      refreshHealth,
      result?.structure,
      structureDraft,
      structureFromLayer,
      structureRerunning,
    ],
  );

  const onMenuAction = useCallback(
    (action: MenuAction) => {
      switch (action) {
        case "file.openImage":
          imageInputRef.current?.click();
          break;
        case "file.openProject":
          void onOpenProjectDialog();
          break;
        case "file.saveProject":
          void onSaveProject();
          break;
        case "file.newScore":
          onNewScore();
          break;
        case "file.clear":
          onClearWorkspace();
          break;
        case "recognize.run":
          void onRecognize();
          break;
        case "recognize.crop":
          void onCropRecognize();
          break;
        case "export.json":
          onExportScoreJson();
          break;
        case "export.musicxml":
          void onExportBinary("musicxml");
          break;
        case "export.midi":
          void onExportBinary("midi");
          break;
        case "view.refreshHealth":
          void refreshHealth();
          break;
        case "help.about":
          setInfo(
            "恩谱 EnPu — 简谱结构识别与校对。工程文件 .enpu.json 可保存谱面、结构叠图与原图。",
          );
          break;
        default:
          break;
      }
    },
    [
      onClearWorkspace,
      onCropRecognize,
      onExportBinary,
      onExportScoreJson,
      onNewScore,
      onOpenProjectDialog,
      onRecognize,
      onSaveProject,
      refreshHealth,
    ],
  );

  // Global shortcuts
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement | null)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
      if (e.key === "Escape") {
        setSelection(null);
        setSelectedStructureId(null);
        return;
      }
      if (e.ctrlKey && e.shiftKey && (e.key === "R" || e.key === "r")) {
        e.preventDefault();
        void onCropRecognize();
        return;
      }
      if (e.ctrlKey && e.shiftKey && (e.key === "O" || e.key === "o")) {
        e.preventDefault();
        void onOpenProjectDialog();
        return;
      }
      if (e.ctrlKey && !e.shiftKey && (e.key === "o" || e.key === "O")) {
        e.preventDefault();
        imageInputRef.current?.click();
        return;
      }
      if (e.ctrlKey && (e.key === "s" || e.key === "S")) {
        e.preventDefault();
        void onSaveProject();
        return;
      }
      if (e.ctrlKey && (e.key === "n" || e.key === "N")) {
        e.preventDefault();
        onNewScore();
        return;
      }
      if (e.ctrlKey && e.key === "Enter") {
        e.preventDefault();
        void onRecognize();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [
    onCropRecognize,
    onNewScore,
    onOpenProjectDialog,
    onRecognize,
    onSaveProject,
  ]);

  const onMessage = (kind: "info" | "error", message: string) => {
    if (kind === "error") {
      setError(message);
      setInfo(null);
    } else {
      setInfo(message);
      setError(null);
    }
  };

  const coreLabel =
    coreState === "online"
      ? `核心在线${health?.engine ? ` · ${health.engine}` : ""}`
      : coreState === "offline"
        ? "核心离线"
        : "检测中…";

  const canCrop = Boolean(file && selection && !loading);

  return (
    <div className="mx-auto flex min-h-screen w-full max-w-[1920px] flex-col gap-0">
      <AppMenuBar
        disabled={loading}
        canRecognize={Boolean(file) && !loading}
        canCrop={canCrop}
        canSave={Boolean(score)}
        canExportBinary={Boolean(score) && coreState === "online"}
        coreOnline={coreState === "online"}
        coreLabel={coreLabel}
        dirty={dirty}
        projectName={projectName}
        onAction={onMenuAction}
      />

      <div className="flex min-h-0 flex-1 flex-col gap-3 px-3 py-3 sm:px-4 lg:px-5">
      <header className="flex shrink-0 flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-slate-400">
          双视图校对 · 结构改框 · 工程保存 ·{" "}
          <span className="text-slate-500" title={baseUrl}>
            {coreLabel}
          </span>
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            disabled={!file || loading}
            onClick={() => void onRecognize()}
            className="rounded-lg bg-indigo-500 px-3 py-1.5 text-xs font-medium text-white hover:bg-indigo-400 disabled:opacity-40"
          >
            {loading ? "识别中…" : "开始识别"}
          </button>
          <button
            type="button"
            disabled={!canCrop}
            onClick={() => void onCropRecognize()}
            className="rounded-lg border border-amber-400/40 bg-amber-500/20 px-3 py-1.5 text-xs font-medium text-amber-100 hover:bg-amber-500/30 disabled:opacity-40"
          >
            局部重识别
          </button>
          <button
            type="button"
            disabled={!score || loading}
            onClick={() => void onSaveProject()}
            className="rounded-lg border border-white/10 px-3 py-1.5 text-xs text-slate-200 hover:bg-white/5 disabled:opacity-40"
          >
            保存工程{dirty ? " *" : ""}
          </button>
        </div>
      </header>

      {error ? (
        <StatusBanner
          kind="error"
          message={error}
          onDismiss={() => setError(null)}
        />
      ) : null}
      {info && !error ? (
        <StatusBanner
          kind="info"
          message={info}
          onDismiss={() => setInfo(null)}
        />
      ) : null}

      {/* Hidden file inputs for menu */}
      <input
        ref={imageInputRef}
        type="file"
        accept="image/png,image/jpeg,image/jpg,.png,.jpg,.jpeg"
        className="hidden"
        onChange={(e) => {
          const f = e.target.files?.[0];
          e.target.value = "";
          if (f) onFile(f);
        }}
      />
      <input
        ref={projectInputRef}
        type="file"
        accept={PROJECT_ACCEPT}
        className="hidden"
        onChange={(e) => {
          const f = e.target.files?.[0];
          e.target.value = "";
          if (f) void onOpenProjectFile(f);
        }}
      />

      <div className="flex shrink-0 flex-wrap items-center gap-2">
        <ImagePicker
          disabled={loading}
          onFile={onFile}
          onError={(msg) => {
            setError(msg);
            setInfo(null);
          }}
        />
        {selection ? (
          <button
            type="button"
            disabled={loading}
            onClick={() => setSelection(null)}
            className="rounded-lg border border-white/10 px-3 py-1.5 text-xs text-slate-300 hover:bg-white/5 disabled:opacity-40"
          >
            清除选区
          </button>
        ) : null}
      </div>

      {/* Left tools + dual-view aligned 原稿 | 识别 (#45/#78) — max work area */}
      <div className="flex min-h-0 flex-1 flex-col gap-3 lg:flex-row lg:items-stretch">
        {/* Tools column — narrow so dual-view gets more width */}
        <aside className="flex w-full shrink-0 flex-col gap-2 lg:sticky lg:top-2 lg:w-64 xl:w-72 lg:max-h-[calc(100vh-6rem)] lg:overflow-y-auto">
          <PreprocessPanel
            options={preprocessOpts}
            onChange={setPreprocessOpts}
            onPreview={() => void onPreprocessPreview()}
            previewing={previewingPp}
            disabled={!file || loading}
            hasSelection={Boolean(selection)}
            steps={preprocessSteps}
          />
          <StructureLayerPanel
            structure={structureDraft ?? result?.structure}
            enabled={structureLayers}
            onChange={(next) => {
              setStructureLayers(next);
              if ((structureDraft ?? result?.structure)?.items?.length) {
                setOverlayMode("structure");
              }
            }}
            editMode={structureEditMode}
            onEditModeChange={(on) => {
              setStructureEditMode(on);
              if (on) {
                setOverlayMode("structure");
                setStructureLayers((prev) => ({
                  ...prev,
                  [structureFromLayer]: true,
                }));
              } else {
                setStructureAddMode(false);
                setSelectedStructureId(null);
              }
            }}
            fromLayer={structureFromLayer}
            onFromLayerChange={(L) => {
              setStructureFromLayer(L);
              setSelectedStructureId(null);
              if (structureEditMode) {
                setStructureLayers((prev) => ({ ...prev, [L]: true }));
              }
            }}
            dirty={structureDirty}
            selectedId={selectedStructureId}
            onRerun={() => void onStructureRerun()}
            onResetEdits={onResetStructureEdits}
            rerunning={structureRerunning}
            addMode={structureAddMode}
            onAddModeChange={setStructureAddMode}
            onDeleteSelected={onDeleteSelectedStructure}
            layerF1={layerF1}
          />
          <LayerMetricsPanel
            file={file}
            score={score}
            structure={structureDraft ?? result?.structure}
            autoStructure={result?.structure ?? null}
            disabled={loading || structureRerunning}
            onErrorsChange={setMetricErrors}
            onLayerF1Change={setLayerF1}
            onRequestRerunFromL2={() => {
              setStructureEditMode(true);
              void onStructureRerun("L2");
            }}
          />
          <ProblemNavPanel
            score={score}
            activeId={activeProblemId}
            onSelect={(p) => {
              setActiveProblemId(p.id);
              if (p.measure != null) {
                setFocusMeasure(p.measure);
                setHoverMeasure(p.measure);
              }
            }}
          />
        </aside>

        {/* Dual-view: tops aligned, equal height work areas */}
        <div className="grid min-w-0 min-h-0 flex-1 gap-3 lg:grid-cols-2 lg:gap-4">
          <section className="flex min-h-0 min-w-0 flex-1 flex-col gap-1.5">
            <div className="flex shrink-0 items-center justify-between gap-2">
              <h2 className="text-sm font-semibold text-slate-200">
                原稿对照
              </h2>
              <span className="text-[11px] text-slate-500">
                {result?.structure
                  ? "结构叠图 L1–L5 · 悬停联动"
                  : "悬停同步小节 · 原图/叠图/小节格"}
              </span>
            </div>
            <ImagePreview
              src={preprocessPreviewUrl || previewUrl}
              filename={file?.name}
              selectionEnabled={
                Boolean(file) && !structureEditMode && !structureAddMode
              }
              selection={selection}
              onSelectionChange={(r) => {
                setSelection(r);
              }}
              boxes={result?.boxes ?? layoutBoxes}
              highlightSelection
              measureRects={allMeasureRects.length ? allMeasureRects : null}
              activeMeasureNumbers={activeMeasureNumbers}
              overlayMode={overlayMode}
              onOverlayModeChange={setOverlayMode}
              onHoverImage={nMeasures > 0 ? onHoverImage : undefined}
              structure={structureDraft ?? result?.structure}
              structureLayers={structureLayers}
              structureEditMode={structureEditMode}
              structureEditLayer={structureFromLayer}
              structureAddMode={structureAddMode}
              structureAddLayer={structureFromLayer}
              selectedStructureId={selectedStructureId}
              onSelectStructureId={setSelectedStructureId}
              onStructureBoxChange={onStructureBoxChange}
              onStructureBoxAdd={onStructureBoxAdd}
              metricErrors={metricErrors}
              onBarlineMove={onBarlineMove}
              onBarlineDelete={onBarlineDelete}
              onBarlineAdd={onBarlineAdd}
              selectedBarlineId={selectedBarlineId}
              onSelectBarlineId={setSelectedBarlineId}
            />
            {selection && !structureEditMode ? (
              <p className="text-[11px] text-slate-500">
                选区 {Math.round(selection.x2 - selection.x1)}×
                {Math.round(selection.y2 - selection.y1)}
                {selectionPreviewRange
                  ? selectionPreviewRange.large
                    ? ` · 大框选 → 将替换全部 ${selectionPreviewRange.to} 小节`
                    : ` · 预计小节 ${selectionPreviewRange.from}–${selectionPreviewRange.to}`
                  : ""}
              </p>
            ) : (
              <p className="text-[11px] text-slate-600">
                滚轮缩放 · 空格/中键平移
                {structureAddMode && structureFromLayer === "L3"
                  ? " · 拖出区域：在中心 x 插入 L3 分割线"
                  : structureAddMode
                    ? " · 拖拽添加区域（图像像素）"
                    : structureEditMode && structureFromLayer === "L3"
                      ? " · L3：左右拖动红色分割线 · 双击删线 · 添加区域=插线"
                      : structureEditMode
                        ? " · 点选框自动缩放到上一层并居中 · 拖角调框"
                        : " · 拖拽框选"}
              </p>
            )}
          </section>

          <section className="flex min-h-0 min-w-0 flex-1 flex-col gap-1.5">
            <div className="flex shrink-0 items-center justify-between gap-2">
              <h2 className="text-sm font-semibold text-slate-200">
                识别结果 · 编辑
              </h2>
              {hoverMeasure != null ? (
                <span className="text-[11px] text-amber-200/90">
                  联动小节 {hoverMeasure}
                </span>
              ) : (
                <span className="text-[11px] text-slate-500">试听 / 导出</span>
              )}
            </div>
            <ResultPanel
              result={result}
              loading={loading}
              score={score}
              onScoreChange={onScoreChange}
              coreOnline={coreState === "online"}
              onMessage={onMessage}
              highlightMeasures={editorHighlights}
              hoverMeasure={hoverMeasure}
              onHoverMeasure={setHoverMeasure}
              focusMeasure={focusMeasure ?? hoverMeasure}
              onSaveProject={() => void onSaveProject()}
            />
          </section>
        </div>
      </div>

      <footer className="shrink-0 border-t border-white/5 px-3 py-1.5 text-center text-xs text-slate-500">
        文件菜单保存/打开工程 · 双视图 #45 · 结构改框 #78 · core {baseUrl}
      </footer>
      </div>
    </div>
  );
}
