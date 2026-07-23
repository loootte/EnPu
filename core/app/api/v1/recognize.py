"""POST /v1/recognize — image upload and recognition pipeline."""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, File, HTTPException, UploadFile, status

from app.config import get_settings
from app.pipeline import PipelineError, run_recognize
from app.schemas.recognize import RecognizeResponse

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
