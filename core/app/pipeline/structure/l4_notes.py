"""L4: note position candidates inside each measure (#58).

Uses connected components / projection — geometry only, no OCR yet.
"""

from __future__ import annotations

import cv2
import numpy as np

from app.pipeline.structure.ir import MeasureLayout, NoteCandidate, Rect, StaffSystem


def detect_note_candidates(
    image_bgr: np.ndarray,
    systems: list[StaffSystem],
    *,
    min_area: int = 20,
    max_aspect: float = 3.5,
) -> tuple[list[StaffSystem], list[str]]:
    """Fill each measure with note candidate ROIs (left→right)."""
    warnings: list[str] = []
    if image_bgr is None or image_bgr.size == 0:
        return systems, ["L4: empty image"]

    h, w = image_bgr.shape[:2]
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    out_systems: list[StaffSystem] = []
    total_notes = 0

    for sys in systems:
        new_measures: list[MeasureLayout] = []
        for meas in sys.measures:
            notes = _candidates_in_rect(
                bw,
                meas.rect,
                min_area=min_area,
                max_aspect=max_aspect,
                img_w=w,
                img_h=h,
            )
            total_notes += len(notes)
            new_measures.append(
                MeasureLayout(
                    index=meas.index,
                    rect=meas.rect,
                    barline_x_left=meas.barline_x_left,
                    barline_x_right=meas.barline_x_right,
                    notes=notes,
                    confidence=meas.confidence,
                    extra=dict(meas.extra),
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

    warnings.append(f"L4: {total_notes} note candidate(s) across all measures")
    return out_systems, warnings


def _candidates_in_rect(
    bw: np.ndarray,
    rect: Rect,
    *,
    min_area: int,
    max_aspect: float,
    img_w: int,
    img_h: int,
) -> list[NoteCandidate]:
    x0 = max(0, int(rect.x1))
    y0 = max(0, int(rect.y1))
    x1 = min(img_w, int(rect.x2))
    y1 = min(img_h, int(rect.y2))
    if x1 - x0 < 4 or y1 - y0 < 4:
        return []

    roi = bw[y0:y1, x0:x1]
    # Suppress very tall vertical bar remnants on edges
    contours, _ = cv2.findContours(
        roi, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    boxes: list[Rect] = []
    rh, rw = roi.shape[:2]
    for cnt in contours:
        x, y, cw, ch = cv2.boundingRect(cnt)
        area = cw * ch
        if area < min_area:
            continue
        if ch > 0.85 * rh and cw < 0.12 * rw:
            continue  # barline remnant
        aspect = cw / max(ch, 1)
        if aspect > max_aspect or aspect < 1.0 / max_aspect:
            # allow slightly tall digits
            if not (0.25 <= aspect <= 2.8):
                continue
        # global coords
        boxes.append(
            Rect(
                float(x0 + x),
                float(y0 + y),
                float(x0 + x + cw),
                float(y0 + y + ch),
            )
        )

    if not boxes:
        # Fallback: column projection peaks
        return _projection_candidates(bw, rect, img_w=img_w, img_h=img_h)

    # Sort L→R, merge heavily overlapping
    boxes.sort(key=lambda r: r.x1)
    merged: list[Rect] = []
    for b in boxes:
        if not merged:
            merged.append(b)
            continue
        prev = merged[-1]
        # merge if strong x-overlap (same glyph split)
        if b.x1 < prev.x2 - 0.3 * prev.width:
            merged[-1] = Rect(
                min(prev.x1, b.x1),
                min(prev.y1, b.y1),
                max(prev.x2, b.x2),
                max(prev.y2, b.y2),
            )
        else:
            merged.append(b)

    return [
        NoteCandidate(rect=r.pad(2, w=float(img_w), h=float(img_h)), index=i, confidence=0.55)
        for i, r in enumerate(merged)
    ]


def _projection_candidates(
    bw: np.ndarray,
    rect: Rect,
    *,
    img_w: int,
    img_h: int,
) -> list[NoteCandidate]:
    """Fallback note slots from vertical ink projection peaks."""
    x0 = max(0, int(rect.x1))
    y0 = max(0, int(rect.y1))
    x1 = min(img_w, int(rect.x2))
    y1 = min(img_h, int(rect.y2))
    roi = bw[y0:y1, x0:x1]
    if roi.size == 0:
        return []
    col = (roi > 0).sum(axis=0).astype(np.float32)
    if col.max() <= 0:
        return []
    thr = max(col.max() * 0.25, 1.0)
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
            if i - a0 >= 3:
                bands.append((a0, i))
    if in_run and len(active) - a0 >= 3:
        bands.append((a0, len(active)))

    notes: list[NoteCandidate] = []
    for i, (a, b) in enumerate(bands):
        notes.append(
            NoteCandidate(
                rect=Rect(
                    float(x0 + a),
                    float(y0),
                    float(x0 + b),
                    float(y1),
                ),
                index=i,
                confidence=0.4,
            )
        )
    return notes
