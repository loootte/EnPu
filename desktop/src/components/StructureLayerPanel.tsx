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
  { id: "L3", name: "L3 分割线", color: "bg-emerald-500/80", desc: "行内纵向分割线 → 派生小节框 (#85)" },
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
  /** #78 draw new region on image */
  addMode?: boolean;
  onAddModeChange?: (on: boolean) => void;
  onDeleteSelected?: () => void;
  /** #86 per-layer F1 from evaluation panel */
  layerF1?: Partial<Record<StructureLayerId, number>> | null;
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
  addMode = false,
  onAddModeChange,
  onDeleteSelected,
  layerF1 = null,
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
            {layerF1 && layerF1[L.id] != null ? (
              <span
                className={[
                  "rounded px-1 tabular-nums",
                  (layerF1[L.id] as number) >= 0.8
                    ? "bg-emerald-500/30 text-emerald-100"
                    : (layerF1[L.id] as number) >= 0.5
                      ? "bg-amber-500/30 text-amber-100"
                      : "bg-rose-500/30 text-rose-100",
                ].join(" ")}
                title={`${L.id} F1`}
              >
                {(layerF1[L.id] as number).toFixed(2)}
              </span>
            ) : null}
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
          编辑模式自动显示当前层（及上一层作参照）。
          <span className="text-slate-300">只能选中当前层</span>
          。L3 以<strong className="font-medium text-slate-300">拖动/增删分割线</strong>
          为主（小节框为派生）；其它层可拖边角调框。
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <label className="flex items-center gap-1 text-[11px] text-slate-400">
            层
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
                  {L.id} 编辑
                </option>
              ))}
            </select>
          </label>
          <span className="text-[10px] text-sky-300/90">
            仅可选 {fromLayer}
          </span>
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
          {addMode ? (
            <span className="text-[10px] text-emerald-300">
              拖拽添加 {fromLayer} 区域…
            </span>
          ) : null}
        </div>
        <div className="flex flex-wrap gap-1.5">
          <button
            type="button"
            disabled={!editMode || rerunning}
            onClick={() => {
              const next = !addMode;
              onAddModeChange?.(next);
              if (next) onEditModeChange?.(true);
            }}
            className={[
              "rounded-md border px-2.5 py-1 text-[11px] font-medium disabled:opacity-40",
              addMode
                ? "border-emerald-400/50 bg-emerald-500/25 text-emerald-100"
                : "border-white/15 text-slate-200 hover:bg-white/5",
            ].join(" ")}
          >
            {addMode ? "取消添加" : "添加区域"}
          </button>
          <button
            type="button"
            disabled={!onRerun || rerunning || (!dirty && !editMode)}
            onClick={() => onRerun?.()}
            className="rounded-md bg-indigo-500/90 px-2.5 py-1 text-[11px] font-medium text-white hover:bg-indigo-400 disabled:opacity-40"
          >
            {rerunning
              ? "重识别中…"
              : `按 ${fromLayer} 框重识别下层`}
          </button>
          <button
            type="button"
            disabled={!selectedId || !onDeleteSelected || rerunning}
            onClick={() => onDeleteSelected?.()}
            className="rounded-md border border-rose-400/30 px-2.5 py-1 text-[11px] text-rose-200 hover:bg-rose-500/15 disabled:opacity-40"
          >
            删除选中
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
