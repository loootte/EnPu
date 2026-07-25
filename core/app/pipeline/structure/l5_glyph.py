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
    # Expand ROI for underlines / octave dots
    pad_x = max(2, int(0.2 * (x1 - x0)))
    pad_y = max(4, int(0.55 * (y1 - y0)))
    xa, xb = max(0, x0 - pad_x), min(img_w, x1 + pad_x)
    ya, yb = max(0, y0 - pad_y), min(img_h, y1 + pad_y)
    if xb <= xa or yb <= ya:
        return NoteGlyph(confidence=0.1)

    roi_bgr = image_bgr[ya:yb, xa:xb]
    roi_bw = bw[ya:yb, xa:xb]

    pitch = None
    is_rest = False
    ocr_text = ""
    ocr_score = None
    if engine is not None:
        try:
            # Upscale tiny ROIs for OCR stability
            rh, rw = roi_bgr.shape[:2]
            scale = 1.0
            if max(rh, rw) < 48:
                scale = 48.0 / max(rh, rw, 1)
                roi_bgr = cv2.resize(
                    roi_bgr,
                    (max(1, int(rw * scale)), max(1, int(rh * scale))),
                    interpolation=cv2.INTER_CUBIC,
                )
            result = engine.run(roi_bgr)  # type: ignore[attr-defined]
            texts = [it.text for it in result.items if it.text]
            ocr_text = " ".join(texts).strip()
            scores = [it.score for it in result.items if it.score is not None]
            ocr_score = float(sum(scores) / len(scores)) if scores else None
            pitch, is_rest = _parse_pitch_token(ocr_text)
        except Exception as exc:  # noqa: BLE001
            logger.debug("L5 OCR ROI failed: %s", exc)

    underlines = _count_underlines(roi_bw)
    octave = _count_octave_dots(roi_bw)
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


def _count_underlines(roi_bw: np.ndarray) -> int:
    """Count horizontal strokes in the lower third of the note ROI."""
    if roi_bw.size == 0:
        return 0
    h, w = roi_bw.shape[:2]
    strip = roi_bw[int(h * 0.55) : h, :]
    if strip.size == 0:
        return 0
    k_w = max(3, int(w * 0.35))
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (k_w, 1))
    horiz = cv2.morphologyEx(strip, cv2.MORPH_OPEN, kernel, iterations=1)
    row_sum = (horiz > 0).sum(axis=1)
    thr = max(2, int(0.3 * w))
    active = row_sum >= thr
    count = 0
    in_run = False
    for a in active:
        if a and not in_run:
            in_run = True
            count += 1
        elif not a:
            in_run = False
    return min(2, count)


def _count_octave_dots(roi_bw: np.ndarray) -> int:
    """Rough octave: upper dots − lower dots (clamped -2..2)."""
    if roi_bw.size == 0:
        return 0
    h, w = roi_bw.shape[:2]
    top = roi_bw[0 : max(1, int(h * 0.28)), :]
    bot = roi_bw[int(h * 0.72) : h, :]
    mid = roi_bw[int(h * 0.28) : int(h * 0.72), :]

    def n_blobs(region: np.ndarray) -> int:
        if region.size == 0:
            return 0
        # Small circular-ish components
        contours, _ = cv2.findContours(
            region, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        n = 0
        for cnt in contours:
            x, y, cw, ch = cv2.boundingRect(cnt)
            area = cw * ch
            if area < 4 or area > 0.15 * w * h:
                continue
            if max(cw, ch) / max(min(cw, ch), 1) > 2.2:
                continue
            n += 1
        return n

    # Prefer dots outside main digit mass
    upper = n_blobs(top)
    lower = n_blobs(bot)
    # Suppress if mid region dominates (digit body misread as dots)
    if (mid > 0).sum() > 0.35 * mid.size:
        pass
    return int(max(-2, min(2, upper - lower)))
