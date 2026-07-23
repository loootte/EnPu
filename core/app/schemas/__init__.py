"""Pydantic request/response models."""

from app.schemas.recognize import (
    BoundingBox,
    HealthResponse,
    NoteHint,
    RecognizeMeta,
    RecognizeResponse,
)
from app.schemas.score import (
    SCHEMA_VERSION,
    Accidental,
    DurationName,
    Measure,
    NoteEvent,
    Part,
    Score,
    ScoreMeta,
    TieType,
    example_minimal_score,
)

__all__ = [
    "BoundingBox",
    "HealthResponse",
    "NoteHint",
    "RecognizeMeta",
    "RecognizeResponse",
    "SCHEMA_VERSION",
    "Accidental",
    "DurationName",
    "Measure",
    "NoteEvent",
    "Part",
    "Score",
    "ScoreMeta",
    "TieType",
    "example_minimal_score",
]
