"""Rebuild PageLayout from StructureDebug and apply user box edits (#78)."""

from __future__ import annotations

import re
from typing import Any, Literal

from app.pipeline.structure.ir import (
    MeasureLayout,
    NoteCandidate,
    NoteGlyph,
    PageLayout,
    PageRegion,
    Rect,
    RegionRole,
    StaffSystem,
)
from app.schemas.recognize import BoundingBox, StructureBox, StructureDebug
from app.schemas.score import DurationName

StructureLayer = Literal["L1", "L2", "L3", "L4", "L5"]

_L2_RE = re.compile(r"^l2-sys(\d+)$", re.I)
_L3_RE = re.compile(r"^l3-m(\d+)$", re.I)
_L4_RE = re.compile(r"^l4-m(\d+)-(pitch|chord|lyric|other)?(\d+)$", re.I)
_L5_RE = re.compile(r"^l5-m(\d+)-n(\d+)$", re.I)


def _box_to_rect(box: BoundingBox | dict[str, Any]) -> Rect:
    if isinstance(box, BoundingBox):
        return Rect(float(box.x1), float(box.y1), float(box.x2), float(box.y2))
    return Rect(
        float(box["x1"]),
        float(box["y1"]),
        float(box["x2"]),
        float(box["y2"]),
    )


def _norm_rect(r: Rect, *, w: int, h: int, min_side: float = 4.0) -> Rect:
    x1 = max(0.0, min(r.x1, r.x2))
    y1 = max(0.0, min(r.y1, r.y2))
    x2 = min(float(w), max(r.x1, r.x2))
    y2 = min(float(h), max(r.y1, r.y2))
    if x2 - x1 < min_side:
        x2 = min(float(w), x1 + min_side)
    if y2 - y1 < min_side:
        y2 = min(float(h), y1 + min_side)
    return Rect(x1, y1, x2, y2)


def apply_structure_edits(
    structure: StructureDebug,
    edits: list[dict[str, Any]] | list[StructureBox],
    *,
    width: int,
    height: int,
) -> StructureDebug:
    """Return a copy of structure with matching item boxes replaced by edits.

    Each edit needs ``id`` (preferred) or (layer + label) and a ``box``.
    """
    by_id: dict[str, BoundingBox] = {}
    by_layer_label: dict[tuple[str, str], BoundingBox] = {}
    for e in edits:
        if isinstance(e, StructureBox):
            eid = e.id
            layer = e.layer
            label = e.label
            box = e.box
        else:
            eid = str(e.get("id") or "")
            layer = str(e.get("layer") or "")
            label = str(e.get("label") or "")
            raw_box = e.get("box") or e
            box = BoundingBox(
                x1=float(raw_box["x1"] if isinstance(raw_box, dict) else raw_box.x1),
                y1=float(raw_box["y1"] if isinstance(raw_box, dict) else raw_box.y1),
                x2=float(raw_box["x2"] if isinstance(raw_box, dict) else raw_box.x2),
                y2=float(raw_box["y2"] if isinstance(raw_box, dict) else raw_box.y2),
            )
        r = _norm_rect(_box_to_rect(box), w=width, h=height)
        nb = BoundingBox(x1=r.x1, y1=r.y1, x2=r.x2, y2=r.y2)
        if eid:
            by_id[eid] = nb
        if layer and label:
            by_layer_label[(layer, label)] = nb

    items: list[StructureBox] = []
    for it in structure.items:
        box = it.box
        if it.id and it.id in by_id:
            box = by_id[it.id]
        elif (it.layer, it.label) in by_layer_label:
            box = by_layer_label[(it.layer, it.label)]
        items.append(it.model_copy(update={"box": box}))
    return structure.model_copy(update={"items": items})


