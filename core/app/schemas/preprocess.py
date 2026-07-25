"""Schemas for preprocess toolbox API (#47)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class PreprocessResponse(BaseModel):
    """Preview result of OpenCV preprocess toolbox."""

    ok: bool = True
    steps: list[str] = Field(default_factory=list)
    width: int = 0
    height: int = 0
    out_width: int = 0
    out_height: int = 0
    scale: float = 1.0
    # PNG base64 of preprocessed BGR (for UI preview)
    image_png_base64: str = ""
    options: dict[str, Any] = Field(default_factory=dict)
    elapsed_ms: int = 0
