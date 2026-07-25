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
    """Re-run structure pipeline from ``from_layer`` downward using user boxes (#78).

    Upper layers are taken from ``base_structure`` (after applying ``edits``).
    Lower layers are recomputed on the image.

    Examples:
      - from_layer=L2: keep L1, use edited L2 system rects, re-run L3–L5
      - from_layer=L3: keep L1–L2, use edited L3 measure rects, re-run L4–L5
      - from_layer=L4: keep L1–L3, use edited L4 ROIs, re-run L5
      - from_layer=L5: keep L1–L4 candidates, re-OCR / geometry L5
      - from_layer=L1: use edited L1 (score) ROI, re-run L2–L5
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
    clear_below_layer(layout, from_layer)

    # --- recompute from layer ---
    if from_layer == "L1":
        score_rect = layout.score_region
        if score_rect is None:
            # Prefer edited L1 score if present, else redetect all L1
            regions, w1 = detect_page_regions(image_bgr)
            warnings.extend(w1)
            layout.regions = regions
            score_rect = layout.score_region or Rect(0, 0, float(w), float(h))
        else:
            # Keep user L1 regions; only re-run systems inside score
            warnings.append("L1: using user-edited page regions")
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
        # Systems from user L2 boxes (already in layout); re-run L3–L5
        if not layout.systems:
            score_rect = layout.score_region or Rect(0, 0, float(w), float(h))
            systems, w2 = detect_staff_systems(image_bgr, score_rect)
            warnings.extend(w2)
            layout.systems = systems
        else:
            # Drop stale measures
            layout.systems = [
                StaffSystem(
                    index=s.index,
                    rect=s.rect,
                    measures=[],
                    barline_xs=[],
                    confidence=s.confidence,
                    extra={**(s.extra or {}), "user_edited": True},
                )
                for s in layout.systems
            ]
            warnings.append(
                f"L2: using {len(layout.systems)} user system rect(s); re-run L3–L5"
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
        # Keep user measure rects; if none, re-detect
        n_meas = sum(len(s.measures) for s in layout.systems)
        if n_meas == 0:
            systems, w3 = segment_measures_on_systems(image_bgr, layout.systems)
            warnings.extend(w3)
            layout.systems = systems
        else:
            for s in layout.systems:
                for m in s.measures:
                    m.notes = []
                    m.extra = {**(m.extra or {}), "user_edited": True}
            warnings.append(
                f"L3: using {n_meas} user measure rect(s); re-run L4–L5"
            )
        systems, w4 = detect_note_candidates(image_bgr, layout.systems)
        warnings.extend(w4)
        layout.systems = systems
    elif from_layer == "L4":
        n_notes = sum(len(m.notes) for s in layout.systems for m in s.measures)
        if n_notes == 0:
            systems, w4 = detect_note_candidates(image_bgr, layout.systems)
            warnings.extend(w4)
            layout.systems = systems
        else:
            for s in layout.systems:
                for m in s.measures:
                    for n in m.notes:
                        n.glyph = None
                        n.extra = {**(n.extra or {}), "user_edited": True}
            warnings.append(
                f"L4: using {n_notes} user note ROI(s); re-run L5"
            )
    else:  # L5
        n_notes = sum(len(m.notes) for s in layout.systems for m in s.measures)
        if n_notes == 0:
            systems, w4 = detect_note_candidates(image_bgr, layout.systems)
            warnings.extend(w4)
            layout.systems = systems
        else:
            for s in layout.systems:
                for m in s.measures:
                    for n in m.notes:
                        n.glyph = None
            warnings.append(f"L5: re-fill glyphs on {n_notes} candidate(s)")

    # Meta for meter / title (prefer caller overrides, else structure summary)
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
    layout.warnings = warnings

    return _layout_to_response(
        layout,
        settings=settings,
        filename=filename,
        content_type=content_type,
        started=started,
        preprocess_steps=["decode", f"structure_rerun_{from_layer}"],
    )


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
