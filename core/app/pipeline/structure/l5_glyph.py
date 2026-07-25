"""L5: per-note glyph — OCR pitch + geometric fallback + underlines / dots (#58/#69)."""

from __future__ import annotations

import logging
import re
from functools import lru_cache

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

_BEATS: dict[DurationName, float] = {
    DurationName.whole: 4.0,
    DurationName.half: 2.0,
    DurationName.quarter: 1.0,
    DurationName.eighth: 0.5,
    DurationName.sixteenth: 0.25,
    DurationName.thirty_second: 0.125,
}


def fill_note_glyphs(
    image_bgr: np.ndarray,
    systems: list[StaffSystem],
    *,
    engine_name: str = "paddleocr",
    lang: str = "ch",
    use_angle_cls: bool = True,
    use_gpu: bool = False,
) -> tuple[list[StaffSystem], list[str]]:
    """Run L5 on each pitch note candidate ROI."""
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
        warnings.append(f"L5: OCR engine unavailable ({exc}); geometric pitch only")
        engine = None

    h, w = image_bgr.shape[:2]
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    n_ocr = 0
    n_pitch = 0
    n_geom = 0
    out_systems: list[StaffSystem] = []

    for sys in systems:
        new_measures = []
        for meas in sys.measures:
            new_notes: list[NoteCandidate] = []
            for nc in meas.notes:
                kind = (nc.extra or {}).get("kind", "pitch")
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
                    if (glyph.extra or {}).get("pitch_from") == "geometry":
                        n_geom += 1
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
        f"L5: {n_pitch} pitch(es) "
        f"(ocr_text={n_ocr}, geometry_fallback={n_geom})"
    )
    return out_systems, warnings


def validate_measure_durations(
    systems: list[StaffSystem],
    time_signature: str,
    *,
    eps: float = 0.35,
    soft_fit: bool = True,
) -> tuple[list[StaffSystem], list[str]]:
    """Check each measure's filled beats vs meter; optional soft-fit (#69).

    Runs after L5 so underlines/dots are known. Writes
    ``measure.extra['meter_*']`` and shortens default/underline quarters when
    overfull so playback is closer to the bar capacity.
    """
    warnings: list[str] = []
    capacity = _beats_capacity(time_signature)
    if capacity <= 0:
        return systems, ["L4/L5 meter: invalid time signature"]

    out: list[StaffSystem] = []
    n_over = 0
    n_under = 0
    n_fit = 0

    for sys in systems:
        new_measures = []
        for meas in sys.measures:
            notes = list(meas.notes)
            pitch_notes = [
                n
                for n in notes
                if (n.extra or {}).get("kind", "pitch") == "pitch" and n.glyph
            ]
            # Soft-fit overfull bars (quarters → eighths → sixteenths)
            if soft_fit and pitch_notes:
                total0 = _measure_beats(pitch_notes)
                if total0 > capacity + eps:
                    fitted = _soft_fit_glyphs(pitch_notes, capacity, eps=eps)
                    if fitted:
                        n_fit += 1
                        # rebuild notes list with updated glyphs
                        by_idx = {n.index: n for n in fitted}
                        notes = [by_idx.get(n.index, n) for n in notes]
                        pitch_notes = [
                            n
                            for n in notes
                            if (n.extra or {}).get("kind", "pitch") == "pitch"
                            and n.glyph
                        ]

            total = _measure_beats(pitch_notes)
            status = "ok"
            if total > capacity + eps:
                status = "over"
                n_over += 1
            elif total < capacity - eps and pitch_notes:
                status = "under"
                n_under += 1

            from app.pipeline.structure.ir import MeasureLayout

            extra = dict(meas.extra)
            extra.update(
                {
                    "meter_capacity": capacity,
                    "meter_beats": round(total, 3),
                    "meter_status": status,
                    "meter_time_signature": time_signature,
                    "n_pitch_filled": len(
                        [n for n in pitch_notes if n.glyph and (n.glyph.pitch or n.glyph.is_rest)]
                    ),
                }
            )
            new_measures.append(
                MeasureLayout(
                    index=meas.index,
                    rect=meas.rect,
                    barline_x_left=meas.barline_x_left,
                    barline_x_right=meas.barline_x_right,
                    notes=notes,
                    confidence=meas.confidence,
                    extra=extra,
                )
            )
        out.append(
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
        f"L4/L5 meter check ({time_signature}): "
        f"over={n_over} under={n_under} soft_fit={n_fit} capacity={capacity}"
    )
    return out, warnings


