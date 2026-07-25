"""Structure-first end-to-end pipeline (#58).

Order: preprocess → L1 → L2 → L3/L4 → L5 (OCR pitch) → assemble Score.
"""

from __future__ import annotations

import logging
import re
import time

import cv2
import numpy as np

from app.config import Settings
from app.pipeline.ocr import OcrEngineError, get_ocr_engine
from app.pipeline.preprocess import ImageDecodeError, decode_image_bytes, preprocess_for_ocr
from app.pipeline.structure.assemble import layout_debug_summary, page_layout_to_score
from app.pipeline.structure.ir import PageLayout, Rect, RegionRole
from app.pipeline.structure.l1_page import detect_page_regions
from app.pipeline.structure.l2_systems import detect_staff_systems
from app.pipeline.structure.l3_measures import segment_measures_on_systems
from app.pipeline.structure.l4_notes import detect_note_candidates
from app.pipeline.structure.l5_glyph import fill_note_glyphs
from app.schemas.recognize import (
    BoundingBox,
    LayoutRegion,
    NoteHint,
    RecognizeMeta,
    RecognizeResponse,
)

logger = logging.getLogger(__name__)

_KEY_RE = re.compile(
    r"(?:key|调)\s*[:：]?\s*([A-Ga-g][b#]?)|1\s*=\s*([A-Ga-g][b#]?)",
    re.I,
)
_TIME_RE = re.compile(r"([1-9][0-9]*)\s*/\s*([1-9][0-9]*)")


class StructurePipelineError(Exception):
    def __init__(self, message: str, *, status_code: int = 500) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def run_structure_recognize(
    data: bytes,
    *,
    settings: Settings,
    filename: str | None = None,
    content_type: str | None = None,
) -> RecognizeResponse:
    """Structure-first recognition (ENPU_PIPELINE_MODE=structure)."""
    started = time.perf_counter()
    try:
        image_bgr = decode_image_bytes(data)
    except ImageDecodeError as exc:
        raise StructurePipelineError(str(exc), status_code=400) from exc

    # Light preprocess for geometry (keep original for coordinate space)
    try:
        pre = preprocess_for_ocr(
            image_bgr,
            max_side=settings.ocr_max_side,
            denoise=settings.ocr_denoise,
        )
    except ImageDecodeError as exc:
        raise StructurePipelineError(str(exc), status_code=400) from exc

    # Work in original image coordinates for IR; geometry uses original
    work = image_bgr
    h, w = work.shape[:2]
    warnings: list[str] = ["pipeline=structure (#58)"]

    # --- L1
    regions, w1 = detect_page_regions(work)
    warnings.extend(w1)
    score_rect = next((r.rect for r in regions if r.role == RegionRole.score), None)
    if score_rect is None:
        score_rect = Rect(0, 0, float(w), float(h))

    # --- L2
    systems, w2 = detect_staff_systems(work, score_rect)
    warnings.extend(w2)

    # --- L3
    systems, w3 = segment_measures_on_systems(work, systems)
    warnings.extend(w3)

    # --- L4
    systems, w4 = detect_note_candidates(work, systems)
    warnings.extend(w4)

    # --- L5 (OCR pitch on note ROIs — after structure)
    systems, w5 = fill_note_glyphs(
        work,
        systems,
        engine_name=settings.recognize_engine,
        lang=settings.ocr_lang,
        use_angle_cls=settings.ocr_use_angle_cls,
        use_gpu=settings.ocr_use_gpu,
    )
    warnings.extend(w5)

    # Meta text (title / key / time) — light full-page OCR only on top band
    title, key, time_sig, meta_warnings = _read_page_meta(
        work,
        score_rect.y1,
        settings=settings,
    )
    warnings.extend(meta_warnings)

    layout = PageLayout(
        width=w,
        height=h,
        regions=regions,
        systems=systems,
        key=key,
        time_signature=time_sig,
        title=title,
        warnings=warnings,
        debug={"preprocess_steps": list(pre.steps), "scale": pre.scale},
    )

    score = page_layout_to_score(
        layout,
        filename=filename,
        engine=f"structure+{settings.recognize_engine}",
    )

    # Response boxes: note candidate rects (structure debug)
    boxes: list[BoundingBox] = []
    regions_out: list[LayoutRegion] = []
    texts: list[str] = []
    notes: list[NoteHint] = []
    for sys in systems:
        for meas in sys.measures:
            for nc in meas.notes:
                boxes.append(nc.rect.as_box())
                g = nc.glyph
                txt = (g.ocr_text if g else "") or (g.pitch if g and g.pitch else "")
                if txt:
                    texts.append(txt)
                kind = "pitch" if g and g.pitch else "other"
                regions_out.append(
                    LayoutRegion(
                        text=txt,
                        box=nc.rect.as_box(),
                        kind=kind,
                        score=g.ocr_score if g else None,
                    )
                )
                if g and g.pitch:
                    notes.append(
                        NoteHint(
                            pitch=g.pitch,
                            text=g.ocr_text,
                            extra={
                                "source": "structure_l5",
                                "underlines": g.underlines,
                                "octave": g.octave,
                            },
                        )
                    )

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    summary = layout_debug_summary(layout)
    logger.info(
        "structure pipeline: systems=%s measures=%s pitched=%s (%sms)",
        summary["n_systems"],
        summary["n_measures"],
        summary["n_pitched"],
        elapsed_ms,
    )

    return RecognizeResponse(
        ok=True,
        engine=f"structure+{settings.recognize_engine}",
        texts=texts,
        boxes=boxes,
        regions=regions_out,
        notes=notes,
        score=score,
        meta=RecognizeMeta(
            width=w,
            height=h,
            elapsed_ms=elapsed_ms,
            filename=filename,
            content_type=content_type,
            mock=settings.recognize_engine == "mock",
            preprocess_steps=list(pre.steps) + ["structure_l1_l5"],
            scale=1.0,
            item_count=len(boxes),
            parse_mode="score",
            parse_warnings=warnings[:40],
        ),
    )


