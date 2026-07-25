/**
 * Structure-first layer controls + summary (#58).
 * Toggle which L1–L5 overlays appear on the original image.
 */

import type { StructureDebug } from "../lib/types";

export type StructureLayerId = "L1" | "L2" | "L3" | "L4" | "L5";

export const STRUCTURE_LAYERS: {
  id: StructureLayerId;
  name: string;
  color: string;
  desc: string;
}[] = [
  { id: "L1", name: "L1 页面", color: "bg-violet-500/80", desc: "标题 / 调号拍号 / 主谱面" },
  { id: "L2", name: "L2 谱行", color: "bg-sky-500/80", desc: "水平谱行 systems" },
  { id: "L3", name: "L3 小节", color: "bg-emerald-500/80", desc: "小节框 + 小节线" },
  { id: "L4", name: "L4 音符位", color: "bg-cyan-400/80", desc: "音符候选 ROI" },
  { id: "L5", name: "L5 字形", color: "bg-amber-400/80", desc: "音高 OCR + 时值/八度" },
];

interface StructureLayerPanelProps {
  structure: StructureDebug | null | undefined;
  enabled: Record<StructureLayerId, boolean>;
  onChange: (next: Record<StructureLayerId, boolean>) => void;
}

export function StructureLayerPanel({
  structure,
  enabled,
  onChange,
}: StructureLayerPanelProps) {
  if (!structure?.items?.length) {
    return (
      <div className="rounded-xl border border-dashed border-white/15 bg-slate-950/40 px-3 py-3 text-xs text-slate-500">
        <p className="font-medium text-slate-400">结构分层叠图（#58）</p>
        <p className="mt-1 leading-relaxed">
          当前识别未返回 <code className="text-slate-400">structure</code>。
          请用结构管线启动 core：
        </p>
        <pre className="mt-2 overflow-x-auto rounded-md bg-black/40 p-2 text-[11px] text-amber-100/90">
          {`$env:ENPU_PIPELINE_MODE="structure"\n# 然后启动 core 并重新识别`}
        </pre>
      </div>
    );
  }

  const counts: Record<string, number> = { L1: 0, L2: 0, L3: 0, L4: 0, L5: 0 };
  for (const it of structure.items) {
    counts[it.layer] = (counts[it.layer] ?? 0) + 1;
  }
  const s = structure.summary ?? {};

  const setAll = (on: boolean) => {
    const next = { ...enabled };
    for (const L of STRUCTURE_LAYERS) next[L.id] = on;
    onChange(next);
  };

  return (
    <div className="rounded-xl border border-white/10 bg-slate-950/50 px-3 py-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-xs font-semibold text-slate-200">
            结构分层叠图 · #58
          </p>
          <p className="text-[11px] text-slate-500">
            谱行 {String(s.n_systems ?? "—")} · 小节{" "}
            {String(s.n_measures ?? "—")} · 候选{" "}
            {String(s.n_note_candidates ?? "—")} · 音高{" "}
            {String(s.n_pitched ?? "—")}
            {s.key != null ? ` · key=${String(s.key)}` : ""}
            {s.time_signature != null
              ? ` · ${String(s.time_signature)}`
              : ""}
          </p>
        </div>
        <div className="flex gap-1.5">
          <button
            type="button"
            className="rounded border border-white/10 px-2 py-0.5 text-[11px] text-slate-300 hover:bg-white/5"
            onClick={() => setAll(true)}
          >
            全开
          </button>
          <button
            type="button"
            className="rounded border border-white/10 px-2 py-0.5 text-[11px] text-slate-300 hover:bg-white/5"
            onClick={() => setAll(false)}
          >
            全关
          </button>
        </div>
      </div>

      <div className="mt-2 flex flex-wrap gap-1.5">
        {STRUCTURE_LAYERS.map((L) => {
          const on = enabled[L.id];
          return (
            <button
              key={L.id}
              type="button"
              title={L.desc}
              onClick={() => onChange({ ...enabled, [L.id]: !on })}
              className={[
                "inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-[11px] font-medium transition",
                on
                  ? "border-white/25 bg-white/10 text-white"
                  : "border-white/10 text-slate-500 hover:bg-white/5",
              ].join(" ")}
            >
              <span className={`h-2 w-2 rounded-sm ${L.color}`} />
              {L.name}
              <span className="tabular-nums text-slate-400">
                {counts[L.id] ?? 0}
              </span>
            </button>
          );
        })}
      </div>

      {(structure.barlines?.length ?? 0) > 0 ? (
        <p className="mt-2 text-[11px] text-slate-500">
          小节线 {structure.barlines!.length} 条（L3 红线）
        </p>
      ) : null}
    </div>
  );
}

export function defaultStructureLayersEnabled(): Record<StructureLayerId, boolean> {
  return { L1: true, L2: true, L3: true, L4: false, L5: true };
}
