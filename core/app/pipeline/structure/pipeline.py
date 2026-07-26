"""Structure-first end-to-end pipeline (#58).

Order: preprocess → L1 → L2 → L3/L4 → L5 (OCR pitch) → assemble Score.
"""

from __future__ import annotations

import logging
import re
import time

import cv2
import numpy as np

from app.config import Settings
from app.pipeline.ocr import OcrEngineError, get_ocr_engine
from app.pipeline.preprocess import (
    ImageDecodeError,
    PreprocessOptions,
    decode_image_bytes,
    preprocess_for_ocr,
)
from app.pipeline.structure.assemble import (
    layout_debug_summary,
    page_layout_to_score,
    page_layout_to_structure_debug,
)
from app.pipeline.structure.ir import PageLayout, Rect, RegionRole, StaffSystem
from app.pipeline.structure.l1_page import detect_page_regions
from app.pipeline.structure.l2_systems import detect_staff_systems
from app.pipeline.structure.l3_measures import segment_measures_on_systems
from app.pipeline.structure.l4_notes import detect_note_candidates
from app.pipeline.structure.l5_glyph import fill_note_glyphs
from app.pipeline.structure.rebuild import (
    StructureLayer,
    apply_structure_edits,
    clear_below_layer,
    page_layout_from_structure,
    reindex_global_measure_numbers,
    sort_systems_and_measures_by_center,
)
from app.schemas.recognize import (
    BoundingBox,
    LayoutRegion,
    NoteHint,
    RecognizeMeta,
    RecognizeResponse,
    StructureDebug,
)

logger = logging.getLogger(__name__)

_KEY_RE = re.compile(
    r"(?:key|调)\s*[:：]?\s*([A-Ga-g][b#]?)|1\s*=\s*([A-Ga-g][b#]?)",
    re.I,
)
_TIME_RE = re.compile(r"([1-9][0-9]*)\s*/\s*([1-9][0-9]*)")


class StructurePipelineError(Exception):
    def __init__(self, message: str, *, status_code: int = 500) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def run_structure_recognize(
    data: bytes,
    *,
    settings: Settings,
    filename: str | None = None,
    content_type: str | None = None,
    preprocess_options: PreprocessOptions | None = None,
) -> RecognizeResponse:
    """Structure-first recognition (ENPU_PIPELINE_MODE=structure)."""
    started = time.perf_counter()
    try:
        image_bgr = decode_image_bytes(data)
    except ImageDecodeError as exc:
        raise StructurePipelineError(str(exc), status_code=400) from exc

    opts = preprocess_options or PreprocessOptions(
        max_side=settings.ocr_max_side,
        denoise=settings.ocr_denoise,
    )
    try:
        pre = preprocess_for_ocr(
            image_bgr,
            max_side=opts.max_side,
            denoise=opts.denoise,
            options=opts,
        )
    except ImageDecodeError as exc:
        raise StructurePipelineError(str(exc), status_code=400) from exc

    # #47: when deskew/crop/enhance applied, run L1–L5 in processed space
    # (UI should display the same preprocessed preview for dual-view alignment).
    geometric = (
        opts.deskew
        or opts.has_crop()
        or opts.clahe
        or opts.shadow_remove
        or opts.adaptive_binary
        or abs(opts.brightness) > 0.5
        or abs(opts.contrast - 1.0) > 0.02
    )
    work = pre.ocr_bgr if geometric else image_bgr
    h, w = work.shape[:2]
    warnings: list[str] = ["pipeline=structure (#58)"]
    if geometric:
        warnings.append(f"preprocess_toolbox: {' → '.join(pre.steps)}")

    # --- L1
    regions, w1 = detect_page_regions(work)
    warnings.extend(w1)
    score_rect = next((r.rect for r in regions if r.role == RegionRole.score), None)
    if score_rect is None:
        score_rect = Rect(0, 0, float(w), float(h))

    # --- L2
    systems, w2 = detect_staff_systems(work, score_rect)
    warnings.extend(w2)

    # --- L3
    systems, w3 = segment_measures_on_systems(work, systems)
    warnings.extend(w3)

    # --- L4
    systems, w4 = detect_note_candidates(work, systems)
    warnings.extend(w4)

    # Meta text (title / key / time) early — needed for L4/L5 meter check
    title, key, time_sig, meta_warnings = _read_page_meta(
        work,
        score_rect.y1,
        settings=settings,
    )
    warnings.extend(meta_warnings)
    time_sig = time_sig or "4/4"

    # --- L5: pitch + ornaments + measure meter check vs time signature (#72)
    systems, w5 = fill_note_glyphs(
        work,
        systems,
        engine_name=settings.recognize_engine,
        lang=settings.ocr_lang,
        use_angle_cls=settings.ocr_use_angle_cls,
        use_gpu=settings.ocr_use_gpu,
        time_signature=time_sig,
        meter_soft_fit=True,
    )
    warnings.extend(w5)

    layout = PageLayout(
        width=w,
        height=h,
        regions=regions,
        systems=systems,
        key=key,
        time_signature=time_sig,
        title=title,
        warnings=warnings,
        debug={"preprocess_steps": list(pre.steps), "scale": pre.scale},
    )

    return _layout_to_response(
        layout,
        settings=settings,
        filename=filename,
        content_type=content_type,
        started=started,
        preprocess_steps=list(pre.steps) + ["structure_l1_l5"],
    )


