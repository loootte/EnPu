"""POST /v1/export — Score JSON → MusicXML or MIDI (issue #11)."""

from __future__ import annotations

import re
from typing import Annotated, Literal
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Response, status

from app.pipeline.export import ExportError, export_score
from app.schemas.export import ExportResponse
from app.schemas.score import Score

router = APIRouter(tags=["export"])

FormatParam = Literal["musicxml", "midi"]


def _content_disposition(filename: str) -> str:
    """ASCII fallback + RFC 5987 UTF-8 filename* for non-ASCII titles."""
    ext = ""
    if "." in filename:
        ext = filename[filename.rfind(".") :]
    ascii_name = re.sub(r"[^\w.\-]+", "_", filename, flags=re.ASCII).strip("._")
    if not ascii_name or ascii_name in {".", ".."}:
        ascii_name = f"enpu-score{ext or '.bin'}"
    elif ext and not ascii_name.endswith(ext):
        ascii_name = f"{ascii_name}{ext}"
    starred = quote(filename, safe="")
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{starred}"


@router.post(
    "/export",
    response_model=ExportResponse,
    summary="Export EnPu Score to MusicXML or MIDI",
    responses={
        200: {
            "description": (
                "Default: JSON with base64 payload. "
                "Set download=true for raw file bytes."
            ),
            "content": {
                "application/json": {},
                "application/vnd.recordare.musicxml+xml": {},
                "audio/midi": {},
            },
        },
        400: {"description": "Invalid score or format"},
        500: {"description": "music21 missing or export failed"},
    },
)
async def export_score_endpoint(
    score: Score,
    format: Annotated[
        FormatParam,
        Query(description="Target format: musicxml or midi"),
    ] = "musicxml",
    download: Annotated[
        bool,
        Query(description="If true, return raw file bytes instead of JSON"),
    ] = False,
) -> Response | ExportResponse:
    """Convert an EnPu Score v0.1 document to MusicXML or MIDI.

    - **JSON mode** (default): ``content_base64`` for UI save-as.
    - **download=true**: raw file with ``Content-Disposition`` attachment.
    """
    if not score.parts:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Score has no parts.",
        )
    has_notes = any(
        n for p in score.parts for m in p.measures for n in m.notes
    )
    if not has_notes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Score has no notes to export.",
        )

    try:
        result = export_score(score, format)
    except ExportError as exc:
        msg = str(exc)
        code = (
            status.HTTP_500_INTERNAL_SERVER_ERROR
            if "not installed" in msg.lower()
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=code, detail=msg) from exc

    if download:
        return Response(
            content=result.content,
            media_type=result.media_type,
            headers={
                "Content-Disposition": _content_disposition(result.filename),
            },
        )

    return ExportResponse(
        ok=True,
        format=result.format,
        filename=result.filename,
        media_type=result.media_type,
        content_base64=result.content_base64(),
        byte_length=len(result.content),
        warnings=list(result.warnings),
    )
