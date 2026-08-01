/**
 * Measure ↔ image region mapping for dual-view (#45 / #66).
 *
 * Strategy (priority):
 * 1. **#66** When structure L3 measure boxes exist, use them 1:1 with Score
 *    measure order (same flatten as core assemble).
 * 2. Else use pitch (or non-meta) OCR boxes, cluster into staff **rows** by Y,
 *    tile each row into continuous measure slots by X.
 *
 * Avoids: global equal-chunk of boxes (M04 mid-bar dead zones; whole-row
 * unions; score m3 → blank image).
 */

import type {
  BoundingBox,
  CropRect,
  LayoutRegion,
  StructureDebug,
} from "./types";

/**
 * Prefer structure-first L3 measure rects when present (#66 / #85).
 * Order matches Score.parts[0].measures (system top→bottom, L→R).
 *
 * #85: measures may be ``kind=measure_derived`` (from split lines); also
 * accept legacy ``measure`` and any L3 item with a box.
 */
export function measureRectsFromStructure(
  structure?: StructureDebug | null,
): CropRect[] | null {
  if (!structure?.items?.length) return null;
  const l3 = structure.items
    .filter((it) => {
      if (it.layer !== "L3" || !it.box) return false;
      const k = it.kind || "measure";
      // Include derived measures from split model; exclude non-geometry noise
      return (
        k === "measure" ||
        k === "measure_derived" ||
        k === "" ||
        k === "region"
      );
    })
    .sort((a, b) => {
      const acy = (a.box.y1 + a.box.y2) / 2;
      const bcy = (b.box.y1 + b.box.y2) / 2;
      const acx = (a.box.x1 + a.box.x2) / 2;
      const bcx = (b.box.x1 + b.box.x2) / 2;
      return acy - bcy || acx - bcx;
    });
  if (l3.length === 0) {
    // Fallback: derive rects from L2 rows + barline splits (#85)
    return measureRectsFromSplits(structure);
  }
  return l3.map((it) => ({
    x1: it.box.x1,
    y1: it.box.y1,
    x2: it.box.x2,
    y2: it.box.y2,
  }));
}

/**
 * Build measure rects from L2 systems + structure.barlines splits (#85).
 * Same geometry rule as core ``splits_to_measures``.
 */
export function measureRectsFromSplits(
  structure?: StructureDebug | null,
): CropRect[] | null {
  if (!structure?.items?.length) return null;
  const systems = structure.items
    .filter((it) => it.layer === "L2" && it.box)
    .sort((a, b) => a.box.y1 - b.box.y1 || a.box.x1 - b.box.x1);
  if (!systems.length) return null;
  const barlines = structure.barlines ?? [];
  const out: CropRect[] = [];
  for (let order = 0; order < systems.length; order++) {
    const sys = systems[order]!;
    const bars = barlines
      .filter((b) => b.system === order)
      .map((b) => b.x)
      .filter((x) => x > sys.box.x1 + 1 && x < sys.box.x2 - 1)
      .sort((a, b) => a - b);
    const xs: number[] = [sys.box.x1];
    for (const x of bars) {
      if (x - xs[xs.length - 1]! > 2) xs.push(x);
    }
    if (sys.box.x2 - xs[xs.length - 1]! > 2) xs.push(sys.box.x2);
    else xs[xs.length - 1] = sys.box.x2;
    for (let i = 0; i < xs.length - 1; i++) {
      out.push({
        x1: xs[i]!,
        y1: sys.box.y1,
        x2: xs[i + 1]!,
        y2: sys.box.y2,
      });
    }
  }
  return out.length ? out : null;
}

/** Boxes used for measure geometry: pitch-only when regions available. */
export function boxesForMeasureMap(
  regions?: LayoutRegion[] | null,
  fallbackBoxes?: BoundingBox[] | null,
): BoundingBox[] {
  if (regions && regions.length > 0) {
    const pitch = regions
      .filter((r) => r.kind === "pitch" && r.box)
      .map((r) => r.box);
    if (pitch.length > 0) return pitch;
    const staffish = regions
      .filter(
        (r) =>
          r.box &&
          !["title", "meta", "footer", "lyrics", "annotation"].includes(
            r.kind,
          ),
      )
      .map((r) => r.box);
    if (staffish.length > 0) return staffish;
  }
  return (fallbackBoxes ?? []).filter((b) => b.x2 > b.x1 && b.y2 > b.y1);
}

export function estimateMeasuresPerLine(
  nMeasures: number,
  imageW: number,
  imageH: number,
): number {
  if (nMeasures <= 1) return 1;
  const w = Math.max(1, imageW);
  const h = Math.max(1, imageH);
  const aspect = w / h;
  const guess = Math.round(
    Math.sqrt(Math.max(1, nMeasures) * Math.max(0.5, aspect)),
  );
  return Math.max(2, Math.min(8, guess, nMeasures));
}

function boxCenter(b: BoundingBox): { x: number; y: number } {
  return { x: (b.x1 + b.x2) / 2, y: (b.y1 + b.y2) / 2 };
}