def _beats_capacity(time_sig: str) -> float:
    try:
        num, den = time_sig.split("/")
        return int(num) * (4.0 / int(den))
    except Exception:
        return 4.0


def _note_beats_glyph(g: NoteGlyph) -> float:
    base = _BEATS.get(g.duration, 1.0)
    if g.dots == 1:
        return base * 1.5
    if g.dots >= 2:
        return base * 1.75
    return base


def _measure_beats(notes: list[NoteCandidate]) -> float:
    total = 0.0
    for n in notes:
        g = n.glyph
        if g is None:
            continue
        if g.pitch or g.is_rest:
            total += _note_beats_glyph(g)
    return total


def _soft_fit_glyphs(
    pitch_notes: list[NoteCandidate],
    capacity: float,
    *,
    eps: float,
) -> list[NoteCandidate] | None:
    """Return new NoteCandidates with shortened durations, or None if unchanged."""
    glyphs = [n.glyph for n in pitch_notes if n.glyph]
    if not glyphs:
        return None

    def total(gs: list[NoteGlyph]) -> float:
        return sum(_note_beats_glyph(g) for g in gs)

    if total(glyphs) <= capacity + eps:
        return None

    new_gs = [
        NoteGlyph(
            pitch=g.pitch,
            is_rest=g.is_rest,
            duration=g.duration,
            dots=g.dots,
            octave=g.octave,
            accidental=g.accidental,
            underlines=g.underlines,
            ocr_text=g.ocr_text,
            ocr_score=g.ocr_score,
            confidence=g.confidence,
            extra=dict(g.extra or {}),
        )
        for g in glyphs
    ]
    changed = False

    def shrinkable(g: NoteGlyph) -> bool:
        src = (g.extra or {}).get("duration_from", "default")
        return src in {"default", "underline", "meter_fit"}

    for g in new_gs:
        if shrinkable(g) and g.duration == DurationName.quarter and g.dots == 0:
            g.duration = DurationName.eighth
            g.extra["duration_from"] = "meter_fit"
            changed = True
    if total(new_gs) > capacity + eps:
        for g in new_gs:
            if shrinkable(g) and g.duration == DurationName.eighth and g.dots == 0:
                g.duration = DurationName.sixteenth
                g.extra["duration_from"] = "meter_fit"
                changed = True

    if not changed:
        return None

    out: list[NoteCandidate] = []
    gi = 0
    for n in pitch_notes:
        if n.glyph is None:
            out.append(n)
            continue
        out.append(
            NoteCandidate(
                rect=n.rect,
                index=n.index,
                glyph=new_gs[gi],
                confidence=n.confidence,
                extra=dict(n.extra),
            )
        )
        gi += 1
    return out


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
    extra = dict(nc.extra or {})
    bx0 = int(extra.get("body_x0", x0))
    bx1 = int(extra.get("body_x1", x1))
    by0 = int(extra.get("body_y0", y0))
    by1 = int(extra.get("body_y1", y1))
    # Clamp body inside image
    bx0, bx1 = max(0, bx0), min(img_w, bx1)
    by0, by1 = max(0, by0), min(img_h, by1)
    if bx1 <= bx0 or by1 <= by0:
        bx0, by0, bx1, by1 = x0, y0, x1, y1
    body_h = max(4, by1 - by0)
    body_w = max(4, bx1 - bx0)

    pitch = None
    is_rest = False
    ocr_text = ""
    ocr_score = None
    pitch_from = "none"

    ocr_pitch = None
    ocr_rest = False
    if engine is not None:
        ocr_pitch, ocr_rest, ocr_text, ocr_score = _ocr_pitch(
            image_bgr,
            bx0,
            by0,
            bx1,
            by1,
            note_rect=(x0, y0, x1, y1),
            engine=engine,
            img_w=img_w,
            img_h=img_h,
        )

    body_roi = bw[by0:by1, bx0:bx1]
    geom = _infer_pitch_geometry(body_roi)

    # Prefer clean single-digit OCR; else geometry (tiny ROI OCR is unreliable)
    ocr_clean = _is_clean_digit_text(ocr_text) and ocr_pitch is not None
    if ocr_rest and ocr_clean:
        is_rest = True
        pitch = None
        pitch_from = "ocr"
    elif ocr_clean and (ocr_score is None or ocr_score >= 0.45):
        # If geometry strongly disagrees and OCR is weak, trust geometry
        if (
            geom
            and geom != ocr_pitch
            and (ocr_score is not None and ocr_score < 0.72)
        ):
            pitch = geom
            pitch_from = "geometry"
        else:
            pitch = ocr_pitch
            pitch_from = "ocr"
    elif geom:
        pitch = geom
        pitch_from = "geometry"
        if not ocr_text:
            ocr_text = f"geom:{geom}"
    elif ocr_pitch:
        pitch = ocr_pitch
        pitch_from = "ocr"
    elif ocr_rest:
        is_rest = True
        pitch_from = "ocr"

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
    # Prefer L4 precomputed underline count if geometry-based and higher confidence
    if extra.get("underline_count") is not None and underlines == 0:
        underlines = int(extra["underline_count"])

    dots = int(extra.get("aug_dots") or 0)
    if dots == 0:
        dots = _count_aug_dots(
            bw,
            body_x1=bx1,
            body_y0=by0,
            body_y1=by1,
            body_w=body_w,
            body_h=body_h,
            limit_x=min(img_w, x1 + max(4, int(0.5 * body_w))),
        )

    top_y0 = max(0, by0 - max(4, int(0.35 * body_h)))
    top_roi = bw[top_y0:by0, max(0, bx0 - 2) : min(img_w, bx1 + 2)]
    bot_roi = bw[
        by1 : min(img_h, by1 + max(3, int(0.2 * body_h))),
        max(0, bx0 - 2) : min(img_w, bx1 + 2),
    ]
    octave = _octave_from_strips(top_roi, bot_roi, body_w=body_w, body_h=body_h)
    duration = _duration_from_underlines(underlines)

    conf = 0.35
    if pitch or is_rest:
        conf = 0.78 if pitch_from == "ocr" else 0.55
        if ocr_score:
            conf = min(0.92, max(conf, float(ocr_score)))
    conf = min(0.95, conf + 0.04 * underlines + 0.03 * dots)

    return NoteGlyph(
        pitch=None if is_rest else pitch,
        is_rest=is_rest,
        duration=duration,
        dots=min(2, dots),
        octave=octave,
        underlines=underlines,
        ocr_text=ocr_text,
        ocr_score=ocr_score,
        confidence=conf,
        extra={
            "duration_from": "underline" if underlines else "default",
            "pitch_from": pitch_from,
            "has_tie_or_sustain": bool(extra.get("has_sustain")),
        },
    )