def run_structure_rerun(
    data: bytes,
    *,
    settings: Settings,
    from_layer: StructureLayer,
    base_structure: StructureDebug,
    edits: list[dict] | None = None,
    filename: str | None = None,
    content_type: str | None = None,
    key: str | None = None,
    time_signature: str | None = None,
    title: str | None = None,
) -> RecognizeResponse:
    """Re-run **layers below** ``from_layer`` using user boxes as fixed geometry (#78).

    **Invariant**: boxes of ``from_layer`` and above are **never re-detected**.
    Only lower layers are recomputed from the image.

    Examples:
      - from_layer=L2: keep L1 + user L2 system rects; re-run L3–L5 only
      - from_layer=L3: keep L1–L2 + user L3 measures; re-run L4–L5 only
      - from_layer=L4: keep L1–L3 + user L4 ROIs; re-run L5 only
      - from_layer=L5: keep L1–L4 candidates; re-fill L5 glyphs only
      - from_layer=L1: keep user L1 regions; re-run L2–L5 only
    """
    started = time.perf_counter()
    layer = from_layer.upper()  # type: ignore[assignment]
    if layer not in {"L1", "L2", "L3", "L4", "L5"}:
        raise StructurePipelineError(
            f"from_layer must be L1–L5 (got {from_layer!r})",
            status_code=400,
        )
    from_layer = layer  # type: ignore[assignment]

    try:
        image_bgr = decode_image_bytes(data)
    except ImageDecodeError as exc:
        raise StructurePipelineError(str(exc), status_code=400) from exc

    h, w = image_bgr.shape[:2]
    warnings: list[str] = [
        "pipeline=structure (#58)",
        f"structure_rerun from={from_layer} (#78)",
        f"structure_rerun pin={from_layer}+above; recompute below only",
    ]

    edited = apply_structure_edits(
        base_structure,
        edits or [],
        width=w,
        height=h,
    )
    layout = page_layout_from_structure(
        edited,
        width=w,
        height=h,
        key=key,
        time_signature=time_signature,
        title=title,
        warnings=warnings,
    )
    # Snapshot user geometry for pin-after (recompute must not move these)
    pinned = _snapshot_pinned_geometry(layout, from_layer)

    # Drop only content *below* from_layer; keep from_layer boxes
    clear_below_layer(layout, from_layer)

    # --- recompute strictly below from_layer ---
    if from_layer == "L1":
        # L1 regions pinned; re-detect systems inside score ROI
        score_rect = layout.score_region or Rect(0, 0, float(w), float(h))
        warnings.append(
            f"L1 pinned ({len(layout.regions)} region(s)); re-run L2–L5"
        )
        systems, w2 = detect_staff_systems(image_bgr, score_rect)
        warnings.extend(w2)
        layout.systems = systems
        systems, w3 = segment_measures_on_systems(image_bgr, layout.systems)
        warnings.extend(w3)
        layout.systems = systems
        systems, w4 = detect_note_candidates(image_bgr, layout.systems)
        warnings.extend(w4)
        layout.systems = systems

    elif from_layer == "L2":
        # User L2 system rects are authoritative — never re-detect systems
        if not layout.systems:
            raise StructurePipelineError(
                "L2 rerun requires at least one L2 system box in base_structure "
                "(edit/add a system region first).",
                status_code=400,
            )
        layout.systems = [
            StaffSystem(
                index=s.index,
                rect=s.rect,
                measures=[],
                barline_xs=[],
                confidence=s.confidence,
                extra={**(s.extra or {}), "user_edited": True, "pinned": True},
            )
            for s in layout.systems
        ]
        warnings.append(
            f"L2 pinned ({len(layout.systems)} system rect(s)); re-run L3–L5"
        )
        systems, w3 = segment_measures_on_systems(image_bgr, layout.systems)
        warnings.extend(w3)
        layout.systems = systems
        systems, w4 = detect_note_candidates(image_bgr, layout.systems)
        warnings.extend(w4)
        layout.systems = systems

    elif from_layer == "L3":
        if not layout.systems:
            raise StructurePipelineError(
                "L3 rerun requires L2 systems in base_structure",
                status_code=400,
            )
        n_meas = sum(len(s.measures) for s in layout.systems)
        if n_meas == 0:
            raise StructurePipelineError(
                "L3 rerun requires at least one L3 measure box in base_structure "
                "(edit/add a measure region first).",
                status_code=400,
            )
        # Reading order by geometric center (never trust previous m1.. ids)
        sort_systems_and_measures_by_center(layout.systems)
        n_global = reindex_global_measure_numbers(layout.systems)
        order_dbg = []
        for s in layout.systems:
            for m in s.measures:
                order_dbg.append(
                    f"m{m.extra.get('global_m')}:cx={m.rect.cx:.0f},cy={m.rect.cy:.0f}"
                )
        warnings.append(
            f"L3 sorted by geometric center → {n_global} measure(s): "
            + "; ".join(order_dbg[:12])
            + ("…" if len(order_dbg) > 12 else "")
        )
        # Keep user measure rects; only re-detect note candidates inside them
        for s in layout.systems:
            for m in s.measures:
                m.notes = []
                m.extra = {**(m.extra or {}), "user_edited": True, "pinned": True}
        warnings.append(f"L3 pinned ({n_meas} measure rect(s)); re-run L4–L5")
        # Snapshot AFTER sort so pin order == reading order (do not use pre-sort pin)
        pinned = _snapshot_pinned_geometry(layout, from_layer)
        systems, w4 = detect_note_candidates(image_bgr, layout.systems)
        warnings.extend(w4)
        layout.systems = systems

    elif from_layer == "L4":
        n_notes = sum(len(m.notes) for s in layout.systems for m in s.measures)
        if n_notes == 0:
            raise StructurePipelineError(
                "L4 rerun requires at least one L4 note ROI in base_structure "
                "(edit/add a note region first).",
                status_code=400,
            )
        for s in layout.systems:
            for m in s.measures:
                for n in m.notes:
                    n.glyph = None
                    n.extra = {**(n.extra or {}), "user_edited": True, "pinned": True}
        warnings.append(f"L4 pinned ({n_notes} note ROI(s)); re-run L5")

    else:  # L5
        n_notes = sum(len(m.notes) for s in layout.systems for m in s.measures)
        if n_notes == 0:
            raise StructurePipelineError(
                "L5 rerun requires L4 note candidates in base_structure.",
                status_code=400,
            )
        for s in layout.systems:
            for m in s.measures:
                for n in m.notes:
                    n.glyph = None
        warnings.append(f"L5: re-fill glyphs on {n_notes} pinned candidate(s)")

    # Meta for meter / title
    if not layout.time_signature or not layout.key or not layout.title:
        score_y0 = layout.score_region.y1 if layout.score_region else h * 0.2
        t, k, ts, meta_w = _read_page_meta(
            image_bgr, score_y0, settings=settings
        )
        warnings.extend(meta_w)
        layout.title = layout.title or title or t
        layout.key = layout.key or key or k
        layout.time_signature = (
            layout.time_signature or time_signature or ts or "4/4"
        )
    time_sig = layout.time_signature or "4/4"

    # L5 only when from_layer <= L5 (always, except we always need glyphs for score)
    systems, w5 = fill_note_glyphs(
        image_bgr,
        layout.systems,
        engine_name=settings.recognize_engine,
        lang=settings.ocr_lang,
        use_angle_cls=settings.ocr_use_angle_cls,
        use_gpu=settings.ocr_use_gpu,
        time_signature=time_sig,
        meter_soft_fit=True,
    )
    warnings.extend(w5)
    layout.systems = systems

    # Re-apply pinned geometry so lower-layer work never moves user boxes
    _restore_pinned_geometry(layout, pinned, from_layer)
    # L5 overlay must use the same ROI as L4 (especially after user L4 edit)
    if from_layer in {"L4", "L5"}:
        _sync_l5_rects_to_l4(layout)
    layout.warnings = warnings

    return _layout_to_response(
        layout,
        settings=settings,
        filename=filename,
        content_type=content_type,
        started=started,
        preprocess_steps=["decode", f"structure_rerun_{from_layer}_below"],
    )


