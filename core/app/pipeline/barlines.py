"""Detect vertical barlines in a score image (issue #10 barline fix)."""

from __future__ import annotations

import re

import cv2
import numpy as np

from app.pipeline.ocr import OcrItem


def detect_barline_xs(
    image_bgr: np.ndarray,
    *,
    y_range: tuple[float, float] | None = None,
    min_height_ratio: float = 0.08,
    max_width: int = 8,
    min_gap: float = 35.0,
) -> list[float]:
    """Return x-centers of tall thin vertical strokes (candidate barlines).

    When ``y_range`` is set (pitch staff band from OCR), only strokes that
    substantially overlap that band are kept — avoids Chinese character stems.
    """
    if image_bgr is None or image_bgr.size == 0:
        return []
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape[:2]
    _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    v_len = max(16, int(h * min_height_ratio))
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, v_len))
    vertical = cv2.morphologyEx(bw, cv2.MORPH_OPEN, kernel, iterations=1)

    contours, _ = cv2.findContours(
        vertical, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    xs: list[float] = []
    min_h = max(24, int(h * min_height_ratio))
    band = y_range
    for cnt in contours:
        x, y, cw, ch = cv2.boundingRect(cnt)
        if ch < min_h or cw > max_width:
            continue
        if ch / max(cw, 1) < 4.0:
            continue
        if band is not None:
            y0, y1 = band
            # require strong overlap with the pitch staff band
            overlap = max(0.0, min(y + ch, y1) - max(y, y0))
            if overlap < 0.45 * (y1 - y0):
                continue
        else:
            # global search: prefer mid-page, not full-height borders
            if y < h * 0.08 and ch > h * 0.45:
                continue
        # skip page-frame borders (left/right edges of the canvas)
        cx = x + cw / 2.0
        if cx < w * 0.03 or cx > w * 0.97:
            continue
        xs.append(cx)

    xs.sort()
    merged: list[float] = []
    for x in xs:
        if not merged or abs(x - merged[-1]) > min_gap:
            merged.append(x)
        else:
            merged[-1] = (merged[-1] + x) / 2.0
    return merged


def pitch_line_y_range(items: list[OcrItem]) -> tuple[float, float] | None:
    """Pick the OCR box most likely to be the jianpu digit line."""
    best: OcrItem | None = None
    best_score = -1.0
    for it in items:
        if it.box is None or not it.text:
            continue
        digits = sum(1 for c in it.text if c in "1234567１２３４５６７")
        cjk = len(re.findall(r"[\u4e00-\u9fff]", it.text))
        if digits < 3:
            continue
        if cjk >= 3 and cjk > digits:
            continue
        score = float(digits) - 0.5 * cjk
        if score > best_score:
            best_score = score
            best = it
    if best is None or best.box is None:
        return None
    # expand a bit
    pad = max(8.0, 0.25 * (best.box.y2 - best.box.y1))
    return (best.box.y1 - pad, best.box.y2 + pad)


def inject_barlines_into_items(
    items: list[OcrItem],
    bar_xs: list[float],
) -> list[OcrItem]:
    """Insert ``|`` into digit-line OCR text using barline x positions."""
    if not bar_xs:
        return items

    out: list[OcrItem] = []
    for it in items:
        text = (it.text or "").strip()
        if it.box is None or not text:
            out.append(it)
            continue
        digit_like = sum(1 for c in text if c in "01234567１２３４５６７０-—－.")
        if digit_like < 3:
            out.append(it)
            continue
        pure_pitch = sum(1 for c in text if c in "1234567１２３４５６７")
        if pure_pitch < 3:
            out.append(it)
            continue

        x1, x2 = it.box.x1, it.box.x2
        width = max(x2 - x1, 1.0)
        n = max(len(text), 1)

        # Only bars that fall strictly inside the digit box
        rel_bars = []
        for bx in bar_xs:
            if bx <= x1 + width * 0.08 or bx >= x2 - width * 0.08:
                continue
            rel_bars.append((bx - x1) / width)

        if not rel_bars:
            out.append(it)
            continue

        # Map relative positions to insert indices between characters
        inserts: list[int] = []
        for rel in rel_bars:
            idx = int(round(rel * n))
            idx = max(1, min(n - 1, idx))
            inserts.append(idx)
        inserts = sorted(set(inserts))

        # Cap bar count — a single staff rarely has > 12 bars
        if len(inserts) > 12:
            out.append(it)
            continue

        chars = list(text)
        for idx in reversed(inserts):
            if 0 < idx < len(chars) and chars[idx] == "|":
                continue
            if idx > 0 and chars[idx - 1] == "|":
                continue
            chars.insert(idx, "|")
        new_text = "".join(chars).replace("|", " | ")
        out.append(OcrItem(text=new_text, score=it.score, box=it.box))
    return out
