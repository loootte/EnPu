"""L3 split-line model (#85): ordered vertical splits on an L2 row.

Coordinates use **full-image pixel x** (same space as Rect / overlays).
Measures are always derived: [x_left, ...splits, x_right] × L2 y-band.
"""

from __future__ import annotations

from typing import Any

from app.pipeline.structure.ir import MeasureLayout, Rect, SplitLine


def normalize_splits(
    xs: list[float] | list[SplitLine],
    *,
    x_left: float,
    x_right: float,
    min_gap: float = 8.0,
    default_source: str = "detect",
) -> list[SplitLine]:
    """Sort, clamp interior splits to (x_left, x_right), dedupe by min_gap."""
    if x_right <= x_left + min_gap:
        return []

    raw: list[SplitLine] = []
    for i, item in enumerate(xs):
        if isinstance(item, SplitLine):
            x = float(item.x)
            src = item.source
            sid = item.split_id or f"s{i}"
            conf = item.confidence
            extra = dict(item.extra or {})
        else:
            x = float(item)
            src = default_source
            sid = f"s{i}"
            conf = 0.7
            extra = {}
        # Strictly interior
        if x <= x_left + 1e-6 or x >= x_right - 1e-6:
            continue
        raw.append(
            SplitLine(x=x, split_id=sid, source=src, confidence=conf, extra=extra)
        )

    raw.sort(key=lambda s: s.x)
    if not raw:
        return []

    cleaned: list[SplitLine] = [raw[0]]
    for s in raw[1:]:
        if s.x - cleaned[-1].x >= min_gap:
            cleaned.append(s)
        else:
            # keep average, prefer user source
            prev = cleaned[-1]
            nx = 0.5 * (prev.x + s.x)
            src = "user" if "user" in (prev.source, s.source) else prev.source
            cleaned[-1] = SplitLine(
                x=nx,
                split_id=prev.split_id or s.split_id,
                source=src,
                confidence=max(prev.confidence, s.confidence),
                extra={**prev.extra, **s.extra},
            )
    # Re-id sequentially for stability
    for i, s in enumerate(cleaned):
        if not s.split_id or s.split_id.startswith("s"):
            s.split_id = f"s{i}"
    return cleaned


def edge_xs(
    splits: list[SplitLine] | list[float],
    *,
    x_left: float,
    x_right: float,
) -> list[float]:
    """``[x_left, ...interior splits, x_right]`` strictly increasing."""
    interiors: list[float] = []
    for s in splits:
        x = float(s.x if isinstance(s, SplitLine) else s)
        if x_left + 1e-6 < x < x_right - 1e-6:
            interiors.append(x)
    interiors = sorted(set(interiors))
    return [float(x_left), *interiors, float(x_right)]


def splits_to_measures(
    *,
    x_left: float,
    x_right: float,
    y_top: float,
    y_bot: float,
    splits: list[SplitLine] | list[float],
    min_measure_width: float = 4.0,
    measure_source: str = "l3_split",
) -> list[MeasureLayout]:
    """Derive measure rects from L2 y-band and ordered vertical splits (#85).

    Endpoints are always L2 left/right bounds. Interior ``splits`` divide the row.
    """
    xs = edge_xs(splits, x_left=x_left, x_right=x_right)
    # No interior splits → single whole-line measure
    if len(xs) <= 2:
        return [
            MeasureLayout(
                index=0,
                rect=Rect(x_left, y_top, x_right, y_bot),
                barline_x_left=x_left,
                barline_x_right=x_right,
                confidence=0.25,
                extra={
                    "segment": "whole_line",
                    "measure_source": "whole_line",
                    "closed": True,
                    "from_splits": True,
                },
            )
        ]

    measures: list[MeasureLayout] = []
    for i in range(len(xs) - 1):
        left, right = xs[i], xs[i + 1]
        if right - left < min_measure_width:
            continue
        measures.append(
            MeasureLayout(
                index=len(measures),
                rect=Rect(left, y_top, right, y_bot),
                barline_x_left=left,
                barline_x_right=right,
                confidence=0.75,
                extra={
                    "segment": "split_derived",
                    "measure_source": measure_source,
                    "closed": True,
                    "from_splits": True,
                },
            )
        )
    if not measures:
        measures.append(
            MeasureLayout(
                index=0,
                rect=Rect(x_left, y_top, x_right, y_bot),
                barline_x_left=x_left,
                barline_x_right=x_right,
                confidence=0.25,
                extra={
                    "segment": "whole_line",
                    "measure_source": "whole_line",
                    "closed": True,
                    "from_splits": True,
                },
            )
        )
    return measures


