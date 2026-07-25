"""Assemble structure IR → EnPu Score JSON + UI debug overlays (#58)."""

from __future__ import annotations

from app.pipeline.duration import fit_notes_to_capacity
from app.pipeline.structure.ir import PageLayout
from app.schemas.recognize import BoundingBox, StructureBox, StructureDebug
from app.schemas.score import (
    DurationName,
    Measure,
    NoteEvent,
    Part,
    Score,
    ScoreMeta,
)


def _beats_capacity(time_sig: str) -> float:
    try:
        num, den = time_sig.split("/")
        return int(num) * (4.0 / int(den))
    except Exception:
        return 4.0


def page_layout_to_score(
    layout: PageLayout,
    *,
    filename: str | None = None,
    engine: str | None = None,
) -> Score:
    """Flatten systems/measures/notes into Score v0.1.

    **#66**: L3 geometry is the authority for measure boundaries.
    Every L3 ``MeasureLayout`` becomes exactly one Score ``Measure`` in
    system order (top→bottom) then left→right, including empty measures.
    Notes without a filled glyph are omitted from that measure's note list
    but do **not** drop the measure slot.
    """
    measures: list[Measure] = []
    n_l3 = 0
    n_empty = 0
    n_duration_fit = 0
    capacity = _beats_capacity(layout.time_signature or "4/4")
    for sys in layout.systems:
        for ml in sys.measures:
            n_l3 += 1
            mnum = n_l3  # 1-based global index == Score.measures position
            notes: list[NoteEvent] = []
            for nc in ml.notes:
                g = nc.glyph
                if g is None:
                    continue
                if g.is_rest:
                    notes.append(
                        NoteEvent(
                            pitch=None,
                            is_rest=True,
                            duration=g.duration or DurationName.quarter,
                            dots=g.dots,
                            octave=0,
                            extra={
                                "source": "structure_l5",
                                "underlines": g.underlines,
                                "duration_from": g.extra.get(
                                    "duration_from", "default"
                                ),
                                "l3_system": sys.index,
                                "l3_measure": ml.index,
                            },
                        )
                    )
                elif g.pitch in set("1234567"):
                    notes.append(
                        NoteEvent(
                            pitch=g.pitch,
                            is_rest=False,
                            duration=g.duration or DurationName.quarter,
                            dots=g.dots,
                            octave=int(g.octave or 0),
                            extra={
                                "source": "structure_l5",
                                "underlines": g.underlines,
                                "ocr_text": g.ocr_text,
                                "duration_from": g.extra.get(
                                    "duration_from", "default"
                                ),
                                "l3_system": sys.index,
                                "l3_measure": ml.index,
                            },
                        )
                    )
            # #54: L3 keeps measure count; soft-fit durations so bar is not overfull
            if notes and capacity > 0:
                notes, fitted = fit_notes_to_capacity(notes, capacity)
                if fitted:
                    n_duration_fit += 1
            if not notes:
                n_empty += 1
            measures.append(
                Measure(
                    number=mnum,
                    notes=notes,
                    extra={
                        "source": "structure_l3",
                        "system_index": sys.index,
                        "measure_index_in_system": ml.index,
                        "global_index": mnum - 1,
                        "rect": {
                            "x1": ml.rect.x1,
                            "y1": ml.rect.y1,
                            "x2": ml.rect.x2,
                            "y2": ml.rect.y2,
                        },
                        "barline_x_left": ml.barline_x_left,
                        "barline_x_right": ml.barline_x_right,
                        "l3_confidence": ml.confidence,
                    },
                )
            )

    if not measures:
        measures = [
            Measure(
                number=1,
                notes=[
                    NoteEvent(
                        pitch="1",
                        duration=DurationName.quarter,
                        extra={"source": "structure_empty_placeholder"},
                    )
                ],
                extra={"source": "structure_empty_placeholder"},
            )
        ]

    return Score(
        schema_version="0.1",
        title=layout.title or "",
        key=layout.key or "C",
        time_signature=layout.time_signature or "4/4",
        tempo_bpm=None,
        parts=[Part(id="P1", name="melody", measures=measures)],
        meta=ScoreMeta(
            source_image=filename,
            engine=engine,
            created_by="enpu-structure-#58",
            comments=(
                "Structure-first pipeline: L3 measures (#66) + duration fit (#54)."
            ),
            extra={
                "pipeline": "structure",
                "n_systems": len(layout.systems),
                "n_measures": len(measures),
                "n_l3_measures": n_l3,
                "n_empty_measures": n_empty,
                "n_duration_fit_measures": n_duration_fit,
                "measure_source": "l3",
                "warnings": list(layout.warnings),
            },
        ),
    )


