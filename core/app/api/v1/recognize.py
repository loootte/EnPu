"""POST /v1/recognize — image upload and recognition (mock in #2)."""

from __future__ import annotations

import io
import time
from typing import Annotated

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from PIL import Image, UnidentifiedImageError

from app.config import get_settings
from app.schemas.recognize import RecognizeMeta, RecognizeResponse

router = APIRouter(tags=["recognize"])

ALLOWED_CONTENT_TYPES = {
    "image/png",
    "image/jpeg",
    "image/jpg",
}
ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg"}

# Deterministic mock OCR strings for PoC UI wiring (replaced by PaddleOCR in #3).
MOCK_TEXTS = ["1", "2", "3", "主", "恩"]


def _extension_ok(filename: str | None) -> bool:
    if not filename or "." not in filename:
        return False
    ext = "." + filename.rsplit(".", 1)[-1].lower()
    return ext in ALLOWED_EXTENSIONS


def _content_type_ok(content_type: str | None) -> bool:
    if not content_type:
        return False
    # Handle "image/png; charset=binary" style values.
    base = content_type.split(";")[0].strip().lower()
    return base in ALLOWED_CONTENT_TYPES


@router.post(
    "/recognize",
    response_model=RecognizeResponse,
    summary="Recognize jianpu image (mock engine until #3)",
)
async def recognize(
    file: Annotated[UploadFile, File(description="简谱图片 png/jpg")],
) -> RecognizeResponse:
    """Accept a score image and return a structured recognition payload.

    Issue #2 returns a **mock** result so the desktop can integrate early.
    Issue #3 will replace the body of this handler with the real pipeline.
    """
    settings = get_settings()
    started = time.perf_counter()

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

    width, height = 0, 0
    try:
        with Image.open(io.BytesIO(data)) as img:
            img.verify()
        with Image.open(io.BytesIO(data)) as img:
            width, height = img.size
    except UnidentifiedImageError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File is not a valid image.",
        ) from exc
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to read image: {exc}",
        ) from exc

    elapsed_ms = int((time.perf_counter() - started) * 1000)

    # Mock path — real OCR in issue #3.
    engine = settings.recognize_engine

    return RecognizeResponse(
        ok=True,
        engine=engine,
        texts=list(MOCK_TEXTS),
        boxes=[],
        notes=[],
        meta=RecognizeMeta(
            width=width,
            height=height,
            elapsed_ms=elapsed_ms,
            filename=filename,
            content_type=content_type,
            mock=engine == "mock",
        ),
    )
