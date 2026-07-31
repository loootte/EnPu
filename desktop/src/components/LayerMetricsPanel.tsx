/**
 * Layered accuracy metrics panel (#86).
 * Load GT → compare with current structure/score → F1 badges + error overlay toggle.
 */

import { useMemo, useRef, useState } from "react";
import { evaluateCompare, evaluateTuneParamUpload } from "../lib/api";
import type {
  LayerMetric,
  MetricErrorBox,
  SampleMetrics,
  Score,
  StructureDebug,
  TuneParamResult,
} from "../lib/types";
import type { StructureLayerId } from "./StructureLayerPanel";

const LAYER_ORDER = ["L1", "L2", "L3", "L3_barlines", "L4", "L4_pitch", "L5"] as const;

function f1Tone(f1: number | undefined): string {
  if (f1 == null || Number.isNaN(f1)) return "bg-slate-700 text-slate-400";
  if (f1 >= 0.8) return "bg-emerald-500/25 text-emerald-200 border-emerald-400/40";
  if (f1 >= 0.5) return "bg-amber-500/25 text-amber-100 border-amber-400/40";
  return "bg-rose-500/25 text-rose-100 border-rose-400/40";
}

function fmt(n: number | undefined): string {
  if (n == null || Number.isNaN(n)) return "—";
  return n.toFixed(2);
}

export interface LayerMetricsPanelProps {
  file: File | null;
  score: Score | null;
  structure: StructureDebug | null | undefined;
  disabled?: boolean;
  onErrorsChange?: (errors: MetricErrorBox[] | null) => void;
  onLayerF1Change?: (map: Partial<Record<StructureLayerId, number>>) => void;
}

