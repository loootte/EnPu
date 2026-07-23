"""End-to-end recognition pipeline."""

from __future__ import annotations

import logging
import time

from app.config import Settings
from app.pipeline.ocr import OcrEngineError, get_ocr_engine
from app.pipeline.parse import extract_note_hints
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
    """Decode → preprocess → OCR → light note extraction."""
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

    notes = extract_note_hints(ocr.items)
    elapsed_ms = int((time.perf_counter() - started) * 1000)

    return RecognizeResponse(
        ok=True,
        engine=ocr.engine,
        texts=ocr.texts,
        boxes=ocr.boxes,
        notes=notes,
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
        ),
    )
