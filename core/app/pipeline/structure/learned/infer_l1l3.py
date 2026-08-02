"""Run learned L2+L3 on a BGR image → PageLayout skeleton (#104).

L1 uses optional rule regions or full-page score ROI (MVP: hybrid).
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

from app.config import Settings
from app.pipeline.structure.ir import PageLayout, PageRegion, Rect, RegionRole
from app.pipeline.structure.learned.adapter import systems_splits_to_page_layout
from app.pipeline.structure.learned.loader import (
    WeightsLoadError,
    get_cached_layout_model,
)
from app.pipeline.structure.learned.postprocess import (
    bgr_to_model_tensor,
    l2_heat_to_system_boxes,
    l3_heat_to_split_xs,
)

logger = logging.getLogger(__name__)


class LearnedL1L3Error(Exception):
    """Inference failure (caller may fallback to rule)."""


def run_learned_l2_l3(
    image_bgr: np.ndarray,
    *,
    settings: Settings,
    l1_regions: list[PageRegion] | None = None,
) -> PageLayout:
    """Infer L2 systems + L3 splits; attach L1 regions if provided."""
    if image_bgr is None or image_bgr.size == 0:
        raise LearnedL1L3Error("empty image")

    weights = (settings.l1l3_weights or "").strip()
    if not weights:
        raise LearnedL1L3Error(
            "ENPU_L1L3_WEIGHTS is empty; set path to train export "
            "(layout_net.pt / best.pt)"
        )

    device = (settings.l1l3_device or "cpu").strip() or "cpu"
    try:
        model, wmeta = get_cached_layout_model(weights, device)
    except WeightsLoadError as e:
        raise LearnedL1L3Error(str(e)) from e

    try:
        import torch
    except ImportError as e:
        raise LearnedL1L3Error("torch not installed") from e

    h, w = image_bgr.shape[:2]
    cfg = model.cfg
    page_h, page_w = cfg.page_h, cfg.page_w
    row_h, row_w = cfg.row_h, cfg.row_w

    page_t = bgr_to_model_tensor(image_bgr, out_h=page_h, out_w=page_w).to(device)
    warnings: list[str] = [
        "l1l3_engine=learned (#104)",
        f"l1l3_weights={wmeta.get('path')}",
        f"l1l3_format={wmeta.get('format')}",
    ]

    with torch.no_grad():
        out = model(page=page_t)
        if "l2_logits" not in out:
            raise LearnedL1L3Error("model has no L2 head / tasks")
        l2_prob = torch.sigmoid(out["l2_logits"])[0].detach().cpu().numpy()

    system_boxes = l2_heat_to_system_boxes(
        l2_prob,
        orig_h=h,
        orig_w=w,
        page_h=page_h,
        page_w=page_w,
    )
    if not system_boxes:
        raise LearnedL1L3Error("L2 produced no systems")

    # L3 per system crop
    splits_per: list[list[float]] = [[] for _ in system_boxes]
    row_tensors: list = []
    row_indices: list[int] = []
    crop_meta: list[dict[str, float]] = []

    for i, box in enumerate(system_boxes):
        x1 = int(max(0, box["x1"]))
        y1 = int(max(0, box["y1"]))
        x2 = int(min(w, box["x2"]))
        y2 = int(min(h, box["y2"]))
        if x2 <= x1 + 2 or y2 <= y1 + 2:
            continue
        pad_x = int(0.02 * (x2 - x1))
        pad_y = int(0.05 * (y2 - y1))
        cx1 = max(0, x1 - pad_x)
        cy1 = max(0, y1 - pad_y)
        cx2 = min(w, x2 + pad_x)
        cy2 = min(h, y2 + pad_y)
        crop = image_bgr[cy1:cy2, cx1:cx2]
        row_tensors.append(bgr_to_model_tensor(crop, out_h=row_h, out_w=row_w)[0])
        row_indices.append(i)
        crop_meta.append(
            {
                "x_left": float(cx1),
                "x_right": float(cx2),
                "y1": float(cy1),
                "y2": float(cy2),
            }
        )

    if row_tensors and "l3" in cfg.tasks:
        rows_batch = torch.stack(row_tensors, dim=0).to(device)
        with torch.no_grad():
            l3_out = model(rows=rows_batch)
            l3_logits = l3_out.get("l3_logits")
            if l3_logits is not None:
                probs = torch.sigmoid(l3_logits).detach().cpu().numpy()
                for j, meta in enumerate(crop_meta):
                    xs = l3_heat_to_split_xs(
                        probs[j],
                        x_left=meta["x_left"],
                        x_right=meta["x_right"],
                    )
                    splits_per[row_indices[j]] = xs
    else:
        warnings.append("L3 skipped (no crops or task disabled)")

    # L1 regions
    score_rect = None
    title_box = None
    key_time_box = None
    if l1_regions:
        for r in l1_regions:
            if r.role == RegionRole.score:
                score_rect = r.rect
            elif r.role == RegionRole.title:
                title_box = r.rect
            elif r.role == RegionRole.key_time:
                key_time_box = r.rect
    if score_rect is None:
        # score band covering all systems
        y1 = min(b["y1"] for b in system_boxes)
        y2 = max(b["y2"] for b in system_boxes)
        score_rect = Rect(0, max(0.0, y1 - 0.02 * h), float(w), min(float(h), y2 + 0.02 * h))

    warnings.append(
        f"L2: learned {len(system_boxes)} system(s); "
        f"L3 splits total={sum(len(s) for s in splits_per)}"
    )

    layout = systems_splits_to_page_layout(
        width=w,
        height=h,
        system_boxes=system_boxes,
        splits_per_system=splits_per,
        score_region=score_rect,
        title_box=title_box,
        key_time_box=key_time_box,
        warnings=warnings,
        engine_meta={
            "weights": wmeta,
            "n_systems": len(system_boxes),
            "n_splits": sum(len(s) for s in splits_per),
        },
    )
    return layout
