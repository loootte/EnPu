"""Convert learned systems + splits → PageLayout skeleton (#104)."""

from __future__ import annotations

from typing import Any

from app.pipeline.structure.ir import (
    PageLayout,
    PageRegion,
    Rect,
    RegionRole,
    SplitLine,
    StaffSystem,
)
from app.pipeline.structure.splits import normalize_splits, splits_to_measures


def systems_splits_to_page_layout(
    *,
    width: int,
    height: int,
    system_boxes: list[dict[str, float]],
    splits_per_system: list[list[float]],
    score_region: Rect | None = None,
    title_box: Rect | None = None,
    key_time_box: Rect | None = None,
    warnings: list[str] | None = None,
    engine_meta: dict[str, Any] | None = None,
    min_gap: float = 6.0,
    min_measure_width: float = 4.0,
) -> PageLayout:
    """Build PageLayout with L1 regions + L2 systems + L3 splits/measures."""
    regions: list[PageRegion] = []
    if title_box is not None:
        regions.append(
            PageRegion(role=RegionRole.title, rect=title_box, confidence=0.6)
        )
    if key_time_box is not None:
        regions.append(
            PageRegion(role=RegionRole.key_time, rect=key_time_box, confidence=0.55)
        )
    if score_region is None:
        score_region = Rect(0, 0, float(width), float(height))
    regions.append(
        PageRegion(role=RegionRole.score, rect=score_region, confidence=0.75)
    )

    systems: list[StaffSystem] = []
    for i, box in enumerate(system_boxes):
        rect = Rect(
            float(box["x1"]),
            float(box["y1"]),
            float(box["x2"]),
            float(box["y2"]),
        )
        raw_xs = splits_per_system[i] if i < len(splits_per_system) else []
        raw_splits = [
            SplitLine(x=float(x), split_id=f"s{i}-{j}", source="detect")
            for j, x in enumerate(raw_xs)
        ]
        splits = normalize_splits(
            raw_splits,
            x_left=rect.x1,
            x_right=rect.x2,
            min_gap=min_gap,
            default_source="detect",
        )
        measures = splits_to_measures(
            x_left=rect.x1,
            x_right=rect.x2,
            y_top=rect.y1,
            y_bot=rect.y2,
            splits=splits,
            min_measure_width=min_measure_width,
            measure_source="l3_split",
        )
        systems.append(
            StaffSystem(
                index=i,
                rect=rect,
                measures=measures,
                barline_xs=[s.x for s in splits],
                splits=splits,
                confidence=0.7,
                extra={"source": "learned_l1l3", "engine": "learned"},
            )
        )

    return PageLayout(
        width=width,
        height=height,
        regions=regions,
        systems=systems,
        warnings=list(warnings or []),
        debug={"l1l3_engine": "learned", **(engine_meta or {})},
    )
