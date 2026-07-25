"""L1: page-level region split — title / key-time / main score ROI (#58 / #60).

Geometry-first: do **not** treat the first ink as score start (titles are ink too).
Prefer locating **staff-like** horizontal bands (digit-ish components, typical height),
then assign everything above the first staff band to title + key_time.
"""

from __future__ import annotations

import cv2
import numpy as np

from app.pipeline.structure.ir import PageRegion, Rect, RegionRole


def detect_page_regions(
    image_bgr: np.ndarray,
    *,
    top_frac: float = 0.12,
    bottom_frac: float = 0.06,
) -> tuple[list[PageRegion], list[str]]:
    """Split page into title band, key/time band, and main score region.

    Fixes #60 (M04): title was empty because the first dense ink row (the title
    itself) was used as the score start.
    """
    warnings: list[str] = []
    if image_bgr is None or image_bgr.size == 0:
        return [], ["empty image for L1"]

    h, w = image_bgr.shape[:2]
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    # Scan-like pages: Otsu often floods; switch to adaptive (#64)
    ink_ratio = float((bw > 0).mean())
    if ink_ratio > 0.30 or ink_ratio < 0.015:
        bw = cv2.adaptiveThreshold(
            gray,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY_INV,
            35,
            11,
        )
        warnings.append("L1: adaptive threshold for scan-like page (#64)")

    row_ink = (bw > 0).sum(axis=1).astype(np.float32)
    if row_ink.max() <= 0:
        warnings.append("L1: no ink detected; full page as score")
        return [
            PageRegion(
                role=RegionRole.score,
                rect=Rect(0, 0, float(w), float(h)),
                confidence=0.3,
            )
        ], warnings

    # Smooth projection to stabilize run detection
    k = max(5, int(h * 0.004) | 1)  # odd-ish
    if k % 2 == 0:
        k += 1
    kernel = np.ones(k, dtype=np.float32) / float(k)
    smooth = np.convolve(row_ink, kernel, mode="same")

    # Local adaptive thr: fraction of local max in sliding window (helps uneven scans)
    thr_global = max(float(smooth.max()) * 0.10, w * 0.008)
    win = max(31, int(h * 0.08) | 1)
    if win % 2 == 0:
        win += 1
    # 1D max filter via morphology on a column image
    col = smooth.reshape(-1, 1).astype(np.float32)
    local_max = cv2.dilate(col, np.ones((win, 1), np.uint8)).ravel()
    thr_local = np.maximum(local_max * 0.22, thr_global * 0.5)
    active = smooth >= thr_local
    runs = _active_runs(active)
    # Drop tiny noise runs
    min_run = max(4, int(h * 0.003))
    runs = [(a, b) for a, b in runs if b - a >= min_run]

    if not runs:
        y0, y1 = int(h * top_frac), int(h * (1 - bottom_frac))
        warnings.append("L1: no ink runs; fractional fallback")
        return _regions_from_bounds(w, h, title_y1=y0, meta_y1=y0, score_y1=y1), warnings

    # Analyze each run for staff-likeness
    analyzed = [_analyze_run(bw, a, b, page_w=w) for a, b in runs]
    staff_heights = [
        r["height"]
        for r in analyzed
        if r["staff_score"] >= 0.45 and 14 <= r["height"] <= 70
    ]
    med_staff_h = (
        float(np.median(staff_heights)) if staff_heights else max(24.0, h * 0.015)
    )

    # Re-score with median staff height context
    for r in analyzed:
        r["is_title_band"] = _is_title_band(r, h=h, med_staff_h=med_staff_h)
        r["is_staff_band"] = _is_staff_band(r, med_staff_h=med_staff_h)

    # First staff band: prefer first staff-like run not in extreme header,
    # or first of a multi-staff cluster in the upper-mid page.
    score_y0 = _find_score_start(analyzed, h=h, med_staff_h=med_staff_h)
    score_y1 = _find_score_end(analyzed, score_y0=score_y0, h=h, bottom_frac=bottom_frac)

    # Title covers top ink through the last title band above score, or the gap above score
    title_y1 = _find_title_end(analyzed, score_y0=score_y0, h=h, top_frac=top_frac)
    # key/time sits between title and score (may be thin)
    meta_y0 = title_y1
    meta_y1 = max(title_y1 + 1, score_y0)
    # Ensure non-empty title when we detected a title band
    if title_y1 <= int(h * 0.02):
        # Still expand title if first ink is below empty top but before score
        first_ink = analyzed[0]["y0"]
        if first_ink < score_y0:
            title_y1 = max(title_y1, min(score_y0, analyzed[0]["y1"] + max(4, int(0.01 * h))))
            meta_y0 = title_y1
            meta_y1 = max(title_y1 + 1, score_y0)
            warnings.append("L1: expanded title to cover first ink band (#60)")

    if title_y1 >= score_y0:
        # Degenerate: force a minimal title strip above score
        title_y1 = max(int(h * 0.04), score_y0 - max(8, int(0.02 * h)))
        meta_y0 = title_y1
        meta_y1 = score_y0
        warnings.append("L1: title/score overlap clamped")

    warnings.append(
        f"L1: title=0-{title_y1} meta={meta_y0}-{meta_y1} "
        f"score={score_y0}-{score_y1} (staff_h≈{med_staff_h:.0f})"
    )

    return (
        _regions_from_bounds(
            w,
            h,
            title_y1=title_y1,
            meta_y1=meta_y1,
            score_y0=score_y0,
            score_y1=score_y1,
        ),
        warnings,
    )


