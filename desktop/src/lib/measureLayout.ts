/**
 * Measure ↔ image region mapping for dual-view (#45).
 *
 * Prefer OCR boxes (reading-order partition) when available — uniform page-grid
 * fails on tall scores (e.g. M04) where measure 1 is mid-page but not mid-score.
 */

import type { BoundingBox, CropRect } from "./types";

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

function unionBoxes(boxes: BoundingBox[]): CropRect | null {
  if (!boxes.length) return null;
  let x1 = Infinity;
  let y1 = Infinity;
  let x2 = -Infinity;
  let y2 = -Infinity;
  for (const b of boxes) {
    x1 = Math.min(x1, b.x1);
    y1 = Math.min(y1, b.y1);
    x2 = Math.max(x2, b.x2);
    y2 = Math.max(y2, b.y2);
  }
  return { x1, y1, x2, y2 };
}

function rectsIntersect(a: CropRect, b: CropRect, pad = 2): boolean {
  return !(
    a.x2 < b.x1 - pad ||
    a.x1 > b.x2 + pad ||
    a.y2 < b.y1 - pad ||
    a.y1 > b.y2 + pad
  );
}

function sortBoxesReadingOrder(boxes: BoundingBox[]): BoundingBox[] {
  // Cluster by row (y), then left→right within row.
  if (boxes.length <= 1) return [...boxes];
  const centers = boxes.map((b) => ({ b, ...boxCenter(b) }));
  const heights = boxes.map((b) => Math.max(4, b.y2 - b.y1));
  const medH =
    [...heights].sort((a, c) => a - c)[Math.floor(heights.length / 2)] ?? 20;
  const rowTol = Math.max(12, medH * 0.65);

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
  const out: BoundingBox[] = [];
  for (const row of rows) {
    row.items.sort((a, c) => a.x - c.x);
    for (const it of row.items) out.push(it.b);
  }
  return out;
}

/**
 * Partition OCR boxes into one rect per measure (reading order).
 * Falls back to uniform page grid when boxes are missing.
 */
export function buildMeasureRects(
  nMeasures: number,
  imageW: number,
  imageH: number,
  boxes?: BoundingBox[] | null,
): CropRect[] {
  const n = Math.max(0, nMeasures);
  if (n === 0) return [];

  const usable = (boxes ?? []).filter(
    (b) => b.x2 > b.x1 && b.y2 > b.y1 && Number.isFinite(b.x1),
  );

  if (usable.length > 0) {
    const ordered = sortBoxesReadingOrder(usable);
    // If fewer boxes than measures, pad by splitting last / equal groups.
    const rects: CropRect[] = [];
    if (ordered.length >= n) {
      // Chunk boxes into n contiguous groups (ceil sizes).
      for (let i = 0; i < n; i += 1) {
        const start = Math.floor((i * ordered.length) / n);
        const end = Math.floor(((i + 1) * ordered.length) / n);
        const chunk = ordered.slice(start, Math.max(start + 1, end));
        const u = unionBoxes(chunk);
        if (u) rects.push(u);
        else rects.push(measureIndexToRectGrid(i, n, imageW, imageH));
      }
      return rects;
    }
    // Fewer boxes: assign each box then fill remaining with grid near last box.
    for (let i = 0; i < n; i += 1) {
      if (i < ordered.length) {
        const u = unionBoxes([ordered[i]!]);
        rects.push(u ?? measureIndexToRectGrid(i, n, imageW, imageH));
      } else {
        const prev = rects[rects.length - 1];
        if (prev) {
          const w = prev.x2 - prev.x1;
          rects.push({
            x1: prev.x2,
            y1: prev.y1,
            x2: prev.x2 + Math.max(8, w),
            y2: prev.y2,
          });
        } else {
          rects.push(measureIndexToRectGrid(i, n, imageW, imageH));
        }
      }
    }
    return rects;
  }

  return Array.from({ length: n }, (_, i) =>
    measureIndexToRectGrid(i, n, imageW, imageH),
  );
}

/** Uniform grid fallback (weak on tall multi-system pages). */
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
  // Staff band: ignore top title / bottom margin more aggressively on tall pages.
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

/** @deprecated use buildMeasureRects / measureIndexToRectGrid */
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

export function pointToMeasureIndex(
  x: number,
  y: number,
  measureRects: CropRect[],
): number {
  if (!measureRects.length) return 0;
  // Prefer containing rect; else nearest center.
  for (let i = 0; i < measureRects.length; i += 1) {
    const r = measureRects[i]!;
    if (x >= r.x1 && x <= r.x2 && y >= r.y1 && y <= r.y2) return i;
  }
  let best = 0;
  let bestD = Infinity;
  for (let i = 0; i < measureRects.length; i += 1) {
    const r = measureRects[i]!;
    const cx = (r.x1 + r.x2) / 2;
    const cy = (r.y1 + r.y2) / 2;
    const d = (x - cx) ** 2 + (y - cy) ** 2;
    if (d < bestD) {
      bestD = d;
      best = i;
    }
  }
  return best;
}

/** Crop rect → 1-based inclusive measure range via spatial intersection. */
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
    // Fall back to centers of TL/BR
    const a = pointToMeasureIndex(rect.x1, rect.y1, measureRects);
    const b = pointToMeasureIndex(rect.x2, rect.y2, measureRects);
    const lo = Math.min(a, b);
    const hi = Math.max(a, b);
    return { from: lo + 1, to: hi + 1 };
  }
  return { from: hits[0]! + 1, to: hits[hits.length - 1]! + 1 };
}

/** Large staff ROI heuristic (mirrors core is_large_staff_roi). */
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

/** Active measure numbers (1-based) → their spatial rects for yellow overlay. */
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
