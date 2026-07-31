"""L3: barlines + measure segmentation on each staff system (#58 / #66 / #84).

#84 focus:
- Detect barlines inside the **melody (pitch-digit) band**, not full staff height
- Suppress silent whole-line single measure; tag ``measure_source``
- Soft gap fallbacks when graphic bars are sparse
- Simple cross-line open-measure merge (P1)
"""

from __future__ import annotations

import uuid

import numpy as np

from app.pipeline.barlines import (
    detect_barline_xs,
    estimate_melody_band,
    gap_soft_bar_xs,
)
from app.pipeline.structure.ir import MeasureLayout, Rect, StaffSystem

# measure_source values (#84)
SRC_L3_BARLINE = "l3_barline"
SRC_FALLBACK_GAP = "fallback_gap"
SRC_WHOLE_LINE = "whole_line"
SRC_CROSS_LINE = "cross_line"


def segment_measures_on_systems(
    image_bgr: np.ndarray,
    systems: list[StaffSystem],
    *,
    min_measure_width: float | None = None,
    enable_cross_line: bool | None = None,
    params: dict | None = None,
) -> tuple[list[StaffSystem], list[str]]:
    """For each system, detect vertical barlines and split into measures.

    **#66**: a measure is a span **between consecutive barlines** (no outer
    page-margin pads) when ≥2 graphic bars exist.

    **#84**: barlines are sought primarily in the estimated melody band;
    soft gap cut + explicit ``measure_source`` when bars are insufficient.

    **#89**: thresholds from ``params`` / runtime L3 store when not passed.
    """
    from app.tuning.params import L3Params, get_l3_params

    base = get_l3_params()
    if params:
        base = L3Params.from_dict({**base.to_dict(), **params})
    if min_measure_width is not None:
        base.min_measure_width = float(min_measure_width)
    if enable_cross_line is not None:
        base.enable_cross_line = bool(enable_cross_line)

    warnings: list[str] = []
    if image_bgr is None or image_bgr.size == 0:
        return systems, ["L3: empty image"]

    out: list[StaffSystem] = []

    for sys in systems:
        sys2, wsys = _segment_one_system(
            image_bgr,
            sys,
            p=base,
        )
        out.append(sys2)
        warnings.extend(wsys)

    if base.enable_cross_line and len(out) >= 2:
        out, w_cross = _merge_cross_line_opens(out)
        warnings.extend(w_cross)

    return out, warnings


