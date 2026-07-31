"""Shared types for layered evaluation (#86)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


@dataclass(frozen=True)
class Box:
    """Axis-aligned box in image coordinates."""

    x1: float
    y1: float
    x2: float
    y2: float
    label: str = ""
    kind: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def width(self) -> float:
        return max(0.0, self.x2 - self.x1)

    @property
    def height(self) -> float:
        return max(0.0, self.y2 - self.y1)

    @property
    def area(self) -> float:
        return self.width * self.height

    def as_dict(self) -> dict[str, Any]:
        return {
            "x1": self.x1,
            "y1": self.y1,
            "x2": self.x2,
            "y2": self.y2,
            "label": self.label,
            "kind": self.kind,
            **({"meta": self.meta} if self.meta else {}),
        }


ErrorKind = Literal["tp", "fp", "fn"]


@dataclass
class ErrorBox:
    """Matched or unmatched box for error visualization."""

    kind: ErrorKind
    box: Box
    iou: float | None = None
    partner: Box | None = None

    def as_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"kind": self.kind, "box": self.box.as_dict()}
        if self.iou is not None:
            d["iou"] = self.iou
        if self.partner is not None:
            d["partner"] = self.partner.as_dict()
        return d


@dataclass
class LayerMetric:
    """Standard metrics for one structure layer."""

    layer: str
    precision: float = 0.0
    recall: float = 0.0
    f1: float = 0.0
    tp: int = 0
    fp: int = 0
    fn: int = 0
    mean_iou: float = 0.0
    # Extra layer-specific counts
    extra: dict[str, Any] = field(default_factory=dict)
    errors: list[ErrorBox] = field(default_factory=list)
    # How this metric was produced
    mode: str = "iou"  # iou | count | sequence | unavailable

    def as_dict(self, *, include_errors: bool = True) -> dict[str, Any]:
        d: dict[str, Any] = {
            "layer": self.layer,
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "f1": round(self.f1, 4),
            "tp": self.tp,
            "fp": self.fp,
            "fn": self.fn,
            "mean_iou": round(self.mean_iou, 4),
            "mode": self.mode,
            "extra": self.extra,
        }
        if include_errors:
            d["errors"] = [e.as_dict() for e in self.errors]
        return d


@dataclass
class SampleMetrics:
    """All-layer metrics for one image/sample."""

    sample_id: str
    layers: dict[str, LayerMetric] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    def as_dict(self, *, include_errors: bool = False) -> dict[str, Any]:
        return {
            "sample_id": self.sample_id,
            "layers": {
                k: v.as_dict(include_errors=include_errors)
                for k, v in self.layers.items()
            },
            "warnings": self.warnings,
            "meta": self.meta,
        }

    def summary_f1(self) -> dict[str, float]:
        return {k: v.f1 for k, v in self.layers.items()}