def layout_debug_summary(layout: PageLayout) -> dict:
    """Compact debug dict for RecognizeMeta / logs."""
    return {
        "pipeline": "structure",
        "width": layout.width,
        "height": layout.height,
        "n_systems": len(layout.systems),
        "n_measures": sum(len(s.measures) for s in layout.systems),
        "n_note_candidates": sum(
            len(m.notes) for s in layout.systems for m in s.measures
        ),
        "n_pitched": sum(
            1
            for s in layout.systems
            for m in s.measures
            for n in m.notes
            if n.glyph and n.glyph.pitch
        ),
        "key": layout.key,
        "time_signature": layout.time_signature,
        "title": layout.title,
        "warnings": list(layout.warnings)[:20],
    }


def page_layout_to_structure_debug(layout: PageLayout) -> StructureDebug:
    """Serialize L1–L5 boxes for desktop layered overlay."""
    items: list[StructureBox] = []
    barlines: list[dict] = []

    for reg in layout.regions:
        items.append(
            StructureBox(
                layer="L1",
                id=f"l1-{reg.role.value}",
                label=reg.role.value,
                box=reg.rect.as_box(),
                kind=reg.role.value,
                confidence=reg.confidence,
            )
        )

    global_m = 0  # 0-based; Score measure number = global_m + 1 (#66)
    for sys in layout.systems:
        items.append(
            StructureBox(
                layer="L2",
                id=f"l2-sys{sys.index}",
                label=f"谱行 {sys.index + 1}",
                box=sys.rect.as_box(),
                kind="system",
                confidence=sys.confidence,
            )
        )
        for x in sys.barline_xs:
            barlines.append(
                {
                    "system": sys.index,
                    "x": x,
                    "y1": sys.rect.y1,
                    "y2": sys.rect.y2,
                }
            )
        for meas in sys.measures:
            global_m += 1
            items.append(
                StructureBox(
                    layer="L3",
                    id=f"l3-m{global_m}",
                    label=f"m{global_m}",
                    box=meas.rect.as_box(),
                    kind="measure",
                    confidence=meas.confidence,
                )
            )
            for nc in meas.notes:
                items.append(
                    StructureBox(
                        layer="L4",
                        id=f"l4-m{global_m}-n{nc.index}",
                        label=f"n{nc.index + 1}",
                        box=nc.rect.as_box(),
                        kind="note_roi",
                        confidence=nc.confidence,
                    )
                )
                g = nc.glyph
                if g is not None:
                    dur = g.duration.value if hasattr(g.duration, "value") else str(g.duration)
                    label = g.pitch or ("0" if g.is_rest else "?")
                    if g.underlines:
                        label = f"{label}_{g.underlines}"
                    if g.octave:
                        label = f"{label}@{g.octave:+d}"
                    items.append(
                        StructureBox(
                            layer="L5",
                            id=f"l5-m{global_m}-n{nc.index}",
                            label=label,
                            box=nc.rect.as_box(),
                            kind="glyph",
                            pitch=g.pitch,
                            duration=dur,
                            underlines=g.underlines,
                            octave=g.octave,
                            confidence=g.confidence,
                        )
                    )

    return StructureDebug(
        pipeline="structure",
        summary=layout_debug_summary(layout),
        items=items,
        barlines=barlines,
    )
