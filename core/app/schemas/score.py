"""EnPu internal score model — JSON Schema v0.1 (issue #9).

This is the **source of truth** for recognition output (post-parse),
editing, and export (MusicXML / MIDI via adapters).
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

SCHEMA_VERSION = "0.1"


class DurationName(str, Enum):
    """Note/rest length in Western names (export-friendly).

    Jianpu underline/dash semantics map here in the parser (#10).
    """

    whole = "whole"
    half = "half"
    quarter = "quarter"
    eighth = "eighth"
    sixteenth = "sixteenth"
    thirty_second = "thirty_second"


class Accidental(str, Enum):
    sharp = "sharp"
    flat = "flat"
    natural = "natural"


class TieType(str, Enum):
    start = "start"
    stop = "stop"
    continue_ = "continue"


class NoteEvent(BaseModel):
    """One timed pitch (or rest) plus optional lyric syllable.

    Pitch uses **jianpu degree** ``\"1\"``–``\"7\"`` (movable-do relative to
    ``Score.key``). Absolute MIDI mapping is done at export time.
    """

    pitch: str | None = Field(
        default=None,
        description='Jianpu degree "1"-"7"; null when is_rest.',
        examples=["1", "5"],
    )
    accidental: Accidental | None = Field(
        default=None,
        description="Chromatic alteration applied to the degree.",
    )
    octave: int = Field(
        default=0,
        ge=-3,
        le=3,
        description=(
            "Relative octave vs middle register: "
            "positive = upper dots, negative = lower dots."
        ),
    )
    duration: DurationName = Field(
        default=DurationName.quarter,
        description="Base duration before dots.",
    )
    dots: int = Field(
        default=0,
        ge=0,
        le=2,
        description="Augmentation dots (0–2).",
    )
    is_rest: bool = Field(default=False, description="True if this event is a rest.")
    lyric: str | None = Field(
        default=None,
        description="Lyric syllable aligned to this note (optional).",
    )
    tie: TieType | None = Field(
        default=None,
        description="Tie / slur attachment for multi-note sustain (v0.1 minimal).",
    )
    extra: dict[str, Any] = Field(
        default_factory=dict,
        description="Extension bag for experimental fields.",
    )

    @field_validator("pitch")
    @classmethod
    def _pitch_is_degree(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if v not in {"1", "2", "3", "4", "5", "6", "7"}:
            raise ValueError('pitch must be "1"-"7" or null for rest')
        return v

    @model_validator(mode="after")
    def _rest_xor_pitch(self) -> NoteEvent:
        if self.is_rest:
            if self.pitch is not None:
                raise ValueError("rest events must not set pitch")
        else:
            if self.pitch is None:
                raise ValueError("non-rest events require pitch")
        return self


class Measure(BaseModel):
    """One bar of music."""

    number: int = Field(..., ge=1, description="1-based measure index.")
    notes: list[NoteEvent] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)


class Part(BaseModel):
    """One voice / staff line (v0.1 typically a single melody)."""

    id: str = Field(default="P1", description="Stable part id.")
    name: str = Field(default="melody", description="Human-readable part name.")
    measures: list[Measure] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)


class ScoreMeta(BaseModel):
    """Optional provenance for recognition / editing pipeline."""

    source_image: str | None = None
    engine: str | None = None
    created_by: str | None = None
    comments: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class Score(BaseModel):
    """EnPu score document (schema_version 0.1)."""

    schema_version: Literal["0.1"] = Field(
        default="0.1",
        description="Document schema version; bump on breaking changes.",
    )
    title: str = Field(default="", description="Song / piece title.")
    key: str = Field(
        default="C",
        description=(
            'Tonal center. Prefer pitch-class letter: "C", "G", "F", "D", "Bb", "Eb". '
            'Jianpu "1=C" style may be stored in extra until normalized.'
        ),
        examples=["C", "G", "F"],
    )
    time_signature: str = Field(
        default="4/4",
        description='Meter as "beats/beat-type", e.g. "4/4", "3/4", "6/8".',
        examples=["4/4", "3/4"],
    )
    tempo_bpm: float | None = Field(
        default=None,
        gt=0,
        description="Optional metronome mark in BPM.",
    )
    parts: list[Part] = Field(
        default_factory=list,
        min_length=0,
        description="One or more parts; minimal song uses a single melody part.",
    )
    meta: ScoreMeta = Field(default_factory=ScoreMeta)
    extra: dict[str, Any] = Field(default_factory=dict)

    @field_validator("time_signature")
    @classmethod
    def _time_sig_format(cls, v: str) -> str:
        parts = v.split("/")
        if len(parts) != 2 or not all(p.isdigit() and int(p) > 0 for p in parts):
            raise ValueError('time_signature must look like "4/4"')
        return v

    def melody_part(self) -> Part | None:
        """Convenience: first part named melody, else first part."""
        for p in self.parts:
            if p.name.lower() in {"melody", "main", "soprano"}:
                return p
        return self.parts[0] if self.parts else None


def example_minimal_score() -> Score:
    """Canonical minimal example: one voice, two bars, lyrics."""
    return Score(
        schema_version="0.1",
        title="示例诗歌（最小）",
        key="C",
        time_signature="4/4",
        tempo_bpm=80,
        parts=[
            Part(
                id="P1",
                name="melody",
                measures=[
                    Measure(
                        number=1,
                        notes=[
                            NoteEvent(
                                pitch="1",
                                octave=0,
                                duration=DurationName.quarter,
                                lyric="主",
                            ),
                            NoteEvent(
                                pitch="2",
                                octave=0,
                                duration=DurationName.quarter,
                                lyric="恩",
                            ),
                            NoteEvent(
                                pitch="3",
                                octave=0,
                                duration=DurationName.quarter,
                                lyric="典",
                            ),
                            NoteEvent(
                                pitch="5",
                                octave=0,
                                duration=DurationName.quarter,
                                lyric="够",
                            ),
                        ],
                    ),
                    Measure(
                        number=2,
                        notes=[
                            NoteEvent(
                                pitch="5",
                                octave=0,
                                duration=DurationName.half,
                                lyric="我",
                            ),
                            NoteEvent(
                                pitch="3",
                                octave=0,
                                duration=DurationName.quarter,
                                lyric="用",
                            ),
                            NoteEvent(is_rest=True, duration=DurationName.quarter),
                        ],
                    ),
                ],
            )
        ],
        meta=ScoreMeta(
            created_by="enpu-schema-v0.1",
            comments="Minimal single-voice + lyrics example for issue #9.",
        ),
    )
