import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ImagePicker } from "../components/ImagePicker";
import { ImagePreview } from "../components/ImagePreview";
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
    setFile(f);
    setInfo(`已选择：${f.name}（${Math.round(f.size / 1024)} KB）`);
  };

  const onRecognize = async () => {
    if (!file || loading) return;
    setError(null);
    setInfo(null);
    setLoading(true);
    setResult(null);
    setScore(null);
    setHighlightMeasures(null);
    try {
      const res = await recognizeImage(file, baseUrl);
      setResult(res);
      setScore(scoreFromRecognize(res.score, res.meta.filename || file.name));
      setCoreState("online");
      setInfo(
        `识别完成 · engine=${res.engine} · ${res.texts.length} 段文本 · ${res.meta.elapsed_ms} ms` +
          (res.score ? " · 可编辑 Score" : " · 未解析出 Score") +
          " · 可在原图上框选后局部重识别",
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
      const res = await recognizeCrop(f, sel, {
        baseScore: scoreRef.current,
        baseUrl,
      });
      setResult(res);
      const next =
        res.merged_score != null
          ? scoreFromRecognize(res.merged_score, res.meta.filename || f.name)
          : scoreFromRecognize(res.score, res.meta.filename || f.name);
      if (next) setScore(next);
      const from = res.merge?.replaced_measure_from;
      const to = res.merge?.replaced_measure_to;
      if (from != null && to != null) {
        const list: number[] = [];
        for (let n = from; n <= to; n += 1) list.push(n);
        setHighlightMeasures(list);
      } else {
        setHighlightMeasures(null);
      }
      setCoreState("online");
      const mergeHint =
        res.merge != null
          ? ` · 已合并小节 ${res.merge.replaced_measure_from ?? "?"}-${res.merge.replaced_measure_to ?? "?"}（区外手改保留）`
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
  }, [baseUrl, refreshHealth]);

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
    <div className="mx-auto flex min-h-screen max-w-6xl flex-col gap-6 px-4 py-6 sm:px-6">
      <header className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-xs font-medium tracking-[0.2em] text-indigo-300 uppercase">
            EnPu · Phase 2
          </p>
          <h1 className="mt-1 text-3xl font-bold tracking-tight text-white">
            恩谱
          </h1>
          <p className="mt-1 text-sm text-slate-400">
            导入识别 · 框选精调 · 编辑修正 · 试听 · 导出
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

      <div className="grid flex-1 gap-6 lg:grid-cols-2">
        <section className="flex flex-col gap-4">
          <h2 className="text-sm font-semibold text-slate-200">
            1. 导入 · 预览 · 框选
          </h2>
          <ImagePicker
            disabled={loading}
            onFile={onFile}
            onError={(msg) => {
              setError(msg);
              setInfo(null);
            }}
          />
          <ImagePreview
            src={previewUrl}
            filename={file?.name}
            selectionEnabled={Boolean(file)}
            selection={selection}
            onSelectionChange={setSelection}
            boxes={result?.boxes ?? null}
            highlightSelection
          />
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
          {selection ? (
            <p className="text-[11px] text-slate-500">
              选区（原图像素）：(
              {Math.round(selection.x1)},{Math.round(selection.y1)}) – (
              {Math.round(selection.x2)},{Math.round(selection.y2)}) ·{" "}
              {Math.round(selection.x2 - selection.x1)}×
              {Math.round(selection.y2 - selection.y1)}
            </p>
          ) : (
            <p className="text-[11px] text-slate-600">
              在预览图上拖拽矩形框选有效谱表或问题小节，再点「局部重识别」。选区外人工修改不会被覆盖。
            </p>
          )}
        </section>

        <section className="flex flex-col gap-4">
          <h2 className="text-sm font-semibold text-slate-200">
            2. 编辑 · 试听 · 导出
          </h2>
          <ResultPanel
            result={result}
            loading={loading}
            score={score}
            onScoreChange={setScore}
            coreOnline={coreState === "online"}
            onMessage={onMessage}
            highlightMeasures={highlightMeasures}
          />
        </section>
      </div>

      <footer className="pb-4 text-center text-xs text-slate-500">
        Phase 2 · 框选精调 #49 · core 默认 {baseUrl}
      </footer>
    </div>
  );
}
