/**
 * Image preview: selection, zoom/pan (#49), dual-view overlays (#45).
 */

import { useCallback, useEffect, useRef, useState } from "react";
import type {
  BoundingBox,
  CropRect,
  StructureBox,
  StructureDebug,
} from "../lib/types";
import type { StructureLayerId } from "./StructureLayerPanel";

export type ImageOverlayMode = "off" | "boxes" | "measures" | "structure";

export interface ImagePreviewProps {
  src: string | null;
  filename?: string | null;
  selectionEnabled?: boolean;
  selection?: CropRect | null;
  onSelectionChange?: (rect: CropRect | null) => void;
  boxes?: BoundingBox[] | null;
  highlightSelection?: boolean;
  /** Dual-view: approx measure rects (full-image pixels) to draw. */
  measureRects?: CropRect[] | null;
  /** Dual-view: which measure numbers (1-based) are hovered/active. */
  activeMeasureNumbers?: number[] | null;
  overlayMode?: ImageOverlayMode;
  onOverlayModeChange?: (mode: ImageOverlayMode) => void;
  /** Hover image → measure index callback (0-based or null). */
  onHoverImage?: (point: { x: number; y: number } | null) => void;
  compact?: boolean;
  /** #58 structure-first layer overlays */
  structure?: StructureDebug | null;
  structureLayers?: Record<StructureLayerId, boolean> | null;
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

const LAYER_STYLE: Record<
  StructureBox["layer"],
  { border: string; bg: string; text: string }
> = {
  L1: {
    border: "border-violet-400/80",
    bg: "bg-violet-500/10",
    text: "text-violet-100",
  },
  L2: {
    border: "border-sky-400/80",
    bg: "bg-sky-500/10",
    text: "text-sky-100",
  },
  L3: {
    border: "border-emerald-400/80",
    bg: "bg-emerald-500/10",
    text: "text-emerald-100",
  },
  L4: {
    border: "border-cyan-300/90",
    bg: "bg-cyan-400/15",
    text: "text-cyan-50",
  },
  L5: {
    border: "border-amber-300/90",
    bg: "bg-amber-400/20",
    text: "text-amber-50",
  },
};

function StructureItemOverlay({
  item,
  scaleX,
  scaleY,
}: {
  item: StructureBox;
  scaleX: number;
  scaleY: number;
}) {
  const st = LAYER_STYLE[item.layer];
  const showLabel = item.layer === "L1" || item.layer === "L2" || item.layer === "L5";
  const thick = item.layer === "L1" || item.layer === "L2" ? "border-2" : "border";
  return (
    <div
      className={`pointer-events-none absolute ${thick} ${st.border} ${st.bg}`}
      style={{
        left: item.box.x1 * scaleX,
        top: item.box.y1 * scaleY,
        width: Math.max(1, (item.box.x2 - item.box.x1) * scaleX),
        height: Math.max(1, (item.box.y2 - item.box.y1) * scaleY),
      }}
      title={[item.layer, item.label, item.pitch, item.duration]
        .filter(Boolean)
        .join(" · ")}
    >
      {showLabel && item.label ? (
        <span
          className={`absolute -top-0.5 left-0 max-w-full truncate px-0.5 text-[9px] leading-tight ${st.text} bg-black/55`}
        >
          {item.label}
        </span>
      ) : null}
    </div>
  );
}

export function ImagePreview({
  src,
  filename,
  selectionEnabled = false,
  selection = null,
  onSelectionChange,
  boxes = null,
  highlightSelection = true,
  measureRects = null,
  activeMeasureNumbers = null,
  overlayMode = "boxes",
  onOverlayModeChange,
  onHoverImage,
  compact = false,
  structure = null,
  structureLayers = null,
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
    const nw = el.naturalWidth;
    const nh = el.naturalHeight;
    if (nw && nh) setNatural({ w: nw, h: nh });
    setBaseSize({
      w: el.offsetWidth || el.clientWidth,
      h: el.offsetHeight || el.clientHeight,
    });
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
      if (!el || clientX == null || clientY == null) {
        setZoom(z);
        return;
      }
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
    e.preventDefault();
    const factor = e.deltaY < 0 ? ZOOM_STEP : 1 / ZOOM_STEP;
    zoomAt(zoom * factor, e.clientX, e.clientY);
  };

  const onPointerDown = (e: React.PointerEvent) => {
    if (!src) return;
    const el = e.currentTarget as HTMLElement;

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
    if (drag) {
      const p = toImageCoords(e.clientX, e.clientY);
      if (!p) return;
      setDrag({ ...drag, curX: p.x, curY: p.y });
      return;
    }
    if (onHoverImage && !spaceDown) {
      const p = toImageCoords(e.clientX, e.clientY);
      onHoverImage(p);
    }
  };

  const onPointerLeave = () => {
    onHoverImage?.(null);
  };

  const onPointerUp = () => {
    if (panDrag) {
      setPanDrag(null);
      return;
    }
    if (!drag) return;
    const r = normRect(drag.startX, drag.startY, drag.curX, drag.curY);
    setDrag(null);
    if (r.x2 - r.x1 < 4 || r.y2 - r.y1 < 4) {
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

  const vh = compact ? "h-[min(360px,42vh)]" : "h-[min(420px,50vh)]";
  const imgMax = compact ? "max-h-[340px]" : "max-h-[400px]";
  const showBoxes = overlayMode === "boxes" && boxes && boxes.length > 0;

  return (
    <div className="overflow-hidden rounded-xl border border-white/10 bg-slate-950/50">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-white/5 px-3 py-2">
        <span className="truncate text-xs text-slate-400" title={filename ?? ""}>
          {filename || "原稿"}
        </span>
        <div className="flex shrink-0 flex-wrap items-center gap-1.5 text-[11px] text-slate-500">
          {onOverlayModeChange ? (
            <div className="mr-1 flex rounded border border-white/10 p-0.5">
              {(
                [
                  ["off", "原图"],
                  ["boxes", "叠图"],
                  ["measures", "小节"],
                  ...(structure?.items?.length
                    ? ([["structure", "结构"]] as const)
                    : []),
                ] as const
              ).map(([mode, label]) => (
                <button
                  key={mode}
                  type="button"
                  className={[
                    "rounded px-1.5 py-0.5",
                    overlayMode === mode
                      ? "bg-indigo-500/30 text-indigo-100"
                      : "text-slate-400 hover:bg-white/5",
                  ].join(" ")}
                  onClick={() => onOverlayModeChange(mode)}
                >
                  {label}
                </button>
              ))}
            </div>
          ) : null}
          <button
            type="button"
            className="rounded border border-white/10 px-1.5 py-0.5 text-slate-300 hover:bg-white/5"
            onClick={() => zoomAt(zoom / ZOOM_STEP)}
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
          >
            +
          </button>
          <button
            type="button"
            className="rounded border border-white/10 px-1.5 py-0.5 text-slate-300 hover:bg-white/5"
            onClick={resetView}
          >
            重置
          </button>
          {selectionEnabled && selection ? (
            <button
              type="button"
              className="rounded border border-white/10 px-1.5 py-0.5 text-slate-300 hover:bg-white/5"
              onClick={() => onSelectionChange?.(null)}
            >
              清除选区
            </button>
          ) : null}
        </div>
      </div>
      <div
        ref={viewportRef}
        className={[
          "relative flex items-center justify-center overflow-hidden bg-slate-950/40 p-3",
          vh,
          cursorClass,
          "touch-none select-none",
        ].join(" ")}
        onWheel={onWheel}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        onPointerLeave={onPointerLeave}
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
            className={`${imgMax} max-w-full object-contain`}
            draggable={false}
            onLoad={() => requestAnimationFrame(syncBaseSize)}
          />
          {showBoxes
            ? boxes!.map((b, i) => {
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
                        ? "border-amber-300/90 bg-amber-400/20"
                        : "border-sky-400/50 bg-sky-400/10",
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
          {measureRects && measureRects.length > 0
            ? measureRects.map((r, i) => {
                const num = i + 1;
                const active = Boolean(activeMeasureNumbers?.includes(num));
                // Grid: show all in "measures" mode; only active when boxes/off
                if (overlayMode !== "measures" && !active) return null;
                return (
                  <div
                    key={`mrect-${i}-${r.x1}`}
                    className={[
                      "pointer-events-none absolute border",
                      active
                        ? "border-amber-300 bg-amber-400/30 ring-1 ring-amber-200/50"
                        : "border-emerald-400/35 bg-emerald-500/10",
                    ].join(" ")}
                    style={{
                      left: r.x1 * scaleX,
                      top: r.y1 * scaleY,
                      width: Math.max(1, (r.x2 - r.x1) * scaleX),
                      height: Math.max(1, (r.y2 - r.y1) * scaleY),
                    }}
                  />
                );
              })
            : null}
          {/* #58 structure L1–L5 overlays */}
          {structure?.items?.length && natural.w > 0
            ? structure.items.map((it) => {
                const show =
                  overlayMode === "structure"
                    ? structureLayers?.[it.layer] !== false
                    : false;
                if (!show) return null;
                return (
                  <StructureItemOverlay
                    key={it.id || `${it.layer}-${it.label}-${it.box.x1}`}
                    item={it}
                    scaleX={scaleX}
                    scaleY={scaleY}
                  />
                );
              })
            : null}
          {structure?.barlines?.length &&
          natural.w > 0 &&
          overlayMode === "structure" &&
          structureLayers?.L3 !== false
            ? structure.barlines.map((bl, i) => (
                <div
                  key={`bar-${i}-${bl.x}`}
                  className="pointer-events-none absolute w-0.5 bg-rose-500/90 shadow-[0_0_4px_rgba(244,63,94,0.8)]"
                  style={{
                    left: bl.x * scaleX,
                    top: bl.y1 * scaleY,
                    height: Math.max(1, (bl.y2 - bl.y1) * scaleY),
                  }}
                  title={`barline S${bl.system + 1}`}
                />
              ))
            : null}
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
        {spaceDown || panDrag ? (
          <div className="pointer-events-none absolute bottom-2 left-2 rounded bg-black/50 px-2 py-0.5 text-[10px] text-slate-300">
            平移
          </div>
        ) : null}
      </div>
    </div>
  );
}
