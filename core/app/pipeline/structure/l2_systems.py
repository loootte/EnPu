"""L2: staff / system (jianpu row) detection via horizontal projection (#58)."""

from __future__ import annotations

import cv2
import numpy as np

from app.pipeline.structure.ir import Rect, StaffSystem


def detect_staff_systems(
    image_bgr: np.ndarray,
    score_rect: Rect,
    *,
    min_row_gap: int = 18,
    min_row_height: int = 12,
) -> tuple[list[StaffSystem], list[str]]:
    """Detect horizontal staff systems inside the main score ROI."""
    warnings: list[str] = []
    h, w = image_bgr.shape[:2]
    x0 = max(0, int(score_rect.x1))
    y0 = max(0, int(score_rect.y1))
    x1 = min(w, int(score_rect.x2))
    y1 = min(h, int(score_rect.y2))
    if x1 <= x0 or y1 <= y0:
        warnings.append("L2: empty score ROI")
        return [], warnings

    roi = image_bgr[y0:y1, x0:x1]
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    rh, rw = bw.shape[:2]
    row_ink = (bw > 0).sum(axis=1).astype(np.float32)
    if row_ink.max() <= 0:
        warnings.append("L2: no ink in score ROI; single system fallback")
        return [
            StaffSystem(
                index=0,
                rect=Rect(float(x0), float(y0), float(x1), float(y1)),
                confidence=0.3,
            )
        ], warnings

    thr = max(row_ink.max() * 0.15, rw * 0.02)
    active = row_ink >= thr

    # Merge active runs into bands
    bands: list[tuple[int, int]] = []
    in_run = False
    a0 = 0
    for i, a in enumerate(active):
        if a and not in_run:
            in_run = True
            a0 = i
        elif not a and in_run:
            in_run = False
            if i - a0 >= min_row_height // 2:
                bands.append((a0, i))
    if in_run and rh - a0 >= min_row_height // 2:
        bands.append((a0, rh))

    # Merge bands that are close (same system with underlines/lyrics noise)
    merged: list[tuple[int, int]] = []
    for b0, b1 in bands:
        if not merged:
            merged.append((b0, b1))
            continue
        p0, p1 = merged[-1]
        if b0 - p1 <= min_row_gap:
            merged[-1] = (p0, b1)
        else:
            merged.append((b0, b1))

    # Filter thin bands
    systems: list[StaffSystem] = []
    for i, (b0, b1) in enumerate(merged):
        if b1 - b0 < min_row_height:
            continue
        # Expand slightly for octave dots / underlines
        pad = max(4, int(0.15 * (b1 - b0)))
        sy0 = max(0, y0 + b0 - pad)
        sy1 = min(h, y0 + b1 + pad)
        systems.append(
            StaffSystem(
                index=len(systems),
                rect=Rect(float(x0), float(sy0), float(x1), float(sy1)),
                confidence=0.7,
            )
        )

    if not systems:
        warnings.append("L2: no staff bands; single system fallback")
        systems = [
            StaffSystem(
                index=0,
                rect=Rect(float(x0), float(y0), float(x1), float(y1)),
                confidence=0.35,
            )
        ]
    else:
        warnings.append(f"L2: detected {len(systems)} staff system(s)")
    return systems, warnings
