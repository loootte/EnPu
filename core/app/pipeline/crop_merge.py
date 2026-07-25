"""Crop ROI recognition helpers and Score merge (issue #49).

Rectangle crop only. Merges crop parse into a base Score by measure range
without overwriting measures outside the replace window.
"""

from __future__ import annotations

import math
from copy import deepcopy
from typing import Any

from app.schemas.recognize import BoundingBox, CropMergeInfo, CropRect
from app.schemas.score import Measure, Part, Score


def normalize_crop_rect(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    *,
    width: int,
    height: int,
    min_side: int = 8,
) -> CropRect:
    """Clamp and order crop corners to image bounds."""
    if width <= 0 or height <= 0:
        raise ValueError("Image dimensions must be positive.")

    ax1 = max(0.0, min(float(x1), float(x2)))
    ay1 = max(0.0, min(float(y1), float(y2)))
    ax2 = min(float(width), max(float(x1), float(x2)))
    ay2 = min(float(height), max(float(y1), float(y2)))

    if ax2 - ax1 < min_side or ay2 - ay1 < min_side:
        raise ValueError(
            f"Crop rect too small ({ax2 - ax1:.0f}x{ay2 - ay1:.0f}); "
            f"min side is {min_side}px."
        )

    return CropRect(x1=ax1, y1=ay1, x2=ax2, y2=ay2)


def crop_slice_indices(rect: CropRect) -> tuple[int, int, int, int]:
    """Integer pixel slices [y1:y2, x1:x2] for numpy/OpenCV."""
    x1 = int(math.floor(rect.x1))
    y1 = int(math.floor(rect.y1))
    x2 = int(math.ceil(rect.x2))
    y2 = int(math.ceil(rect.y2))
    return x1, y1, x2, y2


def offset_boxes(boxes: list[BoundingBox], dx: float, dy: float) -> list[BoundingBox]:
    """Map crop-local boxes back to full-image coordinates."""
    out: list[BoundingBox] = []
    for b in boxes:
        out.append(
            BoundingBox(
                x1=b.x1 + dx,
                y1=b.y1 + dy,
                x2=b.x2 + dx,
                y2=b.y2 + dy,
                score=b.score,
            )
        )
    return out


def _part0(score: Score) -> Part:
    if not score.parts:
        return Part(id="P1", name="melody", measures=[])
    return score.parts[0]


def _measures(score: Score) -> list[Measure]:
    return list(_part0(score).measures)


def estimate_measures_per_line(
    n_base: int,
    *,
    image_width: int,
    image_height: int,
) -> int:
    """Heuristic measures-per-staff-line for jianpu reading order."""
    if n_base <= 1:
        return 1
    w = max(1, image_width)
    h = max(1, image_height)
    # Wider pages → more measures per line; clamp to typical 2–8.
    aspect = w / float(h)
    guess = int(round(math.sqrt(max(1, n_base) * max(0.5, aspect))))
    return max(2, min(8, guess, n_base))


def estimate_measure_index(
    *,
    n_base: int,
    crop: CropRect,
    image_width: int,
    image_height: int,
    measures_per_line: int | None = None,
) -> int:
    """Map crop center to a 0-based measure index using row-major reading order.

    Jianpu measures run left→right on a staff, then top→bottom. Pure Y-fraction
    mapping wrongly sends a top-left (first) measure to a mid-score index.
    """
    if n_base <= 0:
        return 0
    if n_base == 1:
        return 0

    w = max(1, image_width)
    h = max(1, image_height)
    cx = (crop.x1 + crop.x2) / 2.0
    cy = (crop.y1 + crop.y2) / 2.0
    fx = max(0.0, min(0.9999, cx / w))
    fy = max(0.0, min(0.9999, cy / h))

    mpl = measures_per_line or estimate_measures_per_line(
        n_base, image_width=w, image_height=h
    )
    mpl = max(1, min(mpl, n_base))
    n_rows = max(1, math.ceil(n_base / mpl))

    row = min(n_rows - 1, int(fy * n_rows))
    col = min(mpl - 1, int(fx * mpl))
    idx = row * mpl + col
    # Last row may be short.
    return max(0, min(n_base - 1, idx))