def page_layout_from_structure(
    structure: StructureDebug,
    *,
    width: int,
    height: int,
    key: str | None = None,
    time_signature: str | None = None,
    title: str | None = None,
    warnings: list[str] | None = None,
) -> PageLayout:
    """Rehydrate a PageLayout skeleton from structure overlay items (#78)."""
    regions: list[PageRegion] = []
    for it in structure.items:
        if it.layer != "L1":
            continue
        role_name = (it.kind or it.label or "other").lower()
        try:
            role = RegionRole(role_name)
        except ValueError:
            role = RegionRole.other
        regions.append(
            PageRegion(
                role=role,
                rect=_norm_rect(_box_to_rect(it.box), w=width, h=height),
                confidence=float(it.confidence or 0.8),
                extra={"source": "user_structure", "id": it.id},
            )
        )
    if not any(r.role == RegionRole.score for r in regions):
        regions.append(
            PageRegion(
                role=RegionRole.score,
                rect=Rect(0, 0, float(width), float(height)),
                confidence=0.4,
                extra={"source": "fallback_full_page"},
            )
        )

    l2_items = [it for it in structure.items if it.layer == "L2"]
    l2_items = sorted(l2_items, key=lambda it: (it.box.y1, it.box.x1))
    systems: list[StaffSystem] = []
    for i, it in enumerate(l2_items):
        idx = i
        m = _L2_RE.match(it.id or "")
        if m:
            idx = int(m.group(1))
        systems.append(
            StaffSystem(
                index=idx,
                rect=_norm_rect(_box_to_rect(it.box), w=width, h=height),
                confidence=float(it.confidence or 0.8),
                extra={"source": "user_structure", "id": it.id},
            )
        )
    systems.sort(key=lambda s: (s.rect.y1, s.rect.x1))
    for i, s in enumerate(systems):
        s.index = i

    # L3 measures → assign to systems by vertical center
    l3_items = [it for it in structure.items if it.layer == "L3"]
    l3_items = sorted(l3_items, key=lambda it: (it.box.y1, it.box.x1))
    for it in l3_items:
        rect = _norm_rect(_box_to_rect(it.box), w=width, h=height)
        sys = _nearest_system(systems, rect)
        if sys is None:
            continue
        mi = len(sys.measures)
        m_id = _L3_RE.match(it.id or "")
        global_m = int(m_id.group(1)) if m_id else None
        sys.measures.append(
            MeasureLayout(
                index=mi,
                rect=rect,
                confidence=float(it.confidence or 0.75),
                extra={
                    "source": "user_structure",
                    "id": it.id,
                    "global_m": global_m,
                },
            )
        )
    for sys in systems:
        sys.measures.sort(key=lambda m: (m.rect.x1, m.rect.y1))
        for i, m in enumerate(sys.measures):
            m.index = i
        # Reconstruct barline xs from measure edges
        xs: list[float] = []
        for m in sys.measures:
            if m.barline_x_left is None:
                m.barline_x_left = m.rect.x1
            if m.barline_x_right is None:
                m.barline_x_right = m.rect.x2
            xs.extend([m.rect.x1, m.rect.x2])
        # Prefer barlines from structure if present
        bl = [
            float(b.get("x"))
            for b in (structure.barlines or [])
            if int(b.get("system", -1)) == sys.index and b.get("x") is not None
        ]
        if bl:
            sys.barline_xs = sorted(set(bl))
        else:
            sys.barline_xs = sorted(set(xs))

    # L4 note candidates
    l4_items = [it for it in structure.items if it.layer == "L4"]
    for it in l4_items:
        rect = _norm_rect(_box_to_rect(it.box), w=width, h=height)
        kind = _l4_kind(it)
        global_m, local_i = _parse_l4_ids(it)
        meas = _find_measure(systems, global_m=global_m, rect=rect)
        if meas is None:
            continue
        idx = local_i if local_i is not None else len(meas.notes)
        meas.notes.append(
            NoteCandidate(
                rect=rect,
                index=idx,
                confidence=float(it.confidence or 0.7),
                extra={"kind": kind, "source": "user_structure", "id": it.id},
            )
        )
    for sys in systems:
        for meas in sys.measures:
            meas.notes.sort(key=lambda n: (n.rect.x1, n.rect.y1))
            for i, n in enumerate(meas.notes):
                n.index = i

    # L5 glyphs onto matching L4 pitch slots
    l5_items = [it for it in structure.items if it.layer == "L5"]
    for it in l5_items:
        m_id = _L5_RE.match(it.id or "")
        global_m = int(m_id.group(1)) if m_id else None
        n_idx = int(m_id.group(2)) if m_id else None
        meas = _find_measure(
            systems,
            global_m=global_m,
            rect=_norm_rect(_box_to_rect(it.box), w=width, h=height),
        )
        if meas is None or not meas.notes:
            continue
        target = None
        if n_idx is not None:
            for n in meas.notes:
                if n.index == n_idx and (n.extra or {}).get("kind", "pitch") == "pitch":
                    target = n
                    break
        if target is None:
            # nearest pitch candidate
            pitch_notes = [
                n for n in meas.notes if (n.extra or {}).get("kind", "pitch") == "pitch"
            ]
            if not pitch_notes:
                continue
            cy = (it.box.y1 + it.box.y2) / 2.0
            cx = (it.box.x1 + it.box.x2) / 2.0
            target = min(
                pitch_notes,
                key=lambda n: abs(n.rect.cx - cx) + abs(n.rect.cy - cy),
            )
        dur_name = DurationName.quarter
        if it.duration:
            try:
                dur_name = DurationName(it.duration)
            except ValueError:
                pass
        target.glyph = NoteGlyph(
            pitch=it.pitch,
            is_rest=(it.pitch is None or it.pitch in {"0", "rest"}),
            duration=dur_name,
            underlines=int(it.underlines or 0),
            octave=int(it.octave or 0),
            confidence=float(it.confidence or 0.6),
            extra={"source": "user_structure", "id": it.id},
        )
        # Keep L5 box if user edited it
        target.rect = _norm_rect(_box_to_rect(it.box), w=width, h=height)

    summary = structure.summary or {}
    return PageLayout(
        width=width,
        height=height,
        regions=regions,
        systems=systems,
        key=key or (str(summary["key"]) if summary.get("key") else None),
        time_signature=time_signature
        or (str(summary["time_signature"]) if summary.get("time_signature") else "4/4"),
        title=title or (str(summary["title"]) if summary.get("title") else None),
        warnings=list(warnings or []) + ["layout rebuilt from structure (#78)"],
        debug={"source": "structure_rebuild"},
    )


