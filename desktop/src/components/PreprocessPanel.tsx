/**
 * Image preprocess toolbox UI (#47 / P4-H).
 * OpenCV options only — no heavy deps.
 */

import type { PreprocessOptions } from "../lib/types";

interface PreprocessPanelProps {
  options: PreprocessOptions;
  onChange: (next: PreprocessOptions) => void;
  onPreview: () => void;
  previewing?: boolean;
  disabled?: boolean;
  hasSelection?: boolean;
  steps?: string[] | null;
  className?: string;
}

export function PreprocessPanel({
  options,
  onChange,
  onPreview,
  previewing = false,
  disabled = false,
  hasSelection = false,
  steps = null,
  className = "",
}: PreprocessPanelProps) {
  const set = <K extends keyof PreprocessOptions>(
    key: K,
    value: PreprocessOptions[K],
  ) => onChange({ ...options, [key]: value });

  return (
    <div
      className={`rounded-xl border border-white/10 bg-slate-950/50 ${className}`}
    >
      <div className="flex items-center justify-between gap-2 border-b border-white/5 px-3 py-2">
        <h3 className="text-xs font-semibold text-slate-200">
          预处理工具箱
          <span className="ml-1.5 font-normal text-slate-500">#47 · OpenCV</span>
        </h3>
        <button
          type="button"
          disabled={disabled || previewing}
          onClick={onPreview}
          className="rounded-md bg-sky-600/80 px-2 py-0.5 text-[11px] font-medium text-white hover:bg-sky-500 disabled:opacity-40"
        >
          {previewing ? "预览中…" : "预览效果"}
        </button>
      </div>

      <div className="space-y-2 p-3 text-[11px] text-slate-300">
        <div className="grid grid-cols-2 gap-x-3 gap-y-1.5">
          <Toggle
            label="去噪"
            checked={options.denoise}
            onChange={(v) => set("denoise", v)}
            disabled={disabled}
          />
          <Toggle
            label="倾斜矫正"
            checked={options.deskew}
            onChange={(v) => set("deskew", v)}
            disabled={disabled}
          />
          <Toggle
            label="CLAHE 对比度"
            checked={options.clahe}
            onChange={(v) => set("clahe", v)}
            disabled={disabled}
          />
          <Toggle
            label="阴影抑制"
            checked={options.shadow_remove}
            onChange={(v) => set("shadow_remove", v)}
            disabled={disabled}
          />
          <Toggle
            label="自适应二值化"
            checked={options.adaptive_binary}
            onChange={(v) => set("adaptive_binary", v)}
            disabled={disabled}
          />
          <Toggle
            label="用当前框选裁切"
            checked={options.use_selection_crop}
            onChange={(v) => set("use_selection_crop", v)}
            disabled={disabled || !hasSelection}
            title={
              hasSelection
                ? "识别/预览时裁到当前选区（去掉页眉页脚）"
                : "先在原图拖拽框选"
            }
          />
        </div>

        <label className="flex items-center gap-2">
          <span className="w-14 shrink-0 text-slate-500">亮度</span>
          <input
            type="range"
            min={-40}
            max={40}
            step={1}
            value={options.brightness}
            disabled={disabled}
            onChange={(e) => set("brightness", Number(e.target.value))}
            className="flex-1 accent-indigo-400"
          />
          <span className="w-8 text-right tabular-nums text-slate-400">
            {options.brightness}
          </span>
        </label>
        <label className="flex items-center gap-2">
          <span className="w-14 shrink-0 text-slate-500">对比度</span>
          <input
            type="range"
            min={0.5}
            max={1.8}
            step={0.05}
            value={options.contrast}
            disabled={disabled}
            onChange={(e) => set("contrast", Number(e.target.value))}
            className="flex-1 accent-indigo-400"
          />
          <span className="w-8 text-right tabular-nums text-slate-400">
            {options.contrast.toFixed(2)}
          </span>
        </label>

        {steps && steps.length > 0 ? (
          <p className="break-all font-mono text-[10px] leading-relaxed text-slate-500">
            {steps.join(" → ")}
          </p>
        ) : (
          <p className="text-[10px] text-slate-600">
            拍照/扫描可先开「阴影抑制 + CLAHE + 倾斜矫正」再预览
          </p>
        )}
      </div>
    </div>
  );
}

function Toggle({
  label,
  checked,
  onChange,
  disabled,
  title,
}: {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
  disabled?: boolean;
  title?: string;
}) {
  return (
    <label
      className="flex cursor-pointer items-center gap-1.5"
      title={title}
    >
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
        className="accent-indigo-400"
      />
      <span className={disabled ? "text-slate-600" : ""}>{label}</span>
    </label>
  );
}
