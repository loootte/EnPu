"""Request/response models for /v1/recognize."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class BoundingBox(BaseModel):
    """Axis-aligned box in image pixel coordinates (x1,y1)-(x2,y2)."""

    x1: float
    y1: float
    x2: float
    y2: float
    score: float | None = None


class NoteHint(BaseModel):
    """Lightweight note placeholder; full schema in issue #9."""

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


class RecognizeResponse(BaseModel):
    """Stable response shape for desktop UI and future cloud clients."""

    ok: bool = True
    engine: str
    texts: list[str] = Field(default_factory=list)
    boxes: list[BoundingBox] = Field(default_factory=list)
    notes: list[NoteHint] = Field(default_factory=list)
    meta: RecognizeMeta = Field(default_factory=RecognizeMeta)


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str | None = None
    engine: str | None = None
