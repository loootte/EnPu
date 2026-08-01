"""L1–L3 layout GT export & validation (#93)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.layout_gt.export import (
    _interior_splits_from_edges,
    layout_sample_from_project,
    layout_sample_from_structure,
)
from app.layout_gt.validate import validate_layout_sample


def _minimal_structure() -> dict:
    return {
        "pipeline": "structure",
        "summary": {"width": 400, "height": 300, "n_systems": 1, "n_measures": 3},
        "items": [
            {
                "layer": "L1",
                "id": "l1-title",
                "label": "title",
                "kind": "title",
                "box": {"x1": 50, "y1": 10, "x2": 350, "y2": 40},
            },
            {
                "layer": "L1",
                "id": "l1-score",
                "label": "score",
                "kind": "score",
                "box": {"x1": 0, "y1": 50, "x2": 400, "y2": 280},
            },
            {
                "layer": "L2",
                "id": "l2-sys0",
                "label": "谱行 1",
                "kind": "system",
                "box": {"x1": 20, "y1": 80, "x2": 380, "y2": 140},
            },
            {
                "layer": "L3",
                "id": "l3-m1",
                "label": "m1",
                "kind": "measure",
                "box": {"x1": 40, "y1": 80, "x2": 140, "y2": 140},
            },
            {
                "layer": "L3",
                "id": "l3-m2",
                "label": "m2",
                "kind": "measure",
                "box": {"x1": 140, "y1": 80, "x2": 240, "y2": 140},
            },
            {
                "layer": "L3",
                "id": "l3-m3",
                "label": "m3",
                "kind": "measure",
                "box": {"x1": 240, "y1": 80, "x2": 360, "y2": 140},
            },
            # L4 ignored
            {
                "layer": "L4",
                "id": "l4-m1-pitch0",
                "kind": "note_roi",
                "box": {"x1": 50, "y1": 90, "x2": 70, "y2": 120},
            },
        ],
        # #66-style edges: 4 xs for 3 measures
        "barlines": [
            {"system": 0, "x": 40, "y1": 80, "y2": 140},
            {"system": 0, "x": 140, "y1": 80, "y2": 140},
            {"system": 0, "x": 240, "y1": 80, "y2": 140},
            {"system": 0, "x": 360, "y1": 80, "y2": 140},
        ],
    }


def test_interior_from_edges_chain() -> None:
    xs = _interior_splits_from_edges(
        [40, 140, 240, 360], n_measures=3, x_left=20, x_right=380
    )
    assert xs == pytest.approx([140, 240])


def test_structure_to_sample_strips_l4_and_edge_barlines() -> None:
    sample = layout_sample_from_structure(
        _minimal_structure(),
        image={"path": "image.png", "width": 400, "height": 300},
        sample_id="toy",
    )
    assert sample["layout_schema_version"] == "0.1"
    assert sample["l1"]["score_region"]["x2"] == 400
    assert len(sample["l2"]["systems"]) == 1
    row = sample["l3"]["rows"][0]
    assert len(row["splits"]) == 2
    assert [s["x"] for s in row["splits"]] == pytest.approx([140.0, 240.0])
    assert len(row["measures"]) == 3
    r = validate_layout_sample(sample)
    assert r.ok, r.errors


def test_project_wrapper() -> None:
    project = {
        "project_version": "0.2",
        "kind": "enpu-project",
        "title": "toy",
        "score": {
            "schema_version": "0.1",
            "title": "toy",
            "key": "A",
            "time_signature": "4/4",
            "parts": [],
        },
        "source_image": "toy.png",
        "structure": _minimal_structure(),
        "meta": {"engine": "structure+mock", "pipeline_mode": "structure"},
    }
    sample = layout_sample_from_project(project, sample_id="toy")
    assert sample["meta"]["key"] == "A"
    assert sample["source"]["type"] == "enpu_project"
    assert validate_layout_sample(sample).ok


def test_validate_rejects_split_outside_l2() -> None:
    sample = layout_sample_from_structure(
        _minimal_structure(),
        image={"width": 400, "height": 300},
    )
    sample["l3"]["rows"][0]["splits"].append({"id": "bad", "x": 10})  # left of L2
    r = validate_layout_sample(sample)
    assert not r.ok
    assert any("interior" in e for e in r.errors)


def test_validate_rejects_measure_split_count_mismatch() -> None:
    sample = layout_sample_from_structure(
        _minimal_structure(),
        image={"width": 400, "height": 300},
    )
    # drop one split but keep 3 measures
    sample["l3"]["rows"][0]["splits"] = sample["l3"]["rows"][0]["splits"][:1]
    r = validate_layout_sample(sample)
    assert not r.ok
    assert any("n_measures" in e for e in r.errors)


def test_messy_barlines_prefer_measures_and_rederive() -> None:
    """Real projects often have detector barlines that don't match L3 boxes."""
    structure = _minimal_structure()
    # 6 barlines + 3 measures → old code failed n_m == n_s+1
    structure["barlines"] = [
        {"system": 0, "x": 50, "y1": 80, "y2": 140},
        {"system": 0, "x": 90, "y1": 80, "y2": 140},
        {"system": 0, "x": 140, "y1": 80, "y2": 140},
        {"system": 0, "x": 200, "y1": 80, "y2": 140},
        {"system": 0, "x": 240, "y1": 80, "y2": 140},
        {"system": 0, "x": 300, "y1": 80, "y2": 140},
    ]
    sample = layout_sample_from_structure(
        structure,
        image={"path": "image.png", "width": 400, "height": 300},
    )
    row = sample["l3"]["rows"][0]
    # Prefer measure-derived interiors: 3 measures → 2 splits
    assert len(row["splits"]) == 2
    assert len(row["measures"]) == 3
    r = validate_layout_sample(sample)
    assert r.ok, r.errors


def test_repo_sample_if_present() -> None:
    """Optional: samples/layout/*/layout.json committed for #93."""
    root = Path(__file__).resolve().parents[2] / "samples" / "layout"
    if not root.is_dir():
        pytest.skip("no samples/layout")
    layouts = list(root.glob("*/layout.json"))
    if not layouts:
        pytest.skip("no layout.json under samples/layout")
    for p in layouts:
        data = json.loads(p.read_text(encoding="utf-8"))
        r = validate_layout_sample(data)
        assert r.ok, f"{p}: {r.errors}"