def _ocr_pitch(
    image_bgr: np.ndarray,
    bx0: int,
    by0: int,
    bx1: int,
    by1: int,
    *,
    note_rect: tuple[int, int, int, int],
    engine: object,
    img_w: int,
    img_h: int,
) -> tuple[str | None, bool, str, float | None]:
    """OCR digit with padded white canvas — critical for Paddle on tiny crops."""
    nx0, ny0, nx1, ny1 = note_rect
    crops: list[tuple[int, int, int, int]] = [
        (bx0, by0, bx1, by1),
        (
            max(0, bx0 - 4),
            max(0, by0 - 4),
            min(img_w, bx1 + 4),
            min(img_h, by1 + 4),
        ),
        # Full L4 note rect (body + underline zone) as last OCR try
        (nx0, ny0, nx1, min(img_h, by1 + max(6, (by1 - by0) // 3))),
    ]
    best_text = ""
    best_score: float | None = None
    for xa, ya, xb, yb in crops:
        if xb - xa < 3 or yb - ya < 3:
            continue
        roi = image_bgr[ya:yb, xa:xb]
        prepared = _prepare_ocr_patch(roi)
        try:
            result = engine.run(prepared)  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001
            logger.debug("L5 OCR failed: %s", exc)
            continue
        texts = [it.text for it in result.items if it.text]
        text = " ".join(texts).strip()
        scores = [it.score for it in result.items if it.score is not None]
        score = float(sum(scores) / len(scores)) if scores else None
        # Mock engine returns fixed list — take first jianpu digit only once
        pitch, is_rest = _parse_pitch_token(text)
        if pitch or is_rest:
            return pitch, is_rest, text, score
        if text and (not best_text or (score or 0) > (best_score or 0)):
            best_text, best_score = text, score
    pitch, is_rest = _parse_pitch_token(best_text)
    return pitch, is_rest, best_text, best_score


def _prepare_ocr_patch(roi_bgr: np.ndarray, *, min_side: int = 80, border: int = 16) -> np.ndarray:
    """White-pad + upscale so PaddleOCR sees a readable digit."""
    if roi_bgr.size == 0:
        return np.full((min_side, min_side, 3), 255, dtype=np.uint8)
    rh, rw = roi_bgr.shape[:2]
    # Light contrast stretch on gray, keep as BGR
    gray = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX)
    # Mild adaptive threshold look while keeping soft edges for OCR
    blur = cv2.GaussianBlur(gray, (3, 3), 0)
    roi = cv2.cvtColor(blur, cv2.COLOR_GRAY2BGR)
    scale = max(1.0, float(min_side) / max(rh, rw, 1))
    if scale > 1.01:
        roi = cv2.resize(
            roi,
            (max(1, int(rw * scale)), max(1, int(rh * scale))),
            interpolation=cv2.INTER_CUBIC,
        )
    roi = cv2.copyMakeBorder(
        roi,
        border,
        border,
        border,
        border,
        cv2.BORDER_CONSTANT,
        value=(255, 255, 255),
    )
    return roi


@lru_cache(maxsize=8)
def _digit_templates(height: int) -> dict[str, np.ndarray]:
    """Ink=255 templates for digits 0–7 (jianpu)."""
    h = max(24, int(height))
    w = max(14, int(h * 0.65))
    out: dict[str, np.ndarray] = {}
    font = cv2.FONT_HERSHEY_SIMPLEX
    for d in "01234567":
        canvas = np.full((h, w), 255, dtype=np.uint8)
        scale = h / 36.0
        thickness = max(1, int(round(h / 18)))
        (tw, th), base = cv2.getTextSize(d, font, scale, thickness)
        x = max(0, (w - tw) // 2)
        y = min(h - 1, (h + th) // 2)
        cv2.putText(canvas, d, (x, y), font, scale, 0, thickness, cv2.LINE_AA)
        inv = (255 - canvas).astype(np.uint8)
        # Crop to ink bbox
        ys, xs = np.where(inv > 0)
        if ys.size:
            inv = inv[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1]
        out[d] = inv
    return out


def _infer_pitch_geometry(body_bw: np.ndarray) -> str | None:
    """Template-match digit body ink to 1–7 (0 → rest handled by caller)."""
    if body_bw is None or body_bw.size == 0:
        return None
    # Ensure ink=255
    ink = body_bw.copy()
    if ink.max() <= 1:
        ink = (ink * 255).astype(np.uint8)
    # Trim
    ys, xs = np.where(ink > 0)
    if ys.size < 8:
        return None
    digit = ink[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1]
    th, tw = digit.shape[:2]
    if th < 6 or tw < 3:
        return None
    templates = _digit_templates(max(24, th))
    best_d = None
    best_s = -1.0
    target_h = 32
    scale = target_h / th
    dig_r = cv2.resize(
        digit,
        (max(4, int(tw * scale)), target_h),
        interpolation=cv2.INTER_AREA,
    )
    for d, tmpl in templates.items():
        if d == "0":
            continue
        th0, tw0 = tmpl.shape[:2]
        sc = target_h / max(th0, 1)
        t = cv2.resize(
            tmpl,
            (max(4, int(tw0 * sc)), target_h),
            interpolation=cv2.INTER_AREA,
        )
        # Match same size
        hh = min(dig_r.shape[0], t.shape[0])
        ww = min(dig_r.shape[1], t.shape[1])
        a = cv2.resize(dig_r, (ww, hh))
        b = cv2.resize(t, (ww, hh))
        if a.size == 0 or b.size == 0:
            continue
        a_f = a.astype(np.float32).ravel()
        b_f = b.astype(np.float32).ravel()
        a_f = a_f - a_f.mean()
        b_f = b_f - b_f.mean()
        denom = float(np.linalg.norm(a_f) * np.linalg.norm(b_f)) + 1e-6
        score = float(np.dot(a_f, b_f) / denom)
        if score > best_s:
            best_s = score
            best_d = d
    if best_d is not None and best_s >= 0.25:
        return best_d
    return None


def _is_clean_digit_text(text: str) -> bool:
    """True when OCR looks like a single jianpu digit (not multi-token junk)."""
    t = (text or "").translate(_FULLWIDTH).strip()
    if not t:
        return False
    if t in set("12345670"):
        return True
    # Allow slight decoration: "5." "5_" 
    if len(t) <= 3 and t[0] in set("12345670") and all(
        c in "._-·• " for c in t[1:]
    ):
        return True
    return False


def _parse_pitch_token(text: str) -> tuple[str | None, bool]:
    t = (text or "").translate(_FULLWIDTH).strip()
    if not t:
        return None, False
    # Prefer standalone digit tokens over incidental digits in Chinese OCR junk
    for part in re.split(r"\s+", t):
        p = part.strip()
        if p in set("1234567"):
            return p, False
        if p in {"0", "〇", "零"}:
            return None, True
    if "0" in t and not _DIGIT_RE.search(t.replace("0", "")):
        return None, True
    # Only take embedded digit if the whole string is short (avoid "1 2 3 主")
    if len(t) <= 4:
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
    """Count duration underlines strictly below the digit body."""
    if x1 - x0 < 3:
        return 0
    y0 = body_y1 + 1
    y1 = body_y1 + max(8, int(0.75 * body_h))
    if underline_band_y0 is not None and underline_band_y1 is not None:
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
    k_w = max(3, int(rw * 0.45))
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (k_w, 1))
    horiz = cv2.morphologyEx(strip, cv2.MORPH_OPEN, kernel, iterations=1)
    row_sum = (horiz > 0).sum(axis=1).astype(np.float32)
    thr = max(2.0, 0.35 * rw)
    active = row_sum >= thr

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
        raw = (strip > 0).sum(axis=1).astype(np.float32)
        thr2 = max(2.0, 0.45 * rw)
        active2 = raw >= thr2
        in_run = False
        a0 = 0
        for i, a in enumerate(active2):
            if a and not in_run:
                in_run = True
                a0 = i
            elif not a and in_run:
                in_run = False
                if i - a0 <= 4:
                    runs.append((a0, i))
        if in_run and len(active2) - a0 <= 4:
            runs.append((a0, len(active2)))

    if not runs:
        return 0

    merged: list[float] = []
    for a, b in runs:
        cy = 0.5 * (a + b)
        if not merged or cy - merged[-1] > 3.5:
            merged.append(cy)
        else:
            merged[-1] = 0.5 * (merged[-1] + cy)
    return min(2, len(merged))


def _count_aug_dots(
    bw: np.ndarray,
    *,
    body_x1: int,
    body_y0: int,
    body_y1: int,
    body_w: int,
    body_h: int,
    limit_x: int,
) -> int:
    """Count augmentation dots to the right of the digit body."""
    x0 = body_x1 + 1
    x1 = min(limit_x, body_x1 + max(6, int(0.85 * body_w)))
    y0 = body_y0 + int(0.15 * body_h)
    y1 = body_y1 - int(0.1 * body_h)
    if x1 - x0 < 2 or y1 - y0 < 2:
        return 0
    roi = bw[y0:y1, x0:x1]
    if roi.size == 0:
        return 0
    contours, _ = cv2.findContours(roi, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    n = 0
    max_a = max(10, 0.12 * body_w * body_h)
    for cnt in contours:
        _x, _y, cw, ch = cv2.boundingRect(cnt)
        area = cw * ch
        if area < 3 or area > max_a:
            continue
        if max(cw, ch) / max(min(cw, ch), 1) > 2.0:
            continue  # not a roundish dot
        n += 1
    return min(2, n)


def _octave_from_strips(
    top: np.ndarray,
    bot: np.ndarray,
    *,
    body_w: int,
    body_h: int,
) -> int:
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
    """Legacy helper for tests."""
    if roi_bw.size == 0:
        return 0
    h, w = roi_bw.shape[:2]
    body_y1 = int(h * 0.55)
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
