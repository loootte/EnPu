"""Tests for score problem tags (#46)."""

from __future__ import annotations

from app.pipeline.problems import attach_problems_to_score, collect_score_problems
from app.schemas.recognize import BoundingBox, LayoutRegion
from app.schemas.score import DurationName, Measure, NoteEvent, Part, Score, ScoreMeta


def _score_with_meter() -> Score:
    return Score(
        schema_version="0.1",
        title="t",
        key="C",
        time_signature="4/4",
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
                                duration=DurationName.quarter,
                                extra={
                                    "confidence": 0.4,
                                    "pitch_from": "geometry",
                                    "source": "structure_l5",
                                },
                            ),
                            NoteEvent(
                                pitch="5",
                                duration=DurationName.quarter,
                                extra={"confidence": 0.9, "source": "structure_l5"},
                            ),
                        ],
                        extra={
                            "meter_status": "under",
                            "meter_beats": 2.0,
                            "meter_capacity": 4.0,
                            "source": "structure_l3",
                        },
                    ),
                    Measure(
                        number=2,
                        notes=[],
                        extra={"source": "structure_l3", "meter_status": "ok"},
                    ),
                ],
            )
        ],
        meta=ScoreMeta(),
    )


def test_collect_meter_and_confidence_problems() -> None:
    sc = _score_with_meter()
    problems = collect_score_problems(sc)
    kinds = {p.kind for p in problems}
    assert "meter_under" in kinds
    assert "low_confidence" in kinds
    assert "geometry_pitch" in kinds
    assert "empty_measure" in kinds
    m1 = [p for p in problems if p.measure == 1]
    assert any(p.kind == "low_confidence" for p in m1)


def test_layout_pollution_from_regions() -> None:
    sc = Score(
        schema_version="0.1",
        parts=[Part(measures=[Measure(number=1, notes=[])])],
    )
    regions = [
        LayoutRegion(
            text="奇 妙 123",
            box=BoundingBox(x1=0, y1=0, x2=10, y2=10),
            kind="title",
        )
    ]
    problems = collect_score_problems(sc, regions=regions)
    assert any(p.kind == "layout_pollution" for p in problems)


def test_attach_problems_to_score_extra() -> None:
    sc = _score_with_meter()
    problems = collect_score_problems(sc)
    out = attach_problems_to_score(sc, problems)
    assert out.extra.get("n_problems") == len(problems)
    assert isinstance(out.extra.get("problems"), list)
    assert out.meta.extra.get("n_problems") == len(problems)
