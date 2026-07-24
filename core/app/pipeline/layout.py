"""Layout / region classification for OCR items (issue #34).

Goal: keep pitch digits from **staff (jianpu) lines** and drop numbers in
titles, page headers, lyrics, footers, and GT annotation lines that pollute
pitch sequences (hurts Precision / F1 on print_clear eval).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from app.pipeline.ocr import OcrItem

_DIGIT_CHARS = set("01234567１２３４５６７０")
_PITCH_CHARS = set("1234567１２３４５６７")

_META_RE = re.compile(
    r"(key|time|tempo|bpm|拍号|调\s*[:：]|速度|1\s*=\s*[A-Ga-g]|time\s*signature)",
    re.I,
)
_TITLE_RE = re.compile(
    r"(title|样例|sample|enpu\s*eval|eval\s*e\d|标题|示意)",
    re.I,
)
_FOOTER_RE = re.compile(
    r"(来源|授权|cc0|copyright|©|issue\s*#|generate-eval|scripts/)",
    re.I,
)
_ANNOT_RE = re.compile(
    r"(音高序列|pitch\s*sequence|\bgt\b|ground[\s-]?truth|子集)",
    re.I,
)
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


class RegionKind(str, Enum):
    title = "title"
    meta = "meta"
    pitch = "pitch"
    lyrics = "lyrics"
    footer = "footer"
    annotation = "annotation"  # eval GT labels printed on sample images
    other = "other"


@dataclass(frozen=True)
class ClassifiedItem:
    item: OcrItem
    kind: RegionKind
    confidence: float


def _counts(text: str) -> tuple[int, int, int, int]:
    digits = sum(1 for c in text if c in _DIGIT_CHARS)
    pitches = sum(1 for c in text if c in _PITCH_CHARS)
    cjk = len(_CJK_RE.findall(text))
    letters = sum(1 for c in text if c.isalpha() or ("\u4e00" <= c <= "\u9fff"))
    return digits, pitches, cjk, letters


def _page_extent(items: list[OcrItem]) -> tuple[float, float, float, float] | None:
    boxes = [it.box for it in items if it.box is not None]
    if not boxes:
        return None
    return (
        min(b.x1 for b in boxes),
        min(b.y1 for b in boxes),
        max(b.x2 for b in boxes),
        max(b.y2 for b in boxes),
    )


def classify_item(
    item: OcrItem,
    *,
    page: tuple[float, float, float, float] | None,
    pitch_y_band: tuple[float, float] | None,
) -> ClassifiedItem:
    text = (item.text or "").strip()
    if not text:
        return ClassifiedItem(item, RegionKind.other, 0.0)

    digits, pitches, cjk, _letters = _counts(text)
    y_frac: float | None = None
    box_h = 0.0
    if item.box is not None and page is not None:
        _x1, y1, _x2, y2 = page
        ph = max(y2 - y1, 1.0)
        cy = (item.box.y1 + item.box.y2) / 2.0
        y_frac = (cy - y1) / ph
        box_h = max(item.box.y2 - item.box.y1, 1.0)

    # Strong keyword gates first
    if _ANNOT_RE.search(text):
        return ClassifiedItem(item, RegionKind.annotation, 0.95)
    if _FOOTER_RE.search(text):
        return ClassifiedItem(item, RegionKind.footer, 0.9)
    if _META_RE.search(text) and pitches < 4:
        return ClassifiedItem(item, RegionKind.meta, 0.9)
    if _TITLE_RE.search(text) and pitches < 5:
        return ClassifiedItem(item, RegionKind.title, 0.85)

    # Geometric footer / header
    if y_frac is not None:
        if y_frac > 0.88 and pitches < 4:
            return ClassifiedItem(item, RegionKind.footer, 0.75)
        if y_frac < 0.12 and pitches < 4 and cjk >= 0:
            # top band: title-ish unless dense pitch run
            if pitches < 3:
                return ClassifiedItem(item, RegionKind.title, 0.7)

    # Lyrics: CJK-heavy, few pitch digits
    if cjk >= 2 and pitches <= 1:
        return ClassifiedItem(item, RegionKind.lyrics, 0.8)
    if cjk >= 4 and pitches < cjk:
        return ClassifiedItem(item, RegionKind.lyrics, 0.75)

    # Pure jianpu token stream (digits / bars / sustains only) → always pitch
    stripped = re.sub(r"\s+", "", text)
    if stripped and re.fullmatch(r"[0-7|\-–—\.·•]+", stripped) and pitches >= 1:
        conf = 0.88
        if pitch_y_band is not None and item.box is not None:
            cy = (item.box.y1 + item.box.y2) / 2.0
            if pitch_y_band[0] <= cy <= pitch_y_band[1]:
                conf = 0.97
        return ClassifiedItem(item, RegionKind.pitch, conf)

    # Pitch staff: dense 1-7 tokens, limited CJK
    pitch_ratio = pitches / max(len(text.replace(" ", "")), 1)
    looks_pitch = pitches >= 2 and cjk <= max(2, pitches // 2)
    if looks_pitch or (pitches >= 3 and pitch_ratio >= 0.25):
        conf = 0.7 + min(0.25, 0.03 * pitches)
        # Boost if near known pitch band or taller boxes (large font digits)
        if pitch_y_band is not None and item.box is not None:
            cy = (item.box.y1 + item.box.y2) / 2.0
            if pitch_y_band[0] <= cy <= pitch_y_band[1]:
                conf = min(0.99, conf + 0.15)
        if box_h >= 28:
            conf = min(0.99, conf + 0.05)
        return ClassifiedItem(item, RegionKind.pitch, conf)

    # Single/double digit alone near pitch band or mid-page → still pitch
    if pitches >= 1 and cjk == 0 and len(text) <= 12:
        if pitch_y_band and item.box is not None:
            cy = (item.box.y1 + item.box.y2) / 2.0
            if pitch_y_band[0] <= cy <= pitch_y_band[1]:
                return ClassifiedItem(item, RegionKind.pitch, 0.8)
        if y_frac is not None and 0.18 <= y_frac <= 0.82:
            return ClassifiedItem(item, RegionKind.pitch, 0.62)

    # Meta-like short lines with 4/4 only
    if re.fullmatch(r"\s*[1-9][0-9]*\s*/\s*[1-9][0-9]*\s*", text):
        return ClassifiedItem(item, RegionKind.meta, 0.85)

    return ClassifiedItem(item, RegionKind.other, 0.3)


def estimate_pitch_y_band(items: list[OcrItem]) -> tuple[float, float] | None:
    """Rough staff band from digit-dense boxes (pre-classification)."""
    scored: list[tuple[float, OcrItem]] = []
    for it in items:
        if it.box is None or not it.text:
            continue
        _d, pitches, cjk, _ = _counts(it.text)
        stripped = re.sub(r"\s+", "", it.text)
        pure = bool(stripped and re.fullmatch(r"[0-7|\-–—\.·•]+", stripped))

        if pitches < 1:
            continue
        if pitches < 3 and not pure:
            continue
        if cjk >= 3 and cjk > pitches:
            continue
        scored.append((float(pitches) - 0.5 * cjk + (2.0 if pure else 0.0), it))
    if not scored:
        return None
    scored.sort(key=lambda x: x[0], reverse=True)
    best = scored[0][1]
    assert best.box is not None
    pad = max(16.0, 0.5 * (best.box.y2 - best.box.y1))
    # Include nearby peer pitch lines (multi-staff / split digit boxes)
    y1, y2 = best.box.y1 - pad, best.box.y2 + pad
    for _s, it in scored[:12]:
        if it.box is None:
            continue
        # same vertical neighborhood
        if abs((it.box.y1 + it.box.y2) / 2 - (best.box.y1 + best.box.y2) / 2) < 100:
            y1 = min(y1, it.box.y1 - pad)
            y2 = max(y2, it.box.y2 + pad)
    return (y1, y2)


def classify_items(items: list[OcrItem]) -> list[ClassifiedItem]:
    page = _page_extent(items)
    band = estimate_pitch_y_band(items)
    return [
        classify_item(it, page=page, pitch_y_band=band) for it in items if it.text
    ]


def items_of_kind(
    classified: list[ClassifiedItem], *kinds: RegionKind
) -> list[OcrItem]:
    allow = set(kinds)
    return [c.item for c in classified if c.kind in allow]


def pitch_items(classified: list[ClassifiedItem]) -> list[OcrItem]:
    """Items allowed to contribute pitch digits to the score."""
    pitches = items_of_kind(classified, RegionKind.pitch)
    if pitches:
        return pitches
    # Fallback: if nothing classified as pitch, keep non-rejected digit-ish items
    reject = {
        RegionKind.title,
        RegionKind.footer,
        RegionKind.annotation,
        RegionKind.lyrics,
    }
    return [c.item for c in classified if c.kind not in reject]


def meta_items(classified: list[ClassifiedItem]) -> list[OcrItem]:
    return items_of_kind(
        classified, RegionKind.meta, RegionKind.title, RegionKind.other
    )


def lyric_items(classified: list[ClassifiedItem]) -> list[OcrItem]:
    return items_of_kind(classified, RegionKind.lyrics)


def summarize_classification(classified: list[ClassifiedItem]) -> str:
    from collections import Counter

    c = Counter(x.kind.value for x in classified)
    return ", ".join(f"{k}={v}" for k, v in sorted(c.items()))
