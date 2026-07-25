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
import {
  problemMeasureNumbers,
  problemsFromScore,
} from "../lib/problems";
import {
  CoreApiError,
  getCoreBaseUrl,
  healthCheck,
  preprocessImage,
  recognizeCrop,
  recognizeImage,
  recognizeStructureRerun,
} from "../lib/api";
import {
  buildMeasureRects,
  measureRectsFromStructure,
  isLargeStaffRoi,
  pointToMeasureIndex,
  rectToMeasureRange,
} from "../lib/measureLayout";
import {
  emptyScore,
  parseProjectJson,
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

function highestEditedLayer(
  edits: StructureBoxEdit[],
  fallback: StructureLayerId,
): StructureLayerId {
  if (!edits.length) return fallback;
  let best = fallback;
  let bestRank = LAYER_RANK[fallback];
  for (const e of edits) {
    const L = (e.layer || fallback) as StructureLayerId;
    const r = LAYER_RANK[L] ?? 9;
    if (r < bestRank) {
      best = L;
      bestRank = r;
    }
  }
  return best;
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
  // Keep latest score for keyboard crop without stale closures.
  const scoreRef = useRef<Score | null>(null);
  scoreRef.current = score;
  const fileRef = useRef<File | null>(null);
  fileRef.current = file;
  const selectionRef = useRef<CropRect | null>(null);
  selectionRef.current = selection;
  const loadingRef = useRef(false);
  loadingRef.current = loading;

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

  const onFile = (f: File) => {
    setError(null);
    setInfo(null);
    setResult(null);
    setScore(null);
    setSelection(null);
    setHighlightMeasures(null);
    if (preprocessPreviewUrl) {
      URL.revokeObjectURL(preprocessPreviewUrl);
      setPreprocessPreviewUrl(null);
    }
    setPreprocessSteps(null);
    setHoverMeasure(null);
    setLayoutBoxes(null);
    setLayoutRegions(null);
    setFile(f);
    setInfo(`已选择：${f.name}（${Math.round(f.size / 1024)} KB）`);
  };

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
   * Spatial map (#66): prefer structure L3 boxes (1:1 with Score measures);
   * else pitch-region row tiles.
   */
  const allMeasureRects = useMemo((): CropRect[] => {
    if (!nMeasures || !imageSize.w || !imageSize.h) return [];
    const fromL3 = measureRectsFromStructure(result?.structure);
    if (fromL3 && fromL3.length > 0) {
      // Align length to Score measure count (pad/truncate edge cases)
      if (fromL3.length === nMeasures) return fromL3;
      if (fromL3.length > nMeasures) return fromL3.slice(0, nMeasures);
      const padded = [...fromL3];
      const last = fromL3[fromL3.length - 1]!;
      while (padded.length < nMeasures) {
        const w = Math.max(8, last.x2 - last.x1);
        padded.push({
          x1: last.x1,
          y1: last.y2 + 4,
          x2: last.x1 + w,
          y2: last.y2 + 4 + Math.max(8, last.y2 - last.y1),
        });
      }
      return padded;
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

  const onRecognize = async () => {
    if (!file || loading) return;
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
        file,
        baseUrl,
        undefined,
        preprocessOpts,
        preprocessOpts.use_selection_crop ? selection : null,
      );
      setResult(res);
      setLayoutBoxes(res.boxes ?? null);
      setLayoutRegions(res.regions ?? null);
      setScore(scoreFromRecognize(res.score, res.meta.filename || file.name));
      setStructureDraft(
        res.structure ? structuredClone(res.structure) : null,
      );
      setSelectedStructureId(null);
      setStructureEditMode(false);
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
  };

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
          const fromL3 = measureRectsFromStructure(result?.structure);
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
  }, []);

  const onResetStructureEdits = useCallback(() => {
    setStructureDraft(
      result?.structure ? structuredClone(result.structure) : null,
    );
    setSelectedStructureId(null);
    setStructureAddMode(false);
  }, [result?.structure]);

  const onStructureBoxAdd = useCallback(
    (box: BoundingBox, layer: StructureLayerId) => {
      setStructureDraft((prev) => {
        const base =
          prev ??
          (result?.structure
            ? structuredClone(result.structure)
            : { pipeline: "structure", items: [], summary: {} });
        const nSame = base.items.filter((it) => it.layer === layer).length;
        const id = `user-${layer.toLowerCase()}-${Date.now().toString(36)}`;
        const kindByLayer: Record<StructureLayerId, string> = {
          L1: "score",
          L2: "system",
          L3: "measure",
          L4: "note_roi",
          L5: "glyph",
        };
        const labelByLayer: Record<StructureLayerId, string> = {
          L1: "自定义区域",
          L2: `谱行+${nSame + 1}`,
          L3: `m+${nSame + 1}`,
          L4: `n+${nSame + 1}`,
          L5: `g+${nSame + 1}`,
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
        `已添加 ${layer} 区域 · 可继续拖拽调整，然后点「重识别 ${layer} 及下层」`,
      );
    },
    [result?.structure],
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

  const onStructureRerun = useCallback(async () => {
    const f = fileRef.current;
    const base = result?.structure;
    if (!f || !base || structureRerunning || loading) return;
    setError(null);
    setInfo(null);
    setStructureRerunning(true);
    setLoading(true);
    try {
      const edits = collectStructureEdits(base, structureDraft);
      const fromLayer =
        edits.length > 0
          ? highestEditedLayer(edits, structureFromLayer)
          : structureFromLayer;
      // Prefer user's explicit from_layer if higher (earlier) than auto
      const chosen =
        LAYER_RANK[structureFromLayer] <= LAYER_RANK[fromLayer]
          ? structureFromLayer
          : fromLayer;
      const res = await recognizeStructureRerun(f, {
        fromLayer: chosen,
        baseStructure: structureDraft ?? base,
        edits,
        baseUrl,
      });
      setResult(res);
      setLayoutBoxes(res.boxes ?? null);
      setLayoutRegions(res.regions ?? null);
      setScore(scoreFromRecognize(res.score, res.meta.filename || f.name));
      setStructureDraft(
        res.structure ? structuredClone(res.structure) : null,
      );
      setSelectedStructureId(null);
      setOverlayMode("structure");
      setCoreState("online");
      setInfo(
        `结构层重识别完成 · from=${res.from_layer} · 改框 ${res.edited_item_count} · ${res.meta.elapsed_ms} ms · L${res.from_layer.slice(1)} 及下层已更新`,
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
  }, [
    baseUrl,
    loading,
    refreshHealth,
    result?.structure,
    structureDraft,
    structureFromLayer,
    structureRerunning,
  ]);

  // Esc clear selection; Ctrl+Shift+R crop re-recognize
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement | null)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
      if (e.key === "Escape") {
        setSelection(null);
        setSelectedStructureId(null);
        return;
      }
      if (e.key === "R" && e.ctrlKey && e.shiftKey) {
        e.preventDefault();
        void onCropRecognize();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onCropRecognize]);

  const onOpenProject = async (f: File) => {
    setError(null);
    setInfo(null);
    try {
      const text = await f.text();
      const raw = JSON.parse(text) as unknown;
      const proj = parseProjectJson(raw);
      setScore(proj.score);
      setResult(null);
      setFile(null);
      setSelection(null);
      setHighlightMeasures(null);
      setHoverMeasure(null);
      setLayoutBoxes(null);
      setLayoutRegions(null);
      setInfo(`已打开工程：${f.name}${proj.title ? ` · ${proj.title}` : ""}`);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "无法打开工程文件",
      );
    }
  };

  const onMessage = (kind: "info" | "error", message: string) => {
    if (kind === "error") {
      setError(message);
      setInfo(null);
    } else {
      setInfo(message);
      setError(null);
    }
  };

  const coreBadge =
    coreState === "online"
      ? "bg-emerald-500/20 text-emerald-200"
      : coreState === "offline"
        ? "bg-rose-500/20 text-rose-200"
        : "bg-slate-500/20 text-slate-300";

  const coreLabel =
    coreState === "online"
      ? `核心在线${health?.engine ? ` · ${health.engine}` : ""}`
      : coreState === "offline"
        ? "核心离线"
        : "检测中…";

  const canCrop = Boolean(file && selection && !loading);

  return (
    <div className="mx-auto flex min-h-screen w-full max-w-[1920px] flex-col gap-3 px-3 py-3 sm:px-4 lg:px-5">
      <header className="flex shrink-0 flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-xs font-medium tracking-[0.2em] text-indigo-300 uppercase">
            EnPu · Phase 2 / 4
          </p>
          <h1 className="mt-0.5 text-2xl font-bold tracking-tight text-white sm:text-3xl">
            恩谱
          </h1>
          <p className="mt-0.5 text-sm text-slate-400">
            双视图校对 · 框选精调 · 编辑试听 · 导出
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span
            className={`rounded-full px-3 py-1 text-xs font-medium ${coreBadge}`}
            title={baseUrl}
          >
            {coreLabel}
          </span>
          <button
            type="button"
            onClick={() => void refreshHealth()}
            className="rounded-lg border border-white/10 px-3 py-1 text-xs text-slate-300 hover:bg-white/5"
          >
            刷新状态
          </button>
          <span className="text-[11px] text-slate-500">{baseUrl}</span>
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

      <div className="flex shrink-0 flex-wrap items-center gap-2">
        <ImagePicker
          disabled={loading}
          onFile={onFile}
          onError={(msg) => {
            setError(msg);
            setInfo(null);
          }}
        />
        <button
          type="button"
          disabled={!file || loading}
          onClick={() => void onRecognize()}
          className="rounded-lg bg-indigo-500 px-4 py-2 text-sm font-medium text-white transition hover:bg-indigo-400 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {loading ? "识别中…" : "开始识别"}
        </button>
        <button
          type="button"
          disabled={!canCrop}
          onClick={() => void onCropRecognize()}
          className="rounded-lg border border-amber-400/40 bg-amber-500/20 px-4 py-2 text-sm font-medium text-amber-100 transition hover:bg-amber-500/30 disabled:cursor-not-allowed disabled:opacity-40"
          title="对矩形选区重新识别并合并进当前 Score（Ctrl+Shift+R）"
        >
          {loading ? "局部识别中…" : "局部重识别"}
        </button>
        <button
          type="button"
          disabled={loading || !selection}
          onClick={() => setSelection(null)}
          className="rounded-lg border border-white/10 px-4 py-2 text-sm text-slate-300 hover:bg-white/5 disabled:opacity-40"
        >
          清除选区
        </button>
        <button
          type="button"
          disabled={loading}
          onClick={() => projectInputRef.current?.click()}
          className="rounded-lg border border-white/10 px-4 py-2 text-sm text-slate-300 hover:bg-white/5"
        >
          打开工程
        </button>
        <button
          type="button"
          disabled={loading}
          onClick={() => {
            setScore(emptyScore("未命名"));
            setResult(null);
            setFile(null);
            setSelection(null);
            setHighlightMeasures(null);
            setHoverMeasure(null);
            setLayoutBoxes(null);
            setLayoutRegions(null);
            setInfo("已新建空白 Score，可直接编辑后导出");
          }}
          className="rounded-lg border border-white/10 px-4 py-2 text-sm text-slate-300 hover:bg-white/5"
        >
          新建谱
        </button>
        <button
          type="button"
          disabled={loading || (!file && !result && !score && !error)}
          onClick={() => {
            setFile(null);
            setResult(null);
            setScore(null);
            setSelection(null);
            setHighlightMeasures(null);
            setHoverMeasure(null);
            setLayoutBoxes(null);
            setLayoutRegions(null);
            setError(null);
            setInfo(null);
          }}
          className="rounded-lg border border-white/10 px-4 py-2 text-sm text-slate-300 hover:bg-white/5 disabled:opacity-40"
        >
          清空
        </button>
        <input
          ref={projectInputRef}
          type="file"
          accept=".json,.enpu.json,application/json"
          className="hidden"
          onChange={(e) => {
            const f = e.target.files?.[0];
            e.target.value = "";
            if (f) void onOpenProject(f);
          }}
        />
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
              if (on) setOverlayMode("structure");
              if (!on) setStructureAddMode(false);
            }}
            fromLayer={structureFromLayer}
            onFromLayerChange={setStructureFromLayer}
            dirty={structureDirty}
            selectedId={selectedStructureId}
            onRerun={() => void onStructureRerun()}
            onResetEdits={onResetStructureEdits}
            rerunning={structureRerunning}
            addMode={structureAddMode}
            onAddModeChange={setStructureAddMode}
            onDeleteSelected={onDeleteSelectedStructure}
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
              structureAddMode={structureAddMode}
              structureAddLayer={structureFromLayer}
              selectedStructureId={selectedStructureId}
              onSelectStructureId={setSelectedStructureId}
              onStructureBoxChange={onStructureBoxChange}
              onStructureBoxAdd={onStructureBoxAdd}
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
                {structureAddMode
                  ? " · 拖拽添加区域（图像像素）"
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
              onScoreChange={setScore}
              coreOnline={coreState === "online"}
              onMessage={onMessage}
              highlightMeasures={editorHighlights}
              hoverMeasure={hoverMeasure}
              onHoverMeasure={setHoverMeasure}
              focusMeasure={focusMeasure ?? hoverMeasure}
            />
          </section>
        </div>
      </div>

      <footer className="shrink-0 py-1 text-center text-xs text-slate-500">
        双视图 #45 · 问题导航 #46 · 框选 #49 · core {baseUrl}
      </footer>
    </div>
  );
}
