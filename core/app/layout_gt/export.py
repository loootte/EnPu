"""Export EnPu project / structure → L1–L3 layout training sample (#93).

Primary input is a desktop ``.enpu.json`` project (``project_version`` 0.2)::

    {
      "kind": "enpu-project",
      "project_version": "0.2",
      "title": "...",
      "score": { ... Score v0.1 ... },
      "source_image": "M04_manual.png",
      "source_image_data_url": "data:image/png;base64,...",  # optional
      "structure": {
        "pipeline": "structure",
        "summary": { "width", "height", "n_systems", ... },
        "items": [ { "layer": "L1"|"L2"|..., "box", "kind", "id", ... } ],
        "barlines": [ { "system", "x", "y1", "y2", "id"?, "source"? } ]
      },
      ...
    }

Layout GT **does not** embed Score note sequences; only optional page meta
(title/key/time) and L1–L3 geometry.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from app.layout_gt.validate import validate_layout_sample

LAYOUT_SCHEMA_VERSION = "0.1"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _as_dict(obj: Any) -> dict[str, Any]:
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    if hasattr(obj, "dict"):
        return obj.dict()
    raise TypeError(f"expected mapping, got {type(obj)!r}")


def _box(raw: Any) -> dict[str, float] | None:
    if raw is None:
        return None
    if isinstance(raw, dict):
        try:
            x1, y1 = float(raw["x1"]), float(raw["y1"])
            x2, y2 = float(raw["x2"]), float(raw["y2"])
        except (KeyError, TypeError, ValueError):
            return None
    else:
        try:
            x1, y1, x2, y2 = (
                float(raw.x1),
                float(raw.y1),
                float(raw.x2),
                float(raw.y2),
            )
        except (AttributeError, TypeError, ValueError):
            return None
    if x2 < x1:
        x1, x2 = x2, x1
    if y2 < y1:
        y1, y2 = y2, y1
    return {"x1": x1, "y1": y1, "x2": x2, "y2": y2}


def _item_layer(it: dict[str, Any]) -> str:
    return str(it.get("layer") or "").upper()


def _l1_role(it: dict[str, Any]) -> str:
    kind = str(it.get("kind") or "").lower()
    label = str(it.get("label") or "").lower()
    for role in ("title", "key_time", "score", "other"):
        if kind == role or role in label:
            return role
    if "key" in kind or "time" in kind or "meta" in kind:
        return "key_time"
    return kind or "other"


def _decode_data_url(data_url: str) -> tuple[bytes, str]:
    """Return (bytes, ext) from a data:image/...;base64,... URL."""
    m = re.match(
        r"^data:image/(png|jpeg|jpg|webp|gif);base64,(.+)$",
        data_url.strip(),
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not m:
        raise ValueError("unsupported or invalid source_image_data_url")
    fmt = m.group(1).lower()
    ext = "jpg" if fmt in ("jpeg", "jpg") else fmt
    raw = base64.b64decode(m.group(2))
    return raw, ext


def _image_size_from_png(data: bytes) -> tuple[int, int] | None:
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    # IHDR: width/height big-endian at bytes 16..24
    w = int.from_bytes(data[16:20], "big")
    h = int.from_bytes(data[20:24], "big")
    return w, h


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _interior_splits_from_edges(
    xs: list[float],
    *,
    x_left: float | None = None,
    x_right: float | None = None,
    n_measures: int | None = None,
    edge_eps: float = 2.0,
) -> list[float]:
    """Convert barline x list to #85 **interior** splits.

    Real ``.enpu.json`` files may store either:

    - **#85 interiors**: ``n_splits = n_measures - 1``
    - **#66 edges**: ``n_barlines = n_measures + 1`` (includes outer measure bounds)
    - raw detector xs that may hug L2 left/right

    We drop endpoints near L2 bounds and, when ``n_measures`` is known and
    ``len(xs) == n_measures + 1``, drop the first/last edge.
    """
    xs = sorted(float(x) for x in xs)
    if not xs:
        return []

    if (
        n_measures is not None
        and n_measures >= 1
        and len(xs) == n_measures + 1
    ):
        # Full edge chain → interiors
        return xs[1:-1] if len(xs) >= 2 else []

    out = list(xs)
    if x_left is not None:
        out = [x for x in out if x > x_left + edge_eps]
    if x_right is not None:
        out = [x for x in out if x < x_right - edge_eps]
    return out


def _measures_to_interior_xs(
    measures: list[dict[str, float]],
    *,
    min_gap: float = 4.0,
) -> list[float]:
    """Shared vertical boundaries between left-sorted measure boxes."""
    if len(measures) < 2:
        return []
    ms = sorted(measures, key=lambda b: (b["x1"] + b["x2"]) / 2.0)
    xs: list[float] = []
    for i in range(len(ms) - 1):
        # Shared boundary ≈ mid of right edge of i and left edge of i+1
        x = 0.5 * (ms[i]["x2"] + ms[i + 1]["x1"])
        if not xs or x - xs[-1] >= min_gap:
            xs.append(x)
    return xs


# ---------------------------------------------------------------------------
# Core conversion
# ---------------------------------------------------------------------------


def layout_sample_from_structure(
    structure: dict[str, Any] | Any,
    *,
    image: dict[str, Any] | None = None,
    meta: dict[str, Any] | None = None,
    sample_id: str | None = None,
    include_derived_measures: bool = True,
    source: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a layout sample dict from RecognizeResponse.structure / project.structure."""
    st = _as_dict(structure)
    items = list(st.get("items") or [])
    barlines = list(st.get("barlines") or [])
    summary = st.get("summary") or {}

    # --- image ---
    img = dict(image or {})
    if "width" not in img and summary.get("width") is not None:
        img["width"] = int(summary["width"])
    if "height" not in img and summary.get("height") is not None:
        img["height"] = int(summary["height"])

    # --- L1 ---
    l1_regions: list[dict[str, Any]] = []
    l1_map: dict[str, dict[str, float]] = {}
    for it in items:
        if _item_layer(it) != "L1":
            continue
        box = _box(it.get("box"))
        if not box:
            continue
        role = _l1_role(it)
        entry = {
            "role": role,
            "box": box,
            "id": it.get("id") or f"l1-{role}",
            "confidence": it.get("confidence"),
        }
        l1_regions.append(entry)
        # first wins for known roles
        if role in ("title", "key_time", "score") and role not in l1_map:
            l1_map[role] = box

    l1: dict[str, Any] = {"regions": l1_regions}
    if "score" in l1_map:
        l1["score_region"] = l1_map["score"]
    if "title" in l1_map:
        l1["title"] = l1_map["title"]
    if "key_time" in l1_map:
        l1["key_time"] = l1_map["key_time"]

    # --- L2 ---
    l2_items = [it for it in items if _item_layer(it) == "L2"]
    l2_items = sorted(
        l2_items,
        key=lambda it: (
            float((_box(it.get("box")) or {}).get("y1", 0)),
            float((_box(it.get("box")) or {}).get("x1", 0)),
        ),
    )
    systems: list[dict[str, Any]] = []
    for order, it in enumerate(l2_items):
        box = _box(it.get("box"))
        if not box:
            continue
        # Prefer id index when present (l2-sys0)
        sid = str(it.get("id") or f"l2-sys{order}")
        m = re.search(r"(\d+)$", sid)
        sys_index = int(m.group(1)) if m else order
        systems.append(
            {
                "id": sid,
                "index": sys_index,
                "bbox": box,
                "kind": str(it.get("kind") or "system"),
                "label": it.get("label"),
                "confidence": it.get("confidence"),
            }
        )
    # Re-index 0..n-1 in reading order for stable export
    systems.sort(key=lambda s: (s["bbox"]["y1"], s["bbox"]["x1"]))
    for i, s in enumerate(systems):
        s["index"] = i

    # --- L3 measures per system (optional derived) ---
    l3_items = [it for it in items if _item_layer(it) == "L3"]
    measures_by_sys: dict[int, list[dict[str, Any]]] = {s["index"]: [] for s in systems}

    def _assign_system(box: dict[str, float]) -> int | None:
        if not systems:
            return None
        cy = 0.5 * (box["y1"] + box["y2"])
        cx = 0.5 * (box["x1"] + box["x2"])
        best_i = None
        best_pen = 1e18
        for s in systems:
            b = s["bbox"]
            # vertical containment preferred
            if b["y1"] - 2 <= cy <= b["y2"] + 2:
                pen = 0.0
            else:
                pen = min(abs(cy - b["y1"]), abs(cy - b["y2"])) + 1000.0
            # horizontal soft
            if cx < b["x1"] or cx > b["x2"]:
                pen += min(abs(cx - b["x1"]), abs(cx - b["x2"]))
            if pen < best_pen:
                best_pen = pen
                best_i = s["index"]
        return best_i

    for it in l3_items:
        box = _box(it.get("box"))
        if not box:
            continue
        si = _assign_system(box)
        if si is None:
            continue
        measures_by_sys.setdefault(si, []).append(
            {
                "id": it.get("id"),
                "label": it.get("label"),
                "kind": it.get("kind") or "measure_derived",
                "box": box,
                "confidence": it.get("confidence"),
            }
        )
    for si in measures_by_sys:
        measures_by_sys[si].sort(
            key=lambda m: (m["box"]["x1"] + m["box"]["x2"]) / 2.0
        )

    # --- L3 splits from barlines (primary) ---
    # Map original structure system index → export index
    # Barlines use structure system index; L2 may have been re-sorted.
    # Prefer matching by order: if structure L2 ids are l2-sys{k}, barline.system == k.
    raw_by_sys: dict[int, list[dict[str, Any]]] = {}
    for b in barlines:
        if not isinstance(b, dict) or b.get("x") is None:
            continue
        try:
            si = int(b.get("system", -1))
        except (TypeError, ValueError):
            continue
        raw_by_sys.setdefault(si, []).append(b)

    # If barline system ids don't match re-indexed systems, try identity
    rows: list[dict[str, Any]] = []
    for s in systems:
        si = s["index"]
        # barlines may still use original system numbers matching l2-sys{n}
        # Use original id number if present
        orig_m = re.search(r"sys(\d+)", str(s.get("id") or ""))
        candidates: list[dict[str, Any]] = []
        if orig_m:
            candidates = list(raw_by_sys.get(int(orig_m.group(1)), []))
        if not candidates:
            candidates = list(raw_by_sys.get(si, []))

        raw_xs = [float(b["x"]) for b in candidates]
        n_meas = len(measures_by_sys.get(si) or [])
        interiors = _interior_splits_from_edges(
            raw_xs,
            x_left=s["bbox"]["x1"],
            x_right=s["bbox"]["x2"],
            n_measures=n_meas if n_meas > 0 else None,
        )
        # Fallback: derive from measure boxes
        if not interiors and n_meas >= 2:
            interiors = _measures_to_interior_xs(
                [m["box"] for m in measures_by_sys[si]]
            )

        # Attach metadata from nearest raw barline when possible
        splits: list[dict[str, Any]] = []
        for i, x in enumerate(interiors):
            src = "migrate"
            sid = f"s{si}-{i}"
            conf = None
            y1 = s["bbox"]["y1"]
            y2 = s["bbox"]["y2"]
            best = None
            best_d = 1e18
            for b in candidates:
                d = abs(float(b["x"]) - x)
                if d < best_d:
                    best_d = d
                    best = b
            if best is not None and best_d <= 4.0:
                src = str(best.get("source") or "detect")
                if best.get("id"):
                    sid = str(best["id"])
                if best.get("confidence") is not None:
                    conf = best.get("confidence")
                if best.get("y1") is not None:
                    y1 = float(best["y1"])
                if best.get("y2") is not None:
                    y2 = float(best["y2"])
            sp: dict[str, Any] = {
                "id": sid,
                "x": float(x),
                "y1": y1,
                "y2": y2,
                "source": src,
            }
            if conf is not None:
                sp["confidence"] = conf
            splits.append(sp)

        row: dict[str, Any] = {
            "system_id": s["id"],
            "system_index": si,
            "splits": splits,
        }
        if include_derived_measures and measures_by_sys.get(si):
            row["measures"] = [
                {
                    "id": m.get("id"),
                    "label": m.get("label"),
                    "box": m["box"],
                }
                for m in measures_by_sys[si]
            ]
        rows.append(row)

    sample: dict[str, Any] = {
        "layout_schema_version": LAYOUT_SCHEMA_VERSION,
        "kind": "enpu-layout-gt",
        "image": img,
        "l1": l1,
        "l2": {"systems": systems},
        "l3": {"rows": rows},
    }
    if sample_id:
        sample["id"] = sample_id
    if meta:
        sample["meta"] = meta
    if source:
        sample["source"] = source
    return sample


