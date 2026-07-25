"""Tests for structure-first pipeline (#58)."""

from __future__ import annotations

import io

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from app.config import clear_settings_cache
from app.main import app
from app.pipeline.structure.ir import Rect
from app.pipeline.structure.l1_page import detect_page_regions
from app.pipeline.structure.l2_systems import detect_staff_systems
from app.pipeline.structure.l3_measures import segment_measures_on_systems
from app.pipeline.structure.l4_notes import detect_note_candidates
from app.pipeline.structure.assemble import page_layout_to_score
from app.pipeline.structure.ir import PageLayout, StaffSystem, MeasureLayout, NoteCandidate, NoteGlyph
from app.schemas.score import DurationName

client = TestClient(app)


def _synthetic_score_bgr(w: int = 400, h: int = 300) -> np.ndarray:
    """White page with two dark staff bands and vertical bars."""
    img = np.full((h, w, 3), 255, dtype=np.uint8)
    # two horizontal staff bands (ink)
    img[80:110, 40:360] = 30
    img[160:190, 40:360] = 30
    # vertical barlines
    for x in (40, 140, 240, 340):
        img[75:195, x : x + 3] = 0
    # note-like blobs on first system
    for x in (60, 90, 120, 160, 190, 220):
        img[85:105, x : x + 12] = 0
    return img


def test_l1_detects_score_region() -> None:
    img = _synthetic_score_bgr()
    regions, warnings = detect_page_regions(img)
    roles = {r.role.value for r in regions}
    assert "score" in roles
    score = next(r for r in regions if r.role.value == "score")
    assert score.rect.height > 50


def test_l2_detects_systems() -> None:
    img = _synthetic_score_bgr()
    regions, _ = detect_page_regions(img)
    score = next(r for r in regions if r.role.value == "score")
    systems, warnings = detect_staff_systems(img, score.rect)
    assert len(systems) >= 1
    assert systems[0].rect.width > 0


def test_l3_segments_measures() -> None:
    img = _synthetic_score_bgr()
    regions, _ = detect_page_regions(img)
    score = next(r for r in regions if r.role.value == "score")
    systems, _ = detect_staff_systems(img, score.rect)
    systems, warnings = segment_measures_on_systems(img, systems)
    total_m = sum(len(s.measures) for s in systems)
    assert total_m >= 1
    assert any("L3" in w for w in warnings)


def test_l4_note_candidates() -> None:
    img = _synthetic_score_bgr()
    regions, _ = detect_page_regions(img)
    score = next(r for r in regions if r.role.value == "score")
    systems, _ = detect_staff_systems(img, score.rect)
    systems, _ = segment_measures_on_systems(img, systems)
    systems, warnings = detect_note_candidates(img, systems)
    n = sum(len(m.notes) for s in systems for m in s.measures)
    assert n >= 1
    assert any("L4" in w for w in warnings)


def test_assemble_score_from_ir() -> None:
    layout = PageLayout(
        width=100,
        height=100,
        key="C",
        time_signature="4/4",
        title="t",
        systems=[
            StaffSystem(
                index=0,
                rect=Rect(0, 0, 100, 40),
                measures=[
                    MeasureLayout(
                        index=0,
                        rect=Rect(0, 0, 50, 40),
                        notes=[
                            NoteCandidate(
                                rect=Rect(5, 5, 20, 30),
                                index=0,
                                glyph=NoteGlyph(
                                    pitch="1",
                                    duration=DurationName.quarter,
                                ),
                            ),
                            NoteCandidate(
                                rect=Rect(25, 5, 40, 30),
                                index=1,
                                glyph=NoteGlyph(
                                    pitch="5",
                                    duration=DurationName.eighth,
                                    underlines=1,
                                ),
                            ),
                        ],
                    )
                ],
            )
        ],
    )
    score = page_layout_to_score(layout, filename="x.png", engine="test")
    assert score.schema_version == "0.1"
    assert score.key == "C"
    mel = score.melody_part()
    assert mel is not None
    assert len(mel.measures) == 1
    assert [n.pitch for n in mel.measures[0].notes] == ["1", "5"]


def test_recognize_structure_mode_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENPU_RECOGNIZE_ENGINE", "mock")
    monkeypatch.setenv("ENPU_PIPELINE_MODE", "structure")
    clear_settings_cache()
    try:
        buf = io.BytesIO()
        img = Image.fromarray(_synthetic_score_bgr())
        img.save(buf, format="PNG")
        data = buf.getvalue()
        resp = client.post(
            "/v1/recognize",
            files={"file": ("syn.png", data, "image/png")},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["ok"] is True
        assert "structure" in body["engine"]
        assert body["meta"]["parse_mode"] == "score"
        assert body.get("score") is not None
        assert body.get("structure") is not None
        assert body["structure"]["pipeline"] == "structure"
        assert isinstance(body["structure"]["items"], list)
        assert len(body["structure"]["items"]) >= 1
        layers = {it["layer"] for it in body["structure"]["items"]}
        assert "L1" in layers or "L2" in layers
        assert any(
            "pipeline=structure" in w or "L2" in w or "L3" in w
            for w in body["meta"].get("parse_warnings") or []
        )
    finally:
        monkeypatch.delenv("ENPU_PIPELINE_MODE", raising=False)
        clear_settings_cache()


def test_recognize_legacy_still_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENPU_RECOGNIZE_ENGINE", "mock")
    monkeypatch.delenv("ENPU_PIPELINE_MODE", raising=False)
    clear_settings_cache()
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), (255, 255, 255)).save(buf, format="PNG")
    resp = client.post(
        "/v1/recognize",
        files={"file": ("a.png", buf.getvalue(), "image/png")},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["engine"] == "mock"
    assert "structure" not in body["engine"]
