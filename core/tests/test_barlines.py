"""Tests for vertical barline detection / injection."""

from __future__ import annotations

import numpy as np

from app.pipeline.barlines import (
    detect_barline_xs,
    inject_barlines_into_items,
    pitch_line_y_range,
)
from app.pipeline.ocr import OcrItem
from app.pipeline.parse import parse_ocr_to_score
from app.schemas.recognize import BoundingBox


def test_detect_vertical_bars_in_synthetic_image() -> None:
    img = np.full((200, 400, 3), 255, dtype=np.uint8)
    # three thick vertical bars in mid band
    for x in (100, 200, 300):
        img[70:150, x : x + 3] = 0
    xs = detect_barline_xs(img, y_range=(60.0, 160.0))
    assert len(xs) >= 3
    assert xs[0] < xs[1] < xs[2]


def test_pitch_line_y_range_picks_digit_box() -> None:
    items = [
        OcrItem(
            text="标题文字很多",
            score=1.0,
            box=BoundingBox(x1=0, y1=0, x2=100, y2=20),
        ),
        OcrItem(
            text="12355617",
            score=0.99,
            box=BoundingBox(x1=10, y1=100, x2=300, y2=140),
        ),
    ]
    band = pitch_line_y_range(items)
    assert band is not None
    assert band[0] < 100 < band[1]


def test_inject_bars_into_digit_run() -> None:
    item = OcrItem(
        text="12355617653",
        score=0.99,
        box=BoundingBox(x1=0, y1=0, x2=110, y2=20, score=0.99),
    )
    out = inject_barlines_into_items([item], bar_xs=[30.0, 60.0, 100.0])
    assert len(out) == 1
    assert "|" in out[0].text


def test_end_to_end_parse_with_injected_bars() -> None:
    item = OcrItem(
        text="12355617653",
        score=0.99,
        box=BoundingBox(x1=50, y1=150, x2=650, y2=200, score=0.99),
    )
    n = 11
    # bars after 3rd, 6th, 10th char → measures 123 | 556 | 1765 | 3
    bar_xs = [50 + 600 * (i / n) for i in (3, 6, 10)]
    items = inject_barlines_into_items(
        [
            OcrItem(text="调：C 拍号：4/4", score=1.0, box=None),
            item,
            OcrItem(text="主恩典够我用", score=0.9, box=None),
        ],
        bar_xs,
    )
    result = parse_ocr_to_score(items)
    assert result.mode == "score"
    assert result.score is not None
    mel = result.score.melody_part()
    assert mel is not None
    assert len(mel.measures) >= 3
    assert [n.pitch for n in mel.measures[0].notes if n.pitch] == ["1", "2", "3"]
