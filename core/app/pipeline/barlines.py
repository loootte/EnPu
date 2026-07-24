"""Detect vertical barlines in a score image (issues #10 / #35)."""

from __future__ import annotations

import re

import cv2
import numpy as np

from app.pipeline.ocr import OcrItem


def _merge_xs(xs: list[float], min_gap: float) -> list[float]:
    xs = sorted(xs)
    merged: list[float] = []
    for x in xs:
        if not merged or abs(x - merged[-1]) > min_gap:
            merged.append(x)
        else:
            merged[-1] = (merged[-1] + x) / 2.0
    return merged


def detect_barline_xs(
    image_bgr: np.ndarray,
    *,
    y_range: tuple[float, float] | None = None,
    y_ranges: list[tuple[float, float]] | None = None,
    min_height_ratio: float = 0.06,
    max_width: int = 10,
    min_gap: float = 28.0,
) -> list[float]:
    """Return x-centers of tall thin vertical strokes (candidate barlines).

    ``y_range`` — single staff band; ``y_ranges`` — multi-row systems (#35).
    When bands are set, only strokes that overlap a band are kept.
    """
    if image_bgr is None or image_bgr.size == 0:
        return []
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape[:2]
    _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    bands: list[tuple[float, float]] = []
    if y_ranges:
        bands = list(y_ranges)
    elif y_range is not None:
        bands = [y_range]

    # Morphology: slightly shorter kernel so per-line bars still register
    v_len = max(12, int(h * min_height_ratio))
    if bands:
        # Prefer kernel ~ 50% of average band height
        avg_bh = sum(b1 - b0 for b0, b1 in bands) / max(len(bands), 1)
        v_len = max(10, min(v_len, int(0.55 * avg_bh)))
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, v_len))
    vertical = cv2.morphologyEx(bw, cv2.MORPH_OPEN, kernel, iterations=1)

    contours, _ = cv2.findContours(
        vertical, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    xs: list[float] = []
    min_h = max(14, int(h * min_height_ratio * 0.7))
    if bands:
        min_h = max(10, min(min_h, int(0.35 * min(b1 - b0 for b0, b1 in bands))))

    for cnt in contours:
        x, y, cw, ch = cv2.boundingRect(cnt)
        if ch < min_h or cw > max_width:
            continue
        if ch / max(cw, 1) < 3.0:
            continue
        cx = x + cw / 2.0
        if cx < w * 0.03 or cx > w * 0.97:
            continue
        if bands:
            ok = False
            for y0, y1 in bands:
                overlap = max(0.0, min(y + ch, y1) - max(y, y0))
                band_h = max(y1 - y0, 1.0)
                if overlap >= 0.35 * band_h or overlap >= 0.6 * ch:
                    ok = True
                    break
            if not ok:
                continue
        else:
            if y < h * 0.08 and ch > h * 0.45:
                continue
        xs.append(cx)

    # Hough supplement for thin printed bars (#35)
    xs.extend(
        _hough_bar_xs(
            bw,
            bands=bands if bands else None,
            min_gap=min_gap,
            max_width=max_width,
        )
    )
    return _merge_xs(xs, min_gap)


def _hough_bar_xs(
    bw: np.ndarray,
    *,
    bands: list[tuple[float, float]] | None,
    min_gap: float,
    max_width: int,
) -> list[float]:
    h, w = bw.shape[:2]
    # Restrict search ROI when bands known
    mask = np.zeros_like(bw)
    if bands:
        for y0, y1 in bands:
            ya, yb = max(0, int(y0)), min(h, int(y1))
            if yb > ya:
                mask[ya:yb, :] = bw[ya:yb, :]
        roi = mask
    else:
        roi = bw

    lines = cv2.HoughLinesP(
        roi,
        rho=1,
        theta=np.pi / 180,
        threshold=40,
        minLineLength=max(12, int(h * 0.04)),
        maxLineGap=4,
    )
    if lines is None:
        return []
    xs: list[float] = []
    # OpenCV may return (N,1,4) or (N,4)
    arr = lines.reshape(-1, 4)
    for x1, y1, x2, y2 in arr:
        x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)
        dx, dy = abs(x2 - x1), abs(y2 - y1)
        if dy < 12 or dx > max_width:
            continue
        if dy < 3 * max(dx, 1):
            continue  # not vertical enough
        cx = (x1 + x2) / 2.0
        if cx < w * 0.03 or cx > w * 0.97:
            continue
        xs.append(cx)
    return xs


def pitch_y_bands_from_items(
    items: list[OcrItem],
    *,
    y_gap: float = 28.0,
) -> list[tuple[float, float]]:
    """Cluster pitch-like OCR boxes into horizontal staff bands (#35 multi-line)."""
    rows: list[tuple[float, float, float]] = []  # cy, y1, y2
    for it in items:
        if it.box is None or not it.text:
            continue
        digits = sum(1 for c in it.text if c in "1234567１２３４５６７")
        if digits < 2:
            continue
        cjk = len(re.findall(r"[\u4e00-\u9fff]", it.text))
        if cjk >= 4 and cjk > digits:
            continue
        cy = (it.box.y1 + it.box.y2) / 2.0
        rows.append((cy, it.box.y1, it.box.y2))
    if not rows:
        return []
    rows.sort(key=lambda t: t[0])
    bands: list[list[tuple[float, float, float]]] = [[rows[0]]]
    for row in rows[1:]:
        prev = bands[-1][-1]
        if abs(row[0] - prev[0]) <= y_gap:
            bands[-1].append(row)
        else:
            bands.append([row])
    out: list[tuple[float, float]] = []
    for group in bands:
        y1 = min(g[1] for g in group)
        y2 = max(g[2] for g in group)
        pad = max(6.0, 0.25 * (y2 - y1))
        out.append((y1 - pad, y2 + pad))
    return out


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
