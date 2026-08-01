"""Validate L1–L3 layout training samples (#93)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ValidationResult:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def raise_if_error(self) -> None:
        if not self.ok:
            raise ValueError(
                "layout validation failed:\n"
                + "\n".join(f"  - {e}" for e in self.errors)
            )


def _box_ok(box: Any, *, name: str, errors: list[str]) -> bool:
    if not isinstance(box, dict):
        errors.append(f"{name}: box must be object")
        return False
    for k in ("x1", "y1", "x2", "y2"):
        if k not in box:
            errors.append(f"{name}: missing box.{k}")
            return False
        try:
            float(box[k])
        except (TypeError, ValueError):
            errors.append(f"{name}: box.{k} not numeric")
            return False
    if float(box["x2"]) < float(box["x1"]):
        errors.append(f"{name}: x2 < x1")
        return False
    if float(box["y2"]) < float(box["y1"]):
        errors.append(f"{name}: y2 < y1")
        return False
    return True


def validate_layout_sample(
    sample: dict[str, Any],
    *,
    min_split_gap: float = 1.0,
    require_score_region: bool = True,
    require_systems: bool = True,
) -> ValidationResult:
    """Check schema + geometric consistency of a layout GT sample.

    Rules (hard errors unless noted):

    - ``layout_schema_version`` present
    - image width/height > 0 when present
    - L1 score_region recommended (error if ``require_score_region``)
    - L2 systems with valid bboxes
    - L3 rows: splits strictly increasing, strictly interior to L2 x-range
    - if measures present: ``n_measures == n_splits + 1`` (warn if only measures)
    """
    errors: list[str] = []
    warnings: list[str] = []

    if not isinstance(sample, dict):
        return ValidationResult(ok=False, errors=["sample must be a JSON object"])

    ver = sample.get("layout_schema_version")
    if not ver:
        errors.append("missing layout_schema_version")

    image = sample.get("image") or {}
    w = image.get("width")
    h = image.get("height")
    if w is not None:
        try:
            if int(w) <= 0:
                errors.append("image.width must be > 0")
        except (TypeError, ValueError):
            errors.append("image.width not int")
    else:
        warnings.append("image.width missing")
    if h is not None:
        try:
            if int(h) <= 0:
                errors.append("image.height must be > 0")
        except (TypeError, ValueError):
            errors.append("image.height not int")
    else:
        warnings.append("image.height missing")

    # ----- L1 -----
    l1 = sample.get("l1") or {}
    score = l1.get("score_region")
    if score is None:
        # try regions
        for r in l1.get("regions") or []:
            if str(r.get("role") or "").lower() == "score" and r.get("box"):
                score = r["box"]
                break
    if score is None:
        msg = "L1 score_region missing"
        if require_score_region:
            errors.append(msg)
        else:
            warnings.append(msg)
    else:
        _box_ok(score, name="l1.score_region", errors=errors)

    for key in ("title", "key_time"):
        if key in l1 and l1[key] is not None:
            _box_ok(l1[key], name=f"l1.{key}", errors=errors)

    # ----- L2 -----
    l2 = sample.get("l2") or {}
    systems = list(l2.get("systems") or [])
    if not systems:
        msg = "L2 systems empty"
        if require_systems:
            errors.append(msg)
        else:
            warnings.append(msg)

    sys_by_id: dict[str, dict[str, Any]] = {}
    sys_by_index: dict[int, dict[str, Any]] = {}
    prev_y = -1e18
    for i, s in enumerate(systems):
        name = f"l2.systems[{i}]"
        if not isinstance(s, dict):
            errors.append(f"{name}: not object")
            continue
        bbox = s.get("bbox") or s.get("box")
        if not _box_ok(bbox, name=f"{name}.bbox", errors=errors):
            continue
        sid = str(s.get("id") or f"sys{i}")
        sys_by_id[sid] = s
        try:
            idx = int(s.get("index", i))
        except (TypeError, ValueError):
            idx = i
        sys_by_index[idx] = s
        y1 = float(bbox["y1"])
        if y1 + 1e-3 < prev_y:
            warnings.append(f"{name}: systems not sorted by y (ok if multi-column)")
        prev_y = y1

    # ----- L3 -----
    l3 = sample.get("l3") or {}
    rows = list(l3.get("rows") or [])
    if systems and not rows:
        warnings.append("L3 rows empty (no splits annotated)")

    for i, row in enumerate(rows):
        name = f"l3.rows[{i}]"
        if not isinstance(row, dict):
            errors.append(f"{name}: not object")
            continue
        sid = row.get("system_id")
        sidx = row.get("system_index")
        sys = None
        if sid is not None and str(sid) in sys_by_id:
            sys = sys_by_id[str(sid)]
        elif sidx is not None:
            try:
                sys = sys_by_index.get(int(sidx))
            except (TypeError, ValueError):
                sys = None
        if sys is None and systems:
            # fallback by row order
            if i < len(systems):
                sys = systems[i]
                warnings.append(f"{name}: system_id/index not matched; used systems[{i}]")
            else:
                errors.append(f"{name}: cannot resolve parent L2 system")
                continue
        bbox = (sys or {}).get("bbox") or (sys or {}).get("box") or {}
        x_left = float(bbox.get("x1", 0)) if bbox else None
        x_right = float(bbox.get("x2", 0)) if bbox else None

        splits = list(row.get("splits") or [])
        xs: list[float] = []
        for j, sp in enumerate(splits):
            sn = f"{name}.splits[{j}]"
            if isinstance(sp, (int, float)):
                x = float(sp)
            elif isinstance(sp, dict) and sp.get("x") is not None:
                try:
                    x = float(sp["x"])
                except (TypeError, ValueError):
                    errors.append(f"{sn}: x not numeric")
                    continue
            else:
                errors.append(f"{sn}: need x")
                continue
            xs.append(x)
            if x_left is not None and x_right is not None:
                if x <= x_left + 1e-6 or x >= x_right - 1e-6:
                    errors.append(
                        f"{sn}: x={x} not strictly interior to L2 "
                        f"({x_left}, {x_right})"
                    )

        for a, b in zip(xs, xs[1:]):
            if b - a < min_split_gap:
                errors.append(
                    f"{name}: splits not strictly increasing with gap>={min_split_gap} "
                    f"({a} → {b})"
                )
            if b < a - 1e-9:
                errors.append(f"{name}: splits not sorted ({a} > {b})")

        measures = list(row.get("measures") or [])
        if measures:
            n_m = len(measures)
            n_s = len(xs)
            if n_m != n_s + 1:
                errors.append(
                    f"{name}: n_measures ({n_m}) must equal n_splits+1 ({n_s + 1}) "
                    f"when measures are stored"
                )
            # soft: measures left→right
            mids = []
            for j, m in enumerate(measures):
                box = m.get("box") if isinstance(m, dict) else None
                if box and _box_ok(box, name=f"{name}.measures[{j}]", errors=errors):
                    mids.append(0.5 * (float(box["x1"]) + float(box["x2"])))
            for a, b in zip(mids, mids[1:]):
                if b < a - 1e-3:
                    warnings.append(f"{name}: measures not left-to-right ordered")

    ok = len(errors) == 0
    return ValidationResult(ok=ok, errors=errors, warnings=warnings)
