"""Tests for layout classification / non-staff digit filter (#34)."""

from __future__ import annotations

from app.pipeline.layout import (
    RegionKind,
    classify_items,
    pitch_items,
)
from app.pipeline.ocr import OcrItem
from app.pipeline.parse import parse_ocr_to_score
from app.schemas.recognize import BoundingBox


def _box(y1: float, y2: float, x1: float = 10, x2: float = 400) -> BoundingBox:
    return BoundingBox(x1=x1, y1=y1, x2=x2, y2=y2)


def test_classify_title_meta_pitch_lyrics() -> None:
    items = [
        OcrItem(text="EnPu Eval E01", score=1.0, box=_box(20, 45)),
        OcrItem(text="调：C  拍号：4/4  速度：80", score=1.0, box=_box(60, 85)),
        OcrItem(text="1 2 3 | 5 5 6 | 1 7 6 5", score=0.99, box=_box(150, 200)),
        OcrItem(text="主 恩 典 够 我 用", score=0.9, box=_box(240, 270)),
        OcrItem(text="来源：仓库 · 授权：CC0", score=0.9, box=_box(350, 375)),
        OcrItem(text="音高序列 GT: 1 2 3 5 5 6", score=0.9, box=_box(300, 330)),
    ]
    classified = classify_items(items)
    kinds = {c.item.text[:8]: c.kind for c in classified}
    assert kinds["EnPu Eva"].value == "title" or kinds["EnPu Eva"] == RegionKind.title
    assert any(c.kind == RegionKind.meta for c in classified)
    assert any(c.kind == RegionKind.pitch for c in classified)
    assert any(c.kind == RegionKind.lyrics for c in classified)
    assert any(c.kind == RegionKind.footer for c in classified)
    assert any(c.kind == RegionKind.annotation for c in classified)

    staff = pitch_items(classified)
    staff_text = " ".join(it.text for it in staff)
    assert "1 2 3" in staff_text
    assert "音高序列" not in staff_text
    assert "EnPu Eval" not in staff_text
    assert "CC0" not in staff_text


def test_parse_ignores_title_and_gt_annotation_digits() -> None:
    """Title / GT print line digits must not enter pitch stream."""
    items = [
        OcrItem(
            text="EnPu Eval E01 · 001",
            score=1.0,
            box=_box(15, 40),
        ),
        OcrItem(
            text="Key: C  Time: 4/4  Tempo: 80",
            score=1.0,
            box=_box(50, 75),
        ),
        OcrItem(
            text="1  2  3  |  5  5  6  |  1  7  6  5",
            score=0.99,
            box=_box(140, 195),
        ),
        OcrItem(
            text="音高序列 GT: 9 9 9 9 9 9 9 9",
            score=0.9,
            box=_box(280, 310),
        ),
        OcrItem(
            text="主 恩 典",
            score=0.9,
            box=_box(230, 260),
        ),
    ]
    result = parse_ocr_to_score(items)
    assert result.mode == "score"
    assert result.score is not None
    mel = result.score.melody_part()
    assert mel is not None
    pitches = [n.pitch for m in mel.measures for n in m.notes if n.pitch]
    # Must be staff melody only — not title 001 and not fake GT 999...
    assert pitches == ["1", "2", "3", "5", "5", "6", "1", "7", "6", "5"]
    assert "9" not in pitches
    assert any("layout" in w for w in result.warnings)


def test_parse_still_reads_key_from_meta() -> None:
    items = [
        OcrItem(text="调：G    拍号：3/4", score=1.0, box=_box(40, 70)),
        OcrItem(text="1 3 5 | 5 - -", score=0.99, box=_box(150, 200)),
    ]
    result = parse_ocr_to_score(items)
    assert result.score is not None
    assert result.score.key == "G"
    assert result.score.time_signature == "3/4"


def test_pitch_items_fallback_without_boxes() -> None:
    items = [
        OcrItem(text="Key: C Time: 4/4", score=1.0, box=None),
        OcrItem(text="1 2 3 | 5 6 7", score=0.9, box=None),
        OcrItem(text="主恩典够我用", score=0.9, box=None),
    ]
    result = parse_ocr_to_score(items)
    assert result.mode == "score"
    assert result.score is not None
    pitches = [
        n.pitch
        for m in result.score.melody_part().measures  # type: ignore[union-attr]
        for n in m.notes
        if n.pitch
    ]
    assert pitches[:3] == ["1", "2", "3"]
