"""Assemble structure IR → EnPu Score JSON (#58)."""

from __future__ import annotations

from app.pipeline.structure.ir import PageLayout
from app.schemas.score import (
    DurationName,
    Measure,
    NoteEvent,
    Part,
    Score,
    ScoreMeta,
)


def page_layout_to_score(
    layout: PageLayout,
    *,
    filename: str | None = None,
    engine: str | None = None,
) -> Score:
    """Flatten systems/measures/notes into Score v0.1."""
    measures: list[Measure] = []
    mnum = 1
    for sys in layout.systems:
        for ml in sys.measures:
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
                            },
                        )
                    )
            if notes:
                measures.append(Measure(number=mnum, notes=notes))
                mnum += 1

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
            comments="Structure-first pipeline: L1–L4 geometry, L5 OCR pitch.",
            extra={
                "pipeline": "structure",
                "n_systems": len(layout.systems),
                "n_measures": len(measures),
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
