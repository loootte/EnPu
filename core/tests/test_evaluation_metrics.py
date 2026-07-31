"""Unit tests for layered evaluation metrics (#86)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.evaluation.compare import compare_sample
from app.evaluation.extract import PredGeometry
from app.evaluation.gt_loader import load_ground_truth, load_layer_geometry
from app.evaluation.metrics import box_match_metrics, count_metrics, iou, pitch_sequence_metrics
from app.evaluation.types import Box
from app.main import app

client = TestClient(app)
REPO = Path(__file__).resolve().parents[2]
EVAL = REPO / "samples" / "eval"


def test_iou_basic() -> None:
    a = Box(0, 0, 10, 10)
    b = Box(0, 0, 10, 10)
    assert iou(a, b) == pytest.approx(1.0)
    c = Box(5, 0, 15, 10)
    assert 0.3 < iou(a, c) < 0.4


def test_box_match_perfect() -> None:
    gt = [Box(0, 0, 10, 10, kind="measure"), Box(20, 0, 30, 10, kind="measure")]
    pred = [Box(0, 0, 10, 10, kind="measure"), Box(20, 0, 30, 10, kind="measure")]
    m = box_match_metrics(gt, pred, layer="L3", iou_threshold=0.5)
    assert m.tp == 2 and m.fp == 0 and m.fn == 0
    assert m.f1 == pytest.approx(1.0)


def test_box_match_fp_fn() -> None:
    gt = [Box(0, 0, 10, 10)]
    pred = [Box(50, 50, 60, 60), Box(0, 0, 10, 10)]
    m = box_match_metrics(gt, pred, layer="L3")
    assert m.tp == 1 and m.fp == 1 and m.fn == 0


def test_count_metrics() -> None:
    m = count_metrics(layer="L3", n_gt=4, n_pred=3)
    assert m.tp == 3 and m.fp == 0 and m.fn == 1
    assert m.extra["abs_delta"] == 1


def test_pitch_sequence_metrics() -> None:
    m = pitch_sequence_metrics(["1", "2", "3", "5"], ["1", "2", "3", "5"], layer="L5")
    assert m.f1 == pytest.approx(1.0)
    m2 = pitch_sequence_metrics(["1", "2", "3"], ["1", "9", "3"], layer="L5")
    assert m2.extra["lcs"] == 2
    assert m2.f1 > 0.5


def test_compare_sample_score_only_gt() -> None:
    gt = {
        "pitch_sequence": ["1", "2", "3"],
        "measure_count": 2,
        "system_count": 1,
        "geometry": {},
        "barline_xs": [],
    }
    pred = PredGeometry(
        layers={
            "L1": [Box(0, 0, 100, 100, kind="score")],
            "L2": [Box(0, 20, 100, 40, kind="system")],
            "L3": [Box(0, 20, 40, 40), Box(40, 20, 80, 40)],
            "L4": [
                Box(5, 22, 15, 38, kind="pitch"),
                Box(20, 22, 30, 38, kind="pitch"),
                Box(50, 22, 60, 38, kind="pitch"),
            ],
        },
        barline_xs=[0, 40, 80],
    )
    sm = compare_sample(
        sample_id="t1",
        gt=gt,
        pred=pred,
        pred_pitch=["1", "2", "3"],
        pred_measure_count=2,
        pred_system_count=1,
    )
    assert "L3" in sm.layers and sm.layers["L3"].mode == "count"
    assert sm.layers["L3"].f1 == pytest.approx(1.0)
    assert sm.layers["L5"].f1 == pytest.approx(1.0)
    assert sm.layers["L3"].extra.get("abs_delta_bars") == 0


def test_compare_with_geometry_gt() -> None:
    gt_boxes = [Box(0, 0, 50, 20, kind="measure"), Box(50, 0, 100, 20, kind="measure")]
    gt = {
        "pitch_sequence": [],
        "measure_count": 2,
        "geometry": {"L3": gt_boxes},
        "barline_xs": [0.0, 50.0, 100.0],
    }
    pred = PredGeometry(
        layers={"L3": [Box(1, 1, 49, 19), Box(51, 1, 99, 19)]},
        barline_xs=[0.5, 50.5, 99.5],
    )
    sm = compare_sample(sample_id="g1", gt=gt, pred=pred)
    assert sm.layers["L3"].mode == "iou"
    assert sm.layers["L3"].f1 == pytest.approx(1.0)
    assert sm.layers["L3_barlines"].tp == 3


def test_load_layer_geometry() -> None:
    raw = {
        "layers": {
            "L3": {
                "measures": [
                    {"box": {"x1": 0, "y1": 0, "x2": 10, "y2": 10}},
                ],
                "barlines": [1, 2, 3],
            }
        }
    }
    geom = load_layer_geometry(raw)
    assert len(geom["L3"]) == 1


@pytest.mark.skipif(
    not (EVAL / "gt" / "E01_print_c_4_4_grace_demo.json").is_file(),
    reason="eval sample missing",
)
def test_load_real_gt() -> None:
    g = load_ground_truth(EVAL / "gt" / "E01_print_c_4_4_grace_demo.json")
    assert g["measure_count"] >= 1
    assert len(g["pitch_sequence"]) >= 1


def test_param_tuner_grid() -> None:
    import numpy as np
    from app.evaluation.param_tuner import tune_param_on_image

    img = np.full((120, 400, 3), 255, dtype=np.uint8)
    img[40:90, 20:380] = 245
    for x in (60, 150, 240, 330):
        img[45:85, x : x + 2] = 0
    gt = {
        "pitch_sequence": ["1"],
        "measure_count": 3,
        "geometry": {},
        "barline_xs": [],
    }
    r = tune_param_on_image(
        img,
        gt=gt,
        param="l3_min_measure_width",
        start=16,
        stop=40,
        step=8,
    )
    assert r.n_runs == 4
    assert r.best_value is not None
    assert all(0.0 <= p.f1 <= 1.0 for p in r.points)


def test_baseline_diff() -> None:
    from app.evaluation.param_tuner import diff_baselines

    d = diff_baselines(
        {"mean_f1": {"L3": 0.8, "L5": 0.5}},
        {"mean_f1": {"L3": 0.6, "L5": 0.6}},
    )
    assert d["deltas"]["L3"] == pytest.approx(0.2)
    assert "L3" in d["improved"]
    assert "L5" in d["regressed"]


def test_api_compare() -> None:
    body = {
        "sample_id": "api1",
        "gt": {
            "schema_version": "0.1",
            "key": "C",
            "time_signature": "4/4",
            "parts": [
                {
                    "id": "P1",
                    "name": "melody",
                    "measures": [
                        {
                            "number": 1,
                            "notes": [
                                {"pitch": "1", "duration": "quarter"},
                                {"pitch": "2", "duration": "quarter"},
                            ],
                        }
                    ],
                }
            ],
            "extra": {"eval": {"pitch_sequence": ["1", "2"], "measure_count": 1}},
        },
        "score": {
            "schema_version": "0.1",
            "key": "C",
            "time_signature": "4/4",
            "parts": [
                {
                    "id": "P1",
                    "name": "melody",
                    "measures": [
                        {
                            "number": 1,
                            "notes": [
                                {"pitch": "1", "duration": "quarter"},
                                {"pitch": "2", "duration": "quarter"},
                            ],
                        }
                    ],
                }
            ],
        },
        "structure": {
            "items": [
                {
                    "layer": "L3",
                    "id": "l3-m1",
                    "label": "m1",
                    "box": {"x1": 0, "y1": 0, "x2": 100, "y2": 30},
                    "kind": "measure",
                }
            ],
            "barlines": [{"system": 0, "x": 0}, {"system": 0, "x": 100}],
        },
        "include_errors": False,
    }
    r = client.post("/v1/evaluation/compare", json=body)
    assert r.status_code == 200, r.text
    data = r.json()["metrics"]
    assert data["sample_id"] == "api1"
    assert "L5" in data["layers"]
    assert data["layers"]["L5"]["f1"] == pytest.approx(1.0)
