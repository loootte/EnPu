"""Structure layer edit + re-run from layer (#78)."""

from __future__ import annotations

import json

import numpy as np
import pytest

from app.pipeline.structure.rebuild import (
    apply_structure_edits,
    page_layout_from_structure,
)
from app.schemas.recognize import BoundingBox, StructureBox, StructureDebug


def _structure_two_systems() -> StructureDebug:
    return StructureDebug(
        pipeline="structure",
        summary={"n_systems": 2, "key": "C", "time_signature": "4/4", "title": "t"},
        items=[
            StructureBox(
                layer="L1",
                id="l1-score",
                label="score",
                kind="score",
                box=BoundingBox(x1=0, y1=40, x2=400, y2=300),
            ),
            StructureBox(
                layer="L2",
                id="l2-sys0",
                label="谱行 1",
                kind="system",
                box=BoundingBox(x1=10, y1=50, x2=390, y2=120),
            ),
            StructureBox(
                layer="L2",
                id="l2-sys1",
                label="谱行 2",
                kind="system",
                box=BoundingBox(x1=10, y1=160, x2=390, y2=240),
            ),
            StructureBox(
                layer="L3",
                id="l3-m1",
                label="m1",
                kind="measure",
                box=BoundingBox(x1=20, y1=55, x2=180, y2=115),
            ),
            StructureBox(
                layer="L3",
                id="l3-m2",
                label="m2",
                kind="measure",
                box=BoundingBox(x1=200, y1=55, x2=370, y2=115),
            ),
            StructureBox(
                layer="L3",
                id="l3-m3",
                label="m3",
                kind="measure",
                box=BoundingBox(x1=20, y1=165, x2=370, y2=235),
            ),
        ],
        barlines=[],
    )


def test_apply_structure_edits_by_id() -> None:
    st = _structure_two_systems()
    edited = apply_structure_edits(
        st,
        [{"id": "l2-sys0", "box": {"x1": 10, "y1": 40, "x2": 390, "y2": 140}}],
        width=400,
        height=300,
    )
    sys0 = next(i for i in edited.items if i.id == "l2-sys0")
    assert sys0.box.y1 == 40
    assert sys0.box.y2 == 140
    # untouched
    sys1 = next(i for i in edited.items if i.id == "l2-sys1")
    assert sys1.box.y1 == 160


def test_page_layout_from_structure_assigns_measures() -> None:
    st = _structure_two_systems()
    layout = page_layout_from_structure(st, width=400, height=300)
    assert len(layout.systems) == 2
    assert layout.score_region is not None
    # m1,m2 on first system; m3 on second
    assert len(layout.systems[0].measures) == 2
    assert len(layout.systems[1].measures) == 1
    assert layout.systems[0].measures[0].rect.x1 == 20


def _synthetic_png() -> bytes:
    img = np.full((320, 420, 3), 255, dtype=np.uint8)
    for y0 in (60, 180):
        for x in range(30, 380, 28):
            img[y0 : y0 + 24, x : x + 12] = 0
        for x in (100, 200, 300):
            img[y0 - 5 : y0 + 30, x : x + 2] = 0
    ok, buf = __import__("cv2").imencode(".png", img)
    assert ok
    return buf.tobytes()