def _l4_kind(it: StructureBox) -> str:
    k = (it.kind or "").lower()
    if k in {"chord"}:
        return "chord"
    if k in {"lyric", "lyrics"}:
        return "lyric"
    if k in {"note_roi", "pitch", "note"}:
        return "pitch"
    # id fallback
    m = _L4_RE.match(it.id or "")
    if m and m.group(2):
        g = m.group(2).lower()
        if g in {"chord", "lyric", "pitch"}:
            return g
    return "pitch"


def _parse_l4_ids(it: StructureBox) -> tuple[int | None, int | None]:
    m = _L4_RE.match(it.id or "")
    if not m:
        # try looser: l4-m12-pitch3
        m2 = re.match(r"^l4-m(\d+)-[a-zA-Z]*(\d+)$", it.id or "")
        if m2:
            return int(m2.group(1)), int(m2.group(2))
        return None, None
    return int(m.group(1)), int(m.group(3)) if m.group(3) else None


def _nearest_system(systems: list[StaffSystem], rect: Rect) -> StaffSystem | None:
    if not systems:
        return None
    cy = rect.cy
    for s in systems:
        if s.rect.y1 - 4 <= cy <= s.rect.y2 + 4:
            return s
    return min(systems, key=lambda s: abs(s.rect.cy - cy))


def _find_measure(
    systems: list[StaffSystem],
    *,
    global_m: int | None,
    rect: Rect,
) -> MeasureLayout | None:
    if global_m is not None:
        g = 0
        for s in systems:
            for m in s.measures:
                g += 1
                if g == global_m:
                    return m
                if (m.extra or {}).get("global_m") == global_m:
                    return m
    # containment / nearest by center
    cx, cy = rect.cx, rect.cy
    best: MeasureLayout | None = None
    best_d = 1e18
    for s in systems:
        for m in s.measures:
            if m.rect.x1 - 2 <= cx <= m.rect.x2 + 2 and m.rect.y1 - 2 <= cy <= m.rect.y2 + 2:
                return m
            d = abs(m.rect.cx - cx) + abs(m.rect.cy - cy)
            if d < best_d:
                best_d = d
                best = m
    return best


def clear_below_layer(layout: PageLayout, from_layer: StructureLayer) -> PageLayout:
    """Clear IR content that will be recomputed from ``from_layer`` downward."""
    if from_layer == "L1":
        # Keep nothing structural except optional meta; caller redetects all
        layout.systems = []
        return layout
    if from_layer == "L2":
        # Keep L1 regions; systems will be replaced by caller or kept as shells
        for s in layout.systems:
            s.measures = []
            s.barline_xs = []
        return layout
    if from_layer == "L3":
        for s in layout.systems:
            for m in s.measures:
                m.notes = []
            # measures kept (user/system rects)
        return layout
    if from_layer == "L4":
        for s in layout.systems:
            for m in s.measures:
                for n in m.notes:
                    n.glyph = None
        return layout
    # L5: keep candidates, glyphs will be refilled
    for s in layout.systems:
        for m in s.measures:
            for n in m.notes:
                n.glyph = None
    return layout
