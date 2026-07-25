"""L5: per-note glyph — local OCR pitch + geometric underlines / octave dots (#58)."""

from __future__ import annotations

import logging
import re

import cv2
import numpy as np

from app.pipeline.ocr import OcrEngineError, get_ocr_engine
from app.pipeline.structure.ir import (
    NoteCandidate,
    NoteGlyph,
    StaffSystem,
)
from app.schemas.score import DurationName

logger = logging.getLogger(__name__)

_DIGIT_RE = re.compile(r"[1-7]")
_FULLWIDTH = str.maketrans("１２３４５６７０", "12345670")


def fill_note_glyphs(
    image_bgr: np.ndarray,
    systems: list[StaffSystem],
    *,
    engine_name: str = "paddleocr",
    lang: str = "ch",
    use_angle_cls: bool = True,
    use_gpu: bool = False,
) -> tuple[list[StaffSystem], list[str]]:
    """Run L5 on each note candidate ROI."""
    warnings: list[str] = []
    if image_bgr is None or image_bgr.size == 0:
        return systems, ["L5: empty image"]

    try:
        engine = get_ocr_engine(
            engine_name,
            lang=lang,
            use_angle_cls=use_angle_cls,
            use_gpu=use_gpu,
        )
    except OcrEngineError as exc:
        warnings.append(f"L5: OCR engine unavailable ({exc}); geometry-only glyphs")
        engine = None

    h, w = image_bgr.shape[:2]
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    n_ocr = 0
    n_pitch = 0
    out_systems: list[StaffSystem] = []

    for sys in systems:
        new_measures = []
        for meas in sys.measures:
            new_notes: list[NoteCandidate] = []
            for nc in meas.notes:
                kind = (nc.extra or {}).get("kind", "pitch")
                # #69: only OCR pitch-note ROIs; chord/lyric keep empty glyph for overlay
                if kind != "pitch":
                    new_notes.append(
                        NoteCandidate(
                            rect=nc.rect,
                            index=nc.index,
                            glyph=None,
                            confidence=nc.confidence,
                            extra=dict(nc.extra),
                        )
                    )
                    continue
                glyph = _glyph_for_candidate(
                    image_bgr,
                    bw,
                    nc,
                    engine=engine,
                    img_w=w,
                    img_h=h,
                )
                if glyph.ocr_text:
                    n_ocr += 1
                if glyph.pitch:
                    n_pitch += 1
                new_notes.append(
                    NoteCandidate(
                        rect=nc.rect,
                        index=nc.index,
                        glyph=glyph,
                        confidence=glyph.confidence,
                        extra=dict(nc.extra),
                    )
                )
            from app.pipeline.structure.ir import MeasureLayout

            new_measures.append(
                MeasureLayout(
                    index=meas.index,
                    rect=meas.rect,
                    barline_x_left=meas.barline_x_left,
                    barline_x_right=meas.barline_x_right,
                    notes=new_notes,
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

    warnings.append(
        f"L5: OCR on note ROIs → {n_pitch} pitch(es) from {n_ocr} non-empty OCR"
    )
    return out_systems, warnings


def _glyph_for_candidate(
    image_bgr: np.ndarray,
    bw: np.ndarray,
    nc: NoteCandidate,
    *,
    engine: object | None,
    img_w: int,
    img_h: int,
) -> NoteGlyph:
    x0 = max(0, int(nc.rect.x1))
    y0 = max(0, int(nc.rect.y1))
    x1 = min(img_w, int(nc.rect.x2))
    y1 = min(img_h, int(nc.rect.y2))
    extra = nc.extra or {}
    # Prefer tight digit body for OCR (from L4); fall back to note rect
    bx0 = int(extra.get("body_x0", x0))
    bx1 = int(extra.get("body_x1", x1))
    by0 = int(extra.get("body_y0", y0))
    by1 = int(extra.get("body_y1", y1))
    body_h = max(4, by1 - by0)
    body_w = max(4, bx1 - bx0)

    pitch = None
    is_rest = False
    ocr_text = ""
    ocr_score = None
    if engine is not None:
        pitch, is_rest, ocr_text, ocr_score = _ocr_pitch_on_body(
            image_bgr,
            bx0,
            by0,
            bx1,
            by1,
            engine=engine,
            img_w=img_w,
            img_h=img_h,
        )

    # Underlines: only strokes **below** the digit body (not digit ink itself)
    underlines = _count_underlines_below_body(
        bw,
        x0=max(0, bx0 - 2),
        x1=min(img_w, bx1 + 2),
        body_y1=by1,
        body_h=body_h,
        underline_band_y0=extra.get("underline_band_y0"),
        underline_band_y1=extra.get("underline_band_y1"),
        img_h=img_h,
    )
    # Octave dots: small pad above body inside note rect
    top_y0 = max(0, by0 - max(4, int(0.35 * body_h)))
    top_roi = bw[top_y0:by0, max(0, bx0 - 2) : min(img_w, bx1 + 2)]
    bot_roi = bw[
        by1 : min(img_h, by1 + max(3, int(0.2 * body_h))),
        max(0, bx0 - 2) : min(img_w, bx1 + 2),
    ]
    octave = _octave_from_strips(top_roi, bot_roi, body_w=body_w, body_h=body_h)
    duration = _duration_from_underlines(underlines)

    conf = 0.4
    if pitch or is_rest:
        conf = 0.75 if (ocr_score or 0) > 0.5 else 0.55
    conf = min(0.95, conf + 0.05 * underlines)

    return NoteGlyph(
        pitch=None if is_rest else pitch,
        is_rest=is_rest,
        duration=duration,
        dots=0,
        octave=octave,
        underlines=underlines,
        ocr_text=ocr_text,
        ocr_score=ocr_score,
        confidence=conf,
        extra={"duration_from": "underline" if underlines else "default"},
    )


def _ocr_pitch_on_body(
    image_bgr: np.ndarray,
    bx0: int,
    by0: int,
    bx1: int,
    by1: int,
    *,
    engine: object,
    img_w: int,
    img_h: int,
) -> tuple[str | None, bool, str, float | None]:
    """OCR a tight digit body crop; retry with padding if empty."""
    attempts = [
        (2, 2),
        (4, 4),
        (6, 8),
    ]
    best_text = ""
    best_score: float | None = None
    for pad_x, pad_y in attempts:
        xa = max(0, bx0 - pad_x)
        xb = min(img_w, bx1 + pad_x)
        ya = max(0, by0 - pad_y)
        yb = min(img_h, by1 + pad_y)
        if xb - xa < 3 or yb - ya < 3:
            continue
        roi = image_bgr[ya:yb, xa:xb]
        rh, rw = roi.shape[:2]
        # Upscale small digits aggressively for PaddleOCR
        target = 64
        if max(rh, rw) < target:
            scale = target / max(rh, rw, 1)
            roi = cv2.resize(
                roi,
                (max(1, int(rw * scale)), max(1, int(rh * scale))),
                interpolation=cv2.INTER_CUBIC,
            )
        try:
            result = engine.run(roi)  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001
            logger.debug("L5 OCR ROI failed: %s", exc)
            continue
        texts = [it.text for it in result.items if it.text]
        text = " ".join(texts).strip()
        scores = [it.score for it in result.items if it.score is not None]
        score = float(sum(scores) / len(scores)) if scores else None
        pitch, is_rest = _parse_pitch_token(text)
        if pitch or is_rest:
            return pitch, is_rest, text, score
        if text and (not best_text or (score or 0) > (best_score or 0)):
            best_text = text
            best_score = score
    pitch, is_rest = _parse_pitch_token(best_text)
    return pitch, is_rest, best_text, best_score


def _parse_pitch_token(text: str) -> tuple[str | None, bool]:
    t = (text or "").translate(_FULLWIDTH).strip()
    if not t:
        return None, False
    if "0" in t and not _DIGIT_RE.search(t.replace("0", "")):
        return None, True
    m = _DIGIT_RE.search(t)
    if m:
        return m.group(0), False
    return None, False


def _duration_from_underlines(n: int) -> DurationName:
    if n >= 2:
        return DurationName.sixteenth
    if n == 1:
        return DurationName.eighth
    return DurationName.quarter


def _count_underlines_below_body(
    bw: np.ndarray,
    *,
    x0: int,
    x1: int,
    body_y1: int,
    body_h: int,
    underline_band_y0: float | None,
    underline_band_y1: float | None,
    img_h: int,
) -> int:
    """Count duration underlines strictly **below** the digit body.

    Jianpu eighths have a thin stroke under the digit; counting inside the
    digit ROI lower half wrongly treats digit strokes as underlines (often
    +1 → eighth becomes sixteenth).
    """
    if x1 - x0 < 3:
        return 0
    # Search window just under the body
    y0 = body_y1 + 1
    y1 = body_y1 + max(8, int(0.75 * body_h))
    if underline_band_y0 is not None and underline_band_y1 is not None:
        # Prefer L2 underline band when it sits under this staff
        uy0, uy1 = int(underline_band_y0), int(underline_band_y1)
        if uy0 >= body_y1 - 2 and uy0 <= body_y1 + max(24, int(0.9 * body_h)):
            y0 = min(y0, uy0 - 1)
            y1 = max(y1, uy1 + 2)
    y0 = max(0, y0)
    y1 = min(img_h, y1)
    if y1 - y0 < 2:
        return 0

    strip = bw[y0:y1, x0:x1]
    if strip.size == 0:
        return 0
    rh, rw = strip.shape[:2]
    # Thin horizontal morphology
    k_w = max(3, int(rw * 0.45))
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (k_w, 1))
    horiz = cv2.morphologyEx(strip, cv2.MORPH_OPEN, kernel, iterations=1)
    row_sum = (horiz > 0).sum(axis=1).astype(np.float32)
    # Require stroke spanning a good fraction of digit width
    thr = max(2.0, 0.35 * rw)
    active = row_sum >= thr

    # Collect run centers; merge runs within 3px (one thick underline)
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

    if not runs:
        # Fallback: raw ink row without morphology (very thin underlines)
        raw = (strip > 0).sum(axis=1).astype(np.float32)
        thr2 = max(2.0, 0.45 * rw)
        active2 = raw >= thr2
        runs = []
        in_run = False
        a0 = 0
        for i, a in enumerate(active2):
            if a and not in_run:
                in_run = True
                a0 = i
            elif not a and in_run:
                in_run = False
                if i - a0 <= 4:  # thin stroke
                    runs.append((a0, i))
        if in_run and len(active2) - a0 <= 4:
            runs.append((a0, len(active2)))

    if not runs:
        return 0

    # Merge nearby runs (same underline)
    merged: list[float] = []
    for a, b in runs:
        cy = 0.5 * (a + b)
        if not merged or cy - merged[-1] > 3.5:
            merged.append(cy)
        else:
            merged[-1] = 0.5 * (merged[-1] + cy)
    return min(2, len(merged))


def _octave_from_strips(
    top: np.ndarray,
    bot: np.ndarray,
    *,
    body_w: int,
    body_h: int,
) -> int:
    """Rough octave: upper dots − lower dots (clamped -2..2)."""

    def n_blobs(region: np.ndarray) -> int:
        if region is None or region.size == 0:
            return 0
        contours, _ = cv2.findContours(
            region, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        n = 0
        max_area = max(12, 0.2 * body_w * body_h)
        for cnt in contours:
            _x, _y, cw, ch = cv2.boundingRect(cnt)
            area = cw * ch
            if area < 4 or area > max_area:
                continue
            if max(cw, ch) / max(min(cw, ch), 1) > 2.2:
                continue
            n += 1
        return n

    return int(max(-2, min(2, n_blobs(top) - n_blobs(bot))))


def _count_underlines(roi_bw: np.ndarray) -> int:
    """Legacy helper (tests): approximate with lower-half strip of a ROI."""
    if roi_bw.size == 0:
        return 0
    h, w = roi_bw.shape[:2]
    # Assume body ends ~mid ROI; count below
    body_y1 = int(h * 0.55)
    # Build a fake full image strip by embedding roi
    return _count_underlines_below_body(
        roi_bw,
        x0=0,
        x1=w,
        body_y1=body_y1,
        body_h=max(4, body_y1),
        underline_band_y0=None,
        underline_band_y1=None,
        img_h=h,
    )
