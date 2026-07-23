"""Lightweight mapping from OCR text to note hints (PoC)."""

from __future__ import annotations

import re

from app.pipeline.ocr import OcrItem
from app.schemas.recognize import NoteHint

# Jianpu pitch digits 1-7, optional octave dots are ignored at this stage.
_DIGIT_RE = re.compile(r"[1-7]")


def extract_note_hints(items: list[OcrItem]) -> list[NoteHint]:
    """Pull simple pitch digits out of OCR strings for early structure demos.

    Not a real rhythm parser — full parsing is issue #10.
    """
    notes: list[NoteHint] = []
    for item in items:
        for ch in _DIGIT_RE.findall(item.text):
            notes.append(
                NoteHint(
                    pitch=ch,
                    text=item.text,
                    extra={
                        "source": "ocr_digit",
                        "score": item.score,
                    },
                )
            )
    return notes