def _segment_one_system(
    image_bgr: np.ndarray,
    sys: StaffSystem,
    *,
    p: "object",
) -> tuple[StaffSystem, list[str]]:
    from app.tuning.params import L3Params

    if not isinstance(p, L3Params):
        p = L3Params.from_dict(dict(p) if p else None)  # type: ignore[arg-type]

    min_measure_width = float(p.min_measure_width)
    warnings: list[str] = []
    y0, y1 = sys.rect.y1, sys.rect.y2
    x_lo, x_hi = sys.rect.x1, sys.rect.x2

    # --- #84: melody band (pitch digits), not full system incl. lyrics ---
    my0, my1 = estimate_melody_band(
        image_bgr,
        (sys.rect.x1, sys.rect.y1, sys.rect.x2, sys.rect.y2),
    )
    # Clamp into system
    my0 = max(y0, my0)
    my1 = min(y1, my1)
    if my1 <= my0 + 4:
        my0, my1 = y0, y1
    warnings.append(
        f"L3: system {sys.index} melody_band y=[{my0:.0f},{my1:.0f}] "
        f"(system y=[{y0:.0f},{y1:.0f}])"
    )

    min_gap = max(float(p.min_gap_floor), sys.rect.width * float(p.min_gap_ratio))
    dedup = min_measure_width * float(p.dedup_gap_factor)

    # Graphic bars inside melody band first
    xs_mel = detect_barline_xs(
        image_bgr,
        y_range=(my0, my1),
        min_gap=min_gap,
        melody_mode=True,
    )
    # Full-system pass as weak supplement (double bars / tall printed lines)
    xs_full = detect_barline_xs(
        image_bgr,
        y_range=(y0, y1),
        min_gap=min_gap,
        melody_mode=False,
    )

    xs = _merge_unique_xs(xs_mel + xs_full, min_gap=dedup)
    # Keep xs inside system x range with margin
    xs = [x for x in xs if x_lo + 8 < x < x_hi - 8]
    xs = _dedup_xs(sorted(xs), min_gap=dedup)

    measures: list[MeasureLayout] = []
    source = SRC_L3_BARLINE

    if len(xs) >= 2:
        measures = _measures_between_barlines(
            xs,
            y0=y0,
            y1=y1,
            min_measure_width=min_measure_width,
            source=SRC_L3_BARLINE,
        )

    # #84: not enough bars → soft gap cut inside melody band
    if len(measures) < 2 and p.soft_gap_enabled:
        soft_xs = gap_soft_bar_xs(
            image_bgr,
            y_range=(my0, my1),
            x_range=(x_lo, x_hi),
            min_gap=max(min_gap, min_measure_width),
        )
        soft_xs = [x for x in soft_xs if x_lo + 8 < x < x_hi - 8]
        # Combine graphic bars with soft gaps as split points
        split_xs = _dedup_xs(sorted(set(xs + soft_xs)), min_gap=min_measure_width * 0.45)
        # Need endpoints for soft segmentation: left/right content bounds
        if len(split_xs) >= 1:
            # Add virtual ends at content margins (inner 4%) so soft cuts work
            ends = [x_lo + 4.0, x_hi - 4.0]
            all_xs = _dedup_xs(sorted(ends + split_xs), min_gap=min_measure_width * 0.4)
            soft_measures = _measures_between_barlines(
                all_xs,
                y0=y0,
                y1=y1,
                min_measure_width=min_measure_width,
                source=SRC_FALLBACK_GAP,
            )
            if len(soft_measures) > len(measures):
                measures = soft_measures
                xs = all_xs
                source = SRC_FALLBACK_GAP
                warnings.append(
                    f"L3: system {sys.index} soft-gap split → "
                    f"{len(measures)} measure(s) (measure_source={source})"
                )

    if not measures:
        # Last resort: whole line, low confidence, explicit tag
        measures = [
            MeasureLayout(
                index=0,
                rect=Rect(sys.rect.x1, sys.rect.y1, sys.rect.x2, sys.rect.y2),
                confidence=0.25,
                extra={
                    "segment": "whole_line",
                    "measure_source": SRC_WHOLE_LINE,
                    "closed": True,
                    "parts": [
                        {
                            "line_id": sys.index,
                            "x0": sys.rect.x1,
                            "x1": sys.rect.x2,
                            "y0": sys.rect.y1,
                            "y1": sys.rect.y2,
                        }
                    ],
                },
            )
        ]
        source = SRC_WHOLE_LINE
        if len(xs) < 2:
            warnings.append(
                f"L3: system {sys.index} has {len(xs)} barline(s); "
                f"whole_line fallback (measure_source={SRC_WHOLE_LINE})"
            )
        else:
            warnings.append(
                f"L3: system {sys.index} bar pairs too narrow; "
                f"whole_line fallback (measure_source={SRC_WHOLE_LINE})"
            )
    else:
        # Ensure every measure carries source + parts
        for m in measures:
            m.extra.setdefault("measure_source", source)
            m.extra.setdefault("closed", True)
            m.extra.setdefault(
                "parts",
                [
                    {
                        "line_id": sys.index,
                        "x0": m.rect.x1,
                        "x1": m.rect.x2,
                        "y0": m.rect.y1,
                        "y1": m.rect.y2,
                    }
                ],
            )

    # Open trailing only when ink exists after last bar (not empty margin) (#84 / #66)
    if (
        p.open_trailing_enabled
        and measures
        and source == SRC_L3_BARLINE
        and len(xs) >= 2
    ):
        last_bar = xs[-1]
        if x_hi - last_bar > min_measure_width * 1.2 and _has_ink_in_band(
            image_bgr,
            x0=last_bar + 2,
            x1=x_hi - 2,
            y0=my0,
            y1=my1,
            min_pixels=12,
        ):
            stub = MeasureLayout(
                index=len(measures),
                rect=Rect(last_bar, y0, x_hi, y1),
                barline_x_left=last_bar,
                barline_x_right=None,
                confidence=0.4,
                extra={
                    "segment": "open_trailing",
                    "measure_source": SRC_L3_BARLINE,
                    "closed": False,
                    "parts": [
                        {
                            "line_id": sys.index,
                            "x0": last_bar,
                            "x1": x_hi,
                            "y0": y0,
                            "y1": y1,
                        }
                    ],
                },
            )
            measures.append(stub)
            warnings.append(
                f"L3: system {sys.index} open trailing after last bar "
                f"(for cross-line)"
            )

    sys2 = StaffSystem(
        index=sys.index,
        rect=sys.rect,
        measures=measures,
        barline_xs=xs,
        confidence=sys.confidence,
        extra={
            **dict(sys.extra),
            "melody_band": [my0, my1],
            "measure_source": source,
        },
    )
    if source == SRC_L3_BARLINE and len(measures) >= 1:
        warnings.append(
            f"L3: system {sys.index} → {len(measures)} measure(s), "
            f"{len(xs)} barline(s) (between-barlines only; "
            f"measure_source={source})"
        )
    elif source != SRC_WHOLE_LINE:
        warnings.append(
            f"L3: system {sys.index} → {len(measures)} measure(s), "
            f"{len(xs)} barline(s) (measure_source={source})"
        )
    return sys2, warnings