def layout_sample_from_project(
    project: dict[str, Any] | str | Path,
    *,
    sample_id: str | None = None,
    image_relpath: str = "image.png",
    include_derived_measures: bool = True,
) -> dict[str, Any]:
    """Load ``.enpu.json`` (path or dict) → layout sample (without writing files)."""
    if isinstance(project, (str, Path)):
        path = Path(project)
        project = json.loads(path.read_text(encoding="utf-8"))
        default_id = path.stem.replace(".enpu", "")
        source_path = str(path)
    else:
        default_id = str(project.get("title") or "sample")
        source_path = None

    if not isinstance(project, dict):
        raise TypeError("project must be a dict or path")

    structure = project.get("structure")
    if not structure:
        raise ValueError(
            "project has no structure field; re-open in desktop structure mode "
            "and save after recognition"
        )

    score = project.get("score") or {}
    meta = {
        "title": project.get("title") or score.get("title"),
        "key": score.get("key"),
        "time_signature": score.get("time_signature"),
        "source_image_name": project.get("source_image"),
        "project_version": project.get("project_version"),
        "engine": (project.get("meta") or {}).get("engine")
        or (score.get("meta") or {}).get("engine"),
    }
    # drop empty meta keys
    meta = {k: v for k, v in meta.items() if v is not None and v != ""}

    img: dict[str, Any] = {"path": image_relpath}
    # size from structure summary preferred
    summary = (structure or {}).get("summary") or {}
    if summary.get("width") is not None:
        img["width"] = int(summary["width"])
    if summary.get("height") is not None:
        img["height"] = int(summary["height"])

    source = {
        "type": "enpu_project",
        "kind": project.get("kind"),
        "project_version": project.get("project_version"),
        "path": source_path,
    }

    return layout_sample_from_structure(
        structure,
        image=img,
        meta=meta,
        sample_id=sample_id or default_id,
        include_derived_measures=include_derived_measures,
        source=source,
    )


