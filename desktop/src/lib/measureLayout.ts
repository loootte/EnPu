/**
 * Approximate measure ↔ image region mapping for dual-view (#45).
 * Reading order: left→right on a staff, then top→bottom.
 * Heuristic only until notes carry real bboxes.
 */

import type { CropRect } from "./types";

export function estimateMeasuresPerLine(
  nMeasures: number,
  imageW: number,
  imageH: number,
): number {
  if (nMeasures <= 1) return 1;
  const w = Math.max(1, imageW);
  const h = Math.max(1, imageH);
  const aspect = w / h;
  const guess = Math.round(Math.sqrt(Math.max(1, nMeasures) * Math.max(0.5, aspect)));
  return Math.max(2, Math.min(8, guess, nMeasures));
}

/** 0-based measure index → approximate full-image pixel rect. */
export function measureIndexToRect(
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
  // Leave ~8% margins (title / margins on scans).
  const mx = imageW * 0.06;
  const my = imageH * 0.1;
  const usableW = Math.max(1, imageW - 2 * mx);
  const usableH = Math.max(1, imageH - 2 * my);
  const cellW = usableW / mpl;
  const cellH = usableH / nRows;
  const x1 = mx + col * cellW;
  const y1 = my + row * cellH;
  return {
    x1,
    y1,
    x2: x1 + cellW,
    y2: y1 + cellH,
  };
}

/** Map image point to 0-based measure index. */
export function pointToMeasureIndex(
  x: number,
  y: number,
  nMeasures: number,
  imageW: number,
  imageH: number,
  measuresPerLine?: number,
): number {
  if (nMeasures <= 0) return 0;
  const mpl = measuresPerLine ?? estimateMeasuresPerLine(nMeasures, imageW, imageH);
  const nRows = Math.max(1, Math.ceil(nMeasures / mpl));
  const mx = imageW * 0.06;
  const my = imageH * 0.1;
  const usableW = Math.max(1, imageW - 2 * mx);
  const usableH = Math.max(1, imageH - 2 * my);
  const fx = Math.max(0, Math.min(0.9999, (x - mx) / usableW));
  const fy = Math.max(0, Math.min(0.9999, (y - my) / usableH));
  const col = Math.min(mpl - 1, Math.floor(fx * mpl));
  const row = Math.min(nRows - 1, Math.floor(fy * nRows));
  return Math.max(0, Math.min(nMeasures - 1, row * mpl + col));
}

/** Crop rect → 1-based inclusive measure range for dual-view / merge preview. */
export function rectToMeasureRange(
  rect: CropRect,
  nMeasures: number,
  imageW: number,
  imageH: number,
): { from: number; to: number } {
  if (nMeasures <= 0) return { from: 1, to: 1 };
  const a = pointToMeasureIndex(rect.x1, rect.y1, nMeasures, imageW, imageH);
  const b = pointToMeasureIndex(rect.x2, rect.y2, nMeasures, imageW, imageH);
  const lo = Math.min(a, b);
  const hi = Math.max(a, b);
  return { from: lo + 1, to: hi + 1 };
}

/** 1-based measure numbers → list of approx rects for image overlay. */
export function measuresToRects(
  measures: number[],
  nMeasures: number,
  imageW: number,
  imageH: number,
): CropRect[] {
  return measures.map((m) =>
    measureIndexToRect(m - 1, nMeasures, imageW, imageH),
  );
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
