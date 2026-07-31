"""L3 split-line model tests (#85)."""

from __future__ import annotations

import numpy as np
import pytest

from app.pipeline.structure.ir import MeasureLayout, Rect, StaffSystem
from app.pipeline.structure.l3_measures import segment_measures_on_systems
from app.pipeline.structure.ir import SplitLine
from app.pipeline.structure.splits import (
    delete_split,
    insert_split,
    measures_to_splits,
    move_split,
    normalize_splits,
    splits_to_measures,
)


def test_splits_to_measures_basic() -> None:
    splits = [SplitLine(x=100), SplitLine(x=200), SplitLine(x=300)]
    ms = splits_to_measures(
        x_left=20,
        x_right=400,
        y_top=10,
        y_bot=50,
        splits=splits,
        min_measure_width=4,
    )
    # 3 interiors → 4 measures with L2 endpoints
    assert len(ms) == 4
    assert ms[0].rect.x1 == pytest.approx(20)
    assert ms[0].rect.x2 == pytest.approx(100)
    assert ms[-1].rect.x2 == pytest.approx(400)
    # no overlap
    for i in range(len(ms) - 1):
        assert ms[i].rect.x2 <= ms[i + 1].rect.x1 + 1e-6


def test_splits_empty_whole_line() -> None:
    ms = splits_to_measures(
        x_left=0, x_right=100, y_top=0, y_bot=20, splits=[], min_measure_width=4
    )
    assert len(ms) == 1
    assert ms[0].extra.get("measure_source") == "whole_line"


def test_normalize_dedupes() -> None:
    xs = normalize_splits(
        [50, 52, 100],
        x_left=0,
        x_right=200,
        min_gap=8,
    )
    assert len(xs) == 2
    assert xs[0].x == pytest.approx(51.0)


def test_move_split_clamps_neighbors() -> None:
    splits = [
        SplitLine(x=100, split_id="a"),
        SplitLine(x=200, split_id="b"),
    ]
    out = move_split(splits, "a", 190, x_left=0, x_right=300, min_gap=10)
    a = next(s for s in out if s.split_id == "a")
    b = next(s for s in out if s.split_id == "b")
    assert a.x < b.x
    assert a.source == "user"


def test_insert_delete_split() -> None:
    splits = [SplitLine(x=100, split_id="a")]
    splits = insert_split(splits, 150, x_left=0, x_right=300, min_gap=8)
    assert len(splits) == 2
    mid = splits[1].split_id
    splits = delete_split(splits, mid, x_left=0, x_right=300)
    assert len(splits) == 1


def test_measures_to_splits_migrate() -> None:
    ms = [
        MeasureLayout(0, Rect(10, 0, 50, 20)),
        MeasureLayout(1, Rect(50, 0, 100, 20)),
        MeasureLayout(2, Rect(100, 0, 160, 20)),
    ]
    splits = measures_to_splits(ms, x_left=10, x_right=160, min_gap=4)
    assert len(splits) >= 2
    ms2 = splits_to_measures(
        x_left=10, x_right=160, y_top=0, y_bot=20, splits=splits, min_measure_width=4
    )
    assert len(ms2) == len(splits) + 1


def test_segment_uses_split_model() -> None:
    """Detected bars become interior splits; measures = n_split+1 with L2 ends."""
    h, w = 120, 400
    img = np.full((h, w, 3), 255, dtype=np.uint8)
    img[40:90, 20:380] = 245
    bar_xs = [60, 150, 240, 330]
    for x in bar_xs:
        img[42:88, x : x + 2] = 0
    systems = [StaffSystem(index=0, rect=Rect(10, 35, 390, 95), confidence=0.8)]
    systems, warnings = segment_measures_on_systems(img, systems)
    assert len(systems) == 1
    sys = systems[0]
    assert getattr(sys, "splits", None) is not None
    assert len(sys.splits) >= 3
    # derived measures: interiors + endpoints
    assert len(sys.measures) == len(sys.splits) + 1
    assert any("split" in w.lower() or "measure" in w.lower() for w in warnings)
    # first measure starts at L2 left, last ends at L2 right
    assert sys.measures[0].rect.x1 == pytest.approx(sys.rect.x1)
    assert sys.measures[-1].rect.x2 == pytest.approx(sys.rect.x2)
