"""Tests for OCR → note hint extraction."""

from app.pipeline.ocr import OcrItem
from app.pipeline.parse import extract_note_hints


def test_extract_digits() -> None:
    items = [
        OcrItem(text="123", score=0.9, box=None),
        OcrItem(text="主恩", score=0.8, box=None),
        OcrItem(text="4-5", score=0.7, box=None),
    ]
    notes = extract_note_hints(items)
    pitches = [n.pitch for n in notes]
    assert pitches == ["1", "2", "3", "4", "5"]