def _sync_l5_rects_to_l4(layout: PageLayout) -> None:
    """L5 shares the note candidate rect with L4; keep them identical."""
    for s in layout.systems:
        for m in s.measures:
            for n in m.notes:
                if (n.extra or {}).get("kind", "pitch") != "pitch":
                    continue
                # rect is already the L4 ROI; ensure extra records it for debug
                n.extra = {
                    **(n.extra or {}),
                    "l5_uses_l4_rect": True,
                }


def _snapshot_pinned_geometry(
    layout: PageLayout,
    from_layer: StructureLayer,
) -> dict:
    """Capture geometry that must stay fixed for from_layer and above."""
    snap: dict = {"regions": [], "systems": []}
    rank = {"L1": 1, "L2": 2, "L3": 3, "L4": 4, "L5": 5}[from_layer]
    if rank >= 1:
        snap["regions"] = [
            {
                "role": r.role.value,
                "rect": (r.rect.x1, r.rect.y1, r.rect.x2, r.rect.y2),
                "id": (r.extra or {}).get("id"),
            }
            for r in layout.regions
        ]
    if rank >= 2:
        for s in layout.systems:
            sys_snap: dict = {
                "index": s.index,
                "rect": (s.rect.x1, s.rect.y1, s.rect.x2, s.rect.y2),
                "id": (s.extra or {}).get("id"),
                "measures": [],
            }
            if rank >= 3:
                for m in s.measures:
                    m_snap: dict = {
                        "index": m.index,
                        "rect": (m.rect.x1, m.rect.y1, m.rect.x2, m.rect.y2),
                        "id": (m.extra or {}).get("id"),
                        "global_m": (m.extra or {}).get("global_m"),
                        "notes": [],
                    }
                    if rank >= 4:
                        for n in m.notes:
                            m_snap["notes"].append(
                                {
                                    "index": n.index,
                                    "rect": (
                                        n.rect.x1,
                                        n.rect.y1,
                                        n.rect.x2,
                                        n.rect.y2,
                                    ),
                                    "kind": (n.extra or {}).get("kind", "pitch"),
                                    "id": (n.extra or {}).get("id"),
                                }
                            )
                    sys_snap["measures"].append(m_snap)
            snap["systems"].append(sys_snap)
    return snap


