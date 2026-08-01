"""Intermediate representation for structure-first pipeline (#58).

L1 Page → L2 Systems → L3 Measures → L4 Note candidates → L5 Glyphs.
Coordinates are always in **input image** pixel space unless noted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from app.schemas.recognize import BoundingBox
from app.schemas.score import DurationName


class RegionRole(str, Enum):
    title = "title"
    key_time = "key_time"
    score = "score"
    other = "other"


@dataclass
class Rect:
    x1: float
    y1: float
    x2: float
    y2: float

    def as_box(self) -> BoundingBox:
        return BoundingBox(x1=self.x1, y1=self.y1, x2=self.x2, y2=self.y2)

    @property
    def width(self) -> float:
        return max(0.0, self.x2 - self.x1)

    @property
    def height(self) -> float:
        return max(0.0, self.y2 - self.y1)

    @property
    def cx(self) -> float:
        return (self.x1 + self.x2) / 2.0

    @property
    def cy(self) -> float:
        return (self.y1 + self.y2) / 2.0

    def pad(self, px: float, *, w: float | None = None, h: float | None = None) -> Rect:
        x1 = self.x1 - px
        y1 = self.y1 - px
        x2 = self.x2 + px
        y2 = self.y2 + px
        if w is not None:
            x1 = max(0.0, x1)
            x2 = min(w, x2)
        if h is not None:
            y1 = max(0.0, y1)
            y2 = min(h, y2)
        return Rect(x1, y1, x2, y2)


@dataclass
class PageRegion:
    role: RegionRole
    rect: Rect
    confidence: float = 1.0
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class NoteGlyph:
    """L5: geometry + OCR binding on one note node."""

    pitch: str | None = None  # "1"–"7" or None if rest
    is_rest: bool = False
    duration: DurationName = DurationName.quarter
    dots: int = 0
    octave: int = 0  # relative: + upper dots, - lower dots
    accidental: str | None = None  # sharp/flat/natural
    underlines: int = 0
    ocr_text: str = ""
    ocr_score: float | None = None
    confidence: float = 0.5
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class NoteCandidate:
    """L4: spatial slot for a note inside a measure (before/with L5 fill)."""

    rect: Rect
    index: int = 0
    glyph: NoteGlyph | None = None
    confidence: float = 0.5
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class MeasureLayout:
    """L3: one measure on a staff system (usually **derived** from splits, #85)."""

    index: int  # 0-based within system
    rect: Rect
    barline_x_left: float | None = None
    barline_x_right: float | None = None
    notes: list[NoteCandidate] = field(default_factory=list)
    confidence: float = 0.5
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class SplitLine:
    """L3 interior vertical split on a staff system (#85). Full-image pixel x."""

    x: float
    split_id: str = ""
    source: str = "detect"  # detect | user | soft_gap | migrate
    confidence: float = 0.7
    extra: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "x": self.x,
            "split_id": self.split_id,
            "source": self.source,
            "confidence": self.confidence,
            **({"extra": self.extra} if self.extra else {}),
        }


@dataclass
class StaffSystem:
    """L2: one horizontal staff / jianpu row.

    **#85**: L3 primary state is ``splits`` (interior vertical dividers).
    ``measures`` and ``barline_xs`` are derived for L4/Score compatibility.
    """

    index: int
    rect: Rect
    measures: list[MeasureLayout] = field(default_factory=list)
    barline_xs: list[float] = field(default_factory=list)
    # Interior split lines (full-image x); not including L2 left/right bounds
    splits: list[SplitLine] = field(default_factory=list)
    confidence: float = 0.5
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class PageLayout:
    """L1: full page structure (geometry skeleton)."""

    width: int
    height: int
    regions: list[PageRegion] = field(default_factory=list)
    systems: list[StaffSystem] = field(default_factory=list)
    key: str | None = None
    time_signature: str | None = None
    title: str | None = None
    warnings: list[str] = field(default_factory=list)
    debug: dict[str, Any] = field(default_factory=dict)

    @property
    def score_region(self) -> Rect | None:
        for r in self.regions:
            if r.role == RegionRole.score:
                return r.rect
        return None
