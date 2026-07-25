"""L3–L4: barlines + measure segmentation on each staff system (#58 / #66)."""

from __future__ import annotations

import cv2
import numpy as np

from app.pipeline.barlines import detect_barline_xs
from app.pipeline.structure.ir import MeasureLayout, Rect, StaffSystem


def segment_measures_on_systems(
    image_bgr: np.ndarray,
    systems: list[StaffSystem],
    *,
    min_measure_width: float = 24.0,
) -> tuple[list[StaffSystem], list[str]]:
    """For each system, detect vertical barlines and split into measures.

    **#66 follow-up**: a measure is a span **between consecutive barlines**.
    Do **not** invent measures from system left edge → first barline or
    last barline → system right edge (page/staff margins).
    """
    warnings: list[str] = []
    if image_bgr is None or image_bgr.size == 0:
        return systems, ["L3: empty image"]

    h, w = image_bgr.shape[:2]
    out: list[StaffSystem] = []

    for sys in systems:
        y0, y1 = sys.rect.y1, sys.rect.y2
        # Barlines restricted to this system band
        xs = detect_barline_xs(
            image_bgr,
            y_range=(y0, y1),
            min_gap=max(18.0, sys.rect.width * 0.03),
        )
        # Keep xs inside system x range with margin (drop edge noise)
        x_lo, x_hi = sys.rect.x1, sys.rect.x2
        xs = [x for x in xs if x_lo + 8 < x < x_hi - 8]
        xs = _dedup_xs(sorted(xs), min_gap=min_measure_width * 0.5)

        measures = _measures_between_barlines(
            xs,
            y0=y0,
            y1=y1,
            min_measure_width=min_measure_width,
        )

        if not measures:
            # Fallback: single measure spanning system (no usable bar pair)
            measures = [
                MeasureLayout(
                    index=0,
                    rect=Rect(sys.rect.x1, sys.rect.y1, sys.rect.x2, sys.rect.y2),
                    confidence=0.3,
                )
            ]
            if len(xs) < 2:
                warnings.append(
                    f"L3: system {sys.index} has {len(xs)} barline(s); "
                    "one measure fallback (need ≥2 barlines for split)"
                )
            else:
                warnings.append(
                    f"L3: system {sys.index} bar pairs too narrow; one measure"
                )

        sys2 = StaffSystem(
            index=sys.index,
            rect=sys.rect,
            measures=measures,
            barline_xs=xs,
            confidence=sys.confidence,
            extra=dict(sys.extra),
        )
        out.append(sys2)
        warnings.append(
            f"L3: system {sys.index} → {len(measures)} measure(s), "
            f"{len(xs)} barline(s) (between-barlines only)"
        )

    return out, warnings


def _dedup_xs(xs: list[float], *, min_gap: float) -> list[float]:
    if not xs:
        return []
    cleaned: list[float] = [xs[0]]
    for x in xs[1:]:
        if abs(x - cleaned[-1]) > min_gap:
            cleaned.append(x)
        else:
            cleaned[-1] = (cleaned[-1] + x) / 2.0
    return cleaned


def _measures_between_barlines(
    xs: list[float],
    *,
    y0: float,
    y1: float,
    min_measure_width: float,
) -> list[MeasureLayout]:
    """Build measures only between consecutive barlines (no outer margins)."""
    if len(xs) < 2:
        return []
    measures: list[MeasureLayout] = []
    for i in range(len(xs) - 1):
        left, right = xs[i], xs[i + 1]
        if right - left < min_measure_width:
            continue
        measures.append(
            MeasureLayout(
                index=len(measures),
                rect=Rect(left, y0, right, y1),
                barline_x_left=left,
                barline_x_right=right,
                confidence=0.7,
                extra={"segment": "between_barlines"},
            )
        )
    return measures


def estimate_uniform_measures(
    system: StaffSystem,
    n_measures: int,
) -> StaffSystem:
    """Optional helper: split a system into n equal-width measures."""
    if n_measures <= 0:
        return system
    w = system.rect.width
    measures: list[MeasureLayout] = []
    for i in range(n_measures):
        x1 = system.rect.x1 + i * w / n_measures
        x2 = system.rect.x1 + (i + 1) * w / n_measures
        measures.append(
            MeasureLayout(
                index=i,
                rect=Rect(x1, system.rect.y1, x2, system.rect.y2),
                confidence=0.35,
            )
        )
    return StaffSystem(
        index=system.index,
        rect=system.rect,
        measures=measures,
        barline_xs=list(system.barline_xs),
        confidence=system.confidence,
        extra=system.extra,
    )