function rectsIntersect(a: CropRect, b: CropRect, pad = 2): boolean {
  return !(
    a.x2 < b.x1 - pad ||
    a.x1 > b.x2 + pad ||
    a.y2 < b.y1 - pad ||
    a.y1 > b.y2 + pad
  );
}

/** Cluster boxes into staff rows (top→bottom), each row L→R. */
export function clusterBoxRows(boxes: BoundingBox[]): BoundingBox[][] {
  if (boxes.length === 0) return [];
  const centers = boxes.map((b) => ({ b, ...boxCenter(b) }));
  const heights = boxes.map((b) => Math.max(4, b.y2 - b.y1));
  const medH =
    [...heights].sort((a, c) => a - c)[Math.floor(heights.length / 2)] ?? 20;
  // Slightly looser than before so one staff line stays one row
  const rowTol = Math.max(14, medH * 0.85);

  centers.sort((a, c) => a.y - c.y || a.x - c.x);
  const rows: { y: number; items: typeof centers }[] = [];
  for (const c of centers) {
    const row = rows.find((r) => Math.abs(r.y - c.y) <= rowTol);
    if (row) {
      row.items.push(c);
      row.y = (row.y * (row.items.length - 1) + c.y) / row.items.length;
    } else {
      rows.push({ y: c.y, items: [c] });
    }
  }
  rows.sort((a, c) => a.y - c.y);
  return rows.map((row) => {
    row.items.sort((a, c) => a.x - c.x);
    return row.items.map((it) => it.b);
  });
}

/** How many measures to put on each row (as even as possible). */
function measuresPerRowPlan(nMeasures: number, nRows: number): number[] {
  if (nRows <= 0) return [];
  if (nMeasures <= 0) return Array(nRows).fill(0);
  const base = Math.floor(nMeasures / nRows);
  const rem = nMeasures % nRows;
  // Prefer fuller early rows (top of page)
  return Array.from({ length: nRows }, (_, i) => base + (i < rem ? 1 : 0));
}

/**
 * Build continuous measure hit-rects.
 *
 * @param noteCounts optional per-measure note counts (weights slot widths)
 */
export function buildMeasureRects(
  nMeasures: number,
  imageW: number,
  imageH: number,
  boxes?: BoundingBox[] | null,
  regions?: LayoutRegion[] | null,
  noteCounts?: number[] | null,
): CropRect[] {
  const n = Math.max(0, nMeasures);
  if (n === 0) return [];

  const usable = boxesForMeasureMap(regions, boxes).filter(
    (b) => b.x2 > b.x1 && b.y2 > b.y1 && Number.isFinite(b.x1),
  );

  if (usable.length === 0) {
    return Array.from({ length: n }, (_, i) =>
      measureIndexToRectGrid(i, n, imageW, imageH),
    );
  }

  const rows = clusterBoxRows(usable);
  if (rows.length === 0) {
    return Array.from({ length: n }, (_, i) =>
      measureIndexToRectGrid(i, n, imageW, imageH),
    );
  }

  // Shared staff horizontal span (align columns across systems)
  let staffX1 = Infinity;
  let staffX2 = -Infinity;
  for (const b of usable) {
    staffX1 = Math.min(staffX1, b.x1);
    staffX2 = Math.max(staffX2, b.x2);
  }
  // Slight horizontal pad so edge notes still hit
  const padX = Math.max(4, (staffX2 - staffX1) * 0.02);
  staffX1 = Math.max(0, staffX1 - padX);
  staffX2 = Math.min(imageW || staffX2 + padX, staffX2 + padX);
  const staffW = Math.max(8, staffX2 - staffX1);

  const plan = measuresPerRowPlan(n, rows.length);
  const rects: CropRect[] = [];
  let mi = 0;

  for (let ri = 0; ri < rows.length; ri += 1) {
    const count = plan[ri] ?? 0;
    if (count <= 0) continue;
    const rowBoxes = rows[ri]!;
    let y1 = Infinity;
    let y2 = -Infinity;
    for (const b of rowBoxes) {
      y1 = Math.min(y1, b.y1);
      y2 = Math.max(y2, b.y2);
    }
    // Vertical pad so hover between underlines still hits the row
    const padY = Math.max(6, (y2 - y1) * 0.35);
    y1 = Math.max(0, y1 - padY);
    y2 = y2 + padY;

    const weights: number[] = [];
    for (let j = 0; j < count; j += 1) {
      const c = noteCounts?.[mi + j];
      weights.push(c != null && c > 0 ? c : 1);
    }
    const wSum = weights.reduce((a, b) => a + b, 0) || count;

    let x = staffX1;
    for (let j = 0; j < count; j += 1) {
      const frac = weights[j]! / wSum;
      const slotW =
        j === count - 1 ? staffX2 - x : Math.max(4, staffW * frac);
      const x2 = j === count - 1 ? staffX2 : x + slotW;
      rects.push({ x1: x, y1, x2, y2 });
      x = x2;
      mi += 1;
    }
  }

  // If clustering produced fewer slots than n (shouldn't), pad with grid
  while (rects.length < n) {
    const i = rects.length;
    const prev = rects[i - 1];
    if (prev) {
      const w = Math.max(8, prev.x2 - prev.x1);
      rects.push({
        x1: prev.x1,
        y1: prev.y2 + 4,
        x2: prev.x1 + w,
        y2: prev.y2 + 4 + (prev.y2 - prev.y1),
      });
    } else {
      rects.push(measureIndexToRectGrid(i, n, imageW, imageH));
    }
  }

  return rects.slice(0, n);
}