def _merge_cross_line_opens(
    systems: list[StaffSystem],
) -> tuple[list[StaffSystem], list[str]]:
    """Merge open trailing measure of line i with open/leading of line i+1 (#84 P1).

    Conditions (all required):
    - prev last measure has closed=False OR no right barline
    - next first measure is whole_line OR starts without left bar near system left
    - both low-confidence soft or open stubs

    Result: same measure_id / parts[] spanning two lines; next line loses
    its leading stub (merged away).
    """
    warnings: list[str] = []
    if len(systems) < 2:
        return systems, warnings

    # Work on a shallow copy of measure lists
    systems = [
        StaffSystem(
            index=s.index,
            rect=s.rect,
            measures=list(s.measures),
            barline_xs=list(s.barline_xs),
            confidence=s.confidence,
            extra=dict(s.extra),
        )
        for s in systems
    ]

    for i in range(len(systems) - 1):
        prev, nxt = systems[i], systems[i + 1]
        if not prev.measures or not nxt.measures:
            continue
        last = prev.measures[-1]
        first = nxt.measures[0]
        last_open = (
            last.extra.get("closed") is False
            or last.barline_x_right is None
            or last.extra.get("segment") == "open_trailing"
        )
        first_open = (
            first.extra.get("measure_source") == SRC_WHOLE_LINE
            or first.barline_x_left is None
            or (
                first.barline_x_left is not None
                and abs(first.barline_x_left - nxt.rect.x1) < 12
            )
        )
        # Prefer merging only when last is explicitly open trailing
        if not last_open:
            continue
        if last.extra.get("segment") != "open_trailing" and last.extra.get(
            "measure_source"
        ) not in {SRC_WHOLE_LINE, SRC_FALLBACK_GAP}:
            # Avoid merging solid barline-closed measures
            if last.barline_x_right is not None and last.extra.get("closed", True):
                continue
        if not first_open and first.extra.get("measure_source") == SRC_L3_BARLINE:
            # next starts with a real closed measure → do not merge
            if first.barline_x_left is not None and first.extra.get("closed", True):
                continue

        mid = str(uuid.uuid4())[:8]
        parts = list(last.extra.get("parts") or [])
        parts.extend(list(first.extra.get("parts") or []))
        # Expand last measure extra to multi-part; drop first from next
        last.extra["parts"] = parts
        last.extra["closed"] = bool(first.extra.get("closed", True))
        last.extra["measure_source"] = SRC_CROSS_LINE
        last.extra["measure_id"] = mid
        last.extra["cross_line"] = True
        last.confidence = min(last.confidence, first.confidence, 0.55)
        # Union bbox for primary rect stays on prev line part only (draw/L4
        # still use per-part via extra.parts); keep last.rect as first part
        nxt.measures = nxt.measures[1:]
        # Reindex
        for j, m in enumerate(prev.measures):
            m.index = j
        for j, m in enumerate(nxt.measures):
            m.index = j
        warnings.append(
            f"L3: cross_line merge system {prev.index}→{nxt.index} "
            f"measure_id={mid} (measure_source={SRC_CROSS_LINE})"
        )

    return systems, warnings


def _has_ink_in_band(
    image_bgr: np.ndarray,
    *,
    x0: float,
    x1: float,
    y0: float,
    y1: float,
    min_pixels: int = 12,
) -> bool:
    """True if ROI has enough **dark** content (not light staff wash / empty margin)."""
    import cv2

    h, w = image_bgr.shape[:2]
    xa, xb = max(0, int(x0)), min(w, int(x1))
    ya, yb = max(0, int(y0)), min(h, int(y1))
    if xb <= xa + 1 or yb <= ya + 1:
        return False
    gray = cv2.cvtColor(image_bgr[ya:yb, xa:xb], cv2.COLOR_BGR2GRAY)
    # Fixed dark threshold: ignore light gray staff fill (e.g. 245)
    dark = gray < 80
    return int(dark.sum()) >= min_pixels


def _merge_unique_xs(xs: list[float], *, min_gap: float) -> list[float]:
    return _dedup_xs(sorted(xs), min_gap=min_gap)


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
    source: str = SRC_L3_BARLINE,
) -> list[MeasureLayout]:
    """Build measures only between consecutive barlines (no outer margins)."""
    if len(xs) < 2:
        return []
    measures: list[MeasureLayout] = []
    for i in range(len(xs) - 1):
        left, right = xs[i], xs[i + 1]
        if right - left < min_measure_width:
            continue
        conf = 0.7 if source == SRC_L3_BARLINE else 0.45
        measures.append(
            MeasureLayout(
                index=len(measures),
                rect=Rect(left, y0, right, y1),
                barline_x_left=left,
                barline_x_right=right,
                confidence=conf,
                extra={
                    "segment": (
                        "between_barlines"
                        if source == SRC_L3_BARLINE
                        else "soft_gap"
                    ),
                    "measure_source": source,
                    "closed": True,
                },
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
                extra={"measure_source": "uniform", "closed": True},
            )
        )
    return StaffSystem(
        index=system.index,
        rect=system.rect,
        measures=measures,
        barline_xs=list(system.barline_xs),
        confidence=system.confidence,
        extra=dict(system.extra),
    )
