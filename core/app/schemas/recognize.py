"""Request/response models for /v1/recognize."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.score import Score


class BoundingBox(BaseModel):
    """Axis-aligned box in image pixel coordinates (x1,y1)-(x2,y2)."""

    x1: float
    y1: float
    x2: float
    y2: float
    score: float | None = None


class NoteHint(BaseModel):
    """Lightweight OCR-derived pitch hint (pre-Score).

    Full structured score is ``app.schemas.score.Score`` (v0.1, issue #9).
    """

    pitch: str | None = None
    text: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class RecognizeMeta(BaseModel):
    width: int = 0
    height: int = 0
    elapsed_ms: int = 0
    filename: str | None = None
    content_type: str | None = None
    mock: bool = False
    preprocess_steps: list[str] = Field(default_factory=list)
    scale: float = 1.0
    item_count: int = 0
    parse_mode: Literal["score", "hints", "ocr_only"] | None = None
    parse_warnings: list[str] = Field(default_factory=list)


class RecognizeResponse(BaseModel):
    """Stable response shape for desktop UI and future cloud clients."""

    ok: bool = True
    engine: str
    texts: list[str] = Field(default_factory=list)
    boxes: list[BoundingBox] = Field(default_factory=list)
    notes: list[NoteHint] = Field(default_factory=list)
    score: Score | None = Field(
        default=None,
        description="Structured EnPu Score v0.1 when parse succeeds (#10).",
    )
    meta: RecognizeMeta = Field(default_factory=RecognizeMeta)


class CropRect(BaseModel):
    """Axis-aligned crop ROI in full-image pixel coordinates (issue #49)."""

    x1: float
    y1: float
    x2: float
    y2: float


class CropMergeInfo(BaseModel):
    """How crop Score measures were spliced into base Score."""

    replaced_measure_from: int | None = Field(
        default=None,
        description="1-based first measure index replaced/inserted in merged score.",
    )
    replaced_measure_to: int | None = Field(
        default=None,
        description="1-based last measure index of inserted crop block in merged score.",
    )
    inserted_measure_count: int = 0
    crop: CropRect
    preserved_outside: bool = True


class CropRecognizeResponse(RecognizeResponse):
    """Crop re-recognize result with optional merge into base Score (#49)."""

    crop: CropRect
    merged_score: Score | None = Field(
        default=None,
        description="Base Score with crop measures spliced in; outside measures preserved.",
    )
    merge: CropMergeInfo | None = None


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str | None = None
    engine: str | None = None
