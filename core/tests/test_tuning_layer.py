"""Tests for single-layer tune loop (#89)."""

from __future__ import annotations

import numpy as np
import pytest

from app.evaluation.types import Box
from app.tuning.layer_objective import layer_loss, match_boxes
from app.tuning.params import (
    L3Params,
    get_l3_params,
    reset_layer_params,
    set_layer_params,
)
from app.tuning.search import tune_layer


def test_match_boxes_basic() -> None:
    gt = [Box(0, 0, 10, 10), Box(20, 0, 30, 10)]
    pred = [Box(1, 1, 9, 9), Box(50, 0, 60, 10)]
    m = match_boxes(pred, gt, iou_threshold=0.3)
    assert m.tp == 1
    assert m.fp == 1
    assert m.fn == 1


def test_layer_loss_perfect() -> None:
    boxes = [Box(0, 0, 10, 10), Box(20, 0, 30, 10)]
    loss = layer_loss(boxes, boxes)
    assert loss.loss < 0.05
    assert loss.score > 0.9
    assert loss.match.tp == 2


def test_set_get_l3_params() -> None:
    reset_layer_params()
    set_layer_params("l3", {"min_measure_width": 33.0}, merge=True)
    p = get_l3_params()
    assert p.min_measure_width == pytest.approx(33.0)
    reset_layer_params("l3")
    p2 = get_l3_params()
    assert p2.min_measure_width == pytest.approx(24.0)


def _synthetic_staff() -> np.ndarray:
    img = np.full((120, 400, 3), 255, dtype=np.uint8)
    img[40:90, 20:380] = 245
    for x in (60, 150, 240, 330):
        img[45:85, x : x + 2] = 0
    for x in (90, 180, 270):
        img[55:75, x : x + 10] = 0
    return img


def test_tune_layer_l3_reproducible() -> None:
    reset_layer_params()
    img = _synthetic_staff()
    # GT = three measure boxes roughly between bars
    gt_boxes = [
        Box(60, 40, 150, 90, kind="measure"),
        Box(150, 40, 240, 90, kind="measure"),
        Box(240, 40, 330, 90, kind="measure"),
    ]
    gt = {
        "pitch_sequence": [],
        "measure_count": 3,
        "geometry": {"L3": gt_boxes},
        "barline_xs": [60.0, 150.0, 240.0, 330.0],
    }
    r1 = tune_layer(
        img,
        gt=gt,
        layer="l3",
        max_trials=12,
        max_seconds=30,
        seed=7,
        method="random",
        apply_best=False,
    )
    r2 = tune_layer(
        img,
        gt=gt,
        layer="l3",
        max_trials=12,
        max_seconds=30,
        seed=7,
        method="random",
        apply_best=False,
    )
    assert r1.n_trials == r2.n_trials
    assert r1.best_loss == pytest.approx(r2.best_loss, rel=1e-6, abs=1e-6)
    assert r1.best_params["min_measure_width"] == pytest.approx(
        r2.best_params["min_measure_width"], rel=1e-6, abs=1e-6
    )
    # GT never written into params
    assert "geometry" not in r1.best_params
    assert r1.improved is True
    assert r1.best_loss <= r1.baseline_loss + 1e-9


def test_l3_params_affect_segmentation() -> None:
    """Smoke: changing min_measure_width can change measure count."""
    from app.pipeline.structure.ir import Rect, StaffSystem
    from app.pipeline.structure.l3_measures import segment_measures_on_systems

    img = _synthetic_staff()
    systems = [StaffSystem(index=0, rect=Rect(20, 35, 380, 95), confidence=0.8)]
    s1, _ = segment_measures_on_systems(
        img, systems, params={"min_measure_width": 16.0}
    )
    s2, _ = segment_measures_on_systems(
        img,
        [StaffSystem(index=0, rect=Rect(20, 35, 380, 95), confidence=0.8)],
        params={"min_measure_width": 200.0},
    )
    # Huge min width should collapse / whole-line fewer splits
    assert len(s1[0].measures) >= len(s2[0].measures)
