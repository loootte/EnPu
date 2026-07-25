"""Jianpu duration helpers: underline geometry + meter soft-fit (#54).

Jianpu convention (v0.1 mapping):
- 0 underlines → quarter
- 1 underline  → eighth
- 2+ underlines → sixteenth

OCR rarely emits underlines as text; we detect short horizontal strokes
under digit boxes on the preprocessed image (OpenCV only, no new deps).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import cv2
import numpy as np

from app.pipeline.ocr import OcrItem
from app.schemas.recognize import BoundingBox
from app.schemas.score import DurationName, NoteEvent

logger = logging.getLogger(__name__)

_DIGIT_CHARS = set("01234567０１２３４５６７")


@dataclass(frozen=True)
class UnderlineHit:
    """Underline count for a digit OCR box (input / OCR image coords)."""

    box: BoundingBox
    underlines: int  # 0, 1, or 2+


def underlines_to_duration(underlines: int) -> DurationName:
    if underlines >= 2:
        return DurationName.sixteenth
    if underlines == 1:
        return DurationName.eighth
    return DurationName.quarter


def detect_underlines_for_items(
    image_bgr: np.ndarray,
    items: list[OcrItem],
    *,
    max_underlines: int = 2,
) -> list[UnderlineHit]:
    """Detect horizontal underlines under digit-like OCR boxes.

    Coordinates of ``item.box`` must match ``image_bgr`` (same scale).
    Returns hits only for items that look like single pitch/rest digits.
    """
    if image_bgr is None or image_bgr.size == 0:
        return []
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape[:2]
    # Dark strokes on light paper
    _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    hits: list[UnderlineHit] = []
    for it in items:
        if it.box is None:
            continue
        text = (it.text or "").strip()
        # Single digit (or short glued digit run handled elsewhere)
        if not text or not all(c in _DIGIT_CHARS or c.isspace() for c in text):
            continue
        digits = [c for c in text if c in _DIGIT_CHARS]
        if len(digits) != 1:
            # Multi-digit token: skip geometry (ambiguous)
            continue

        box = it.box
        bw_box = max(box.x2 - box.x1, 4.0)
        bh_box = max(box.y2 - box.y1, 4.0)
        # ROI: slightly wider than digit, strip just below baseline
        x0 = int(max(0, box.x1 - 0.15 * bw_box))
        x1 = int(min(w, box.x2 + 0.15 * bw_box))
        y0 = int(min(h - 1, box.y2 + 0.05 * bh_box))
        y1 = int(min(h, box.y2 + max(4.0, 0.85 * bh_box)))
        if x1 - x0 < 3 or y1 - y0 < 2:
            hits.append(UnderlineHit(box=box, underlines=0))
            continue

        roi = bw[y0:y1, x0:x1]
        if roi.size == 0:
            hits.append(UnderlineHit(box=box, underlines=0))
            continue

        count = _count_horizontal_strokes(
            roi,
            min_width_ratio=0.35,
            max_underlines=max_underlines,
        )
        hits.append(UnderlineHit(box=box, underlines=count))

    if hits:
        n_pos = sum(1 for h in hits if h.underlines > 0)
        logger.info(
            "duration underlines: %s/%s digit boxes have ≥1 stroke (#54)",
            n_pos,
            len(hits),
        )
    return hits


def _count_horizontal_strokes(
    roi_bw: np.ndarray,
    *,
    min_width_ratio: float,
    max_underlines: int,
) -> int:
    """Count distinct horizontal ink bands in a binary (ink=255) ROI."""
    rh, rw = roi_bw.shape[:2]
    if rh < 2 or rw < 3:
        return 0

    # Horizontal morphology: keep long thin rows
    k_w = max(3, int(rw * 0.4))
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (k_w, 1))
    horiz = cv2.morphologyEx(roi_bw, cv2.MORPH_OPEN, kernel, iterations=1)

    # Row ink density
    row_sum = (horiz > 0).sum(axis=1).astype(np.float32)
    thr = max(2.0, min_width_ratio * rw * 0.5)
    active = row_sum >= thr

    # Count contiguous active runs (each ≈ one underline)
    counts = 0
    in_run = False
    run_len = 0
    for a in active:
        if a:
            in_run = True
            run_len += 1
        else:
            if in_run and run_len >= 1:
                counts += 1
            in_run = False
            run_len = 0
    if in_run and run_len >= 1:
        counts += 1

    return int(min(max_underlines, counts))


def lookup_underlines(
    box: BoundingBox,
    hits: list[UnderlineHit],
    *,
    iou_min: float = 0.25,
) -> int:
    """Best underline count for a box by IoU against detection hits."""
    best = 0
    best_iou = 0.0
    for h in hits:
        iou = _iou(box, h.box)
        if iou > best_iou:
            best_iou = iou
            best = h.underlines
    return best if best_iou >= iou_min else 0


def _iou(a: BoundingBox, b: BoundingBox) -> float:
    ix1 = max(a.x1, b.x1)
    iy1 = max(a.y1, b.y1)
    ix2 = min(a.x2, b.x2)
    iy2 = min(a.y2, b.y2)
    iw = max(0.0, ix2 - ix1)
    ih = max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    area_a = max(0.0, a.x2 - a.x1) * max(0.0, a.y2 - a.y1)
    area_b = max(0.0, b.x2 - b.x1) * max(0.0, b.y2 - b.y1)
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def annotate_digit_text_with_underlines(
    text: str,
    box: BoundingBox | None,
    hits: list[UnderlineHit],
) -> str:
    """Append ``_`` markers to a single-digit token for the text parser."""
    t = (text or "").strip()
    if not t or box is None:
        return t
    # Only pure single digit
    digits = [c for c in t if c in _DIGIT_CHARS]
    if len(digits) != 1 or any(c not in _DIGIT_CHARS and not c.isspace() for c in t):
        return t
    u = lookup_underlines(box, hits)
    if u <= 0:
        return digits[0]
    return digits[0] + ("_" * min(2, u))


_BEATS: dict[DurationName, float] = {
    DurationName.whole: 4.0,
    DurationName.half: 2.0,
    DurationName.quarter: 1.0,
    DurationName.eighth: 0.5,
    DurationName.sixteenth: 0.25,
    DurationName.thirty_second: 0.125,
}


def note_beats(note: NoteEvent) -> float:
    base = _BEATS.get(note.duration, 1.0)
    if note.dots == 1:
        return base * 1.5
    if note.dots >= 2:
        return base * 1.75
    return base


def fit_notes_to_capacity(
    notes: list[NoteEvent],
    capacity: float,
    *,
    eps: float = 0.35,
) -> tuple[list[NoteEvent], bool]:
    """Shorten default/underline notes so total beats fit the bar capacity (#54).

    Does not lengthen notes. Does not shrink explicit dash-based half/whole
    unless still overfull after softer steps.
    """
    if not notes or capacity <= 0:
        return notes, False

    def total(ns: list[NoteEvent]) -> float:
        return sum(note_beats(n) for n in ns)

    if total(notes) <= capacity + eps:
        return notes, False

    out = [n.model_copy(deep=True) for n in notes]
    changed = False

    def shrinkable(n: NoteEvent) -> bool:
        src = (n.extra or {}).get("duration_from", "default")
        return src in {"default", "underline", "meter_fit", "ocr_underscore"}

    # Pass 1: default quarters → eighth
    for n in out:
        if not shrinkable(n):
            continue
        if n.duration == DurationName.quarter and n.dots == 0:
            n.duration = DurationName.eighth
            n.extra = {**(n.extra or {}), "duration_from": "meter_fit"}
            changed = True
    if total(out) <= capacity + eps:
        return out, changed

    # Pass 2: eighth (default/meter/underline) → sixteenth
    for n in out:
        if not shrinkable(n):
            continue
        if n.duration == DurationName.eighth and n.dots == 0:
            n.duration = DurationName.sixteenth
            n.extra = {**(n.extra or {}), "duration_from": "meter_fit"}
            changed = True
    if total(out) <= capacity + eps:
        return out, changed

    # Pass 3: still overfull — also shrink dashed half→quarter (OCR may fake dashes)
    for n in out:
        src = (n.extra or {}).get("duration_from", "default")
        if src == "dash" and n.duration == DurationName.half and n.dots == 0:
            n.duration = DurationName.quarter
            n.extra = {**(n.extra or {}), "duration_from": "meter_fit"}
            changed = True
    if total(out) <= capacity + eps:
        return out, changed

    # Pass 4: remaining quarters → sixteenth
    for n in out:
        if n.duration == DurationName.quarter and n.dots == 0:
            n.duration = DurationName.sixteenth
            n.extra = {**(n.extra or {}), "duration_from": "meter_fit"}
            changed = True

    return out, changed