def measures_to_splits(
    measures: list[MeasureLayout],
    *,
    x_left: float | None = None,
    x_right: float | None = None,
    min_gap: float = 8.0,
) -> list[SplitLine]:
    """Migrate old measure-rect L3 into interior splits (shared boundaries)."""
    if not measures:
        return []
    ordered = sorted(measures, key=lambda m: m.rect.cx)
    if x_left is None:
        x_left = min(m.rect.x1 for m in ordered)
    if x_right is None:
        x_right = max(m.rect.x2 for m in ordered)

    # Candidate split xs = interior edges (right of each measure except last,
    # or average of adjacent touching edges)
    candidates: list[float] = []
    for i in range(len(ordered) - 1):
        a, b = ordered[i], ordered[i + 1]
        # shared boundary estimate
        x = 0.5 * (a.rect.x2 + b.rect.x1)
        candidates.append(x)
        # also explicit left/right if barline metadata present
        if a.barline_x_right is not None:
            candidates.append(float(a.barline_x_right))
        if b.barline_x_left is not None:
            candidates.append(float(b.barline_x_left))

    return normalize_splits(
        candidates,
        x_left=float(x_left),
        x_right=float(x_right),
        min_gap=min_gap,
        default_source="migrate",
    )


def move_split(
    splits: list[SplitLine],
    split_id: str,
    new_x: float,
    *,
    x_left: float,
    x_right: float,
    min_gap: float = 8.0,
) -> list[SplitLine]:
    """Move one split by id; clamp between neighbors and row bounds."""
    xs = normalize_splits(splits, x_left=x_left, x_right=x_right, min_gap=min_gap)
    idx = next((i for i, s in enumerate(xs) if s.split_id == split_id), None)
    if idx is None:
        return xs
    lo = x_left + min_gap if idx == 0 else xs[idx - 1].x + min_gap
    hi = x_right - min_gap if idx == len(xs) - 1 else xs[idx + 1].x - min_gap
    if hi <= lo:
        return xs
    nx = max(lo, min(hi, float(new_x)))
    xs[idx] = SplitLine(
        x=nx,
        split_id=xs[idx].split_id,
        source="user",
        confidence=1.0,
        extra=dict(xs[idx].extra or {}),
    )
    return normalize_splits(xs, x_left=x_left, x_right=x_right, min_gap=min_gap)


def insert_split(
    splits: list[SplitLine],
    x: float,
    *,
    x_left: float,
    x_right: float,
    min_gap: float = 8.0,
) -> list[SplitLine]:
    """Insert a user split at x."""
    xs = list(splits) + [
        SplitLine(x=float(x), split_id="new", source="user", confidence=1.0)
    ]
    return normalize_splits(xs, x_left=x_left, x_right=x_right, min_gap=min_gap)


def delete_split(
    splits: list[SplitLine],
    split_id: str,
    *,
    x_left: float,
    x_right: float,
    min_gap: float = 8.0,
) -> list[SplitLine]:
    xs = [s for s in splits if s.split_id != split_id]
    return normalize_splits(xs, x_left=x_left, x_right=x_right, min_gap=min_gap)
