"""Extract prediction boxes / sequences from pipeline outputs (#86)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.evaluation.types import Box
from app.pipeline.structure.ir import PageLayout
from app.schemas.recognize import StructureDebug
from app.schemas.score import Score


@dataclass
class PredGeometry:
    """Layered prediction geometry + barline xs."""

    layers: dict[str, list[Box]] = field(default_factory=dict)
    barline_xs: list[float] = field(default_factory=list)

    def get(self, layer: str) -> list[Box]:
        return list(self.layers.get(layer) or [])


def boxes_from_page_layout(layout: PageLayout) -> PredGeometry:
    """L1–L4 geometry from a finished ``PageLayout``."""
    layers: dict[str, list[Box]] = {"L1": [], "L2": [], "L3": [], "L4": []}
    bar_xs: list[float] = []

    for reg in layout.regions:
        layers["L1"].append(
            Box(
                x1=reg.rect.x1,
                y1=reg.rect.y1,
                x2=reg.rect.x2,
                y2=reg.rect.y2,
                label=reg.role.value,
                kind=reg.role.value,
            )
        )

    for sys in layout.systems:
        layers["L2"].append(
            Box(
                x1=sys.rect.x1,
                y1=sys.rect.y1,
                x2=sys.rect.x2,
                y2=sys.rect.y2,
                label=f"sys{sys.index}",
                kind="system",
            )
        )
        bar_xs.extend(list(sys.barline_xs or []))
        for meas in sys.measures:
            layers["L3"].append(
                Box(
                    x1=meas.rect.x1,
                    y1=meas.rect.y1,
                    x2=meas.rect.x2,
                    y2=meas.rect.y2,
                    label=f"m{meas.index}",
                    kind="measure",
                    meta={
                        "measure_source": (meas.extra or {}).get("measure_source"),
                        "system": sys.index,
                    },
                )
            )
            for nc in meas.notes:
                kind = str((nc.extra or {}).get("kind") or "pitch")
                layers["L4"].append(
                    Box(
                        x1=nc.rect.x1,
                        y1=nc.rect.y1,
                        x2=nc.rect.x2,
                        y2=nc.rect.y2,
                        label=f"{kind}{nc.index}",
                        kind=kind,
                        meta={"system": sys.index, "measure": meas.index},
                    )
                )

    return PredGeometry(layers=layers, barline_xs=bar_xs)


def boxes_from_structure_debug(
    structure: StructureDebug | dict[str, Any],
) -> PredGeometry:
    """Extract layer boxes from API ``structure`` payload."""
    if isinstance(structure, StructureDebug):
        items = structure.items
        barlines = structure.barlines
    else:
        items = structure.get("items") or []
        barlines = structure.get("barlines") or []

    layers: dict[str, list[Box]] = {
        "L1": [],
        "L2": [],
        "L3": [],
        "L4": [],
        "L5": [],
    }
    for it in items:
        if hasattr(it, "layer"):
            layer = str(it.layer)
            box = it.box
            label = it.label or ""
            kind = it.kind or ""
        else:
            layer = str(it.get("layer") or "")
            box = it.get("box") or {}
            label = str(it.get("label") or "")
            kind = str(it.get("kind") or "")
        if layer not in layers or box is None:
            continue
        try:
            if hasattr(box, "x1"):
                b = Box(
                    x1=float(box.x1),
                    y1=float(box.y1),
                    x2=float(box.x2),
                    y2=float(box.y2),
                    label=label,
                    kind=kind,
                )
            else:
                b = Box(
                    x1=float(box["x1"]),
                    y1=float(box["y1"]),
                    x2=float(box["x2"]),
                    y2=float(box["y2"]),
                    label=label,
                    kind=kind,
                )
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
        layers[layer].append(b)

    xs: list[float] = []
    for bl in barlines or []:
        try:
            if isinstance(bl, dict):
                xs.append(float(bl["x"]))
            else:
                xs.append(float(getattr(bl, "x")))
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
    return PredGeometry(layers=layers, barline_xs=xs)


def pitch_sequence_from_score_obj(score: Score | dict[str, Any] | None) -> list[str]:
    if score is None:
        return []
    if isinstance(score, Score):
        data = score.model_dump(mode="json")
    else:
        data = score
    from app.evaluation.gt_loader import pitch_sequence_from_score

    return pitch_sequence_from_score(data)


def measure_count_from_score_obj(score: Score | dict[str, Any] | None) -> int:
    if score is None:
        return 0
    if isinstance(score, Score):
        mel = score.melody_part()
        if mel is None:
            return 0
        return len(mel.measures)
    from app.evaluation.gt_loader import measure_count_from_score

    return measure_count_from_score(score)


def system_count_from_layout(layout: PageLayout | None) -> int:
    if layout is None:
        return 0
    return len(layout.systems)