def _restore_pinned_geometry(
    layout: PageLayout,
    pinned: dict,
    from_layer: StructureLayer,
) -> None:
    """Force layout geometry for from_layer and above back to user boxes.

    Lower-layer content (notes/glyphs) is left as recomputed; only rects of
    pinned layers are restored so re-detection cannot move user frames.
    """
    rank = {"L1": 1, "L2": 2, "L3": 3, "L4": 4, "L5": 5}[from_layer]

    if rank >= 1 and pinned.get("regions"):
        by_role = {r["role"]: r for r in pinned["regions"]}
        for reg in layout.regions:
            pr = by_role.get(reg.role.value)
            if pr:
                x1, y1, x2, y2 = pr["rect"]
                reg.rect = Rect(x1, y1, x2, y2)

    if rank < 2:
        return

    pinned_systems = pinned.get("systems") or []
    for i, s in enumerate(layout.systems):
        if i >= len(pinned_systems):
            break
        ps = pinned_systems[i]
        x1, y1, x2, y2 = ps["rect"]
        s.rect = Rect(x1, y1, x2, y2)
        s.extra = {**(s.extra or {}), "pinned": True}

        if rank < 3:
            continue
        pmeas = ps.get("measures") or []
        for j, m in enumerate(s.measures):
            if j >= len(pmeas):
                break
            pm = pmeas[j]
            mx1, my1, mx2, my2 = pm["rect"]
            m.rect = Rect(mx1, my1, mx2, my2)
            m.extra = {
                **(m.extra or {}),
                "id": pm.get("id") or (m.extra or {}).get("id"),
                "global_m": pm.get("global_m") or (m.extra or {}).get("global_m"),
                "pinned": True,
            }
            if rank < 4:
                continue
            pnotes = pm.get("notes") or []
            if not pnotes:
                continue
            # Restore note ROI rects by index; keep recomputed glyphs
            for k, n in enumerate(m.notes):
                if k >= len(pnotes):
                    break
                pn = pnotes[k]
                nx1, ny1, nx2, ny2 = pn["rect"]
                n.rect = Rect(nx1, ny1, nx2, ny2)
                n.extra = {
                    **(n.extra or {}),
                    "kind": pn.get("kind") or (n.extra or {}).get("kind", "pitch"),
                    "id": pn.get("id") or (n.extra or {}).get("id"),
                    "pinned": True,
                }


