"""L1: page-level region split — title / key-time / main score ROI (#58)."""

from __future__ import annotations

import cv2
import numpy as np

from app.pipeline.structure.ir import PageRegion, Rect, RegionRole


def detect_page_regions(
    image_bgr: np.ndarray,
    *,
    top_frac: float = 0.12,
    bottom_frac: float = 0.06,
) -> tuple[list[PageRegion], list[str]]:
    """Split page into title band, key/time band, and main score region.

    Geometry-first: horizontal ink projection finds the dense score body;
    top sparse band is title/meta.
    """
    warnings: list[str] = []
    if image_bgr is None or image_bgr.size == 0:
        return [], ["empty image for L1"]

    h, w = image_bgr.shape[:2]
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    # Row ink density
    row_ink = (bw > 0).sum(axis=1).astype(np.float32)
    if row_ink.max() <= 0:
        warnings.append("L1: no ink detected; full page as score")
        return [
            PageRegion(
                role=RegionRole.score,
                rect=Rect(0, 0, float(w), float(h)),
                confidence=0.3,
            )
        ], warnings

    thr = max(row_ink.max() * 0.12, w * 0.01)
    active = row_ink >= thr
    # First / last dense rows
    ys = np.where(active)[0]
    if len(ys) == 0:
        y0, y1 = int(h * top_frac), int(h * (1 - bottom_frac))
    else:
        y0, y1 = int(ys[0]), int(ys[-1]) + 1

    # Title: above first dense band, but at least top_frac if score starts late
    title_y1 = max(int(h * 0.04), min(y0, int(h * top_frac)))
    # Key/time often sits just under title — thin band before dense score
    meta_y0 = title_y1
    meta_y1 = min(h, max(title_y1 + 1, y0))
    score_y0 = meta_y1
    score_y1 = min(h, max(score_y0 + 8, y1))

    regions = [
        PageRegion(
            role=RegionRole.title,
            rect=Rect(0, 0, float(w), float(title_y1)),
            confidence=0.6,
        ),
        PageRegion(
            role=RegionRole.key_time,
            rect=Rect(0, float(meta_y0), float(w), float(meta_y1)),
            confidence=0.55,
        ),
        PageRegion(
            role=RegionRole.score,
            rect=Rect(0, float(score_y0), float(w), float(score_y1)),
            confidence=0.75,
        ),
    ]
    return regions, warnings
