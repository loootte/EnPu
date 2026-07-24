"""Tests for OCR → Score parse MVP (#10)."""

from __future__ import annotations

from app.pipeline.ocr import OcrItem
from app.pipeline.parse import extract_note_hints, parse_ocr_to_score
from app.schemas.recognize import BoundingBox


def test_extract_note_hints_digits() -> None:
    items = [
        OcrItem(text="123", score=0.9, box=None),
        OcrItem(text="主恩", score=0.8, box=None),
    ]
    hints = extract_note_hints(items)
    assert [h.pitch for h in hints] == ["1", "2", "3"]


def test_parse_jianpu_line_to_score() -> None:
    items = [
        OcrItem(text="Key: C  Time: 4/4  Tempo: 80", score=1.0, box=None),
        OcrItem(text="1  2  3  |  5  -  -  |  6  5  3", score=0.95, box=None),
        OcrItem(text="主 恩 典  够 我 用", score=0.9, box=None),
    ]
    result = parse_ocr_to_score(items, filename="demo.png", engine="test")
    assert result.mode == "score"
    assert result.score is not None
    assert result.score.schema_version == "0.1"
    assert result.score.key == "C"
    assert result.score.time_signature == "4/4"
    assert result.score.tempo_bpm == 80.0
    mel = result.score.melody_part()
    assert mel is not None
    assert len(mel.measures) >= 2
    # first measure pitches 1,2,3
    pitches = [n.pitch for n in mel.measures[0].notes if not n.is_rest]
    assert pitches == ["1", "2", "3"]
    # "5 - -" → dotted half (half + one dot)
    m2 = mel.measures[1].notes
    assert m2[0].pitch == "5"
    assert m2[0].duration.value == "half"
    assert m2[0].dots >= 1
    # lyrics attached
    assert any(n.lyric for n in mel.measures[0].notes)


def test_parse_fallback_hints_when_no_line() -> None:
    items = [
        OcrItem(text="1", score=1.0, box=None),
        OcrItem(text="5", score=1.0, box=None),
        OcrItem(text="3", score=1.0, box=None),
        OcrItem(text="6", score=1.0, box=None),
    ]
    result = parse_ocr_to_score(items)
    # digit-only lines may not count as jianpu lines; flat pitch fallback still builds score
    assert result.notes
    assert result.mode in {"score", "hints"}
    if result.mode == "score":
        assert result.score is not None
        pitches = []
        for m in result.score.melody_part().measures:  # type: ignore[union-attr]
            pitches.extend(n.pitch for n in m.notes if n.pitch)
        assert pitches == ["1", "5", "3", "6"]


def test_parse_ocr_only_on_empty() -> None:
    result = parse_ocr_to_score([])
    assert result.mode == "ocr_only"
    assert result.score is None
    assert result.notes == []


def test_parse_ocr_only_no_digits() -> None:
    items = [OcrItem(text="hello world", score=0.5, box=None)]
    result = parse_ocr_to_score(items)
    assert result.mode == "ocr_only"
    assert result.score is None


def test_reading_order_uses_boxes() -> None:
    items = [
        OcrItem(
            text="5  6  7",
            score=1.0,
            box=BoundingBox(x1=0, y1=100, x2=50, y2=120),
        ),
        OcrItem(
            text="1  2  3",
            score=1.0,
            box=BoundingBox(x1=0, y1=10, x2=50, y2=30),
        ),
    ]
    result = parse_ocr_to_score(items)
    assert result.mode == "score"
    assert result.score is not None
    first = [n.pitch for n in result.score.melody_part().measures[0].notes]  # type: ignore[union-attr]
    assert first[:3] == ["1", "2", "3"]


def test_ocr_bar_confusion_I_recovered() -> None:
    """OCR often turns | into I/l between digits."""
    items = [
        OcrItem(text="Time: 4/4", score=1.0, box=None),
        OcrItem(text="1 2 3 I 5 5 6 I 1 7 6 5", score=0.9, box=None),
    ]
    result = parse_ocr_to_score(items)
    assert result.mode == "score"
    assert result.score is not None
    mel = result.score.melody_part()
    assert mel is not None
    assert len(mel.measures) >= 3
    assert [n.pitch for n in mel.measures[0].notes] == ["1", "2", "3"]
    assert [n.pitch for n in mel.measures[1].notes] == ["5", "5", "6"]


def test_no_barline_infer_measures_by_meter() -> None:
    """When OCR drops all bars and glues digits, split by 4/4 quarters."""
    items = [
        OcrItem(text="拍号：4/4", score=1.0, box=None),
        OcrItem(text="12315561176513--", score=0.9, box=None),
    ]
    result = parse_ocr_to_score(items)
    assert result.mode == "score"
    assert result.score is not None
    mel = result.score.melody_part()
    assert mel is not None
    assert len(mel.measures) >= 3
    assert any(
        "barline" in w or "time signature" in w or "inferred" in w
        for w in result.warnings
    )
    # first bar should start with 1,2,3...
    assert mel.measures[0].notes[0].pitch == "1"
def test_multiline_does_not_merge_last_and_first_measure() -> None:
    """#35: staff-line break must flush — 001_poc_digits style two systems."""
    items = [
        OcrItem(text="Key: C  Time: 3/4  Tempo: 80", score=1.0, box=None),
        OcrItem(
            text="1  2  3  |  5  -  -  |  6  5  3  |  2  -  -",
            score=0.95,
            box=BoundingBox(x1=40, y1=180, x2=700, y2=220),
        ),
        OcrItem(
            text="1  2  3  |  5  -  -  |  3  2  1  |  1  -  -",
            score=0.95,
            box=BoundingBox(x1=40, y1=240, x2=700, y2=280),
        ),
    ]
    result = parse_ocr_to_score(items, filename="001_poc_digits.png")
    assert result.mode == "score"
    assert result.score is not None
    mel = result.score.melody_part()
    assert mel is not None
    assert len(mel.measures) >= 7
    pitches_by_m = [[n.pitch for n in m.notes if n.pitch] for m in mel.measures]
    # Critical: no single measure like ["2","1","2","3"] (line1 end + line2 start)
    assert not any(p == ["2", "1", "2", "3"] for p in pitches_by_m)
    assert any(p[:3] == ["1", "2", "3"] for p in pitches_by_m)
    assert any("staff-line break" in w or "multi-line" in w for w in result.warnings)


def test_rebalance_overfull_measure_by_meter() -> None:
    """Missing mid-line bars → overfull measure split by 4/4."""
    items = [
        OcrItem(text="Time: 4/4", score=1.0, box=None),
        OcrItem(text="1 2 3 5 6 5 3 2", score=0.95, box=None),
    ]
    result = parse_ocr_to_score(items)
    assert result.score is not None
    mel = result.score.melody_part()
    assert mel is not None
    assert len(mel.measures) >= 2
    assert [n.pitch for n in mel.measures[0].notes if n.pitch] == ["1", "2", "3", "5"]
