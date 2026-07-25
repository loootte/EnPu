/**
 * Image preview with rectangle selection, zoom, and pan (#49).
 * Display coords map to natural image pixels under current transform.
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

type PanDrag = {
  originClientX: number;
  originClientY: number;
  originPanX: number;
  originPanY: number;
};

const MIN_ZOOM = 0.5;
const MAX_ZOOM = 4;
const ZOOM_STEP = 1.15;

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
  const viewportRef = useRef<HTMLDivElement>(null);
  const [natural, setNatural] = useState({ w: 0, h: 0 });
  const [baseSize, setBaseSize] = useState({ w: 0, h: 0 });
  const [drag, setDrag] = useState<DragState | null>(null);
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [panDrag, setPanDrag] = useState<PanDrag | null>(null);
  const [spaceDown, setSpaceDown] = useState(false);

  // Reset view when source changes
  useEffect(() => {
    setZoom(1);
    setPan({ x: 0, y: 0 });
    setDrag(null);
    setPanDrag(null);
  }, [src]);

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.code === "Space" && !e.repeat) {
        const tag = (e.target as HTMLElement | null)?.tagName;
        if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
        e.preventDefault();
        setSpaceDown(true);
      }
    };
    const onKeyUp = (e: KeyboardEvent) => {
      if (e.code === "Space") setSpaceDown(false);
    };
    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("keyup", onKeyUp);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("keyup", onKeyUp);
    };
  }, []);

  const syncBaseSize = useCallback(() => {
    const el = imgRef.current;
    if (!el) return;
    // Unscaled layout size of the image (object-contain base).
    const nw = el.naturalWidth;
    const nh = el.naturalHeight;
    if (nw && nh) setNatural({ w: nw, h: nh });
    // clientWidth is after CSS max constraints but before our transform scale.
    // We keep zoom separate, so measure without relying on transform.
    const parent = el.parentElement;
    if (parent) {
      // The stage uses transform; get layout size from offsetWidth of img at zoom=1
      // Use natural aspect fitted into max box from CSS.
    }
    setBaseSize({ w: el.offsetWidth || el.clientWidth, h: el.offsetHeight || el.clientHeight });
  }, []);

  useEffect(() => {
    syncBaseSize();
    window.addEventListener("resize", syncBaseSize);
    return () => window.removeEventListener("resize", syncBaseSize);
  }, [src, zoom, syncBaseSize]);

  const toImageCoords = useCallback(
    (clientX: number, clientY: number): { x: number; y: number } | null => {
      const el = imgRef.current;
      if (!el || !natural.w || !natural.h) return null;
      // getBoundingClientRect includes CSS transform (zoom) — correct for hit-test.
      const rect = el.getBoundingClientRect();
      if (rect.width <= 0 || rect.height <= 0) return null;
      const dx = clientX - rect.left;
      const dy = clientY - rect.top;
      const x = clamp((dx / rect.width) * natural.w, 0, natural.w);
      const y = clamp((dy / rect.height) * natural.h, 0, natural.h);
      return { x, y };
    },
    [natural.h, natural.w],
  );

  const zoomAt = useCallback(
    (nextZoom: number, clientX?: number, clientY?: number) => {
      const z = clamp(nextZoom, MIN_ZOOM, MAX_ZOOM);
      const el = imgRef.current;
      const vp = viewportRef.current;
      if (!el || !vp || clientX == null || clientY == null) {
        setZoom(z);
        return;
      }
      // Keep the image point under cursor stable when zooming.
      const before = el.getBoundingClientRect();
      const relX = clientX - before.left;
      const relY = clientY - before.top;
      const ratio = z / zoom;
      setZoom(z);
      setPan((p) => ({
        x: p.x - relX * (ratio - 1),
        y: p.y - relY * (ratio - 1),
      }));
    },
    [zoom],
  );

  const onWheel = (e: React.WheelEvent) => {
    // Always zoom with wheel inside viewport (Ctrl optional but not required).
    e.preventDefault();
    const factor = e.deltaY < 0 ? ZOOM_STEP : 1 / ZOOM_STEP;
    zoomAt(zoom * factor, e.clientX, e.clientY);
  };

  const wantsPan = spaceDown || panDrag != null;

  const onPointerDown = (e: React.PointerEvent) => {
    if (!src) return;
    const el = e.currentTarget as HTMLElement;

    // Middle button or Space+drag or Alt+drag → pan
    if (e.button === 1 || e.altKey || spaceDown) {
      e.preventDefault();
      el.setPointerCapture?.(e.pointerId);
      setPanDrag({
        originClientX: e.clientX,
        originClientY: e.clientY,
        originPanX: pan.x,
        originPanY: pan.y,
      });
      return;
    }

    if (!selectionEnabled || e.button !== 0) return;
    const p = toImageCoords(e.clientX, e.clientY);
    if (!p) return;
    el.setPointerCapture?.(e.pointerId);
    setDrag({ startX: p.x, startY: p.y, curX: p.x, curY: p.y });
  };

  const onPointerMove = (e: React.PointerEvent) => {
    if (panDrag) {
      setPan({
        x: panDrag.originPanX + (e.clientX - panDrag.originClientX),
        y: panDrag.originPanY + (e.clientY - panDrag.originClientY),
      });
      return;
    }
    if (!drag) return;
    const p = toImageCoords(e.clientX, e.clientY);
    if (!p) return;
    setDrag({ ...drag, curX: p.x, curY: p.y });
  };

  const onPointerUp = (e: React.PointerEvent) => {
    if (panDrag) {
      setPanDrag(null);
      return;
    }
    if (!drag) return;
    const r = normRect(drag.startX, drag.startY, drag.curX, drag.curY);
    setDrag(null);
    if (r.x2 - r.x1 < 4 || r.y2 - r.y1 < 4) {
      // Tiny click: don't clear existing selection unless empty drag
      if (e.detail === 0) onSelectionChange?.(null);
      return;
    }
    onSelectionChange?.(r);
  };

  const resetView = () => {
    setZoom(1);
    setPan({ x: 0, y: 0 });
  };

  const activeRect: CropRect | null = drag
    ? normRect(drag.startX, drag.startY, drag.curX, drag.curY)
    : selection;

  // Overlay positions use unscaled base image box * (natural→base scale).
  // Transform on stage applies zoom/pan to both image and overlays together.
  const layoutW = baseSize.w || 1;
  const layoutH = baseSize.h || 1;
  const scaleX = natural.w > 0 ? layoutW / natural.w : 1;
  const scaleY = natural.h > 0 ? layoutH / natural.h : 1;

  if (!src) {
    return (
      <div className="flex h-64 items-center justify-center rounded-xl border border-white/10 bg-slate-950/50 text-sm text-slate-500">
        尚未选择图片
      </div>
    );
  }

  const cursorClass = panDrag
    ? "cursor-grabbing"
    : spaceDown
      ? "cursor-grab"
      : selectionEnabled
        ? "cursor-crosshair"
        : "cursor-default";

  return (
    <div className="overflow-hidden rounded-xl border border-white/10 bg-slate-950/50">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-white/5 px-3 py-2">
        <span className="truncate text-xs text-slate-400" title={filename ?? ""}>
          {filename || "预览"}
        </span>
        <div className="flex shrink-0 flex-wrap items-center gap-1.5 text-[11px] text-slate-500">
          <button
            type="button"
            className="rounded border border-white/10 px-1.5 py-0.5 text-slate-300 hover:bg-white/5"
            onClick={() => zoomAt(zoom / ZOOM_STEP)}
            title="缩小"
          >
            −
          </button>
          <span className="min-w-[3rem] text-center tabular-nums text-slate-400">
            {Math.round(zoom * 100)}%
          </span>
          <button
            type="button"
            className="rounded border border-white/10 px-1.5 py-0.5 text-slate-300 hover:bg-white/5"
            onClick={() => zoomAt(zoom * ZOOM_STEP)}
            title="放大"
          >
            +
          </button>
          <button
            type="button"
            className="rounded border border-white/10 px-1.5 py-0.5 text-slate-300 hover:bg-white/5"
            onClick={resetView}
            title="重置缩放/位置"
          >
            重置
          </button>
          {selectionEnabled ? (
            <>
              <span className="mx-1 hidden text-slate-600 sm:inline">|</span>
              <span className="hidden sm:inline">
                滚轮缩放 · 空格/中键拖移 · 拖拽框选
              </span>
              {selection ? (
                <button
                  type="button"
                  className="rounded border border-white/10 px-1.5 py-0.5 text-slate-300 hover:bg-white/5"
                  onClick={() => onSelectionChange?.(null)}
                >
                  清除选区
                </button>
              ) : null}
            </>
          ) : null}
        </div>
      </div>
      <div
        ref={viewportRef}
        className={[
          "relative flex h-[min(420px,50vh)] items-center justify-center overflow-hidden bg-slate-950/40 p-3",
          cursorClass,
          "touch-none select-none",
        ].join(" ")}
        onWheel={onWheel}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        onContextMenu={(e) => e.preventDefault()}
      >
        <div
          className="relative origin-center will-change-transform"
          style={{
            transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`,
          }}
        >
          <img
            ref={imgRef}
            src={src}
            alt={filename ? `预览：${filename}` : "简谱预览"}
            className="max-h-[400px] max-w-full object-contain"
            draggable={false}
            onLoad={() => {
              // Measure after layout
              requestAnimationFrame(syncBaseSize);
            }}
          />
          {/* OCR boxes overlay — same transform as image */}
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
        {wantsPan ? (
          <div className="pointer-events-none absolute bottom-2 left-2 rounded bg-black/50 px-2 py-0.5 text-[10px] text-slate-300">
            平移模式
          </div>
        ) : null}
      </div>
    </div>
  );
}
