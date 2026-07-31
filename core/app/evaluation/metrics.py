"""IoU matching and metric aggregation (#86)."""

from __future__ import annotations

from app.evaluation.types import Box, ErrorBox, LayerMetric


def iou(a: Box, b: Box) -> float:
    """Intersection-over-union of two axis-aligned boxes."""
    ix1 = max(a.x1, b.x1)
    iy1 = max(a.y1, b.y1)
    ix2 = min(a.x2, b.x2)
    iy2 = min(a.y2, b.y2)
    iw = max(0.0, ix2 - ix1)
    ih = max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    union = a.area + b.area - inter
    if union <= 0:
        return 0.0
    return inter / union


def _prf(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    precision = tp / (tp + fp) if (tp + fp) else (1.0 if fn == 0 else 0.0)
    recall = tp / (tp + fn) if (tp + fn) else (1.0 if fp == 0 else 0.0)
    if precision + recall <= 0:
        f1 = 0.0
    else:
        f1 = 2 * precision * recall / (precision + recall)
    return precision, recall, f1


def box_match_metrics(
    gt_boxes: list[Box],
    pred_boxes: list[Box],
    *,
    layer: str,
    iou_threshold: float = 0.5,
    require_same_kind: bool = False,
) -> LayerMetric:
    """Greedy one-to-one matching by descending IoU (standard detection eval)."""
    if not gt_boxes and not pred_boxes:
        return LayerMetric(
            layer=layer,
            precision=1.0,
            recall=1.0,
            f1=1.0,
            mode="iou",
        )

    pairs: list[tuple[float, int, int]] = []
    for gi, g in enumerate(gt_boxes):
        for pi, p in enumerate(pred_boxes):
            if require_same_kind and g.kind and p.kind and g.kind != p.kind:
                continue
            v = iou(g, p)
            if v >= iou_threshold:
                pairs.append((v, gi, pi))
    pairs.sort(key=lambda t: -t[0])

    used_g: set[int] = set()
    used_p: set[int] = set()
    matched_ious: list[float] = []
    errors: list[ErrorBox] = []

    for v, gi, pi in pairs:
        if gi in used_g or pi in used_p:
            continue
        used_g.add(gi)
        used_p.add(pi)
        matched_ious.append(v)
        errors.append(
            ErrorBox(
                kind="tp",
                box=pred_boxes[pi],
                iou=v,
                partner=gt_boxes[gi],
            )
        )

    for pi, p in enumerate(pred_boxes):
        if pi not in used_p:
            errors.append(ErrorBox(kind="fp", box=p))
    for gi, g in enumerate(gt_boxes):
        if gi not in used_g:
            errors.append(ErrorBox(kind="fn", box=g))

    tp = len(used_g)
    fp = len(pred_boxes) - tp
    fn = len(gt_boxes) - tp
    precision, recall, f1 = _prf(tp, fp, fn)
    mean_iou = sum(matched_ious) / len(matched_ious) if matched_ious else 0.0

    return LayerMetric(
        layer=layer,
        precision=precision,
        recall=recall,
        f1=f1,
        tp=tp,
        fp=fp,
        fn=fn,
        mean_iou=mean_iou,
        errors=errors,
        mode="iou",
        extra={
            "n_gt": len(gt_boxes),
            "n_pred": len(pred_boxes),
            "iou_threshold": iou_threshold,
        },
    )


def count_metrics(
    *,
    layer: str,
    n_gt: int,
    n_pred: int,
    extra: dict | None = None,
) -> LayerMetric:
    """Count-based soft metric when geometry GT is missing.

    Treats min(gt, pred) as TP-like agreement; excess as FP/FN.
    """
    tp = min(n_gt, n_pred)
    fp = max(0, n_pred - n_gt)
    fn = max(0, n_gt - n_pred)
    precision, recall, f1 = _prf(tp, fp, fn)
    return LayerMetric(
        layer=layer,
        precision=precision,
        recall=recall,
        f1=f1,
        tp=tp,
        fp=fp,
        fn=fn,
        mean_iou=0.0,
        mode="count",
        extra={
            "n_gt": n_gt,
            "n_pred": n_pred,
            "abs_delta": abs(n_pred - n_gt),
            **(extra or {}),
        },
    )


def pitch_sequence_metrics(
    gt: list[str],
    pred: list[str],
    *,
    layer: str = "L5",
) -> LayerMetric:
    """LCS-based pitch sequence P/R/F1 (token-level)."""
    if not gt and not pred:
        return LayerMetric(
            layer=layer,
            precision=1.0,
            recall=1.0,
            f1=1.0,
            mode="sequence",
            extra={"n_gt": 0, "n_pred": 0, "lcs": 0},
        )
    lcs = _lcs_len(gt, pred)
    # Interpret LCS as TP; unmatched pred as FP; unmatched gt as FN
    tp = lcs
    fp = max(0, len(pred) - lcs)
    fn = max(0, len(gt) - lcs)
    precision, recall, f1 = _prf(tp, fp, fn)
    return LayerMetric(
        layer=layer,
        precision=precision,
        recall=recall,
        f1=f1,
        tp=tp,
        fp=fp,
        fn=fn,
        mode="sequence",
        extra={
            "n_gt": len(gt),
            "n_pred": len(pred),
            "lcs": lcs,
            "gt_sequence": gt,
            "pred_sequence": pred,
        },
    )


def _lcs_len(a: list[str], b: list[str]) -> int:
    n, m = len(a), len(b)
    if n == 0 or m == 0:
        return 0
    prev = [0] * (m + 1)
    for i in range(1, n + 1):
        cur = [0] * (m + 1)
        ai = a[i - 1]
        for j in range(1, m + 1):
            if ai == b[j - 1]:
                cur[j] = prev[j - 1] + 1
            else:
                cur[j] = max(prev[j], cur[j - 1])
        prev = cur
    return prev[m]


def barline_x_metrics(
    gt_xs: list[float],
    pred_xs: list[float],
    *,
    layer: str = "L3_barlines",
    max_dist: float = 12.0,
) -> LayerMetric:
    """Match barline x-positions within max_dist pixels."""
    if not gt_xs and not pred_xs:
        return LayerMetric(
            layer=layer,
            precision=1.0,
            recall=1.0,
            f1=1.0,
            mode="x_distance",
        )
    gt_left = sorted(gt_xs)
    pred_left = list(sorted(pred_xs))
    used_p: set[int] = set()
    tp = 0
    dists: list[float] = []
    for gx in gt_left:
        best_i = -1
        best_d = max_dist + 1
        for pi, px in enumerate(pred_left):
            if pi in used_p:
                continue
            d = abs(px - gx)
            if d < best_d:
                best_d = d
                best_i = pi
        if best_i >= 0 and best_d <= max_dist:
            used_p.add(best_i)
            tp += 1
            dists.append(best_d)
    fp = len(pred_xs) - tp
    fn = len(gt_xs) - tp
    precision, recall, f1 = _prf(tp, fp, fn)
    return LayerMetric(
        layer=layer,
        precision=precision,
        recall=recall,
        f1=f1,
        tp=tp,
        fp=fp,
        fn=fn,
        mean_iou=0.0,
        mode="x_distance",
        extra={
            "n_gt": len(gt_xs),
            "n_pred": len(pred_xs),
            "max_dist": max_dist,
            "mean_abs_dist": (sum(dists) / len(dists)) if dists else None,
            "abs_delta_count": abs(len(pred_xs) - len(gt_xs)),
        },
    )
