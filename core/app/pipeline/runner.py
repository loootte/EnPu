"""End-to-end recognition pipeline."""

from __future__ import annotations

import logging
import time

import numpy as np

from app.config import Settings
from app.pipeline.barlines import (
    detect_barline_xs,
    inject_barlines_into_items,
    pitch_line_y_range,
    pitch_y_bands_from_items,
)
from app.pipeline.crop_merge import (
    crop_slice_indices,
    merge_crop_into_score,
    normalize_crop_rect,
    offset_boxes,
)
from app.pipeline.layout import classify_items, estimate_pitch_y_band, pitch_items
from app.pipeline.ocr import OcrEngineError, get_ocr_engine
from app.pipeline.parse import parse_ocr_to_score
from app.pipeline.preprocess import ImageDecodeError, decode_image_bytes, preprocess_for_ocr
from app.schemas.recognize import (
    BoundingBox,
    CropRecognizeResponse,
    LayoutRegion,
    RecognizeMeta,
    RecognizeResponse,
)
from app.schemas.score import Score

logger = logging.getLogger(__name__)


class PipelineError(Exception):
    """User-facing pipeline failure with HTTP-ish context."""

    def __init__(self, message: str, *, status_code: int = 500) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def _boxes_to_input_space(
    boxes: list[BoundingBox],
    *,
    scale: float,
) -> list[BoundingBox]:
    """Map OCR boxes from preprocessed pixels back to input-image pixels.

    ``preprocess_for_ocr`` may downscale (scale < 1). Dual-view selection uses
    natural image coordinates, so API boxes must match that space (#45).
    """
    if not boxes:
        return []
    if scale <= 0 or abs(scale - 1.0) < 1e-9:
        return list(boxes)
    inv = 1.0 / scale
    return [
        BoundingBox(
            x1=b.x1 * inv,
            y1=b.y1 * inv,
            x2=b.x2 * inv,
            y2=b.y2 * inv,
            score=b.score,
        )
        for b in boxes
    ]


def _run_on_bgr(
    image_bgr: np.ndarray,
    *,
    settings: Settings,
    filename: str | None,
    content_type: str | None,
    started: float,
    preprocess_prefix: list[str] | None = None,
) -> RecognizeResponse:
    """Preprocess → OCR → barlines → Score parse for a BGR image array."""
    try:
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
    steps = list(preprocess_prefix or []) + list(pre.steps)
    # Boxes / regions in input-image pixels (same space as UI selection).
    boxes_in = _boxes_to_input_space(list(ocr.boxes), scale=pre.scale)
    in_h, in_w = image_bgr.shape[:2]

    # Dual-view (#45): paired text+box+layout kind; skip title/meta for measure map.
    regions: list[LayoutRegion] = []
    for c in classified:
        if c.item.box is None:
            continue
        box_list = _boxes_to_input_space([c.item.box], scale=pre.scale)
        if not box_list:
            continue
        regions.append(
            LayoutRegion(
                text=(c.item.text or "").strip(),
                box=box_list[0],
                kind=c.kind.value,
                score=c.item.score,
            )
        )

    return RecognizeResponse(
        ok=True,
        engine=ocr.engine,
        texts=ocr.texts,
        boxes=boxes_in,
        regions=regions,
        notes=parsed.notes,
        score=parsed.score,
        meta=RecognizeMeta(
            width=in_w,
            height=in_h,
            elapsed_ms=elapsed_ms,
            filename=filename,
            content_type=content_type,
            mock=ocr.mock,
            preprocess_steps=steps,
            scale=pre.scale,
            item_count=len(ocr.items),
            parse_mode=parsed.mode,
            parse_warnings=list(parsed.warnings),
        ),
    )


def run_recognize(
    data: bytes,
    *,
    settings: Settings,
    filename: str | None = None,
    content_type: str | None = None,
) -> RecognizeResponse:
    """Decode → recognize. Dispatches legacy OCR-first vs structure-first (#58)."""
    mode = (settings.pipeline_mode or "legacy").strip().lower()
    if mode in {"structure", "structure_first", "l5"}:
        from app.pipeline.structure import StructurePipelineError, run_structure_recognize

        try:
            return run_structure_recognize(
                data,
                settings=settings,
                filename=filename,
                content_type=content_type,
            )
        except StructurePipelineError as exc:
            raise PipelineError(exc.message, status_code=exc.status_code) from exc

    started = time.perf_counter()
    try:
        image_bgr = decode_image_bytes(data)
    except ImageDecodeError as exc:
        raise PipelineError(str(exc), status_code=400) from exc
    return _run_on_bgr(
        image_bgr,
        settings=settings,
        filename=filename,
        content_type=content_type,
        started=started,
    )


def run_recognize_crop(
    data: bytes,
    *,
    settings: Settings,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    filename: str | None = None,
    content_type: str | None = None,
    base_score: Score | None = None,
    measure_from: int | None = None,
    measure_to: int | None = None,
) -> CropRecognizeResponse:
    """Crop full image to ROI, recognize locally, optionally merge into base Score.

    Boxes are remapped to full-image coordinates. Measures outside the replace
    window in ``base_score`` are preserved (hand edits kept).
    """
    started = time.perf_counter()
    try:
        image_bgr = decode_image_bytes(data)
    except ImageDecodeError as exc:
        raise PipelineError(str(exc), status_code=400) from exc

    full_h, full_w = image_bgr.shape[:2]
    try:
        crop = normalize_crop_rect(x1, y1, x2, y2, width=full_w, height=full_h)
    except ValueError as exc:
        raise PipelineError(str(exc), status_code=400) from exc

    cx1, cy1, cx2, cy2 = crop_slice_indices(crop)
    roi = image_bgr[cy1:cy2, cx1:cx2]
    if roi.size == 0:
        raise PipelineError("Crop region is empty.", status_code=400)

    prefix = [f"crop:{cx1},{cy1},{cx2},{cy2}"]
    local = _run_on_bgr(
        roi,
        settings=settings,
        filename=filename,
        content_type=content_type,
        started=started,
        preprocess_prefix=prefix,
    )

    # Boxes / meta dimensions: keep crop-local size for preprocess stats but
    # expose full-image boxes for dual-view overlay.
    full_boxes = offset_boxes(list(local.boxes), float(cx1), float(cy1))
    meta = local.meta.model_copy(
        update={
            "width": full_w,
            "height": full_h,
        }
    )
    # Stash crop-local size for debugging.
    steps = list(meta.preprocess_steps)
    steps.append(f"crop_size:{cx2 - cx1}x{cy2 - cy1}")
    meta.preprocess_steps = steps

    merged_score = None
    merge_info = None
    if base_score is not None:
        try:
            merged_score, merge_info = merge_crop_into_score(
                base_score,
                local.score,
                crop=crop,
                image_height=full_h,
                image_width=full_w,
                measure_from=measure_from,
                measure_to=measure_to,
            )
        except ValueError as exc:
            raise PipelineError(str(exc), status_code=400) from exc

    return CropRecognizeResponse(
        ok=local.ok,
        engine=local.engine,
        texts=local.texts,
        boxes=full_boxes,
        notes=local.notes,
        score=local.score,
        meta=meta,
        crop=crop,
        merged_score=merged_score,
        merge=merge_info,
    )
