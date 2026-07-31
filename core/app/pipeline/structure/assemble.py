"""Assemble structure IR → EnPu Score JSON + UI debug overlays (#58)."""

from __future__ import annotations

from app.pipeline.problems import attach_problems_to_score, collect_score_problems
from app.pipeline.structure.ir import PageLayout
from app.schemas.recognize import BoundingBox, StructureBox, StructureDebug
from app.schemas.score import (
    DurationName,
    Measure,
    NoteEvent,
    Part,
    Score,
    ScoreMeta,
    TieType,
)


def _tie_from_glyph(g) -> TieType | None:
    t = (g.extra or {}).get("tie")
    if t == "start":
        return TieType.start
    if t == "stop":
        return TieType.stop
    if t in {"continue", "continue_"}:
        return TieType.continue_
    return None


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
    for sys in layout.systems:
        for ml in sys.measures:
            n_l3 += 1
            mnum = n_l3  # 1-based global index == Score.measures position
            notes: list[NoteEvent] = []
            for nc in ml.notes:
                # #69: only pitch L4 slots enter the melody Score
                if (nc.extra or {}).get("kind", "pitch") != "pitch":
                    continue
                g = nc.glyph
                if g is None:
                    continue
                tie = _tie_from_glyph(g)
                if g.is_rest:
                    notes.append(
                        NoteEvent(
                            pitch=None,
                            is_rest=True,
                            duration=g.duration or DurationName.quarter,
                            dots=g.dots,
                            octave=0,
                            tie=tie,
                            extra={
                                "source": "structure_l5",
                                "underlines": g.underlines,
                                "duration_from": g.extra.get(
                                    "duration_from", "default"
                                ),
                                "sustain_dashes": g.extra.get("sustain_dashes"),
                                "confidence": g.confidence,
                                "ocr_score": g.ocr_score,
                                "pitch_from": g.extra.get("pitch_from"),
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
                            tie=tie,
                            extra={
                                "source": "structure_l5",
                                "underlines": g.underlines,
                                "ocr_text": g.ocr_text,
                                "duration_from": g.extra.get(
                                    "duration_from", "default"
                                ),
                                "sustain_dashes": g.extra.get("sustain_dashes"),
                                "confidence": g.confidence,
                                "ocr_score": g.ocr_score,
                                "pitch_from": g.extra.get("pitch_from"),
                                "l3_system": sys.index,
                                "l3_measure": ml.index,
                            },
                        )
                    )
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
                        # #84 measure provenance
                        "measure_source": ml.extra.get("measure_source", "l3_barline"),
                        "closed": ml.extra.get("closed", True),
                        "parts": ml.extra.get("parts"),
                        "cross_line": ml.extra.get("cross_line", False),
                        "measure_id": ml.extra.get("measure_id"),
                        # L4/L5 meter check fields (if present)
                        "meter_capacity": ml.extra.get("meter_capacity"),
                        "meter_beats": ml.extra.get("meter_beats"),
                        "meter_status": ml.extra.get("meter_status"),
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

    score = Score(
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
                "Structure-first pipeline: L3 measures are Score authority (#66)."
            ),
            extra={
                "pipeline": "structure",
                "n_systems": len(layout.systems),
                "n_measures": len(measures),
                "n_l3_measures": n_l3,
                "n_empty_measures": n_empty,
                "measure_source": "l3",
                "warnings": list(layout.warnings),
            },
        ),
    )
    # #46: problem tags for navigation UI
    problems = collect_score_problems(
        score,
        parse_warnings=list(layout.warnings),
    )
    return attach_problems_to_score(score, problems)


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
        # Prefer melody-band y for barline overlay (#84); fall back to system rect
        mb = (sys.extra or {}).get("melody_band")
        if isinstance(mb, (list, tuple)) and len(mb) >= 2:
            by1, by2 = float(mb[0]), float(mb[1])
        else:
            by1, by2 = sys.rect.y1, sys.rect.y2
        for x in sys.barline_xs:
            barlines.append(
                {
                    "system": sys.index,
                    "x": x,
                    "y1": by1,
                    "y2": by2,
                }
            )
        for meas in sys.measures:
            global_m += 1
            # global_m follows system/measure iteration after geometry sort (#78)
            src = (meas.extra or {}).get("measure_source", "")
            label = f"m{global_m}"
            if src and src not in ("l3_barline",):
                label = f"m{global_m}/{src}"
            items.append(
                StructureBox(
                    layer="L3",
                    id=f"l3-m{global_m}",
                    label=label,
                    box=meas.rect.as_box(),
                    kind="measure",
                    confidence=meas.confidence,
                )
            )
            for nc in meas.notes:
                kind = (nc.extra or {}).get("kind", "pitch")
                l4_kind = (
                    "note_roi"
                    if kind == "pitch"
                    else ("chord" if kind == "chord" else "lyric")
                )
                l4_label = (
                    f"n{nc.index + 1}"
                    if kind == "pitch"
                    else f"{kind[0]}{nc.index + 1}"
                )
                items.append(
                    StructureBox(
                        layer="L4",
                        id=f"l4-m{global_m}-{kind}{nc.index}",
                        label=l4_label,
                        box=nc.rect.as_box(),
                        kind=l4_kind,
                        confidence=nc.confidence,
                    )
                )
                g = nc.glyph
                if kind == "pitch":
                    # L5 box always equals L4 note ROI (user-edited L4 must cover L5)
                    l5_box = nc.rect.as_box()
                    if g is not None:
                        dur = (
                            g.duration.value
                            if hasattr(g.duration, "value")
                            else str(g.duration)
                        )
                        label = g.pitch or ("0" if g.is_rest else "?")
                        if g.underlines:
                            label = f"{label}_{g.underlines}"
                        if g.dots:
                            label = f"{label}{'.' * min(2, g.dots)}"
                        if g.octave:
                            label = f"{label}@{g.octave:+d}"
                        if (g.extra or {}).get("sustain_dashes"):
                            label = f"{label}-"
                        if (g.extra or {}).get("pitch_from") == "geometry":
                            label = f"{label}~"
                        items.append(
                            StructureBox(
                                layer="L5",
                                id=f"l5-m{global_m}-n{nc.index}",
                                label=label,
                                box=l5_box,
                                kind="glyph",
                                pitch=g.pitch,
                                duration=dur,
                                underlines=g.underlines,
                                octave=g.octave,
                                confidence=g.confidence,
                            )
                        )
                    else:
                        # Still emit L5 slot aligned to L4 after L4-edit rerun
                        items.append(
                            StructureBox(
                                layer="L5",
                                id=f"l5-m{global_m}-n{nc.index}",
                                label="?",
                                box=l5_box,
                                kind="glyph",
                                confidence=nc.confidence,
                            )
                        )

    return StructureDebug(
        pipeline="structure",
        summary=layout_debug_summary(layout),
        items=items,
        barlines=barlines,
    )