def export_project_to_sample_dir(
    project: dict[str, Any] | str | Path,
    out_dir: str | Path,
    *,
    sample_id: str | None = None,
    copy_image: bool = True,
    validate: bool = True,
    include_derived_measures: bool = True,
) -> dict[str, Any]:
    """Write ``layout.json`` (+ ``image.*``) under ``out_dir``.

    Returns the layout sample dict. Raises ``ValueError`` if validation fails
    when ``validate=True``.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    project_path: Path | None = None
    if isinstance(project, (str, Path)):
        project_path = Path(project)
        project_data = json.loads(project_path.read_text(encoding="utf-8"))
    else:
        project_data = project

    # Determine image bytes
    image_bytes: bytes | None = None
    image_ext = "png"
    data_url = project_data.get("source_image_data_url")
    if copy_image and isinstance(data_url, str) and data_url.startswith("data:image"):
        image_bytes, image_ext = _decode_data_url(data_url)
    elif copy_image and project_path is not None:
        # sibling image next to project
        name = project_data.get("source_image")
        if name:
            cand = project_path.parent / name
            if cand.is_file():
                image_bytes = cand.read_bytes()
                image_ext = cand.suffix.lstrip(".") or "png"

    image_name = f"image.{image_ext}"
    if image_bytes is not None:
        (out_dir / image_name).write_bytes(image_bytes)

    sample = layout_sample_from_project(
        project_data,
        sample_id=sample_id,
        image_relpath=image_name if image_bytes is not None else (
            str(project_data.get("source_image") or "image.png")
        ),
        include_derived_measures=include_derived_measures,
    )
    if project_path is not None:
        sample.setdefault("source", {})["path"] = str(project_path)

    if image_bytes is not None:
        sample.setdefault("image", {})["sha256"] = _sha256_hex(image_bytes)
        size = _image_size_from_png(image_bytes)
        if size:
            sample["image"]["width"], sample["image"]["height"] = size

    if validate:
        result = validate_layout_sample(sample)
        if not result.ok:
            raise ValueError(
                "layout sample validation failed:\n"
                + "\n".join(f"  - {e}" for e in result.errors)
            )
        sample.setdefault("export", {})["validation_warnings"] = list(result.warnings)

    layout_path = out_dir / "layout.json"
    layout_path.write_text(
        json.dumps(sample, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return sample
