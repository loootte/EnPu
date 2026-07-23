import { useCallback, useEffect, useMemo, useState } from "react";
import { ImagePicker } from "../components/ImagePicker";
import { ImagePreview } from "../components/ImagePreview";
import { ResultPanel } from "../components/ResultPanel";
import { StatusBanner } from "../components/StatusBanner";
import {
  CoreApiError,
  getCoreBaseUrl,
  healthCheck,
  recognizeImage,
} from "../lib/api";
import type {
  CoreConnectionState,
  HealthResponse,
  RecognizeResponse,
} from "../lib/types";

export function RecognizePage() {
  const baseUrl = useMemo(() => getCoreBaseUrl(), []);
  const [file, setFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [result, setResult] = useState<RecognizeResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [coreState, setCoreState] = useState<CoreConnectionState>("unknown");
  const [health, setHealth] = useState<HealthResponse | null>(null);

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
    setFile(f);
    setInfo(`已选择：${f.name}（${Math.round(f.size / 1024)} KB）`);
  };

  const onRecognize = async () => {
    if (!file || loading) return;
    setError(null);
    setInfo(null);
    setLoading(true);
    setResult(null);
    try {
      const res = await recognizeImage(file, baseUrl);
      setResult(res);
      setCoreState("online");
      setInfo(
        `识别完成 · engine=${res.engine} · ${res.texts.length} 段文本 · ${res.meta.elapsed_ms} ms`,
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

  return (
    <div className="mx-auto flex min-h-screen max-w-6xl flex-col gap-6 px-4 py-6 sm:px-6">
      <header className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-xs font-medium tracking-[0.2em] text-indigo-300 uppercase">
            EnPu · Desktop PoC
          </p>
          <h1 className="mt-1 text-3xl font-bold tracking-tight text-white">
            恩谱
          </h1>
          <p className="mt-1 text-sm text-slate-400">
            导入简谱图片 · 预览 · 识别结果展示
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
          <h2 className="text-sm font-semibold text-slate-200">1. 导入与预览</h2>
          <ImagePicker
            disabled={loading}
            onFile={onFile}
            onError={(msg) => {
              setError(msg);
              setInfo(null);
            }}
          />
          <ImagePreview src={previewUrl} filename={file?.name} />
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
              disabled={loading || (!file && !result && !error)}
              onClick={() => {
                setFile(null);
                setResult(null);
                setError(null);
                setInfo(null);
              }}
              className="rounded-lg border border-white/10 px-4 py-2 text-sm text-slate-300 hover:bg-white/5 disabled:opacity-40"
            >
              清空
            </button>
          </div>
        </section>

        <section className="flex flex-col gap-4">
          <h2 className="text-sm font-semibold text-slate-200">2. 识别结果</h2>
          <ResultPanel result={result} loading={loading} />
        </section>
      </div>

      <footer className="pb-4 text-center text-xs text-slate-500">
        Phase 0 · 需本地 core 运行（默认 {baseUrl}）· 完整联调脚本见 Issue #6
      </footer>
    </div>
  );
}