def test_structure_rerun_l2_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    """from_layer=L2 pins edited system rects and re-runs L3–L5 only."""
    import app.config as config_mod
    from app.pipeline.structure.pipeline import run_structure_rerun

    monkeypatch.setenv("ENPU_RECOGNIZE_ENGINE", "mock")
    monkeypatch.setenv("ENPU_PIPELINE_MODE", "structure")
    config_mod.get_settings.cache_clear()
    settings = config_mod.get_settings()

    st = _structure_two_systems()
    edits = [{"id": "l2-sys0", "box": {"x1": 10, "y1": 45, "x2": 390, "y2": 135}}]
    res = run_structure_rerun(
        _synthetic_png(),
        settings=settings,
        from_layer="L2",
        base_structure=st,
        edits=edits,
        filename="t.png",
    )
    assert res.ok is True
    assert res.structure is not None
    l2 = [i for i in res.structure.items if i.layer == "L2"]
    assert len(l2) >= 1
    # Edited L2 box must be preserved (not re-detected)
    sys0 = next(i for i in l2 if i.id == "l2-sys0" or i.box.y1 == 45)
    assert abs(sys0.box.y1 - 45) < 1.0
    assert abs(sys0.box.y2 - 135) < 1.0
    l1 = [i for i in res.structure.items if i.layer == "L1"]
    assert any(i.id == "l1-score" or i.kind == "score" for i in l1)
    assert any("structure_rerun" in w for w in res.meta.parse_warnings)
    assert any("from=L2" in w for w in res.meta.parse_warnings)
    assert any("pin=L2" in w or "L2 pinned" in w for w in res.meta.parse_warnings)
    config_mod.get_settings.cache_clear()


def test_structure_rerun_l3_keeps_systems(monkeypatch: pytest.MonkeyPatch) -> None:
    """from_layer=L3 pins L2+L3; re-runs L4–L5 only (does not re-detect L3)."""
    import app.config as config_mod
    from app.pipeline.structure.pipeline import run_structure_rerun

    monkeypatch.setenv("ENPU_RECOGNIZE_ENGINE", "mock")
    config_mod.get_settings.cache_clear()
    settings = config_mod.get_settings()

    st = _structure_two_systems()
    edits = [{"id": "l3-m1", "box": {"x1": 15, "y1": 50, "x2": 190, "y2": 118}}]
    res = run_structure_rerun(
        _synthetic_png(),
        settings=settings,
        from_layer="L3",
        base_structure=st,
        edits=edits,
        filename="t.png",
    )
    assert res.ok is True
    assert res.structure is not None
    l2 = [i for i in res.structure.items if i.layer == "L2"]
    assert len(l2) == 2
    sys0 = next(i for i in l2 if i.id == "l2-sys0")
    assert sys0.box.y1 == 50
    assert sys0.box.y2 == 120
    # Edited L3 measure must keep user rect
    l3 = [i for i in res.structure.items if i.layer == "L3"]
    m1 = next((i for i in l3 if i.id == "l3-m1"), None)
    assert m1 is not None
    assert abs(m1.box.x1 - 15) < 1.0
    assert abs(m1.box.y1 - 50) < 1.0
    assert abs(m1.box.x2 - 190) < 1.0
    assert abs(m1.box.y2 - 118) < 1.0
    assert any("from=L3" in w for w in res.meta.parse_warnings)
    assert any("L3 pinned" in w or "pin=L3" in w for w in res.meta.parse_warnings)
    config_mod.get_settings.cache_clear()


def test_structure_rerun_l2_requires_systems(monkeypatch: pytest.MonkeyPatch) -> None:
    """L2 rerun without L2 boxes must not silently re-detect; it errors."""
    import app.config as config_mod
    import pytest as pt
    from app.pipeline.structure.pipeline import (
        StructurePipelineError,
        run_structure_rerun,
    )
    from app.schemas.recognize import BoundingBox, StructureBox, StructureDebug

    monkeypatch.setenv("ENPU_RECOGNIZE_ENGINE", "mock")
    config_mod.get_settings.cache_clear()
    settings = config_mod.get_settings()
    st = StructureDebug(
        pipeline="structure",
        items=[
            StructureBox(
                layer="L1",
                id="l1-score",
                label="score",
                kind="score",
                box=BoundingBox(x1=0, y1=0, x2=400, y2=300),
            )
        ],
    )
    with pt.raises(StructurePipelineError, match="L2 system"):
        run_structure_rerun(
            _synthetic_png(),
            settings=settings,
            from_layer="L2",
            base_structure=st,
            edits=[],
            filename="t.png",
        )
    config_mod.get_settings.cache_clear()
