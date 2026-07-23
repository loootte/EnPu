"""Request/response models for /v1/export (issue #11)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.score import Score

ExportFormatName = Literal["musicxml", "midi"]


class ExportResponse(BaseModel):
    """Base64 file payload so desktop UI can save without binary multipart."""

    ok: bool = True
    format: ExportFormatName
    filename: str
    media_type: str
    content_base64: str = Field(
        ...,
        description="Base64-encoded MusicXML text or MIDI binary.",
    )
    byte_length: int = Field(..., ge=0)
    warnings: list[str] = Field(default_factory=list)


class ExportBody(Score):
    """POST body is a full EnPu Score v0.1 document."""

    pass
