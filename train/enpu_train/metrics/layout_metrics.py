"""Hard metrics: L2 box IoU (approx) + L3 split count / mean abs x (#94 / #86)."""

from __future__ import annotations

from typing import Any

import numpy as np
import torch

from enpu_train.data.dataset import decode_peaks


def split_x_metrics(
    gt_xs: list[float],
    pred_xs: list[float],
    *,
    max_dist: float = 12.0,
) -> dict[str, float]:
    """Match split x positions (same idea as core barline_x_metrics)."""
    gt = sorted(float(x) for x in gt_xs)
    pred = sorted(float(x) for x in pred_xs)
    if not gt and not pred:
        return {
            "split_count_mae": 0.0,
            "split_count_exact": 1.0,
            "split_mean_abs_x_error": 0.0,
            "n_gt": 0.0,
            "n_pred": 0.0,
        }
    used: set[int] = set()
    dists: list[float] = []
    tp = 0
    for gx in gt:
        best_i, best_d = -1, max_dist + 1
        for i, px in enumerate(pred):
            if i in used:
                continue
            d = abs(px - gx)
            if d < best_d:
                best_d, best_i = d, i
        if best_i >= 0 and best_d <= max_dist:
            used.add(best_i)
            tp += 1
            dists.append(best_d)
    return {
        "split_count_mae": float(abs(len(pred) - len(gt))),
        "split_count_exact": 1.0 if len(pred) == len(gt) else 0.0,
        "split_mean_abs_x_error": float(sum(dists) / len(dists)) if dists else float("nan"),
        "n_gt": float(len(gt)),
        "n_pred": float(len(pred)),
        "tp": float(tp),
        "fp": float(len(pred) - tp),
        "fn": float(len(gt) - tp),
    }


def box_iou(a: list[float] | np.ndarray, b: list[float] | np.ndarray) -> float:
    ax1, ay1, ax2, ay2 = map(float, a)
    bx1, by1, bx2, by2 = map(float, b)
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - inter
    return float(inter / union) if union > 0 else 0.0


def boxes_mean_iou(
    gt_boxes: list[list[float]],
    pred_boxes: list[list[float]],
) -> float:
    """Greedy match by IoU; mean over GT (unmatched = 0)."""
    if not gt_boxes:
        return 1.0 if not pred_boxes else 0.0
    remaining = list(range(len(pred_boxes)))
    ious: list[float] = []
    for g in gt_boxes:
        best_j, best = -1, 0.0
        for j in remaining:
            v = box_iou(g, pred_boxes[j])
            if v > best:
                best, best_j = v, j
        if best_j >= 0 and best > 0:
            remaining.remove(best_j)
            ious.append(best)
        else:
            ious.append(0.0)
    return float(sum(ious) / len(ious))


def l2_peaks_to_bands(
    heat: np.ndarray,
    *,
    page_h: float,
    page_w: float,
    band_frac: float = 0.08,
) -> list[list[float]]:
    """Decode y-peaks to full-width horizontal bands (approx L2 boxes)."""
    peaks = decode_peaks(heat, min_prominence=0.25, min_gap=max(3, len(heat) // 40))
    boxes = []
    half = band_frac * page_h * 0.5
    for p in peaks:
        cy = p / max(1, len(heat) - 1) * page_h
        boxes.append([0.0, max(0.0, cy - half), page_w, min(page_h, cy + half)])
    return boxes


def l2_peak_boxes_iou(
    heat: np.ndarray,
    gt_boxes: torch.Tensor | list,
    *,
    page_h: float,
    page_w: float,
) -> float:
    if isinstance(gt_boxes, torch.Tensor):
        gt = gt_boxes.detach().cpu().tolist()
    else:
        gt = list(gt_boxes)
    pred = l2_peaks_to_bands(heat, page_h=page_h, page_w=page_w)
    return boxes_mean_iou(gt, pred)


def l3_heat_to_xs(
    heat: np.ndarray,
    *,
    x_left: float,
    x_right: float,
    min_prominence: float = 0.3,
) -> list[float]:
    peaks = decode_peaks(
        heat,
        min_prominence=min_prominence,
        min_gap=max(3, len(heat) // 32),
    )
    width = max(1e-3, x_right - x_left)
    xs = []
    for p in peaks:
        rel = p / max(1, len(heat) - 1)
        xs.append(x_left + rel * width)
    return xs


def evaluate_batch(
    model_out: dict[str, torch.Tensor],
    batch: dict[str, Any],
    *,
    page_h: float,
    page_w: float,
) -> dict[str, float]:
    """Aggregate L2 IoU and L3 split metrics over a batch."""
    stats = {
        "l2_mean_iou": [],
        "l3_split_count_mae": [],
        "l3_split_count_exact": [],
        "l3_mean_abs_x_error": [],
    }

    if "l2_logits" in model_out:
        probs = torch.sigmoid(model_out["l2_logits"]).detach().cpu().numpy()
        for i in range(probs.shape[0]):
            gt = batch["l2_boxes"][i]
            iou = l2_peak_boxes_iou(
                probs[i], gt, page_h=page_h, page_w=page_w
            )
            stats["l2_mean_iou"].append(iou)

    if "l3_logits" in model_out and batch["row_heats"].numel() > 0:
        probs = torch.sigmoid(model_out["l3_logits"]).detach().cpu().numpy()
        for i, meta in enumerate(batch["row_meta"]):
            pred_xs = l3_heat_to_xs(
                probs[i],
                x_left=meta["x_left"],
                x_right=meta["x_right"],
            )
            m = split_x_metrics(
                meta.get("orig_splits") or [],
                pred_xs,
                max_dist=max(12.0, 0.02 * (meta["x_right"] - meta["x_left"])),
            )
            stats["l3_split_count_mae"].append(m["split_count_mae"])
            stats["l3_split_count_exact"].append(m["split_count_exact"])
            if m["split_mean_abs_x_error"] == m["split_mean_abs_x_error"]:  # not nan
                stats["l3_mean_abs_x_error"].append(m["split_mean_abs_x_error"])

    def _mean(xs: list[float]) -> float:
        return float(sum(xs) / len(xs)) if xs else float("nan")

    return {
        "l2_mean_iou": _mean(stats["l2_mean_iou"]),
        "l3_split_count_mae": _mean(stats["l3_split_count_mae"]),
        "l3_split_count_exact": _mean(stats["l3_split_count_exact"]),
        "l3_mean_abs_x_error": _mean(stats["l3_mean_abs_x_error"]),
        "n_l2": float(len(stats["l2_mean_iou"])),
        "n_l3_rows": float(len(stats["l3_split_count_mae"])),
    }
