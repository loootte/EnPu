"""End-to-end recognition pipeline."""

from __future__ import annotations

import logging
import time

from app.config import Settings
from app.pipeline.barlines import (
    detect_barline_xs,
    inject_barlines_into_items,
    pitch_line_y_range,
    pitch_y_bands_from_items,
)
from app.pipeline.layout import classify_items, estimate_pitch_y_band, pitch_items
from app.pipeline.ocr import OcrEngineError, get_ocr_engine
from app.pipeline.parse import parse_ocr_to_score
from app.pipeline.preprocess import ImageDecodeError, decode_image_bytes, preprocess_for_ocr
from app.schemas.recognize import RecognizeMeta, RecognizeResponse

logger = logging.getLogger(__name__)


class PipelineError(Exception):
    """User-facing pipeline failure with HTTP-ish context."""

    def __init__(self, message: str, *, status_code: int = 500) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def run_recognize(
    data: bytes,
    *,
    settings: Settings,
    filename: str | None = None,
    content_type: str | None = None,
) -> RecognizeResponse:
    """Decode → preprocess → OCR → Score parse (with fallback)."""
    started = time.perf_counter()

    try:
        image_bgr = decode_image_bytes(data)
        pre = preprocess_for_ocr(
            image_bgr,
            max_side=settings.ocr_max_side,
            denoise=settings.ocr_denoise,
        )
    except ImageDecodeError as exc:
        raise PipelineError(str(exc), status_code=400) from exc

    try:
        engine = get_ocr_engine(
            settings.recognize_engine,
            lang=settings.ocr_lang,
            use_angle_cls=settings.ocr_use_angle_cls,
            use_gpu=settings.ocr_use_gpu,
        )
        ocr = engine.run(pre.ocr_bgr)
    except OcrEngineError as exc:
        logger.exception("OCR engine error")
        raise PipelineError(str(exc), status_code=500) from exc

    # Prefer layout-based multi-row pitch bands (#34/#35).
    classified = classify_items(list(ocr.items))
    staff = pitch_items(classified)
    y_bands = pitch_y_bands_from_items(staff if staff else list(ocr.items))
    y_band = None
    if y_bands:
        y_band = (min(b[0] for b in y_bands), max(b[1] for b in y_bands))
    else:
        y_band = estimate_pitch_y_band(staff) or pitch_line_y_range(list(ocr.items))
        if y_band:
            y_bands = [y_band]
    # Graphic barlines are often invisible to OCR as the '|' glyph.
    bar_xs = detect_barline_xs(
        pre.ocr_bgr,
        y_range=y_band,
        y_ranges=y_bands or None,
    )
    ocr_items = inject_barlines_into_items(list(ocr.items), bar_xs)
    if bar_xs:
        logger.info(
            "detected %s barline candidate(s) in %s band(s)",
            len(bar_xs),
            len(y_bands or []),
        )

    parsed = parse_ocr_to_score(
        ocr_items,
        filename=filename,
        engine=ocr.engine,
    )
    elapsed_ms = int((time.perf_counter() - started) * 1000)

    return RecognizeResponse(
        ok=True,
        engine=ocr.engine,
        texts=ocr.texts,
        boxes=ocr.boxes,
        notes=parsed.notes,
        score=parsed.score,
        meta=RecognizeMeta(
            width=pre.width,
            height=pre.height,
            elapsed_ms=elapsed_ms,
            filename=filename,
            content_type=content_type,
            mock=ocr.mock,
            preprocess_steps=list(pre.steps),
            scale=pre.scale,
            item_count=len(ocr.items),
            parse_mode=parsed.mode,
            parse_warnings=list(parsed.warnings),
        ),
    )
