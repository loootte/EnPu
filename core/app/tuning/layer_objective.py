"""Box matching and single-layer loss (#89)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.evaluation.metrics import box_match_metrics, iou
from app.evaluation.types import Box, LayerMetric


@dataclass
class MatchResult:
    tp: int
    fp: int
    fn: int
    mean_iou: float
    pairs: list[tuple[int, int, float]] = field(default_factory=list)
    precision: float = 0.0
    recall: float = 0.0
    f1: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "tp": self.tp,
            "fp": self.fp,
            "fn": self.fn,
            "mean_iou": round(self.mean_iou, 4),
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "f1": round(self.f1, 4),
            "n_pairs": len(self.pairs),
        }


def match_boxes(
    pred: list[Box],
    gt: list[Box],
    *,
    iou_threshold: float = 0.5,
) -> MatchResult:
    """Greedy one-to-one IoU matching (same as eval metrics)."""
    lm = box_match_metrics(gt, pred, layer="match", iou_threshold=iou_threshold)
    pairs: list[tuple[int, int, float]] = []
    # Reconstruct pairs from errors TP entries
    used_g: set[int] = set()
    used_p: set[int] = set()
    for e in lm.errors:
        if e.kind != "tp" or e.partner is None or e.iou is None:
            continue
        # find indices
        gi = next((i for i, g in enumerate(gt) if g is e.partner or _box_eq(g, e.partner)), -1)
        pi = next((i for i, p in enumerate(pred) if p is e.box or _box_eq(p, e.box)), -1)
        if gi >= 0 and pi >= 0 and gi not in used_g and pi not in used_p:
            used_g.add(gi)
            used_p.add(pi)
            pairs.append((pi, gi, e.iou))
    return MatchResult(
        tp=lm.tp,
        fp=lm.fp,
        fn=lm.fn,
        mean_iou=lm.mean_iou,
        pairs=pairs,
        precision=lm.precision,
        recall=lm.recall,
        f1=lm.f1,
    )


def _box_eq(a: Box, b: Box) -> bool:
    return (
        abs(a.x1 - b.x1) < 1e-6
        and abs(a.y1 - b.y1) < 1e-6
        and abs(a.x2 - b.x2) < 1e-6
        and abs(a.y2 - b.y2) < 1e-6
    )


@dataclass
class LayerLoss:
    loss: float
    score: float
    match: MatchResult
    components: dict[str, float] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "loss": round(self.loss, 6),
            "score": round(self.score, 6),
            "match": self.match.as_dict(),
            "components": {k: round(v, 6) for k, v in self.components.items()},
        }


def layer_loss(
    pred: list[Box],
    gt: list[Box],
    *,
    w_iou: float = 1.0,
    w_cnt: float = 0.5,
    w_fn: float = 0.35,
    w_fp: float = 0.25,
    iou_threshold: float = 0.5,
) -> LayerLoss:
    """
    loss = w_iou*(1-mean_iou) + w_cnt*norm_count + w_fn*fn_rate + w_fp*fp_rate

    Only uses current-layer pred vs GT (no downstream pitch).
    """
    m = match_boxes(pred, gt, iou_threshold=iou_threshold)
    n_gt = max(len(gt), 1)
    n_pred = len(pred)
    # count error normalized by gt size (cap at 1)
    cnt_err = min(1.0, abs(n_pred - len(gt)) / n_gt)
    fn_rate = m.fn / n_gt
    fp_rate = m.fp / max(n_pred, 1) if n_pred else (0.0 if len(gt) == 0 else 1.0)
    mean_iou = m.mean_iou if m.tp > 0 else 0.0

    c_iou = w_iou * (1.0 - mean_iou)
    c_cnt = w_cnt * cnt_err
    c_fn = w_fn * fn_rate
    c_fp = w_fp * fp_rate
    loss = c_iou + c_cnt + c_fn + c_fp
    # Bound for score display
    score = max(0.0, 1.0 - loss)
    return LayerLoss(
        loss=loss,
        score=score,
        match=m,
        components={
            "iou_term": c_iou,
            "cnt_term": c_cnt,
            "fn_term": c_fn,
            "fp_term": c_fp,
            "mean_iou": mean_iou,
            "cnt_err": cnt_err,
            "fn_rate": fn_rate,
            "fp_rate": fp_rate,
        },
    )


def metric_to_boxes_from_layer_metric(lm: LayerMetric) -> None:
    """Placeholder — boxes come from extract, not metrics."""
    return None