def estimate_measure_window(
    *,
    n_base: int,
    n_crop: int,
    crop: CropRect,
    image_height: int,
    image_width: int = 0,
) -> tuple[int, int]:
    """Estimate 0-based [start, end) measure indices in base for crop replace.

    Auto mode replaces **one** base measure slot at the estimated reading-order
    index, then splices in all crop measures (even if duration bugs split one
    bar into many). Never shifts the window toward the end of the score when
    ``n_crop`` is large — that caused "first measure → 小节 7" regressions.

    Known limit (defer to #45 dual-view): large ROI covering the whole staff
    (e.g. samples/001_poc_digits.png 10 bars → 15 after crop) still mis-hits
    mid-score and inflates measure count; needs region↔measure mapping + better
    replace span, not only a single hit index. See also duration over-split #54.
    """
    if n_base <= 0:
        return 0, 0

    w = image_width if image_width > 0 else max(1, image_height)
    start = estimate_measure_index(
        n_base=n_base,
        crop=crop,
        image_width=w,
        image_height=max(1, image_height),
    )
    # Replace a single base measure at the hit index. Crop may insert 1..N bars.
    end = min(n_base, start + 1)
    # If crop Y-span is clearly multi-line (tall ROI), widen by span fraction.
    h = max(1, image_height)
    span_frac = max(0.0, min(1.0, (crop.y2 - crop.y1) / h))
    if span_frac > 0.22 and n_base > 1:
        extra = max(0, int(math.floor(span_frac * n_base)) - 1)
        end = min(n_base, start + 1 + extra)
    # n_crop is intentionally not used to *move* start toward the score end.
    _ = n_crop
    return start, end


def merge_crop_into_score(
    base: Score,
    crop_score: Score | None,
    *,
    crop: CropRect,
    image_height: int,
    image_width: int = 0,
    measure_from: int | None = None,
    measure_to: int | None = None,
) -> tuple[Score, CropMergeInfo]:
    """Replace a measure window in ``base`` with measures from ``crop_score``.

    Measures outside the window are deep-copied from ``base`` (hand edits kept).
    Meta (key / time / tempo / title) prefer ``base`` when set.
    """
    merged = deepcopy(base)
    if not merged.parts:
        merged.parts = [Part(id="P1", name="melody", measures=[])]

    base_measures = _measures(merged)
    n_base = len(base_measures)
    crop_measures = _measures(crop_score) if crop_score is not None else []
    n_crop = len(crop_measures)

    if measure_from is not None or measure_to is not None:
        # 1-based inclusive → 0-based [start, end)
        mf = measure_from if measure_from is not None else 1
        mt = measure_to if measure_to is not None else mf
        if mf < 1 or mt < mf:
            raise ValueError("measure_from / measure_to must be 1-based and from ≤ to.")
        start = mf - 1
        end = mt  # exclusive after: numbers mf..mt inclusive → end = mt
        if n_base == 0:
            start, end = 0, 0
        else:
            start = max(0, min(start, n_base))
            end = max(start, min(end, n_base))
            if end == start and start < n_base:
                end = start + 1
    else:
        start, end = estimate_measure_window(
            n_base=n_base,
            n_crop=max(1, n_crop),
            crop=crop,
            image_height=image_height,
            image_width=image_width,
        )

    # Tag crop measures for UI highlight.
    inserted: list[Measure] = []
    for i, m in enumerate(crop_measures):
        cm = deepcopy(m)
        extra: dict[str, Any] = dict(cm.extra or {})
        extra["from_crop"] = True
        extra["crop_index"] = i
        cm.extra = extra
        inserted.append(cm)

    if not inserted and crop_score is None:
        info = CropMergeInfo(
            replaced_measure_from=start + 1 if n_base else None,
            replaced_measure_to=end if n_base else None,
            inserted_measure_count=0,
            crop=crop,
            preserved_outside=True,
        )
        return merged, info

    if not inserted:
        info = CropMergeInfo(
            replaced_measure_from=start + 1 if n_base else None,
            replaced_measure_to=end if n_base else None,
            inserted_measure_count=0,
            crop=crop,
            preserved_outside=True,
        )
        return merged, info

    before = base_measures[:start]
    after = base_measures[end:]
    new_measures = before + inserted + after

    # Renumber 1-based sequentially.
    for i, m in enumerate(new_measures):
        m.number = i + 1

    part = merged.parts[0]
    part.measures = new_measures

    # Prefer base musical context (user may have corrected key/time).
    if crop_score is not None:
        if not merged.key and crop_score.key:
            merged.key = crop_score.key
        if not merged.time_signature and crop_score.time_signature:
            merged.time_signature = crop_score.time_signature
        if merged.tempo_bpm is None and crop_score.tempo_bpm is not None:
            merged.tempo_bpm = crop_score.tempo_bpm

    if merged.meta is None and crop_score is not None and crop_score.meta is not None:
        merged.meta = deepcopy(crop_score.meta)
    elif merged.meta is not None:
        extra = dict(merged.meta.extra or {})
        extra["last_crop"] = crop.model_dump()
        extra["last_crop_merge_start"] = start + 1
        merged.meta.extra = extra

    info = CropMergeInfo(
        replaced_measure_from=(start + 1) if (n_base or inserted) else None,
        replaced_measure_to=(start + len(inserted)) if inserted else None,
        inserted_measure_count=len(inserted),
        crop=crop,
        preserved_outside=True,
    )
    return merged, info
