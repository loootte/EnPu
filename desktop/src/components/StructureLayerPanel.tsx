/**
 * Structure-first layer controls + summary (#58).
 * Toggle L1–L5 overlays; edit boxes and re-run layer (#78).
 */

import type { StructureBox, StructureDebug } from "../lib/types";

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

export function defaultStructureLayersEnabled(): Record<StructureLayerId, boolean> {
  return { L1: true, L2: true, L3: true, L4: true, L5: true };
}

interface StructureLayerPanelProps {
  structure: StructureDebug | null | undefined;
  enabled: Record<StructureLayerId, boolean>;
  onChange: (next: Record<StructureLayerId, boolean>) => void;
  /** #78 */
  editMode?: boolean;
  onEditModeChange?: (on: boolean) => void;
  fromLayer?: StructureLayerId;
  onFromLayerChange?: (layer: StructureLayerId) => void;
  dirty?: boolean;
  selectedId?: string | null;
  onRerun?: () => void;
  onResetEdits?: () => void;
  rerunning?: boolean;
}

export function StructureLayerPanel({
  structure,
  enabled,
  onChange,
  editMode = false,
  onEditModeChange,
  fromLayer = "L2",
  onFromLayerChange,
  dirty = false,
  selectedId = null,
  onRerun,
  onResetEdits,
  rerunning = false,
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
  const selected = structure.items.find(
    (it) => (it.id || `${it.layer}-${it.label}`) === selectedId,
  ) as StructureBox | undefined;

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
            结构分层叠图 · #58 / #78
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
        {STRUCTURE_LAYERS.map((L) => (
          <button
            key={L.id}
            type="button"
            title={L.desc}
            onClick={() => onChange({ ...enabled, [L.id]: !enabled[L.id] })}
            className={[
              "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px]",
              enabled[L.id]
                ? "border-white/20 bg-white/10 text-slate-100"
                : "border-white/10 text-slate-500",
            ].join(" ")}
          >
            <span className={`h-1.5 w-1.5 rounded-full ${L.color}`} />
            {L.name}
            <span className="text-slate-500">{counts[L.id] ?? 0}</span>
          </button>
        ))}
      </div>

      {/* #78 edit + rerun */}
      <div className="mt-3 space-y-2 rounded-lg border border-indigo-500/25 bg-indigo-950/20 px-2.5 py-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-[11px] font-medium text-indigo-100/90">
            改框 · 重识别本层及下层
          </p>
          <label className="inline-flex cursor-pointer items-center gap-1.5 text-[11px] text-slate-300">
            <input
              type="checkbox"
              className="rounded border-white/20"
              checked={editMode}
              onChange={(e) => onEditModeChange?.(e.target.checked)}
            />
            编辑模式
          </label>
        </div>
        <p className="text-[10px] leading-relaxed text-slate-500">
          开启后点选结构框，拖边角缩放 / 拖框移动。确认后从指定层重跑下层，上层结果保留。
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <label className="flex items-center gap-1 text-[11px] text-slate-400">
            起始层
            <select
              className="rounded border border-white/15 bg-slate-900 px-1.5 py-0.5 text-[11px] text-slate-200"
              value={fromLayer}
              onChange={(e) =>
                onFromLayerChange?.(e.target.value as StructureLayerId)
              }
              disabled={!editMode && !dirty}
            >
              {STRUCTURE_LAYERS.map((L) => (
                <option key={L.id} value={L.id}>
                  {L.id}
                </option>
              ))}
            </select>
          </label>
          {selected ? (
            <span className="truncate text-[10px] text-amber-200/90">
              选中 {selected.layer} · {selected.label || selected.id}
            </span>
          ) : (
            <span className="text-[10px] text-slate-600">未选中框</span>
          )}
          {dirty ? (
            <span className="text-[10px] text-rose-300">已改框</span>
          ) : null}
        </div>
        <div className="flex flex-wrap gap-1.5">
          <button
            type="button"
            disabled={!onRerun || rerunning || (!dirty && !editMode)}
            onClick={() => onRerun?.()}
            className="rounded-md bg-indigo-500/90 px-2.5 py-1 text-[11px] font-medium text-white hover:bg-indigo-400 disabled:opacity-40"
          >
            {rerunning ? "重识别中…" : `重识别 ${fromLayer} 及下层`}
          </button>
          <button
            type="button"
            disabled={!dirty || !onResetEdits || rerunning}
            onClick={() => onResetEdits?.()}
            className="rounded-md border border-white/15 px-2.5 py-1 text-[11px] text-slate-300 hover:bg-white/5 disabled:opacity-40"
          >
            恢复自动框
          </button>
        </div>
      </div>
    </div>
  );
}
