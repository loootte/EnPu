"""POST /v1/preprocess — OpenCV preprocess toolbox preview (#47)."""

from __future__ import annotations

import asyncio
import base64
import time
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status

from app.api.v1.recognize import _read_image_upload
from app.config import get_settings
from app.pipeline.preprocess import (
    ImageDecodeError,
    decode_image_bytes,
    encode_image_png,
    options_from_form,
    preprocess_for_ocr,
)
from app.schemas.preprocess import PreprocessResponse

router = APIRouter(tags=["preprocess"])


def _as_bool(v: str | bool | None, default: bool = False) -> bool:
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    if s in {"1", "true", "yes", "on"}:
        return True
    if s in {"0", "false", "no", "off", ""}:
        return False
    return default


@router.post(
    "/preprocess",
    response_model=PreprocessResponse,
    summary="Preview OpenCV preprocess toolbox (#47)",
)
async def preprocess_preview(
    file: Annotated[UploadFile, File(description="简谱图片 png/jpg")],
    denoise: Annotated[str | None, Form()] = None,
    deskew: Annotated[str | None, Form()] = None,
    clahe: Annotated[str | None, Form()] = None,
    shadow_remove: Annotated[str | None, Form()] = None,
    adaptive_binary: Annotated[str | None, Form()] = None,
    brightness: Annotated[float | None, Form(description="-80..80")] = None,
    contrast: Annotated[float | None, Form(description="0.4..2.5")] = None,
    max_side: Annotated[int | None, Form()] = None,
    crop_x1: Annotated[float | None, Form()] = None,
    crop_y1: Annotated[float | None, Form()] = None,
    crop_x2: Annotated[float | None, Form()] = None,
    crop_y2: Annotated[float | None, Form()] = None,
) -> PreprocessResponse:
    """Apply OpenCV preprocess steps and return a PNG preview (base64).

    Does **not** run OCR. Use the same flags on ``/v1/recognize`` to recognize
    with the same pipeline.
    """
    settings = get_settings()
    data, _filename, _ct = await _read_image_upload(file)
    opts = options_from_form(
        max_side=max_side if max_side is not None else settings.ocr_max_side,
        denoise=_as_bool(denoise, settings.ocr_denoise),
        deskew=_as_bool(deskew, False),
        clahe=_as_bool(clahe, False),
        shadow_remove=_as_bool(shadow_remove, False),
        adaptive_binary=_as_bool(adaptive_binary, False),
        brightness=brightness,
        contrast=contrast,
        crop_x1=crop_x1,
        crop_y1=crop_y1,
        crop_x2=crop_x2,
        crop_y2=crop_y2,
    )

    def _run() -> PreprocessResponse:
        t0 = time.perf_counter()
        try:
            bgr = decode_image_bytes(data)
            pre = preprocess_for_ocr(bgr, options=opts)
        except ImageDecodeError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc
        png = encode_image_png(pre.ocr_bgr)
        b64 = base64.b64encode(png).decode("ascii")
        elapsed = int((time.perf_counter() - t0) * 1000)
        return PreprocessResponse(
            ok=True,
            steps=list(pre.steps),
            width=pre.width,
            height=pre.height,
            out_width=pre.out_width or pre.ocr_bgr.shape[1],
            out_height=pre.out_height or pre.ocr_bgr.shape[0],
            scale=pre.scale,
            image_png_base64=b64,
            options={
                "max_side": opts.max_side,
                "denoise": opts.denoise,
                "deskew": opts.deskew,
                "clahe": opts.clahe,
                "shadow_remove": opts.shadow_remove,
                "adaptive_binary": opts.adaptive_binary,
                "brightness": opts.brightness,
                "contrast": opts.contrast,
                "crop": (
                    [opts.crop_x1, opts.crop_y1, opts.crop_x2, opts.crop_y2]
                    if opts.has_crop()
                    else None
                ),
            },
            elapsed_ms=elapsed,
        )

    return await asyncio.to_thread(_run)