def _layout_to_response(
    layout: PageLayout,
    *,
    settings: Settings,
    filename: str | None,
    content_type: str | None,
    started: float,
    preprocess_steps: list[str],
) -> RecognizeResponse:
    score = page_layout_to_score(
        layout,
        filename=filename,
        engine=f"structure+{settings.recognize_engine}",
    )

    boxes: list[BoundingBox] = []
    regions_out: list[LayoutRegion] = []
    texts: list[str] = []
    notes: list[NoteHint] = []
    for sys in layout.systems:
        for meas in sys.measures:
            for nc in meas.notes:
                boxes.append(nc.rect.as_box())
                g = nc.glyph
                txt = (g.ocr_text if g else "") or (g.pitch if g and g.pitch else "")
                if txt:
                    texts.append(txt)
                kind = "pitch" if g and g.pitch else "other"
                regions_out.append(
                    LayoutRegion(
                        text=txt,
                        box=nc.rect.as_box(),
                        kind=kind,
                        score=g.ocr_score if g else None,
                    )
                )
                if g and g.pitch:
                    notes.append(
                        NoteHint(
                            pitch=g.pitch,
                            text=g.ocr_text,
                            extra={
                                "source": "structure_l5",
                                "underlines": g.underlines,
                                "octave": g.octave,
                            },
                        )
                    )

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    summary = layout_debug_summary(layout)
    logger.info(
        "structure pipeline: systems=%s measures=%s pitched=%s (%sms)",
        summary["n_systems"],
        summary["n_measures"],
        summary["n_pitched"],
        elapsed_ms,
    )

    return RecognizeResponse(
        ok=True,
        engine=f"structure+{settings.recognize_engine}",
        texts=texts,
        boxes=boxes,
        regions=regions_out,
        notes=notes,
        score=score,
        structure=page_layout_to_structure_debug(layout),
        meta=RecognizeMeta(
            width=layout.width,
            height=layout.height,
            elapsed_ms=elapsed_ms,
            filename=filename,
            content_type=content_type,
            mock=settings.recognize_engine == "mock",
            preprocess_steps=preprocess_steps,
            scale=1.0,
            item_count=len(boxes),
            parse_mode="score",
            parse_warnings=list(layout.warnings)[:40],
        ),
    )


def _read_page_meta(
    image_bgr: np.ndarray,
    score_y0: float,
    *,
    settings: Settings,
) -> tuple[str | None, str | None, str | None, list[str]]:
    """OCR only the top-of-page band for title / key / time (not full score)."""
    warnings: list[str] = []
    h, w = image_bgr.shape[:2]
    y1 = max(8, min(h, int(max(score_y0, h * 0.18))))
    band = image_bgr[0:y1, 0:w]
    if band.size == 0:
        return None, None, "4/4", ["L1 meta: empty top band"]

    try:
        engine = get_ocr_engine(
            settings.recognize_engine,
            lang=settings.ocr_lang,
            use_angle_cls=settings.ocr_use_angle_cls,
            use_gpu=settings.ocr_use_gpu,
        )
        ocr = engine.run(band)
    except OcrEngineError as exc:
        warnings.append(f"L1 meta OCR failed: {exc}")
        return None, None, "4/4", warnings

    texts = [it.text for it in ocr.items if it.text]
    blob = " ".join(texts)
    title = None
    key = None
    time_sig = None
    for t in texts:
        if re.search(r"[\u4e00-\u9fff]{2,}", t) and not re.search(
            r"[1-7]{3,}", t
        ):
            if title is None and len(t) >= 2:
                title = t[:80]
        mk = _KEY_RE.search(t)
        if mk:
            raw = mk.group(1) or mk.group(2)
            if raw:
                key = raw[0].upper() + raw[1:].lower()
        mt = _TIME_RE.search(t)
        if mt and time_sig is None:
            time_sig = f"{mt.group(1)}/{mt.group(2)}"
    if time_sig is None:
        mt = _TIME_RE.search(blob)
        if mt:
            time_sig = f"{mt.group(1)}/{mt.group(2)}"
    warnings.append(
        f"L1 meta OCR: title={title!r} key={key!r} time={time_sig!r}"
    )
    return title, key, time_sig or "4/4", warnings
