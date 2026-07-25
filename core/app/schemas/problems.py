"""Recognition problem tags for smart navigation (#46 / P4-G)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

ProblemKind = Literal[
    "low_confidence",
    "meter_over",
    "meter_under",
    "empty_measure",
    "layout_pollution",
    "geometry_pitch",
    "other",
]

ProblemSeverity = Literal["error", "warning", "info"]


class ScoreProblem(BaseModel):
    """One reviewable issue linked to a measure (and optional note)."""

    id: str = Field(..., description="Stable id within a Score response.")
    kind: ProblemKind = Field(..., description="Machine-readable problem class.")
    severity: ProblemSeverity = Field(default="warning")
    message: str = Field(..., description="Human-readable summary (zh/en).")
    measure: int | None = Field(
        default=None,
        ge=1,
        description="1-based measure number when applicable.",
    )
    note_index: int | None = Field(
        default=None,
        ge=0,
        description="0-based note index inside the measure.",
    )
    confidence: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Related confidence if available.",
    )
    source: str | None = Field(
        default=None,
        description="Producer: structure_l5, parse, layout, meter, …",
    )
    extra: dict[str, Any] = Field(default_factory=dict)
