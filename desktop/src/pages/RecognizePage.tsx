import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ImagePicker } from "../components/ImagePicker";
import {
  ImagePreview,
  type ImageOverlayMode,
} from "../components/ImagePreview";
import { ResultPanel } from "../components/ResultPanel";
import { StatusBanner } from "../components/StatusBanner";
import {
  CoreApiError,
  getCoreBaseUrl,
  healthCheck,
  recognizeCrop,
  recognizeImage,
} from "../lib/api";
import {
  buildMeasureRects,
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
  CoreConnectionState,
  CropRect,
  HealthResponse,
  RecognizeResponse,
  Score,
} from "../lib/types";

export function RecognizePage() {
  const baseUrl = useMemo(() => getCoreBaseUrl(), []);
  const [file, setFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
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
  const [overlayMode, setOverlayMode] = useState<ImageOverlayMode>("boxes");
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

  // Object URL lifecycle for preview
  useEffect(() => {
    if (!file) {
      setPreviewUrl(null);
      return;
    }
    const url = URL.createObjectURL(file);
    setPreviewUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

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

  const noteCounts = useMemo(() => {
    const measures = score?.parts?.[0]?.measures;
    if (!measures?.length) return null;
    return measures.map((m) => Math.max(1, m.notes?.length ?? 1));
  }, [score?.parts]);

  /** Spatial map: pitch regions, row tiles continuous in X (no dead zones). */
  const allMeasureRects = useMemo((): CropRect[] => {
    if (!nMeasures || !imageSize.w || !imageSize.h) return [];
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
      const res = await recognizeImage(file, baseUrl);
      setResult(res);
      setLayoutBoxes(res.boxes ?? null);
      setLayoutRegions(res.regions ?? null);
      setScore(scoreFromRecognize(res.score, res.meta.filename || file.name));
      setCoreState("online");
      setInfo(
        `识别完成 · engine=${res.engine} · ${res.texts.length} 段文本 · ${res.meta.elapsed_ms} ms` +
          (res.score ? " · 可编辑 Score" : " · 未解析出 Score") +
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
          const counts =
            base?.parts?.[0]?.measures?.map((m) =>
              Math.max(1, m.notes?.length ?? 1),
            ) ?? null;
          const rects = buildMeasureRects(
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

  // Esc clear selection; Ctrl+Shift+R crop re-recognize
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement | null)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
      if (e.key === "Escape") {
        setSelection(null);
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
    <div className="mx-auto flex min-h-screen max-w-7xl flex-col gap-6 px-4 py-6 sm:px-6">
      <header className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-xs font-medium tracking-[0.2em] text-indigo-300 uppercase">
            EnPu · Phase 2 / 4
          </p>
          <h1 className="mt-1 text-3xl font-bold tracking-tight text-white">
            恩谱
          </h1>
          <p className="mt-1 text-sm text-slate-400">
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

      <div className="flex flex-wrap gap-2">
        <ImagePicker
          disabled={loading}
          onFile={onFile}
          onError={(msg) => {
            setError(msg);
            setInfo(null);
          }}
        />
      </div>

      <div className="flex flex-wrap gap-2">
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

      {/* Dual-view: left original · right score (#45) */}
      <div className="grid flex-1 gap-4 lg:grid-cols-2 lg:gap-6">
        <section className="flex min-w-0 flex-col gap-2">
          <div className="flex items-center justify-between gap-2">
            <h2 className="text-sm font-semibold text-slate-200">
              原稿对照
            </h2>
            <span className="text-[11px] text-slate-500">
              悬停同步小节 · 原图/叠图/小节格
            </span>
          </div>
          <ImagePreview
            src={previewUrl}
            filename={file?.name}
            selectionEnabled={Boolean(file)}
            selection={selection}
            onSelectionChange={(r) => {
              setSelection(r);
              if (r && nMeasures && imageSize.w) {
                // Preview which measures will be affected
              }
            }}
            boxes={result?.boxes ?? layoutBoxes}
            highlightSelection
            measureRects={allMeasureRects.length ? allMeasureRects : null}
            activeMeasureNumbers={activeMeasureNumbers}
            overlayMode={overlayMode}
            onOverlayModeChange={setOverlayMode}
            onHoverImage={nMeasures > 0 ? onHoverImage : undefined}
          />
          {selection ? (
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
              滚轮缩放 · 空格/中键平移 · 拖拽框选 · 悬停原图联动右侧小节
            </p>
          )}
        </section>

        <section className="flex min-w-0 flex-col gap-2">
          <div className="flex items-center justify-between gap-2">
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
            highlightMeasures={highlightMeasures}
            hoverMeasure={hoverMeasure}
            onHoverMeasure={setHoverMeasure}
            focusMeasure={hoverMeasure}
          />
        </section>
      </div>

      <footer className="pb-4 text-center text-xs text-slate-500">
        双视图 #45 · 框选 #49 · core {baseUrl}
      </footer>
    </div>
  );
}