/** Uniform grid fallback. */
export function measureIndexToRectGrid(
  index: number,
  nMeasures: number,
  imageW: number,
  imageH: number,
  measuresPerLine?: number,
): CropRect {
  const n = Math.max(1, nMeasures);
  const i = Math.max(0, Math.min(n - 1, index));
  const mpl = measuresPerLine ?? estimateMeasuresPerLine(n, imageW, imageH);
  const nRows = Math.max(1, Math.ceil(n / mpl));
  const row = Math.floor(i / mpl);
  const col = i % mpl;
  const topFrac = imageH > imageW * 1.2 ? 0.14 : 0.1;
  const botFrac = imageH > imageW * 1.2 ? 0.08 : 0.06;
  const mx = imageW * 0.05;
  const my0 = imageH * topFrac;
  const my1 = imageH * (1 - botFrac);
  const usableW = Math.max(1, imageW - 2 * mx);
  const usableH = Math.max(1, my1 - my0);
  const cellW = usableW / mpl;
  const cellH = usableH / nRows;
  const x1 = mx + col * cellW;
  const y1 = my0 + row * cellH;
  return { x1, y1, x2: x1 + cellW, y2: y1 + cellH };
}

export function measureIndexToRect(
  index: number,
  nMeasures: number,
  imageW: number,
  imageH: number,
  measuresPerLine?: number,
): CropRect {
  return measureIndexToRectGrid(
    index,
    nMeasures,
    imageW,
    imageH,
    measuresPerLine,
  );
}

/**
 * Map image point → 0-based measure index, or null if far from staff tiles.
 */
export function pointToMeasureIndex(
  x: number,
  y: number,
  measureRects: CropRect[],
  /** Soft snap (tiles should already be continuous within a row). */
  snapPx = 12,
): number | null {
  if (!measureRects.length) return null;
  for (let i = 0; i < measureRects.length; i += 1) {
    const r = measureRects[i]!;
    if (x >= r.x1 && x <= r.x2 && y >= r.y1 && y <= r.y2) return i;
  }
  if (snapPx <= 0) return null;
  let best: number | null = null;
  let bestD = snapPx * snapPx;
  for (let i = 0; i < measureRects.length; i += 1) {
    const r = measureRects[i]!;
    const dx = x < r.x1 ? r.x1 - x : x > r.x2 ? x - r.x2 : 0;
    const dy = y < r.y1 ? r.y1 - y : y > r.y2 ? y - r.y2 : 0;
    const d = dx * dx + dy * dy;
    if (d <= bestD) {
      bestD = d;
      best = i;
    }
  }
  return best;
}

export function rectToMeasureRange(
  rect: CropRect,
  measureRects: CropRect[],
): { from: number; to: number } {
  if (!measureRects.length) return { from: 1, to: 1 };
  const hits: number[] = [];
  for (let i = 0; i < measureRects.length; i += 1) {
    if (rectsIntersect(rect, measureRects[i]!)) hits.push(i);
  }
  if (hits.length === 0) {
    const a = pointToMeasureIndex(
      (rect.x1 + rect.x2) / 2,
      (rect.y1 + rect.y2) / 2,
      measureRects,
      40,
    );
    if (a == null) return { from: 1, to: 1 };
    return { from: a + 1, to: a + 1 };
  }
  return { from: hits[0]! + 1, to: hits[hits.length - 1]! + 1 };
}

export function isLargeStaffRoi(
  rect: CropRect,
  imageW: number,
  imageH: number,
): boolean {
  const w = Math.max(1, imageW);
  const h = Math.max(1, imageH);
  const cw = Math.max(0, rect.x2 - rect.x1);
  const ch = Math.max(0, rect.y2 - rect.y1);
  const area = (cw * ch) / (w * h);
  const wf = cw / w;
  const hf = ch / h;
  if (area >= 0.4) return true;
  if (wf >= 0.65 && hf >= 0.4) return true;
  if (wf >= 0.85 && hf >= 0.28) return true;
  return false;
}

export function rectsForMeasures(
  measureNumbers: number[],
  measureRects: CropRect[],
): CropRect[] {
  const out: CropRect[] = [];
  for (const m of measureNumbers) {
    const r = measureRects[m - 1];
    if (r) out.push(r);
  }
  return out;
}
