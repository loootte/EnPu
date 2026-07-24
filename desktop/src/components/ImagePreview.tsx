/**
 * Image preview with optional rectangle selection for crop re-recognize (#49).
 * Display coords map to natural image pixels; polygon/brush deferred.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import type { BoundingBox, CropRect } from "../lib/types";

export interface ImagePreviewProps {
  src: string | null;
  filename?: string | null;
  /** Enable drag-to-select ROI on the image. */
  selectionEnabled?: boolean;
  selection?: CropRect | null;
  onSelectionChange?: (rect: CropRect | null) => void;
  /** OCR boxes (full-image coords) to overlay. */
  boxes?: BoundingBox[] | null;
  /** Highlight boxes that intersect selection. */
  highlightSelection?: boolean;
}

type DragState = {
  startX: number;
  startY: number;
  curX: number;
  curY: number;
};

function clamp(n: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, n));
}

function normRect(x1: number, y1: number, x2: number, y2: number): CropRect {
  return {
    x1: Math.min(x1, x2),
    y1: Math.min(y1, y2),
    x2: Math.max(x1, x2),
    y2: Math.max(y1, y2),
  };
}

export function ImagePreview({
  src,
  filename,
  selectionEnabled = false,
  selection = null,
  onSelectionChange,
  boxes = null,
  highlightSelection = true,
}: ImagePreviewProps) {
  const imgRef = useRef<HTMLImageElement>(null);
  const [natural, setNatural] = useState({ w: 0, h: 0 });
  const [display, setDisplay] = useState({ w: 0, h: 0 });
  const [drag, setDrag] = useState<DragState | null>(null);

  const syncDisplaySize = useCallback(() => {
    const el = imgRef.current;
    if (!el) return;
    setDisplay({ w: el.clientWidth, h: el.clientHeight });
    if (el.naturalWidth && el.naturalHeight) {
      setNatural({ w: el.naturalWidth, h: el.naturalHeight });
    }
  }, []);

  useEffect(() => {
    syncDisplaySize();
    window.addEventListener("resize", syncDisplaySize);
    return () => window.removeEventListener("resize", syncDisplaySize);
  }, [src, syncDisplaySize]);

  const toImageCoords = useCallback(
    (clientX: number, clientY: number): { x: number; y: number } | null => {
      const el = imgRef.current;
      if (!el || !natural.w || !natural.h) return null;
      const rect = el.getBoundingClientRect();
      const dx = clientX - rect.left;
      const dy = clientY - rect.top;
      if (dx < 0 || dy < 0 || dx > rect.width || dy > rect.height) {
        // Still allow drag slightly outside while clamping
      }
      const x = clamp((dx / rect.width) * natural.w, 0, natural.w);
      const y = clamp((dy / rect.height) * natural.h, 0, natural.h);
      return { x, y };
    },
    [natural.h, natural.w],
  );

  const onPointerDown = (e: React.PointerEvent) => {
    if (!selectionEnabled || !src) return;
    const p = toImageCoords(e.clientX, e.clientY);
    if (!p) return;
    (e.target as HTMLElement).setPointerCapture?.(e.pointerId);
    setDrag({ startX: p.x, startY: p.y, curX: p.x, curY: p.y });
  };

  const onPointerMove = (e: React.PointerEvent) => {
    if (!drag) return;
    const p = toImageCoords(e.clientX, e.clientY);
    if (!p) return;
    setDrag({ ...drag, curX: p.x, curY: p.y });
  };

  const onPointerUp = () => {
    if (!drag) return;
    const r = normRect(drag.startX, drag.startY, drag.curX, drag.curY);
    setDrag(null);
    if (r.x2 - r.x1 < 4 || r.y2 - r.y1 < 4) {
      onSelectionChange?.(null);
      return;
    }
    onSelectionChange?.(r);
  };

  const activeRect: CropRect | null = drag
    ? normRect(drag.startX, drag.startY, drag.curX, drag.curY)
    : selection;

  const scaleX = natural.w > 0 && display.w > 0 ? display.w / natural.w : 1;
  const scaleY = natural.h > 0 && display.h > 0 ? display.h / natural.h : 1;

  if (!src) {
    return (
      <div className="flex h-64 items-center justify-center rounded-xl border border-white/10 bg-slate-950/50 text-sm text-slate-500">
        尚未选择图片
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-xl border border-white/10 bg-slate-950/50">
      <div className="flex items-center justify-between gap-2 border-b border-white/5 px-3 py-2">
        <span className="truncate text-xs text-slate-400" title={filename ?? ""}>
          {filename || "预览"}
        </span>
        {selectionEnabled ? (
          <div className="flex shrink-0 items-center gap-2 text-[11px] text-slate-500">
            <span>拖拽框选 · Esc 清除 · Ctrl+Shift+R 局部重识别</span>
            {selection ? (
              <button
                type="button"
                className="rounded border border-white/10 px-1.5 py-0.5 text-slate-300 hover:bg-white/5"
                onClick={() => onSelectionChange?.(null)}
              >
                清除选区
              </button>
            ) : null}
          </div>
        ) : null}
      </div>
      <div className="flex max-h-[420px] items-center justify-center overflow-auto p-3">
        <div
          className={[
            "relative inline-block max-h-[400px] max-w-full",
            selectionEnabled ? "cursor-crosshair touch-none select-none" : "",
          ].join(" ")}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onPointerCancel={onPointerUp}
        >
          <img
            ref={imgRef}
            src={src}
            alt={filename ? `预览：${filename}` : "简谱预览"}
            className="max-h-[400px] max-w-full object-contain"
            draggable={false}
            onLoad={syncDisplaySize}
          />
          {/* OCR boxes overlay */}
          {boxes && natural.w > 0
            ? boxes.map((b, i) => {
                const inSel =
                  highlightSelection &&
                  selection &&
                  !(
                    b.x2 < selection.x1 ||
                    b.x1 > selection.x2 ||
                    b.y2 < selection.y1 ||
                    b.y1 > selection.y2
                  );
                return (
                  <div
                    key={`box-${i}`}
                    className={[
                      "pointer-events-none absolute border",
                      inSel
                        ? "border-amber-300/90 bg-amber-400/15"
                        : "border-sky-400/40 bg-sky-400/5",
                    ].join(" ")}
                    style={{
                      left: b.x1 * scaleX,
                      top: b.y1 * scaleY,
                      width: Math.max(1, (b.x2 - b.x1) * scaleX),
                      height: Math.max(1, (b.y2 - b.y1) * scaleY),
                    }}
                  />
                );
              })
            : null}
          {/* Selection rect */}
          {activeRect && natural.w > 0 ? (
            <div
              className="pointer-events-none absolute border-2 border-indigo-400 bg-indigo-500/20 shadow-[0_0_0_1px_rgba(99,102,241,0.4)]"
              style={{
                left: activeRect.x1 * scaleX,
                top: activeRect.y1 * scaleY,
                width: Math.max(1, (activeRect.x2 - activeRect.x1) * scaleX),
                height: Math.max(1, (activeRect.y2 - activeRect.y1) * scaleY),
              }}
            />
          ) : null}
        </div>
      </div>
    </div>
  );
}
