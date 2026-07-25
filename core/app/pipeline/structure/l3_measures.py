"""L3–L4: barlines + measure segmentation on each staff system (#58)."""

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
    """For each system, detect vertical barlines and split into measures."""
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
        # Keep xs inside system x range with margin
        x_lo, x_hi = sys.rect.x1, sys.rect.x2
        xs = [x for x in xs if x_lo + 8 < x < x_hi - 8]
        xs = sorted(xs)

        # Always include system edges as soft boundaries
        edges = [x_lo + 4.0] + xs + [x_hi - 4.0]
        # Dedup close edges
        cleaned: list[float] = []
        for x in edges:
            if not cleaned or abs(x - cleaned[-1]) > min_measure_width * 0.5:
                cleaned.append(x)
            else:
                cleaned[-1] = (cleaned[-1] + x) / 2.0

        measures: list[MeasureLayout] = []
        for i in range(len(cleaned) - 1):
            left, right = cleaned[i], cleaned[i + 1]
            if right - left < min_measure_width:
                continue
            measures.append(
                MeasureLayout(
                    index=len(measures),
                    rect=Rect(left, y0, right, y1),
                    barline_x_left=left if i > 0 else None,
                    barline_x_right=right if i < len(cleaned) - 2 else None,
                    confidence=0.65 if xs else 0.4,
                )
            )

        if not measures:
            # Fallback: single measure spanning system
            measures = [
                MeasureLayout(
                    index=0,
                    rect=Rect(sys.rect.x1, sys.rect.y1, sys.rect.x2, sys.rect.y2),
                    confidence=0.3,
                )
            ]
            warnings.append(f"L3: system {sys.index} has no barlines; one measure")

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
            f"{len(xs)} barline(s)"
        )

    return out, warnings


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
