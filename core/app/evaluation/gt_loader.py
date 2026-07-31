"""Load ground-truth annotations for layered eval (#86)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.evaluation.types import Box


def load_json(path: Path | str) -> dict[str, Any]:
    p = Path(path)
    return json.loads(p.read_text(encoding="utf-8"))


def pitch_sequence_from_score(data: dict[str, Any]) -> list[str]:
    """Pitch token list from Score v0.1 GT (or ``extra.eval.pitch_sequence``)."""
    extra = (data.get("extra") or {}).get("eval") or {}
    if extra.get("pitch_sequence"):
        return [str(p) for p in extra["pitch_sequence"]]
    out: list[str] = []
    parts = data.get("parts") or []
    if not parts:
        return out
    for meas in parts[0].get("measures") or []:
        for n in meas.get("notes") or []:
            if n.get("is_rest"):
                continue
            p = n.get("pitch")
            if not p:
                continue
            tag = str(p)
            acc = n.get("accidental")
            if acc == "sharp":
                tag += "#"
            elif acc == "flat":
                tag += "b"
            out.append(tag)
    return out


def measure_count_from_score(data: dict[str, Any]) -> int:
    extra = (data.get("extra") or {}).get("eval") or {}
    if extra.get("measure_count") is not None:
        return int(extra["measure_count"])
    parts = data.get("parts") or []
    if not parts:
        return 0
    return len(parts[0].get("measures") or [])


def system_count_from_score(data: dict[str, Any]) -> int | None:
    """Optional system/line count if provided in eval extra."""
    extra = (data.get("extra") or {}).get("eval") or {}
    if extra.get("system_count") is not None:
        return int(extra["system_count"])
    if extra.get("n_systems") is not None:
        return int(extra["n_systems"])
    return None


def _box_from_dict(d: dict[str, Any], *, label: str = "", kind: str = "") -> Box | None:
    if not d:
        return None
    # Support {x1,y1,x2,y2} or nested rect
    if "rect" in d and isinstance(d["rect"], dict):
        d = {**d["rect"], "label": d.get("label", label), "kind": d.get("kind", kind)}
    try:
        return Box(
            x1=float(d["x1"]),
            y1=float(d["y1"]),
            x2=float(d["x2"]),
            y2=float(d["y2"]),
            label=str(d.get("label") or label),
            kind=str(d.get("kind") or kind),
        )
    except (KeyError, TypeError, ValueError):
        return None


def load_layer_geometry(gt: dict[str, Any]) -> dict[str, list[Box]]:
    """Extract optional geometry layers from GT JSON.

    Accepted shapes (any subset)::

        {
          "layers": {
            "L1": { "regions": [ {"role":"score","box":{...}} ] },
            "L2": { "systems": [ {"box":{...}} ] },
            "L3": { "measures": [ {"box":{...}} ], "barlines": [x, ...] },
            "L4": { "notes": [ {"box":{...},"kind":"pitch"} ] }
          }
        }

    Or flat keys ``l1_regions`` / ``l2_systems`` / ``l3_measures`` / ``l4_notes``.
    """
    out: dict[str, list[Box]] = {}
    layers = gt.get("layers") or {}

    # --- L1 ---
    l1_src = layers.get("L1") or layers.get("l1") or {}
    regions = l1_src.get("regions") or gt.get("l1_regions") or []
    boxes: list[Box] = []
    for r in regions:
        role = str(r.get("role") or r.get("kind") or "region")
        b = _box_from_dict(r.get("box") or r, label=role, kind=role)
        if b:
            boxes.append(b)
    if boxes:
        out["L1"] = boxes

    # --- L2 ---
    l2_src = layers.get("L2") or layers.get("l2") or {}
    systems = l2_src.get("systems") or gt.get("l2_systems") or []
    boxes = []
    for i, s in enumerate(systems):
        b = _box_from_dict(
            s.get("box") or s,
            label=str(s.get("label") or f"sys{i}"),
            kind="system",
        )
        if b:
            boxes.append(b)
    if boxes:
        out["L2"] = boxes

    # --- L3 measures ---
    l3_src = layers.get("L3") or layers.get("l3") or {}
    measures = l3_src.get("measures") or gt.get("l3_measures") or []
    boxes = []
    for i, m in enumerate(measures):
        b = _box_from_dict(
            m.get("box") or m,
            label=str(m.get("label") or f"m{i + 1}"),
            kind="measure",
        )
        if b:
            boxes.append(b)
    if boxes:
        out["L3"] = boxes

    # --- L4 notes ---
    l4_src = layers.get("L4") or layers.get("l4") or {}
    notes = l4_src.get("notes") or gt.get("l4_notes") or []
    boxes = []
    for i, n in enumerate(notes):
        kind = str(n.get("kind") or "pitch")
        b = _box_from_dict(
            n.get("box") or n,
            label=str(n.get("label") or f"n{i}"),
            kind=kind,
        )
        if b:
            boxes.append(b)
    if boxes:
        out["L4"] = boxes

    return out


def load_barline_xs(gt: dict[str, Any]) -> list[float]:
    layers = gt.get("layers") or {}
    l3 = layers.get("L3") or layers.get("l3") or {}
    xs = l3.get("barlines") or gt.get("l3_barlines") or []
    out: list[float] = []
    for x in xs:
        try:
            out.append(float(x))
        except (TypeError, ValueError):
            continue
    return out


def load_ground_truth(path: Path | str) -> dict[str, Any]:
    """Load GT file and normalize common fields."""
    data = load_json(path)
    return {
        "raw": data,
        "pitch_sequence": pitch_sequence_from_score(data),
        "measure_count": measure_count_from_score(data),
        "system_count": system_count_from_score(data),
        "geometry": load_layer_geometry(data),
        "barline_xs": load_barline_xs(data),
        "key": data.get("key"),
        "time_signature": data.get("time_signature"),
        "title": data.get("title"),
    }
