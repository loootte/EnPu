"""Tests for duration underlines + meter soft-fit (#54)."""

from __future__ import annotations

import numpy as np

from app.pipeline.duration import (
    detect_underlines_for_items,
    fit_notes_to_capacity,
    underlines_to_duration,
)
from app.pipeline.ocr import OcrItem
from app.pipeline.parse import parse_ocr_to_score
from app.schemas.recognize import BoundingBox
from app.schemas.score import DurationName, NoteEvent


def test_underlines_to_duration_map() -> None:
    assert underlines_to_duration(0) == DurationName.quarter
    assert underlines_to_duration(1) == DurationName.eighth
    assert underlines_to_duration(2) == DurationName.sixteenth
    assert underlines_to_duration(3) == DurationName.sixteenth


def test_ocr_underscore_tokens_eighth() -> None:
    items = [
        OcrItem(text="Time: 4/4", score=1.0, box=None),
        # 8 eighths in one bar (with bars so soft-fit applies inside measure)
        OcrItem(text="1_ 2_ 3_ 5_ 6_ 5_ 3_ 1_ | 5 5 6 5", score=0.95, box=None),
    ]
    result = parse_ocr_to_score(items)
    assert result.mode == "score"
    assert result.score is not None
    mel = result.score.melody_part()
    assert mel is not None
    m0 = mel.measures[0].notes
    assert len(m0) == 8
    assert all(n.duration == DurationName.eighth for n in m0)


def test_ocr_double_underscore_sixteenth() -> None:
    items = [
        OcrItem(text="4/4", score=1.0, box=None),
        OcrItem(text="1__ 2__ 3__ 5__ 6__ 5__ 3__ 1__ 2__ 3__ 5__ 6__ 5__ 3__ 1__ 2__", score=0.9, box=None),
    ]
    result = parse_ocr_to_score(items)
    assert result.mode == "score"
    assert result.score is not None
    mel = result.score.melody_part()
    assert mel is not None
    # 16 sixteenths → one 4/4 bar ideally
    assert len(mel.measures) == 1
    assert len(mel.measures[0].notes) == 16
    assert all(n.duration == DurationName.sixteenth for n in mel.measures[0].notes)


def test_meter_fit_prevents_quarter_inflation() -> None:
    """8 notes without underlines in one OCR bar must not become 2 measures of quarters."""
    items = [
        OcrItem(text="拍号：4/4", score=1.0, box=None),
        OcrItem(text="1 2 3 5 6 5 3 1 | 5 - - -", score=0.9, box=None),
    ]
    result = parse_ocr_to_score(items)
    assert result.mode == "score"
    assert result.score is not None
    mel = result.score.melody_part()
    assert mel is not None
    # First bar: 8 notes → soft-fit to eighths, stay one measure
    assert len(mel.measures[0].notes) == 8
    assert all(
        n.duration in {DurationName.eighth, DurationName.sixteenth}
        for n in mel.measures[0].notes
    )
    # Should not split 8 quarters into two bars
    assert len(mel.measures[0].notes) == 8


def test_fit_notes_to_capacity_unit() -> None:
    notes = [
        NoteEvent(
            pitch="1",
            duration=DurationName.quarter,
            extra={"duration_from": "default"},
        )
        for _ in range(8)
    ]
    fitted, changed = fit_notes_to_capacity(notes, 4.0)
    assert changed
    assert abs(sum(0.5 for _ in fitted) - 4.0) < 1e-6
    assert all(n.duration == DurationName.eighth for n in fitted)


def test_detect_underlines_on_synthetic_image() -> None:
    """Draw digit box + one horizontal stroke below → count 1."""
    img = np.full((80, 60, 3), 255, dtype=np.uint8)
    # Fake "ink" digit blob
    img[20:40, 20:40] = 0
    # One underline
    img[48:51, 18:42] = 0
    box = BoundingBox(x1=20, y1=20, x2=40, y2=40)
    items = [OcrItem(text="5", score=1.0, box=box)]
    hits = detect_underlines_for_items(img, items)
    assert len(hits) == 1
    assert hits[0].underlines >= 1
