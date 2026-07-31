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
    melody_mode: bool = False,
) -> list[float]:
    """Return x-centers of tall thin vertical strokes (candidate barlines).

    ``y_range`` — single staff band; ``y_ranges`` — multi-row systems (#35).
    When bands are set, only strokes that overlap a band are kept.

    ``melody_mode`` (#84): target short/mid barlines that only span the
    **pitch-digit band** (not full staff + lyrics). Uses a shorter
    morphology kernel and lower min-height relative to the band.
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
        avg_bh = sum(b1 - b0 for b0, b1 in bands) / max(len(bands), 1)
        # #84: short bars only need ~35% of melody-band height as kernel
        kern_frac = 0.35 if melody_mode else 0.55
        v_len = max(8 if melody_mode else 10, min(v_len, int(kern_frac * avg_bh)))
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, v_len))
    vertical = cv2.morphologyEx(bw, cv2.MORPH_OPEN, kernel, iterations=1)

    contours, _ = cv2.findContours(
        vertical, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    xs: list[float] = []
    min_h = max(14, int(h * min_height_ratio * 0.7))
    if bands:
        min_band = min(b1 - b0 for b0, b1 in bands)
        # #84: accept bars ≥ ~50% of melody band (was 35% of full system → too tall)
        band_frac = 0.50 if melody_mode else 0.35
        floor = 8 if melody_mode else 10
        min_h = max(floor, min(min_h, int(band_frac * min_band)))

    aspect_min = 2.5 if melody_mode else 3.0
    for cnt in contours:
        x, y, cw, ch = cv2.boundingRect(cnt)
        if ch < min_h or cw > max_width:
            continue
        if ch / max(cw, 1) < aspect_min:
            continue
        cx = x + cw / 2.0
        if cx < w * 0.03 or cx > w * 0.97:
            continue
        if bands:
            ok = False
            for y0, y1 in bands:
                overlap = max(0.0, min(y + ch, y1) - max(y, y0))
                band_h = max(y1 - y0, 1.0)
                # Melody bars: mostly inside band (overlap with band, not full ch)
                if melody_mode:
                    if overlap >= 0.45 * ch or overlap >= 0.40 * band_h:
                        ok = True
                        break
                elif overlap >= 0.35 * band_h or overlap >= 0.6 * ch:
                    ok = True
                    break
            if not ok:
                continue
        else:
            if y < h * 0.08 and ch > h * 0.45:
                continue
        xs.append(cx)

    # Hough supplement for thin printed bars (#35 / #84)
    xs.extend(
        _hough_bar_xs(
            bw,
            bands=bands if bands else None,
            min_gap=min_gap,
            max_width=max_width,
            melody_mode=melody_mode,
        )
    )
    # Column projection only when morph+Hough are sparse (avoid digit false peaks)
    if melody_mode and bands:
        merged_so_far = _merge_xs(xs, min_gap)
        if len(merged_so_far) < 2:
            xs.extend(
                _projection_bar_xs(
                    bw,
                    bands=bands,
                    min_gap=min_gap,
                    max_width=max(3, max_width - 4),
                )
            )
    return _merge_xs(xs, min_gap)


def _hough_bar_xs(
    bw: np.ndarray,
    *,
    bands: list[tuple[float, float]] | None,
    min_gap: float,
    max_width: int,
    melody_mode: bool = False,
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

    if melody_mode and bands:
        avg_bh = sum(b1 - b0 for b0, b1 in bands) / max(len(bands), 1)
        min_len = max(8, int(0.45 * avg_bh))
        thr = 25
    else:
        min_len = max(12, int(h * 0.04))
        thr = 40

    lines = cv2.HoughLinesP(
        roi,
        rho=1,
        theta=np.pi / 180,
        threshold=thr,
        minLineLength=min_len,
        maxLineGap=4,
    )
    if lines is None:
        return []
    xs: list[float] = []
    # OpenCV may return (N,1,4) or (N,4)
    arr = lines.reshape(-1, 4)
    min_dy = 8 if melody_mode else 12
    for x1, y1, x2, y2 in arr:
        x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)
        dx, dy = abs(x2 - x1), abs(y2 - y1)
        if dy < min_dy or dx > max_width:
            continue
        if dy < 3 * max(dx, 1):
            continue  # not vertical enough
        cx = (x1 + x2) / 2.0
        if cx < w * 0.03 or cx > w * 0.97:
            continue
        xs.append(cx)
    return xs


def _projection_bar_xs(
    bw: np.ndarray,
    *,
    bands: list[tuple[float, float]],
    min_gap: float,
    max_width: int,
) -> list[float]:
    """Vertical-ink column peaks inside melody bands (#84 short bars).

    Requires near-full-band column fill so wide digit blobs are rejected.
    """
    h, w = bw.shape[:2]
    col = np.zeros(w, dtype=np.float32)
    band_h = 0.0
    for y0, y1 in bands:
        ya, yb = max(0, int(y0)), min(h, int(y1))
        if yb <= ya:
            continue
        strip = bw[ya:yb, :]
        band_h = max(band_h, float(yb - ya))
        col += (strip > 0).sum(axis=0).astype(np.float32)

    if col.max() < 3 or band_h < 4:
        return []
    # Bar columns fill most of the band height; digit blobs fill less
    thr = max(band_h * 0.55, float(col.max()) * 0.55, 4.0)
    xs: list[float] = []
    i = 1
    while i < w - 1:
        if col[i] >= thr and col[i] >= col[i - 1] and col[i] >= col[i + 1]:
            left = i
            while left > 0 and col[left] >= thr * 0.55:
                left -= 1
            right = i
            while right < w - 1 and col[right] >= thr * 0.55:
                right += 1
            width = right - left
            if 1 <= width <= max_width:
                cx = 0.5 * (left + right)
                if w * 0.03 < cx < w * 0.97:
                    xs.append(float(cx))
            i = right + 1
        else:
            i += 1
    return xs


def estimate_melody_band(
    image_bgr: np.ndarray,
    system_rect: tuple[float, float, float, float],
    *,
    top_frac: float = 0.18,
    bottom_frac: float = 0.28,
) -> tuple[float, float]:
    """Estimate vertical range of pitch-digit band inside a staff system (#84).

    Strategy:
    1. Prefer dense-ink horizontal strip in the middle of the system
       (digit row usually has more compact ink than sparse lyrics).
    2. Fallback: middle strip excluding top ``top_frac`` (chords) and
       bottom ``bottom_frac`` (lyrics).

    Returns ``(y0, y1)`` in image coordinates.
    """
    x1, y1, x2, y2 = system_rect
    ih, iw = image_bgr.shape[:2]
    xa, xb = max(0, int(x1)), min(iw, int(x2))
    ya, yb = max(0, int(y1)), min(ih, int(y2))
    if xb <= xa + 4 or yb <= ya + 4:
        return (float(y1), float(y2))

    gray = cv2.cvtColor(image_bgr[ya:yb, xa:xb], cv2.COLOR_BGR2GRAY)
    _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    row_ink = (bw > 0).sum(axis=1).astype(np.float32)
    sh = len(row_ink)
    if sh < 8 or row_ink.max() < 2:
        # geometric fallback
        y0 = y1 + top_frac * (y2 - y1)
        y1b = y2 - bottom_frac * (y2 - y1)
        if y1b <= y0 + 4:
            return (float(y1), float(y2))
        return (float(y0), float(y1b))

    # Smooth and pick densest contiguous window (~40–55% of system height)
    k = max(3, sh // 12)
    kernel = np.ones(k, dtype=np.float32) / k
    smooth = np.convolve(row_ink, kernel, mode="same")
    win = max(6, int(0.42 * sh))
    win = min(win, sh)
    best_sum = -1.0
    best_i = 0
    csum = np.cumsum(np.insert(smooth, 0, 0.0))
    for i in range(0, sh - win + 1):
        s = csum[i + win] - csum[i]
        if s > best_sum:
            best_sum = s
            best_i = i
    # Slight pad
    pad = max(2, int(0.08 * win))
    a = max(0, best_i - pad)
    b = min(sh, best_i + win + pad)
    return (float(ya + a), float(ya + b))


def gap_soft_bar_xs(
    image_bgr: np.ndarray,
    *,
    y_range: tuple[float, float],
    x_range: tuple[float, float],
    min_gap: float = 36.0,
    max_bars: int = 12,
) -> list[float]:
    """Place soft boundaries at large ink gaps between digit columns (#84).

    Used when few graphic barlines are found. Returns x positions of gap
    centers suitable as pseudo-barlines (not true ink bars).
    """
    if image_bgr is None or image_bgr.size == 0:
        return []
    h, w = image_bgr.shape[:2]
    y0, y1 = y_range
    x0, x1 = x_range
    ya, yb = max(0, int(y0)), min(h, int(y1))
    xa, xb = max(0, int(x0)), min(w, int(x1))
    if yb <= ya + 2 or xb <= xa + 8:
        return []

    gray = cv2.cvtColor(image_bgr[ya:yb, xa:xb], cv2.COLOR_BGR2GRAY)
    _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    col = (bw > 0).sum(axis=0).astype(np.float32)
    if col.max() < 2:
        return []

    thr = max(col.max() * 0.12, 1.0)
    # Find ink runs (digit columns)
    ink = col >= thr
    gaps: list[tuple[int, int, float]] = []  # left, right, width
    i = 0
    n = len(ink)
    while i < n:
        if not ink[i]:
            j = i
            while j < n and not ink[j]:
                j += 1
            width = j - i
            # gap must be interior and reasonably wide
            if i > 2 and j < n - 2 and width >= max(4, int(min_gap * 0.25)):
                gaps.append((i, j, float(width)))
            i = j
        else:
            i += 1

    if not gaps:
        return []
    # Keep largest gaps (bar-sized white space between measures)
    gaps.sort(key=lambda g: -g[2])
    chosen = sorted(gaps[:max_bars], key=lambda g: g[0])
    # Filter: gap center should be reasonably spaced
    xs: list[float] = []
    for left, right, _w in chosen:
        cx = xa + 0.5 * (left + right)
        if not xs or abs(cx - xs[-1]) >= min_gap * 0.6:
            xs.append(float(cx))
        else:
            xs[-1] = 0.5 * (xs[-1] + cx)
    return sorted(xs)


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
