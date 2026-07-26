"""POST /v1/recognize and /v1/recognize/crop — image recognition pipeline."""

from __future__ import annotations

import asyncio
import json
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status

from app.config import get_settings
from app.pipeline import PipelineError, run_recognize, run_recognize_crop
from app.pipeline.preprocess import options_from_form
from app.pipeline.structure import StructurePipelineError, run_structure_rerun
from app.schemas.recognize import (
    CropRecognizeResponse,
    RecognizeResponse,
    StructureDebug,
    StructureRerunResponse,
)
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


def _form_bool(v: str | bool | None, default: bool | None = None) -> bool | None:
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    if s in {"1", "true", "yes", "on"}:
        return True
    if s in {"0", "false", "no", "off"}:
        return False
    return default


@router.post(
    "/recognize",
    response_model=RecognizeResponse,
    summary="Recognize jianpu image (OpenCV + PaddleOCR)",
)
async def recognize(
    file: Annotated[UploadFile, File(description="简谱图片 png/jpg")],
    denoise: Annotated[str | None, Form()] = None,
    deskew: Annotated[str | None, Form()] = None,
    clahe: Annotated[str | None, Form()] = None,
    shadow_remove: Annotated[str | None, Form()] = None,
    adaptive_binary: Annotated[str | None, Form()] = None,
    brightness: Annotated[float | None, Form()] = None,
    contrast: Annotated[float | None, Form()] = None,
    max_side: Annotated[int | None, Form()] = None,
    crop_x1: Annotated[float | None, Form()] = None,
    crop_y1: Annotated[float | None, Form()] = None,
    crop_x2: Annotated[float | None, Form()] = None,
    crop_y2: Annotated[float | None, Form()] = None,
) -> RecognizeResponse:
    """Accept a score image and run the recognition pipeline.

    Default engine is PaddleOCR (issue #3). Set ``ENPU_RECOGNIZE_ENGINE=mock``
    for offline/UI wiring without heavy models.

    Optional form fields enable the **preprocess toolbox** (#47), same as
    ``POST /v1/preprocess``.
    """
    settings = get_settings()
    data, filename, content_type = await _read_image_upload(file)
    opts = options_from_form(
        max_side=max_side if max_side is not None else settings.ocr_max_side,
        denoise=_form_bool(denoise, settings.ocr_denoise),
        deskew=_form_bool(deskew, False),
        clahe=_form_bool(clahe, False),
        shadow_remove=_form_bool(shadow_remove, False),
        adaptive_binary=_form_bool(adaptive_binary, False),
        brightness=brightness,
        contrast=contrast,
        crop_x1=crop_x1,
        crop_y1=crop_y1,
        crop_x2=crop_x2,
        crop_y2=crop_y2,
    )

    try:
        # OCR is CPU-heavy; do not block the event loop.
        result = await asyncio.to_thread(
            run_recognize,
            data,
            settings=settings,
            filename=filename,
            content_type=content_type,
            preprocess_options=opts,
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


def _parse_structure_debug(raw: str | None) -> StructureDebug:
    if raw is None or not str(raw).strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="base_structure JSON is required for structure rerun (#78).",
        )
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"base_structure is not valid JSON: {exc}",
        ) from exc
    try:
        return StructureDebug.model_validate(payload)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"base_structure failed StructureDebug validation: {exc}",
        ) from exc


def _parse_structure_edits(raw: str | None) -> list[dict]:
    if raw is None or not str(raw).strip():
        return []
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"edits is not valid JSON: {exc}",
        ) from exc
    if not isinstance(payload, list):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="edits must be a JSON array of {id, layer?, box}.",
        )
    return payload


@router.post(
    "/recognize/structure/rerun",
    response_model=StructureRerunResponse,
    summary="Re-run structure layers from a user-edited layer downward (#78)",
)
async def recognize_structure_rerun(
    file: Annotated[UploadFile, File(description="与首次识别相同的简谱原图 png/jpg")],
    from_layer: Annotated[
        str,
        Form(description="起始层 L1|L2|L3|L4|L5；重跑该层及下层，保留上层"),
    ],
    base_structure: Annotated[
        str,
        Form(description="当前 structure JSON（RecognizeResponse.structure）"),
    ],
    edits: Annotated[
        str | None,
        Form(
            description=(
                "可选：用户改框 JSON 数组 "
                '[{ "id": "l2-sys0", "box": {x1,y1,x2,y2} }, ...]'
            )
        ),
    ] = None,
    key: Annotated[str | None, Form(description="可选：覆盖调号")] = None,
    time_signature: Annotated[
        str | None, Form(description="可选：覆盖拍号，如 4/4")
    ] = None,
    title: Annotated[str | None, Form(description="可选：覆盖标题")] = None,
) -> StructureRerunResponse:
    """Structure-first local re-recognize after the user adjusts layer boxes.

    * **from_layer=L2** — keep L1; use (edited) system rects; re-run L3–L5
    * **from_layer=L3** — keep L1–L2; use measure rects; re-run L4–L5
    * **from_layer=L4** — keep L1–L3; use note ROIs; re-run L5
    * **from_layer=L5** — re-fill glyphs on existing candidates
    * **from_layer=L1** — use page regions; re-run L2–L5
    """
    settings = get_settings()
    data, filename, content_type = await _read_image_upload(file)
    structure = _parse_structure_debug(base_structure)
    edit_list = _parse_structure_edits(edits)
    layer = (from_layer or "").strip().upper()
    if layer not in {"L1", "L2", "L3", "L4", "L5"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"from_layer must be L1–L5 (got {from_layer!r})",
        )

    try:
        result = await asyncio.to_thread(
            run_structure_rerun,
            data,
            settings=settings,
            from_layer=layer,  # type: ignore[arg-type]
            base_structure=structure,
            edits=edit_list,
            filename=filename,
            content_type=content_type,
            key=key,
            time_signature=time_signature,
            title=title,
        )
    except StructurePipelineError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    except PipelineError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    return StructureRerunResponse(
        **result.model_dump(),
        from_layer=layer,  # type: ignore[arg-type]
        edited_item_count=len(edit_list),
    )
