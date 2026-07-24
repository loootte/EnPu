"""Unit tests for crop rect normalize + score merge (#49)."""

from __future__ import annotations

import pytest

from app.pipeline.crop_merge import (
    estimate_measure_window,
    merge_crop_into_score,
    normalize_crop_rect,
    offset_boxes,
)
from app.schemas.recognize import BoundingBox, CropRect
from app.schemas.score import DurationName, Measure, NoteEvent, Part, Score


def _note(p: str) -> NoteEvent:
    return NoteEvent(pitch=p, duration=DurationName.quarter)


def _score(pitches_per_measure: list[list[str]], *, title: str = "base") -> Score:
    measures = [
        Measure(number=i + 1, notes=[_note(p) for p in pitches])
        for i, pitches in enumerate(pitches_per_measure)
    ]
    return Score(
        schema_version="0.1",
        title=title,
        key="C",
        time_signature="4/4",
        parts=[Part(id="P1", name="melody", measures=measures)],
    )


def test_normalize_crop_orders_and_clamps() -> None:
    r = normalize_crop_rect(50, 40, 10, 5, width=100, height=80)
    assert r.x1 == 10 and r.y1 == 5
    assert r.x2 == 50 and r.y2 == 40


def test_normalize_crop_rejects_tiny() -> None:
    with pytest.raises(ValueError, match="too small"):
        normalize_crop_rect(1, 1, 4, 4, width=100, height=100, min_side=8)


def test_offset_boxes() -> None:
    boxes = [BoundingBox(x1=1, y1=2, x2=3, y2=4, score=0.9)]
    out = offset_boxes(boxes, 10, 20)
    assert out[0].x1 == 11 and out[0].y1 == 22
    assert out[0].x2 == 13 and out[0].y2 == 24


def test_estimate_measure_window_top_third() -> None:
    crop = CropRect(x1=0, y1=0, x2=100, y2=30)
    start, end = estimate_measure_window(
        n_base=9, n_crop=2, crop=crop, image_height=90
    )
    assert start == 0
    assert end >= 2


def test_merge_preserves_outside_hand_edits() -> None:
    base = _score([["1"], ["2"], ["3"], ["4"], ["5"]])
    # Simulate hand edit on measure 5
    base.parts[0].measures[4].notes[0].pitch = "7"
    base.parts[0].measures[4].notes[0].lyric = "手改"

    crop = _score([["6"], ["6"]], title="crop")
    rect = CropRect(x1=0, y1=0, x2=100, y2=40)
    merged, info = merge_crop_into_score(
        base,
        crop,
        crop=rect,
        image_height=100,
        measure_from=2,
        measure_to=3,
    )

    notes = [
        m.notes[0].pitch for m in merged.parts[0].measures
    ]
    lyrics = [
        m.notes[0].lyric for m in merged.parts[0].measures
    ]
    # m1 kept, m2-3 replaced by two crop measures, m4-5 kept (incl. hand edit)
    assert notes[0] == "1"
    assert notes[1] == "6"
    assert notes[2] == "6"
    assert notes[3] == "4"
    assert notes[-1] == "7"
    assert lyrics[-1] == "手改"
    assert info.preserved_outside is True
    assert info.inserted_measure_count == 2
    assert info.replaced_measure_from == 2
    assert all(
        m.extra.get("from_crop") for m in merged.parts[0].measures[1:3]
    )


def test_merge_auto_window_without_explicit_measures() -> None:
    base = _score([["1"], ["2"], ["3"], ["4"]])
    crop = _score([["5"]])
    # Bottom half of image → later measures
    rect = CropRect(x1=0, y1=50, x2=80, y2=100)
    merged, info = merge_crop_into_score(
        base, crop, crop=rect, image_height=100
    )
    assert info.inserted_measure_count == 1
    assert any(
        m.notes[0].pitch == "5" for m in merged.parts[0].measures
    )
    # First measure should still be base "1" if window starts mid-page
    assert merged.parts[0].measures[0].notes[0].pitch == "1"