export function LayerMetricsPanel({
  file,
  score,
  structure,
  disabled,
  onErrorsChange,
  onLayerF1Change,
}: LayerMetricsPanelProps) {
  const gtInputRef = useRef<HTMLInputElement>(null);
  const [gt, setGt] = useState<Record<string, unknown> | null>(null);
  const [gtName, setGtName] = useState<string | null>(null);
  const [metrics, setMetrics] = useState<SampleMetrics | null>(null);
  const [tune, setTune] = useState<TuneParamResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showErrors, setShowErrors] = useState(true);
  const [tuneStart, setTuneStart] = useState(16);
  const [tuneStop, setTuneStop] = useState(64);
  const [tuneStep, setTuneStep] = useState(8);

  const layerList = useMemo(() => {
    if (!metrics) return [] as LayerMetric[];
    const layers = metrics.layers || {};
    const ordered = LAYER_ORDER.filter((k) => layers[k]).map((k) => layers[k]);
    const rest = Object.keys(layers)
      .filter((k) => !(LAYER_ORDER as readonly string[]).includes(k))
      .map((k) => layers[k]);
    return [...ordered, ...rest];
  }, [metrics]);

  const onLoadGt = async (f: File) => {
    setError(null);
    try {
      const text = await f.text();
      const data = JSON.parse(text) as Record<string, unknown>;
      setGt(data);
      setGtName(f.name);
      setMetrics(null);
      setTune(null);
      onErrorsChange?.(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const onCompare = async () => {
    if (!gt) {
      setError("请先导入 GT JSON");
      return;
    }
    if (!score && !structure) {
      setError("请先完成识别（需要 score 或 structure）");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const m = await evaluateCompare({
        sample_id: gtName || file?.name || "sample",
        gt,
        score,
        structure: structure ?? null,
        include_errors: true,
      });
      setMetrics(m);
      const f1map: Partial<Record<StructureLayerId, number>> = {};
      for (const L of ["L1", "L2", "L3", "L4", "L5"] as StructureLayerId[]) {
        if (m.layers[L]) f1map[L] = m.layers[L].f1;
      }
      onLayerF1Change?.(f1map);
      const errs: MetricErrorBox[] = [];
      for (const lm of Object.values(m.layers)) {
        for (const e of lm.errors || []) {
          if (e.kind === "fp" || e.kind === "fn" || e.kind === "tp") {
            errs.push(e);
          }
        }
      }
      onErrorsChange?.(showErrors ? errs : null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const onToggleErrors = (on: boolean) => {
    setShowErrors(on);
    if (!on) {
      onErrorsChange?.(null);
      return;
    }
    if (!metrics) return;
    const errs: MetricErrorBox[] = [];
    for (const lm of Object.values(metrics.layers)) {
      for (const e of lm.errors || []) errs.push(e);
    }
    onErrorsChange?.(errs);
  };

  const onTune = async () => {
    if (!file || !gt) {
      setError("参数扫描需要当前图片 + GT");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const r = await evaluateTuneParamUpload(file, {
        gt,
        param: "l3_min_measure_width",
        start: tuneStart,
        stop: tuneStop,
        step: tuneStep,
        layer: "L3",
        sample_id: gtName || file.name,
      });
      setTune(r);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const spark = useMemo(() => {
    if (!tune?.points?.length) return null;
    const vals = tune.points.map((p) => p.f1);
    const max = Math.max(...vals, 0.01);
    const w = 160;
    const h = 36;
    const pts = vals
      .map((v, i) => {
        const x = (i / Math.max(vals.length - 1, 1)) * (w - 4) + 2;
        const y = h - 2 - (v / max) * (h - 6);
        return `${x},${y}`;
      })
      .join(" ");
    return { w, h, pts, best: tune.best_value, bestF1: tune.best_f1 };
  }, [tune]);

  return (
    <div className="rounded-xl border border-teal-500/25 bg-teal-950/20 px-3 py-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="text-xs font-semibold text-teal-100/95">
            分层精度评测 · #86
          </p>
          <p className="mt-0.5 text-[10px] leading-relaxed text-slate-500">
            导入 Score/分层 GT → 与当前识别结果对比 · 支持 L3 参数扫描
          </p>
        </div>
      </div>

      <div className="mt-2 flex flex-wrap gap-1.5">
        <input
          ref={gtInputRef}
          type="file"
          accept="application/json,.json"
          className="hidden"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) void onLoadGt(f);
            e.target.value = "";
          }}
        />
        <button
          type="button"
          disabled={disabled || busy}
          onClick={() => gtInputRef.current?.click()}
          className="rounded-md border border-white/15 px-2.5 py-1 text-[11px] text-slate-200 hover:bg-white/5 disabled:opacity-40"
        >
          导入 GT JSON
        </button>
        <button
          type="button"
          disabled={disabled || busy || !gt}
          onClick={() => void onCompare()}
          className="rounded-md bg-teal-600/90 px-2.5 py-1 text-[11px] font-medium text-white hover:bg-teal-500 disabled:opacity-40"
        >
          {busy ? "计算中…" : "对比当前识别"}
        </button>
        <label className="inline-flex items-center gap-1 text-[10px] text-slate-400">
          <input
            type="checkbox"
            className="rounded border-white/20"
            checked={showErrors}
            onChange={(e) => onToggleErrors(e.target.checked)}
          />
          误差叠图
        </label>
      </div>

      {gtName ? (
        <p className="mt-1.5 truncate text-[10px] text-teal-200/80">
          GT: {gtName}
        </p>
      ) : (
        <p className="mt-1.5 text-[10px] text-slate-600">
          未加载 GT（可用 samples/eval/gt/*.json）
        </p>
      )}

      {error ? (
        <p className="mt-2 rounded-md border border-rose-400/30 bg-rose-950/40 px-2 py-1 text-[11px] text-rose-100">
          {error}
        </p>
      ) : null}

      {layerList.length > 0 ? (
        <>
          <div className="mt-2 flex flex-wrap gap-1">
            {layerList.map((lm) => (
              <span
                key={lm.layer}
                title={`${lm.layer} mode=${lm.mode} P=${fmt(lm.precision)} R=${fmt(lm.recall)}`}
                className={[
                  "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium",
                  f1Tone(lm.f1),
                ].join(" ")}
              >
                {lm.layer}
                <span className="tabular-nums">{fmt(lm.f1)}</span>
              </span>
            ))}
          </div>
          <div className="mt-2 overflow-x-auto">
            <table className="w-full min-w-[240px] border-collapse text-[10px] text-slate-300">
              <thead>
                <tr className="border-b border-white/10 text-slate-500">
                  <th className="py-1 text-left font-medium">层</th>
                  <th className="py-1 text-right font-medium">P</th>
                  <th className="py-1 text-right font-medium">R</th>
                  <th className="py-1 text-right font-medium">F1</th>
                  <th className="py-1 text-right font-medium">TP/FP/FN</th>
                </tr>
              </thead>
              <tbody>
                {layerList.map((lm) => (
                  <tr key={lm.layer} className="border-b border-white/5">
                    <td className="py-0.5">
                      {lm.layer}
                      <span className="ml-1 text-slate-600">{lm.mode}</span>
                    </td>
                    <td className="py-0.5 text-right tabular-nums">
                      {fmt(lm.precision)}
                    </td>
                    <td className="py-0.5 text-right tabular-nums">
                      {fmt(lm.recall)}
                    </td>
                    <td className="py-0.5 text-right tabular-nums font-medium text-teal-100">
                      {fmt(lm.f1)}
                    </td>
                    <td className="py-0.5 text-right tabular-nums text-slate-500">
                      {lm.tp}/{lm.fp}/{lm.fn}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {(metrics?.warnings?.length ?? 0) > 0 ? (
            <p className="mt-1 text-[10px] text-amber-200/80">
              {metrics!.warnings.slice(0, 3).join(" · ")}
            </p>
          ) : null}
        </>
      ) : null}

      {/* L3 param sweep */}
      <div className="mt-3 space-y-1.5 rounded-lg border border-white/10 bg-black/20 px-2 py-2">
        <p className="text-[11px] font-medium text-slate-300">
          L3 参数扫描 · min_measure_width
        </p>
        <div className="flex flex-wrap items-center gap-1.5 text-[10px] text-slate-400">
          <label className="flex items-center gap-1">
            起
            <input
              type="number"
              className="w-12 rounded border border-white/15 bg-slate-900 px-1 py-0.5 text-slate-200"
              value={tuneStart}
              onChange={(e) => setTuneStart(Number(e.target.value))}
            />
          </label>
          <label className="flex items-center gap-1">
            止
            <input
              type="number"
              className="w-12 rounded border border-white/15 bg-slate-900 px-1 py-0.5 text-slate-200"
              value={tuneStop}
              onChange={(e) => setTuneStop(Number(e.target.value))}
            />
          </label>
          <label className="flex items-center gap-1">
            步
            <input
              type="number"
              className="w-12 rounded border border-white/15 bg-slate-900 px-1 py-0.5 text-slate-200"
              value={tuneStep}
              onChange={(e) => setTuneStep(Number(e.target.value))}
            />
          </label>
          <button
            type="button"
            disabled={disabled || busy || !file || !gt}
            onClick={() => void onTune()}
            className="rounded-md border border-teal-400/40 px-2 py-0.5 text-[11px] text-teal-100 hover:bg-teal-500/15 disabled:opacity-40"
          >
            扫描
          </button>
        </div>
        {spark ? (
          <div className="flex items-center gap-2">
            <svg width={spark.w} height={spark.h} className="shrink-0">
              <polyline
                fill="none"
                stroke="rgb(45 212 191)"
                strokeWidth="1.5"
                points={spark.pts}
              />
            </svg>
            <p className="text-[10px] text-teal-100/90">
              最优 <span className="font-medium">{String(spark.best)}</span>
              {" · "}
              F1={fmt(spark.bestF1)}
              {tune ? ` · ${tune.n_runs} 次 / ${tune.elapsed_sec}s` : ""}
            </p>
          </div>
        ) : (
          <p className="text-[10px] text-slate-600">
            需图片 + GT；缓存 L1/L2，仅重跑 L3
          </p>
        )}
      </div>
    </div>
  );
}