def _regions_from_bounds(
    w: int,
    h: int,
    *,
    title_y1: int,
    meta_y1: int,
    score_y0: int | None = None,
    score_y1: int | None = None,
) -> list[PageRegion]:
    sy0 = score_y0 if score_y0 is not None else meta_y1
    sy1 = score_y1 if score_y1 is not None else h
    title_y1 = int(np.clip(title_y1, 1, h - 2))
    meta_y1 = int(np.clip(meta_y1, title_y1 + 1, h - 1))
    sy0 = int(np.clip(sy0, meta_y1, h - 1))
    sy1 = int(np.clip(sy1, sy0 + 1, h))
    return [
        PageRegion(
            role=RegionRole.title,
            rect=Rect(0, 0, float(w), float(title_y1)),
            confidence=0.7,
        ),
        PageRegion(
            role=RegionRole.key_time,
            rect=Rect(0, float(title_y1), float(w), float(meta_y1)),
            confidence=0.55,
        ),
        PageRegion(
            role=RegionRole.score,
            rect=Rect(0, float(sy0), float(w), float(sy1)),
            confidence=0.8,
        ),
    ]


def _active_runs(active: np.ndarray) -> list[tuple[int, int]]:
    runs: list[tuple[int, int]] = []
    in_run = False
    a0 = 0
    for i, a in enumerate(active):
        if a and not in_run:
            in_run = True
            a0 = i
        elif not a and in_run:
            in_run = False
            runs.append((a0, i))
    if in_run:
        runs.append((a0, len(active)))
    return runs


def _analyze_run(
    bw: np.ndarray,
    y0: int,
    y1: int,
    *,
    page_w: int,
) -> dict:
    """Ink / component stats for one horizontal band."""
    h = max(1, y1 - y0)
    strip = bw[y0:y1, :]
    ink = float((strip > 0).sum())
    num, _labels, stats, _ = cv2.connectedComponentsWithStats(strip, connectivity=8)
    comps: list[tuple[int, int, int]] = []
    for i in range(1, num):
        _x, _y, cw, ch, area = stats[i]
        if area < 25:
            continue
        comps.append((int(cw), int(ch), int(area)))

    dig = 0
    chs: list[float] = []
    for cw, ch, _area in comps:
        chs.append(float(ch))
        aspect = cw / max(ch, 1)
        # Digit-like or CJK block of similar height
        if 10 <= ch <= 100 and 0.2 <= aspect <= 2.2:
            dig += 1

    med_ch = float(np.median(chs)) if chs else float(h)
    # Staff score: many mid-size comps, band height in staff range
    staff_score = 0.0
    if dig >= 6 and 16 <= h <= 65:
        staff_score = 0.55 + min(0.4, 0.02 * dig)
    elif dig >= 3 and 14 <= h <= 70:
        staff_score = 0.4
    if 20 <= med_ch <= 45 and dig >= 4:
        staff_score = max(staff_score, 0.5)

    return {
        "y0": y0,
        "y1": y1,
        "height": h,
        "ink": ink,
        "n_comps": len(comps),
        "n_digitish": dig,
        "med_ch": med_ch,
        "staff_score": staff_score,
        "is_title_band": False,
        "is_staff_band": False,
    }