def _read_page_meta(
    image_bgr: np.ndarray,
    score_y0: float,
    *,
    settings: Settings,
) -> tuple[str | None, str | None, str | None, list[str]]:
    """OCR only the top-of-page band for title / key / time (not full score)."""
    warnings: list[str] = []
    h, w = image_bgr.shape[:2]
    y1 = max(8, min(h, int(max(score_y0, h * 0.18))))
    band = image_bgr[0:y1, 0:w]
    if band.size == 0:
        return None, None, "4/4", ["L1 meta: empty top band"]

    try:
        engine = get_ocr_engine(
            settings.recognize_engine,
            lang=settings.ocr_lang,
            use_angle_cls=settings.ocr_use_angle_cls,
            use_gpu=settings.ocr_use_gpu,
        )
        ocr = engine.run(band)
    except OcrEngineError as exc:
        warnings.append(f"L1 meta OCR failed: {exc}")
        return None, None, "4/4", warnings

    texts = [it.text for it in ocr.items if it.text]
    blob = " ".join(texts)
    title = None
    key = None
    time_sig = None
    for t in texts:
        if re.search(r"[\u4e00-\u9fff]{2,}", t) and not re.search(
            r"[1-7]{3,}", t
        ):
            if title is None and len(t) >= 2:
                title = t[:80]
        mk = _KEY_RE.search(t)
        if mk:
            raw = mk.group(1) or mk.group(2)
            if raw:
                key = raw[0].upper() + raw[1:].lower()
        mt = _TIME_RE.search(t)
        if mt and time_sig is None:
            time_sig = f"{mt.group(1)}/{mt.group(2)}"
    if time_sig is None:
        mt = _TIME_RE.search(blob)
        if mt:
            time_sig = f"{mt.group(1)}/{mt.group(2)}"
    warnings.append(
        f"L1 meta OCR: title={title!r} key={key!r} time={time_sig!r}"
    )
    return title, key, time_sig or "4/4", warnings
