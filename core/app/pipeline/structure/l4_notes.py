"""L4: note / chord / lyric candidates inside each measure (#58 / #69).

**Note (pitch) ROIs** are restricted to the L2 **pitch band** (plus a small
pad for underlines / octave dots). They must **not** swallow chord or lyric
glyphs in the same vertical stack.

Chord and lyric bands produce **separate** L4 candidates (`kind=chord|lyric`)
for overlay / later OCR — they are not merged into pitch note ROIs.
"""

from __future__ import annotations

from typing import Any, Literal

import cv2
import numpy as np

from app.pipeline.structure.ir import MeasureLayout, NoteCandidate, Rect, StaffSystem

CandidateKind = Literal["pitch", "chord", "lyric"]


def detect_note_candidates(
    image_bgr: np.ndarray,
    systems: list[StaffSystem],
    *,
    min_area: int = 18,
    max_aspect: float = 3.5,
) -> tuple[list[StaffSystem], list[str]]:
    """Fill each measure with pitch note ROIs (+ optional chord/lyric slots)."""
    warnings: list[str] = []
    if image_bgr is None or image_bgr.size == 0:
        return systems, ["L4: empty image"]

    h, w = image_bgr.shape[:2]
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    out_systems: list[StaffSystem] = []
    total_pitch = 0
    total_aux = 0

    for sys in systems:
        band_ranges = _band_y_ranges(sys)
        pitch_y = band_ranges.get("pitch")
        new_measures: list[MeasureLayout] = []
        for meas in sys.measures:
            pitch_notes = _pitch_candidates_in_measure(
                bw,
                meas.rect,
                pitch_y=pitch_y,
                system_rect=sys.rect,
                min_area=min_area,
                max_aspect=max_aspect,
                img_w=w,
                img_h=h,
            )
            aux: list[NoteCandidate] = []
            for role in ("chord", "lyric"):
                by = band_ranges.get(role)
                if by is None:
                    continue
                aux.extend(
                    _aux_candidates_in_measure(
                        bw,
                        meas.rect,
                        band_y=by,
                        kind=role,  # type: ignore[arg-type]
                        min_area=max(12, min_area // 2),
                        img_w=w,
                        img_h=h,
                        index_start=len(pitch_notes) + len(aux),
                    )
                )
            # Reindex pitch first, then aux (stable for L5 which only OCRs pitch)
            notes: list[NoteCandidate] = []
            for i, n in enumerate(pitch_notes):
                notes.append(
                    NoteCandidate(
                        rect=n.rect,
                        index=i,
                        glyph=n.glyph,
                        confidence=n.confidence,
                        extra=dict(n.extra),
                    )
                )
            base = len(notes)
            for j, n in enumerate(aux):
                notes.append(
                    NoteCandidate(
                        rect=n.rect,
                        index=base + j,
                        glyph=n.glyph,
                        confidence=n.confidence,
                        extra=dict(n.extra),
                    )
                )
            total_pitch += len(pitch_notes)
            total_aux += len(aux)
            new_measures.append(
                MeasureLayout(
                    index=meas.index,
                    rect=meas.rect,
                    barline_x_left=meas.barline_x_left,
                    barline_x_right=meas.barline_x_right,
                    notes=notes,
                    confidence=meas.confidence,
                    extra={
                        **dict(meas.extra),
                        "n_pitch_candidates": len(pitch_notes),
                        "n_aux_candidates": len(aux),
                    },
                )
            )
        out_systems.append(
            StaffSystem(
                index=sys.index,
                rect=sys.rect,
                measures=new_measures,
                barline_xs=list(sys.barline_xs),
                confidence=sys.confidence,
                extra=dict(sys.extra),
            )
        )

    warnings.append(
        f"L4: {total_pitch} pitch + {total_aux} chord/lyric candidate(s) "
        f"(pitch band only for notes #69)"
    )
    return out_systems, warnings


def _band_y_ranges(sys: StaffSystem) -> dict[str, tuple[float, float]]:
    """Map role → (y0, y1) from L2 band metadata."""
    out: dict[str, tuple[float, float]] = {}
    bands = sys.extra.get("bands") or []
    for b in bands:
        role = b.get("role")
        if role not in {"pitch", "chord", "lyric", "underline"}:
            continue
        y0, y1 = float(b["y0"]), float(b["y1"])
        if role in out:
            py0, py1 = out[role]
            out[role] = (min(py0, y0), max(py1, y1))
        else:
            out[role] = (y0, y1)
    return out


def _pitch_body_y(
    pitch_y: tuple[float, float] | None,
    system_rect: Rect,
    meas_rect: Rect,
) -> tuple[float, float]:
    """Y range for **detecting** digit bodies only (exclude continuous underlines).

    Duration underlines are a horizontal stroke under the whole staff; including
    them in the CC ROI glues multiple digits into one wide blob.
    """
    if pitch_y is not None:
        y0, y1 = pitch_y
        h = max(8.0, y1 - y0)
        # Slight pad for octave dots / digit tops; keep bottom at digit body
        y0 = y0 - 0.25 * h
        y1 = y1 + 0.08 * h
    else:
        y0 = system_rect.y1
        y1 = system_rect.y1 + 0.38 * max(system_rect.height, 1.0)
    y0 = max(meas_rect.y1, y0)
    y1 = min(meas_rect.y2, y1)
    if y1 - y0 < 8:
        y0, y1 = meas_rect.y1, meas_rect.y1 + min(
            meas_rect.height * 0.35, system_rect.height * 0.35
        )
    return y0, y1


def _pitch_candidates_in_measure(
    bw: np.ndarray,
    meas_rect: Rect,
    *,
    pitch_y: tuple[float, float] | None,
    system_rect: Rect,
    min_area: int,
    max_aspect: float,
    img_w: int,
    img_h: int,
) -> list[NoteCandidate]:
    # Detect on digit body only (no underline glue)
    by0, by1 = _pitch_body_y(pitch_y, system_rect, meas_rect)
    search = Rect(meas_rect.x1, by0, meas_rect.x2, by1)
    boxes = _digit_like_boxes(
        bw,
        search,
        min_area=min_area,
        max_aspect=max_aspect,
        img_w=img_w,
        img_h=img_h,
        prefer_height=True,
    )
    if not boxes:
        boxes = _column_peak_boxes(
            bw,
            search,
            img_w=img_w,
            img_h=img_h,
            full_height=False,
        )
    clamped: list[Rect] = []
    for b in boxes:
        cy0 = max(b.y1, by0)
        cy1 = min(b.y2, by1)
        if cy1 - cy0 < 4:
            continue
        clamped.append(Rect(b.x1, cy0, b.x2, cy1))
    merged = _merge_horizontal_same_row(clamped, y_tol_factor=0.55)
    # Reject absurdly wide boxes (multiple notes glued) → re-split by projection
    final: list[Rect] = []
    heights = [r.height for r in merged if r.height >= 8]
    med_h = float(np.median(heights)) if heights else 20.0
    # Jianpu digits are roughly square-ish; wider → multiple notes glued
    max_w = max(22.0, 1.15 * med_h)
    for r in merged:
        if r.width <= max_w * 1.25:
            final.append(r)
            continue
        sub = _column_peak_boxes(
            bw,
            r,
            img_w=img_w,
            img_h=img_h,
            full_height=False,
        )
        # Keep only subs that look like single digits
        sub = [s for s in sub if s.width <= max_w * 1.4]
        if len(sub) >= 2:
            final.extend(sub)
        else:
            n_est = max(2, int(np.ceil(r.width / max(max_w, 1.0))))
            slot = r.width / n_est
            for k in range(n_est):
                final.append(
                    Rect(
                        r.x1 + k * slot,
                        r.y1,
                        r.x1 + (k + 1) * slot if k < n_est - 1 else r.x2,
                        r.y2,
                    )
                )
    final.sort(key=lambda r: r.x1)
    band_mid = 0.5 * (by0 + by1)
    band_h = max(by1 - by0, 1.0)
    filtered: list[Rect] = []
    for r in final:
        if r.width < 4 or r.height < 6:
            continue
        if abs(r.cy - band_mid) > 0.55 * band_h:
            continue
        filtered.append(r)
    final = filtered

    # Expand final ROIs for L5 (underline below + octave dots above) without
    # expanding so far that chord/lyric bands enter the box.
    chord_top = None
    # system_rect.y2 is full system; use body bottom + limited pad
    out: list[NoteCandidate] = []
    for i, r in enumerate(final):
        pad_x = max(2.0, 0.12 * r.width)
        pad_top = max(3.0, 0.22 * r.height)
        pad_bot = max(4.0, 0.45 * r.height)  # duration underlines under digit
        # Cap bottom so we do not reach typical chord band (~pitch+1.5*h)
        max_bot = r.y2 + max(14.0, 0.7 * r.height)
        if pitch_y is not None:
            max_bot = min(max_bot, pitch_y[1] + max(12.0, 0.55 * (pitch_y[1] - pitch_y[0])))
        pr = Rect(
            max(0.0, r.x1 - pad_x),
            max(0.0, r.y1 - pad_top),
            min(float(img_w), r.x2 + pad_x),
            min(float(img_h), min(max_bot, r.y2 + pad_bot)),
        )
        # Never deeper than mid-gap toward chord (if system tall)
        if system_rect.height > 2.5 * band_h:
            pr = Rect(
                pr.x1,
                pr.y1,
                pr.x2,
                min(pr.y2, by1 + max(10.0, 0.5 * band_h)),
            )
        out.append(
            NoteCandidate(
                rect=pr,
                index=i,
                confidence=0.65,
                extra={"kind": "pitch", "layer": "L4"},
            )
        )
    _ = chord_top
    return out


def _aux_candidates_in_measure(
    bw: np.ndarray,
    meas_rect: Rect,
    *,
    band_y: tuple[float, float],
    kind: CandidateKind,
    min_area: int,
    img_w: int,
    img_h: int,
    index_start: int,
) -> list[NoteCandidate]:
    y0 = max(meas_rect.y1, band_y[0] - 2)
    y1 = min(meas_rect.y2, band_y[1] + 2)
    if y1 - y0 < 6:
        return []
    search = Rect(meas_rect.x1, y0, meas_rect.x2, y1)
    boxes = _digit_like_boxes(
        bw,
        search,
        min_area=min_area,
        max_aspect=4.0,
        img_w=img_w,
        img_h=img_h,
        prefer_height=False,
    )
    if not boxes:
        boxes = _column_peak_boxes(
            bw, search, img_w=img_w, img_h=img_h, full_height=True
        )
    boxes = _merge_horizontal_same_row(boxes, y_tol_factor=0.7)
    out: list[NoteCandidate] = []
    for i, r in enumerate(boxes):
        # Keep aux strictly in band y
        r2 = Rect(r.x1, max(r.y1, y0), r.x2, min(r.y2, y1))
        if r2.height < 4 or r2.width < 3:
            continue
        out.append(
            NoteCandidate(
                rect=r2.pad(1, w=float(img_w), h=float(img_h)),
                index=index_start + i,
                confidence=0.5,
                extra={"kind": kind, "layer": "L4"},
            )
        )
    return out


def _digit_like_boxes(
    bw: np.ndarray,
    rect: Rect,
    *,
    min_area: int,
    max_aspect: float,
    img_w: int,
    img_h: int,
    prefer_height: bool,
) -> list[Rect]:
    x0 = max(0, int(rect.x1))
    y0 = max(0, int(rect.y1))
    x1 = min(img_w, int(rect.x2))
    y1 = min(img_h, int(rect.y2))
    if x1 - x0 < 4 or y1 - y0 < 4:
        return []
    roi = bw[y0:y1, x0:x1]
    rh, rw = roi.shape[:2]
    contours, _ = cv2.findContours(
        roi, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    boxes: list[Rect] = []
    # Typical digit height is a large fraction of the pitch strip
    med_target_h = rh * 0.55 if prefer_height else rh * 0.7
    for cnt in contours:
        x, y, cw, ch = cv2.boundingRect(cnt)
        area = cw * ch
        if area < min_area:
            continue
        # Full-height thin = barline
        if ch > 0.85 * rh and cw < 0.08 * max(rw, 1):
            continue
        aspect = cw / max(ch, 1)
        if aspect > max_aspect or aspect < 0.12:
            if not (0.18 <= aspect <= 3.2):
                continue
        if prefer_height:
            # Reject tiny noise and very short (underline-only) strokes
            if ch < 0.28 * rh and ch < 10:
                continue
            # Reject extremely wide multi-glyph blobs (handled by split later)
            if cw > 0.55 * rw and ch < 0.9 * rh:
                # still keep; splitter will break
                pass
        boxes.append(
            Rect(
                float(x0 + x),
                float(y0 + y),
                float(x0 + x + cw),
                float(y0 + y + ch),
            )
        )
    boxes.sort(key=lambda r: r.x1)
    _ = med_target_h
    return boxes


def _column_peak_boxes(
    bw: np.ndarray,
    rect: Rect,
    *,
    img_w: int,
    img_h: int,
    full_height: bool,
) -> list[Rect]:
    """Note slots from vertical ink projection peaks within rect."""
    x0 = max(0, int(rect.x1))
    y0 = max(0, int(rect.y1))
    x1 = min(img_w, int(rect.x2))
    y1 = min(img_h, int(rect.y2))
    if x1 - x0 < 4 or y1 - y0 < 4:
        return []
    roi = bw[y0:y1, x0:x1]
    col = (roi > 0).sum(axis=0).astype(np.float32)
    if col.max() <= 0:
        return []
    thr = max(col.max() * 0.22, 1.0)
    active = col >= thr
    bands: list[tuple[int, int]] = []
    in_run = False
    a0 = 0
    for i, a in enumerate(active):
        if a and not in_run:
            in_run = True
            a0 = i
        elif not a and in_run:
            in_run = False
            if i - a0 >= 2:
                bands.append((a0, i))
    if in_run and len(active) - a0 >= 2:
        bands.append((a0, len(active)))

    rh = y1 - y0
    boxes: list[Rect] = []
    for a, b in bands:
        # Tight y from local row ink inside the column span
        strip = roi[:, a:b]
        if strip.size == 0:
            continue
        row = (strip > 0).sum(axis=1)
        rthr = max(1.0, 0.15 * (b - a))
        ys = np.where(row >= rthr)[0]
        if ys.size == 0 or full_height:
            gy0, gy1 = float(y0), float(y1)
        else:
            gy0 = float(y0 + max(0, int(ys[0]) - 1))
            gy1 = float(y0 + min(rh, int(ys[-1]) + 2))
        boxes.append(
            Rect(float(x0 + a), gy0, float(x0 + b), gy1)
        )
    return boxes


def _merge_horizontal_same_row(
    boxes: list[Rect],
    *,
    y_tol_factor: float,
) -> list[Rect]:
    """Merge only fragments of the **same glyph** (strong x-overlap + similar y).

    Does **not** union vertically stacked chord/lyric into pitch.
    """
    if not boxes:
        return []
    boxes = sorted(boxes, key=lambda r: (r.x1, r.y1))
    merged: list[Rect] = []
    for b in boxes:
        if not merged:
            merged.append(b)
            continue
        prev = merged[-1]
        y_tol = y_tol_factor * min(prev.height, b.height)
        same_row = abs(prev.cy - b.cy) <= y_tol
        # Strong horizontal overlap → same split glyph
        overlap = min(prev.x2, b.x2) - max(prev.x1, b.x1)
        min_w = min(prev.width, b.width)
        strong_x = overlap > 0.45 * min_w
        # Very small gap between fragments of one digit
        gap = b.x1 - prev.x2
        tiny_gap = gap <= max(2.0, 0.12 * min(prev.height, b.height)) and same_row
        if same_row and (strong_x or tiny_gap):
            merged[-1] = Rect(
                min(prev.x1, b.x1),
                min(prev.y1, b.y1),
                max(prev.x2, b.x2),
                max(prev.y2, b.y2),
            )
        else:
            merged.append(b)
    return merged
