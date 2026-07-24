"""POST /v1/recognize and /v1/recognize/crop — image recognition pipeline."""

from __future__ import annotations

import asyncio
import json
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status

from app.config import get_settings
from app.pipeline import PipelineError, run_recognize, run_recognize_crop
from app.schemas.recognize import CropRecognizeResponse, RecognizeResponse
from app.schemas.score import Score

router = APIRouter(tags=["recognize"])

ALLOWED_CONTENT_TYPES = {
    "image/png",
    "image/jpeg",
    "image/jpg",
}
ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg"}


def _extension_ok(filename: str | None) -> bool:
    if not filename or "." not in filename:
        return False
    ext = "." + filename.rsplit(".", 1)[-1].lower()
    return ext in ALLOWED_EXTENSIONS


def _content_type_ok(content_type: str | None) -> bool:
    if not content_type:
        return False
    base = content_type.split(";")[0].strip().lower()
    return base in ALLOWED_CONTENT_TYPES


async def _read_image_upload(file: UploadFile) -> tuple[bytes, str, str | None]:
    """Validate and read image upload; returns (bytes, filename, content_type)."""
    settings = get_settings()
    filename = file.filename or "upload"
    content_type = file.content_type

    if not (_content_type_ok(content_type) or _extension_ok(filename)):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Unsupported file type. Upload png or jpg "
                f"(got content_type={content_type!r}, filename={filename!r})."
            ),
        )

    data = await file.read()
    if not data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Empty file.",
        )
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"File too large ({len(data)} bytes). "
                f"Max is {settings.max_upload_bytes} bytes."
            ),
        )
    return data, filename, content_type


def _parse_base_score(raw: str | None) -> Score | None:
    if raw is None or not str(raw).strip():
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"base_score is not valid JSON: {exc}",
        ) from exc
    try:
        return Score.model_validate(payload)
    except Exception as exc:  # pydantic ValidationError
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"base_score failed Score validation: {exc}",
        ) from exc


@router.post(
    "/recognize",
    response_model=RecognizeResponse,
    summary="Recognize jianpu image (OpenCV + PaddleOCR)",
)
async def recognize(
    file: Annotated[UploadFile, File(description="简谱图片 png/jpg")],
) -> RecognizeResponse:
    """Accept a score image and run the recognition pipeline.

    Default engine is PaddleOCR (issue #3). Set ``ENPU_RECOGNIZE_ENGINE=mock``
    for offline/UI wiring without heavy models.
    """
    settings = get_settings()
    data, filename, content_type = await _read_image_upload(file)

    try:
        # OCR is CPU-heavy; do not block the event loop.
        result = await asyncio.to_thread(
            run_recognize,
            data,
            settings=settings,
            filename=filename,
            content_type=content_type,
        )
    except PipelineError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    return result


@router.post(
    "/recognize/crop",
    response_model=CropRecognizeResponse,
    summary="Recognize a rectangular crop and merge into base Score (#49)",
)
async def recognize_crop(
    file: Annotated[UploadFile, File(description="完整简谱原图 png/jpg")],
    x1: Annotated[float, Form(description="裁剪左上 x（原图像素）")],
    y1: Annotated[float, Form(description="裁剪左上 y（原图像素）")],
    x2: Annotated[float, Form(description="裁剪右下 x（原图像素）")],
    y2: Annotated[float, Form(description="裁剪右下 y（原图像素）")],
    base_score: Annotated[
        str | None,
        Form(description="可选：当前 Score JSON 字符串，用于局部合并"),
    ] = None,
    measure_from: Annotated[
        int | None,
        Form(description="可选：1-based 起始小节（覆盖自动估计）"),
    ] = None,
    measure_to: Annotated[
        int | None,
        Form(description="可选：1-based 结束小节（含）"),
    ] = None,
) -> CropRecognizeResponse:
    """Crop ROI → OCR/parse → optional splice into ``base_score``.

    Only **axis-aligned rectangles** are supported. Measures outside the
    replace window are preserved so hand edits outside the selection survive.
    """
    settings = get_settings()
    data, filename, content_type = await _read_image_upload(file)
    score_obj = _parse_base_score(base_score)

    try:
        result = await asyncio.to_thread(
            run_recognize_crop,
            data,
            settings=settings,
            x1=x1,
            y1=y1,
            x2=x2,
            y2=y2,
            filename=filename,
            content_type=content_type,
            base_score=score_obj,
            measure_from=measure_from,
            measure_to=measure_to,
        )
    except PipelineError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    return result