def _is_title_band(r: dict, *, h: int, med_staff_h: float) -> bool:
    """Title: upper page, often taller than a single staff row.

    Scans (#64): titles may be shorter than print M04; use position + fewer
    digitish comps + larger median glyph when possible.
    """
    if r["y0"] > 0.28 * h:
        return False
    tall = r["height"] >= max(28.0, 1.25 * med_staff_h)
    big_glyphs = r["med_ch"] >= max(24.0, 1.1 * med_staff_h) and r["n_comps"] >= 6
    # Top strip with moderate comps but not staff-dense
    top_sparse = (
        r["y0"] < 0.12 * h
        and r["n_digitish"] <= 8
        and r["staff_score"] < 0.5
        and r["height"] >= max(18.0, 0.7 * med_staff_h)
    )
    return bool(tall or big_glyphs or top_sparse)


def _is_staff_band(r: dict, *, med_staff_h: float) -> bool:
    if r["staff_score"] >= 0.45:
        return True
    # Typical jianpu staff row height
    if 16 <= r["height"] <= 70 and r["n_digitish"] >= 5:
        if abs(r["height"] - med_staff_h) <= 0.55 * med_staff_h:
            return True
    return False


def _find_score_start(analyzed: list[dict], *, h: int, med_staff_h: float) -> int:
    """Y where main score body begins (first staff-like band after title)."""
    staff_idxs = [i for i, r in enumerate(analyzed) if r["is_staff_band"]]
    if not staff_idxs:
        # Fallback: first run after top 8% that is not title-like
        for r in analyzed:
            if r["y0"] >= 0.08 * h and not r["is_title_band"]:
                return int(r["y0"])
        return int(analyzed[0]["y0"])

    # Prefer first staff band after any leading title band(s)
    for i in staff_idxs:
        r = analyzed[i]
        # Skip staff-like false positive on title (tall + digitish CJK)
        if r["is_title_band"] and r["y0"] < 0.16 * h:
            continue
        # Prefer bands that have nearby following staff bands (real systems)
        followers = [
            analyzed[j]
            for j in staff_idxs
            if j > i and analyzed[j]["y0"] - r["y1"] < 4.5 * med_staff_h
        ]
        # Multi-staff cluster is strong evidence of score body (#64 scans)
        if len(followers) >= 1:
            return int(r["y0"])
        if r["y0"] >= 0.10 * h and not r["is_title_band"]:
            return int(r["y0"])

    # If all early staff candidates look title-like, take first staff after 12%
    for i in staff_idxs:
        if analyzed[i]["y0"] >= 0.12 * h:
            return int(analyzed[i]["y0"])

    return int(analyzed[staff_idxs[0]]["y0"])


def _find_score_end(
    analyzed: list[dict],
    *,
    score_y0: int,
    h: int,
    bottom_frac: float,
) -> int:
    last = score_y0 + 8
    for r in analyzed:
        if r["y1"] <= score_y0:
            continue
        if r["y0"] > h * (1.0 - bottom_frac):
            break
        last = max(last, r["y1"])
    return min(h, max(last + 4, int(h * (1.0 - bottom_frac))))


def _find_title_end(
    analyzed: list[dict],
    *,
    score_y0: int,
    h: int,
    top_frac: float,
) -> int:
    """Bottom of title region: cover title band(s) above score_y0."""
    title_runs = [
        r
        for r in analyzed
        if r["y1"] <= score_y0 + 2 and (r["is_title_band"] or r["y0"] < 0.12 * h)
    ]
    if title_runs:
        # Use the first contiguous header block (title), not all pre-score runs
        # (key/time may sit between title and score).
        first = title_runs[0]
        y1 = first["y1"]
        # Merge immediately following header runs if still title-like / close
        for r in title_runs[1:]:
            if r["y0"] - y1 <= max(12, int(0.01 * h)) and (
                r["is_title_band"] or r["height"] >= first["height"] * 0.5
            ):
                y1 = r["y1"]
            else:
                break
        pad = max(6, int(0.006 * h))
        return min(score_y0, y1 + pad)

    # No clear title band: keep a small top strip only if score starts lower
    if score_y0 > int(h * 0.08):
        return max(int(h * 0.04), min(score_y0, int(h * top_frac)))
    return max(1, int(h * 0.03))
