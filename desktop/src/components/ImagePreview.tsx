/**
 * Image preview: selection, zoom/pan (#49), dual-view overlays (#45).
 */

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type PointerEvent as ReactPointerEvent,
  type WheelEvent as ReactWheelEvent,
} from "react";
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
  /** #78: allow drag-resize of structure boxes */
  structureEditMode?: boolean;
  /** #78: drag on image to create a new region of addLayer */
  structureAddMode?: boolean;
  structureAddLayer?: StructureLayerId;
  selectedStructureId?: string | null;
  onSelectStructureId?: (id: string | null) => void;
  onStructureBoxChange?: (id: string, box: BoundingBox) => void;
  onStructureBoxAdd?: (box: BoundingBox, layer: StructureLayerId) => void;
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

const MIN_ZOOM = 0.35;
const MAX_ZOOM = 4;
/** Auto-fit in edit mode may zoom closer than manual wheel max. */
const MAX_AUTO_ZOOM = 12;
const ZOOM_STEP = 1.15;
/** Padding fraction when fitting parent layer box into viewport. */
const FIT_PAD = 0.08;

const PARENT_LAYER: Record<StructureLayerId, StructureLayerId | null> = {
  L5: "L4",
  L4: "L3",
  L3: "L2",
  L2: "L1",
  L1: null,
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

function itemId(it: StructureBox): string {
  return it.id || `${it.layer}-${it.label}`;
}

/**
 * Focus region for edit selection: parent layer box that contains the selection
 * (e.g. L4 → surrounding L3). Falls back to the selected box itself.
 */
function focusBoxForSelection(
  structure: StructureDebug,
  selectedId: string,
): BoundingBox | null {
  const items = structure.items ?? [];
  const selected = items.find((it) => itemId(it) === selectedId);
  if (!selected) return null;

  const parentLayer = PARENT_LAYER[selected.layer];
  if (!parentLayer) {
    // L1: prefer score region if selecting title/key; else self
    if (selected.layer === "L1") {
      const score = items.find(
        (it) =>
          it.layer === "L1" &&
          (it.kind === "score" || it.label === "score" || it.id === "l1-score"),
      );
      if (
        score &&
        selected.kind !== "score" &&
        selected.label !== "score" &&
        selected.id !== "l1-score"
      ) {
        // Still zoom to the selected L1 band itself (title etc.)
        return selected.box;
      }
    }
    return selected.box;
  }

  const cx = (selected.box.x1 + selected.box.x2) / 2;
  const cy = (selected.box.y1 + selected.box.y2) / 2;
  let candidates = items.filter((it) => it.layer === parentLayer);

  // L2→L1: prefer score region over title/key_time
  if (parentLayer === "L1") {
    const scores = candidates.filter(
      (it) =>
        it.kind === "score" || it.label === "score" || it.id === "l1-score",
    );
    if (scores.length) candidates = scores;
  }

  if (!candidates.length) return selected.box;

  const containing = candidates.filter(
    (c) =>
      cx >= c.box.x1 - 2 &&
      cx <= c.box.x2 + 2 &&
      cy >= c.box.y1 - 2 &&
      cy <= c.box.y2 + 2,
  );
  if (containing.length === 1) return containing[0].box;
  if (containing.length > 1) {
    // Smallest containing parent (tightest)
    return containing.reduce((a, b) => {
      const aa = (a.box.x2 - a.box.x1) * (a.box.y2 - a.box.y1);
      const bb = (b.box.x2 - b.box.x1) * (b.box.y2 - b.box.y1);
      return aa <= bb ? a : b;
    }).box;
  }

  // Nearest by center distance
  let best = candidates[0];
  let bestD = Infinity;
  for (const c of candidates) {
    const bcx = (c.box.x1 + c.box.x2) / 2;
    const bcy = (c.box.y1 + c.box.y2) / 2;
    const d = (bcx - cx) ** 2 + (bcy - cy) ** 2;
    if (d < bestD) {
      bestD = d;
      best = c;
    }
  }
  return best.box;
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

type ResizeHandle =
  | "n"
  | "s"
  | "e"
  | "w"
  | "ne"
  | "nw"
  | "se"
  | "sw"
  | "move";

/**
 * Structure box geometry is always in **natural image pixels** (authoritative).
 * Screen size = natural * scale * zoom (zoom applied on parent transform).
 * Drag deltas must divide by (scale * zoom) so edit handles match the painted box.
 */
function StructureItemOverlay({
  item,
  scaleX,
  scaleY,
  zoom,
  editable,
  selected,
  onSelect,
  onBoxChange,
  naturalW,
  naturalH,
}: {
  item: StructureBox;
  scaleX: number;
  scaleY: number;
  zoom: number;
  editable?: boolean;
  selected?: boolean;
  onSelect?: (id: string) => void;
  onBoxChange?: (id: string, box: BoundingBox) => void;
  naturalW: number;
  naturalH: number;
}) {
  const st = LAYER_STYLE[item.layer];
  const showLabel = item.layer === "L1" || item.layer === "L2" || item.layer === "L5";
  const id = item.id || `${item.layer}-${item.label}`;
  // Visual scale: CSS layout px per natural px, then parent applies zoom
  const sx = Math.max(scaleX * zoom, 1e-6);
  const sy = Math.max(scaleY * zoom, 1e-6);

  const onPointerDownHandle = (
    e: ReactPointerEvent,
    handle: ResizeHandle,
  ) => {
    if (!editable || !onBoxChange) return;
    e.preventDefault();
    e.stopPropagation();
    onSelect?.(id);
    const startX = e.clientX;
    const startY = e.clientY;
    const origin = { ...item.box };
    const target = e.currentTarget as HTMLElement;
    target.setPointerCapture(e.pointerId);

    const onMove = (ev: PointerEvent) => {
      // client delta → natural image pixels (accounts for zoom)
      const dx = (ev.clientX - startX) / sx;
      const dy = (ev.clientY - startY) / sy;
      let { x1, y1, x2, y2 } = origin;
      if (handle === "move") {
        const w = x2 - x1;
        const h = y2 - y1;
        x1 = clamp(origin.x1 + dx, 0, Math.max(0, naturalW - w));
        y1 = clamp(origin.y1 + dy, 0, Math.max(0, naturalH - h));
        x2 = x1 + w;
        y2 = y1 + h;
      } else {
        if (handle.includes("e")) x2 = origin.x2 + dx;
        if (handle.includes("w")) x1 = origin.x1 + dx;
        if (handle.includes("s")) y2 = origin.y2 + dy;
        if (handle.includes("n")) y1 = origin.y1 + dy;
        x1 = clamp(x1, 0, naturalW);
        x2 = clamp(x2, 0, naturalW);
        y1 = clamp(y1, 0, naturalH);
        y2 = clamp(y2, 0, naturalH);
      }
      const next = normRect(x1, y1, x2, y2);
      if (next.x2 - next.x1 < 4 || next.y2 - next.y1 < 4) return;
      onBoxChange(id, next);
    };
    const onUp = (ev: PointerEvent) => {
      target.releasePointerCapture(ev.pointerId);
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
  };

  const handles: { h: ResizeHandle; style: CSSProperties; cursor: string }[] = [
    { h: "nw", style: { left: 0, top: 0, transform: "translate(-50%, -50%)" }, cursor: "nwse-resize" },
    { h: "ne", style: { left: "100%", top: 0, transform: "translate(-50%, -50%)" }, cursor: "nesw-resize" },
    { h: "sw", style: { left: 0, top: "100%", transform: "translate(-50%, -50%)" }, cursor: "nesw-resize" },
    { h: "se", style: { left: "100%", top: "100%", transform: "translate(-50%, -50%)" }, cursor: "nwse-resize" },
    { h: "n", style: { left: "50%", top: 0, transform: "translate(-50%, -50%)" }, cursor: "ns-resize" },
    { h: "s", style: { left: "50%", top: "100%", transform: "translate(-50%, -50%)" }, cursor: "ns-resize" },
    { h: "w", style: { left: 0, top: "50%", transform: "translate(-50%, -50%)" }, cursor: "ew-resize" },
    { h: "e", style: { left: "100%", top: "50%", transform: "translate(-50%, -50%)" }, cursor: "ew-resize" },
  ];

  return (
    <div
      className={`absolute border-2 ${st.border} ${st.bg} box-border ${
        editable ? "pointer-events-auto" : "pointer-events-none"
      } ${selected ? "z-20" : "z-10"}`}
      style={{
        left: item.box.x1 * scaleX,
        top: item.box.y1 * scaleY,
        width: Math.max(1, (item.box.x2 - item.box.x1) * scaleX),
        height: Math.max(1, (item.box.y2 - item.box.y1) * scaleY),
        // Outline outside geometry so selected frame matches natural-pixel box
        outline: selected ? "2px solid rgba(255,255,255,0.9)" : undefined,
        outlineOffset: 0,
      }}
      title={[
        item.layer,
        item.label,
        item.pitch,
        item.duration,
        `像素 ${Math.round(item.box.x1)},${Math.round(item.box.y1)}–${Math.round(item.box.x2)},${Math.round(item.box.y2)}`,
        editable ? "拖角缩放 · 拖框移动 · 以图像像素为准" : "",
      ]
        .filter(Boolean)
        .join(" · ")}
      onPointerDown={(e) => {
        if (!editable) return;
        onPointerDownHandle(e, "move");
      }}
      onClick={(e) => {
        if (!editable) return;
        e.stopPropagation();
        onSelect?.(id);
      }}
    >
      {showLabel && item.label ? (
        <span
          className={`pointer-events-none absolute -top-0.5 left-0 max-w-full truncate px-0.5 text-[9px] leading-tight ${st.text} bg-black/55`}
        >
          {item.label}
        </span>
      ) : null}
      {editable && selected
        ? handles.map(({ h, style, cursor }) => (
            <div
              key={h}
              className="absolute h-2.5 w-2.5 rounded-sm border border-white bg-indigo-400"
              style={{ ...style, cursor }}
              onPointerDown={(e) => onPointerDownHandle(e, h)}
            />
          ))
        : null}
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
  structureEditMode = false,
  structureAddMode = false,
  structureAddLayer = "L2",
  selectedStructureId = null,
  onSelectStructureId,
  onStructureBoxChange,
  onStructureBoxAdd,
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

  // Keep latest structure for parent lookup without re-fitting on every drag
  const structureRef = useRef(structure);
  structureRef.current = structure;

  /**
   * Fit a natural-pixel box into the viewport and center it.
   * Uses flex-centered image + transform-origin center:
   *   pan = -(boxCenter - imageCenter) * zoom  (in layout px)
   */
  const fitNaturalBox = useCallback(
    (box: BoundingBox) => {
      const vp = viewportRef.current;
      const img = imgRef.current;
      if (!vp || !img || !natural.w || !natural.h) return;

      const layoutW = img.offsetWidth || img.clientWidth || baseSize.w;
      const layoutH = img.offsetHeight || img.clientHeight || baseSize.h;
      if (layoutW <= 1 || layoutH <= 1) return;

      const sx = layoutW / natural.w;
      const sy = layoutH / natural.h;
      const tw = Math.max(8, (box.x2 - box.x1) * sx);
      const th = Math.max(8, (box.y2 - box.y1) * sy);
      const tcx = ((box.x1 + box.x2) / 2) * sx;
      const tcy = ((box.y1 + box.y2) / 2) * sy;

      const vpW = vp.clientWidth;
      const vpH = vp.clientHeight;
      if (vpW <= 1 || vpH <= 1) return;

      const availW = vpW * (1 - 2 * FIT_PAD);
      const availH = vpH * (1 - 2 * FIT_PAD);
      const z = clamp(
        Math.min(availW / tw, availH / th),
        MIN_ZOOM,
        MAX_AUTO_ZOOM,
      );

      // Flex-centers the unscaled image; pan offsets scaled delta from image center
      const panX = -(tcx - layoutW / 2) * z;
      const panY = -(tcy - layoutH / 2) * z;

      setZoom(z);
      setPan({ x: panX, y: panY });
    },
    [baseSize.h, baseSize.w, natural.h, natural.w],
  );

  // #78 edit mode: on selection change only → zoom/pan to parent layer region
  // (do not re-run when box is resized — structure updates on every drag)
  useEffect(() => {
    if (!structureEditMode || structureAddMode) return;
    if (!selectedStructureId) return;
    if (!natural.w || !natural.h) return;
    const st = structureRef.current;
    if (!st?.items?.length) return;

    const focus = focusBoxForSelection(st, selectedStructureId);
    if (!focus) return;

    const id = requestAnimationFrame(() => {
      fitNaturalBox(focus);
    });
    return () => cancelAnimationFrame(id);
  }, [
    selectedStructureId,
    structureEditMode,
    structureAddMode,
    natural.w,
    natural.h,
    fitNaturalBox,
  ]);

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

  const onWheel = (e: ReactWheelEvent) => {
    e.preventDefault();
    const factor = e.deltaY < 0 ? ZOOM_STEP : 1 / ZOOM_STEP;
    zoomAt(zoom * factor, e.clientX, e.clientY);
  };

  const onPointerDown = (e: ReactPointerEvent) => {
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

    // #78: draw a new structure region
    if (structureAddMode && structureEditMode && onStructureBoxAdd && e.button === 0) {
      const p = toImageCoords(e.clientX, e.clientY);
      if (!p) return;
      el.setPointerCapture?.(e.pointerId);
      setDrag({ startX: p.x, startY: p.y, curX: p.x, curY: p.y });
      return;
    }

    if (!selectionEnabled || e.button !== 0) return;
    const p = toImageCoords(e.clientX, e.clientY);
    if (!p) return;
    el.setPointerCapture?.(e.pointerId);
    setDrag({ startX: p.x, startY: p.y, curX: p.x, curY: p.y });
  };

  const onPointerMove = (e: ReactPointerEvent) => {
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
    if (structureAddMode && structureEditMode && onStructureBoxAdd) {
      onStructureBoxAdd(r, structureAddLayer ?? "L2");
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
      <div className="flex min-h-[420px] h-[min(780px,calc(100vh-11rem))] items-center justify-center rounded-xl border border-white/10 bg-slate-950/50 text-sm text-slate-500">
        尚未选择图片
      </div>
    );
  }

  const cursorClass = panDrag
    ? "cursor-grabbing"
    : spaceDown
      ? "cursor-grab"
      : structureAddMode && structureEditMode
        ? "cursor-crosshair"
        : selectionEnabled
          ? "cursor-crosshair"
          : "cursor-default";

  // Prefer large work area for dual-view proofing (#78 layout)
  const vh = compact
    ? "h-[min(420px,48vh)]"
    : "h-[min(780px,calc(100vh-11rem))] min-h-[420px]";
  const imgMax = compact
    ? "max-h-[400px]"
    : "max-h-[min(760px,calc(100vh-12rem))]";
  const showBoxes = overlayMode === "boxes" && boxes && boxes.length > 0;

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl border border-white/10 bg-slate-950/50">
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
          <span
            className="min-w-[3rem] text-center tabular-nums text-slate-400"
            title={
              structureEditMode
                ? "编辑模式选中框时自动缩放到上一层区域"
                : undefined
            }
          >
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
          "relative flex min-h-0 flex-1 items-center justify-center overflow-hidden bg-slate-950/40 p-2 sm:p-3",
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
            className={`${imgMax} max-w-full w-auto object-contain`}
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
          {/* #58 structure L1–L5 overlays (#78 editable) */}
          {structure?.items?.length && natural.w > 0
            ? structure.items.map((it) => {
                const show =
                  overlayMode === "structure"
                    ? structureLayers?.[it.layer] !== false
                    : false;
                if (!show) return null;
                const sid = it.id || `${it.layer}-${it.label}`;
                return (
                  <StructureItemOverlay
                    key={sid}
                    item={it}
                    scaleX={scaleX}
                    scaleY={scaleY}
                    zoom={zoom}
                    editable={structureEditMode && !structureAddMode}
                    selected={selectedStructureId === sid}
                    onSelect={onSelectStructureId}
                    onBoxChange={onStructureBoxChange}
                    naturalW={natural.w}
                    naturalH={natural.h}
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
