"""Collect Score problem tags for navigation UI (#46)."""

from __future__ import annotations

from app.schemas.problems import ScoreProblem
from app.schemas.recognize import LayoutRegion
from app.schemas.score import Score

# Note confidence below this → low_confidence warning
_LOW_CONF = 0.55
# Geometry pitch without strong OCR
_GEOM_CONF = 0.62


def collect_score_problems(
    score: Score,
    *,
    regions: list[LayoutRegion] | None = None,
    parse_warnings: list[str] | None = None,
) -> list[ScoreProblem]:
    """Scan Score (+ optional layout regions) for reviewable issues."""
    problems: list[ScoreProblem] = []
    n = 0

    def add(
        kind: str,
        message: str,
        *,
        severity: str = "warning",
        measure: int | None = None,
        note_index: int | None = None,
        confidence: float | None = None,
        source: str | None = None,
        extra: dict | None = None,
    ) -> None:
        nonlocal n
        n += 1
        problems.append(
            ScoreProblem(
                id=f"p{n}",
                kind=kind,  # type: ignore[arg-type]
                severity=severity,  # type: ignore[arg-type]
                message=message,
                measure=measure,
                note_index=note_index,
                confidence=confidence,
                source=source,
                extra=extra or {},
            )
        )

    part = score.melody_part()
    if part is None:
        add("other", "Score 无旋律声部", severity="error", source="score")
        return problems

    for meas in part.measures:
        mnum = meas.number
        m_extra = meas.extra or {}
        status = m_extra.get("meter_status")
        capacity = m_extra.get("meter_capacity")
        beats = m_extra.get("meter_beats")
        if status == "over":
            add(
                "meter_over",
                f"小节 {mnum} 时值过满（{beats}/{capacity} 拍）",
                severity="error",
                measure=mnum,
                source="meter",
                extra={"beats": beats, "capacity": capacity},
            )
        elif status == "under":
            add(
                "meter_under",
                f"小节 {mnum} 时值不足（{beats}/{capacity} 拍）",
                severity="warning",
                measure=mnum,
                source="meter",
                extra={"beats": beats, "capacity": capacity},
            )

        notes = meas.notes or []
        if not notes and m_extra.get("source") != "structure_empty_placeholder":
            # Empty slot from L3 without L5 pitch
            if m_extra.get("source") == "structure_l3" or m_extra.get("meter_status"):
                add(
                    "empty_measure",
                    f"小节 {mnum} 无识别音符",
                    severity="warning",
                    measure=mnum,
                    source="structure",
                )

        for ni, note in enumerate(notes):
            ex = note.extra or {}
            conf = ex.get("confidence")
            if conf is None and note.extra:
                conf = ex.get("ocr_score")
            try:
                conf_f = float(conf) if conf is not None else None
            except (TypeError, ValueError):
                conf_f = None

            pitch_from = ex.get("pitch_from")
            if pitch_from == "geometry":
                add(
                    "geometry_pitch",
                    f"小节 {mnum} 音 {ni + 1}：音高来自几何兜底"
                    + (f"（{note.pitch}）" if note.pitch else ""),
                    severity="info",
                    measure=mnum,
                    note_index=ni,
                    confidence=conf_f if conf_f is not None else _GEOM_CONF,
                    source="structure_l5",
                )
            if conf_f is not None and conf_f < _LOW_CONF and not note.is_rest:
                add(
                    "low_confidence",
                    f"小节 {mnum} 音 {ni + 1}：低置信度 {conf_f:.2f}"
                    + (f"（{note.pitch}）" if note.pitch else ""),
                    severity="warning",
                    measure=mnum,
                    note_index=ni,
                    confidence=conf_f,
                    source=str(ex.get("source") or "recognize"),
                )

    # Layout pollution: title/meta digits that look like pitch pollution
    if regions:
        poll = [
            r
            for r in regions
            if r.kind in {"title", "meta", "lyrics", "footer", "annotation"}
            and r.text
            and any(c.isdigit() for c in r.text)
        ]
        # Cap noise
        for r in poll[:12]:
            add(
                "layout_pollution",
                f"版面「{r.kind}」含数字：{r.text[:24]}",
                severity="info",
                source="layout",
                extra={"kind": r.kind, "text": r.text[:40]},
            )

    if parse_warnings:
        for w in parse_warnings[:8]:
            if "meter" in w.lower() or "时值" in w or "overfull" in w.lower():
                continue  # already covered by meter_* tags
            if "L1" in w or "L2" in w or "L3" in w or "L4" in w or "L5" in w:
                if "fallback" in w or "empty" in w or "failed" in w.lower():
                    add(
                        "other",
                        w[:120],
                        severity="info",
                        source="pipeline",
                    )

    return problems


def attach_problems_to_score(
    score: Score,
    problems: list[ScoreProblem],
) -> Score:
    """Write problems into score.extra (schema-compatible bag)."""
    extra = dict(score.extra or {})
    extra["problems"] = [p.model_dump() for p in problems]
    extra["n_problems"] = len(problems)
    meta = score.meta
    meta_extra = dict(meta.extra or {})
    meta_extra["n_problems"] = len(problems)
    meta_extra["problem_kinds"] = sorted({p.kind for p in problems})
    # Pydantic model_copy
    return score.model_copy(
        update={
            "extra": extra,
            "meta": meta.model_copy(update={"extra": meta_extra}),
        }
    )
