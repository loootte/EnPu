"""Compare GT vs prediction into per-layer metrics (#86)."""

from __future__ import annotations

from typing import Any

from app.evaluation.extract import PredGeometry
from app.evaluation.metrics import (
    barline_x_metrics,
    box_match_metrics,
    count_metrics,
    pitch_sequence_metrics,
)
from app.evaluation.types import LayerMetric, SampleMetrics


def _unavailable(layer: str, reason: str) -> LayerMetric:
    return LayerMetric(
        layer=layer,
        precision=0.0,
        recall=0.0,
        f1=0.0,
        mode="unavailable",
        extra={"reason": reason},
    )


def compare_sample(
    *,
    sample_id: str,
    gt: dict[str, Any],
    pred: PredGeometry,
    pred_pitch: list[str] | None = None,
    pred_measure_count: int | None = None,
    pred_system_count: int | None = None,
    iou_threshold: float = 0.5,
    barline_max_dist: float = 12.0,
) -> SampleMetrics:
    """Build layered metrics for one sample.

    ``gt`` is the normalized dict from ``load_ground_truth``.
    Geometry IoU is used when GT provides boxes; otherwise count/sequence modes.
    """
    warnings: list[str] = []
    layers: dict[str, LayerMetric] = {}
    geom: dict = gt.get("geometry") or {}

    # ---- L1 ----
    if geom.get("L1"):
        layers["L1"] = box_match_metrics(
            geom["L1"],
            pred.get("L1"),
            layer="L1",
            iou_threshold=iou_threshold,
            require_same_kind=True,
        )
    else:
        # Score-region presence: 1 if any L1 pred, else 0 vs expected 1
        n_pred = len(pred.get("L1"))
        layers["L1"] = count_metrics(
            layer="L1",
            n_gt=1 if n_pred >= 0 else 0,
            n_pred=1 if n_pred > 0 else 0,
            extra={"note": "no L1 geometry GT; presence-only"},
        )
        warnings.append("L1: no geometry GT — presence-only count metric")

    # ---- L2 ----
    if geom.get("L2"):
        layers["L2"] = box_match_metrics(
            geom["L2"],
            pred.get("L2"),
            layer="L2",
            iou_threshold=iou_threshold,
        )
    else:
        n_gt = gt.get("system_count")
        n_pred = (
            pred_system_count
            if pred_system_count is not None
            else len(pred.get("L2"))
        )
        if n_gt is not None:
            layers["L2"] = count_metrics(
                layer="L2",
                n_gt=int(n_gt),
                n_pred=int(n_pred),
                extra={"note": "system_count from score/eval extra"},
            )
        else:
            layers["L2"] = count_metrics(
                layer="L2",
                n_gt=len(pred.get("L2")),
                n_pred=len(pred.get("L2")),
                extra={"note": "no L2 GT — self-count placeholder"},
            )
            warnings.append("L2: no system_count / geometry GT")

    # ---- L3 measures + barlines ----
    if geom.get("L3"):
        layers["L3"] = box_match_metrics(
            geom["L3"],
            pred.get("L3"),
            layer="L3",
            iou_threshold=iou_threshold,
        )
    else:
        n_gt = int(gt.get("measure_count") or 0)
        n_pred = (
            pred_measure_count
            if pred_measure_count is not None
            else len(pred.get("L3"))
        )
        layers["L3"] = count_metrics(
            layer="L3",
            n_gt=n_gt,
            n_pred=int(n_pred),
            extra={
                "note": "measure_count from score GT",
                "abs_delta_bars": abs(int(n_pred) - n_gt),
            },
        )
        if n_gt == 0:
            warnings.append("L3: measure_count GT is 0")

    gt_bars = list(gt.get("barline_xs") or [])
    if gt_bars:
        layers["L3_barlines"] = barline_x_metrics(
            gt_bars,
            list(pred.barline_xs),
            layer="L3_barlines",
            max_dist=barline_max_dist,
        )
    elif pred.barline_xs:
        layers["L3_barlines"] = count_metrics(
            layer="L3_barlines",
            n_gt=0,
            n_pred=len(pred.barline_xs),
            extra={"note": "no barline GT — pred count only"},
        )

    # ---- L4 notes ----
    if geom.get("L4"):
        # Prefer pitch-kind matching when kinds present
        layers["L4"] = box_match_metrics(
            geom["L4"],
            pred.get("L4"),
            layer="L4",
            iou_threshold=iou_threshold,
            require_same_kind=False,
        )
        # Pitch-only subset
        gt_pitch = [b for b in geom["L4"] if (b.kind or "pitch") == "pitch"]
        pred_pitch_boxes = [
            b for b in pred.get("L4") if (b.kind or "pitch") == "pitch"
        ]
        if gt_pitch:
            layers["L4_pitch"] = box_match_metrics(
                gt_pitch,
                pred_pitch_boxes,
                layer="L4_pitch",
                iou_threshold=iou_threshold,
            )
    else:
        n_pred = len(
            [b for b in pred.get("L4") if (b.kind or "pitch") == "pitch"]
        )
        n_gt_pitch = len(gt.get("pitch_sequence") or [])
        if n_gt_pitch:
            layers["L4"] = count_metrics(
                layer="L4",
                n_gt=n_gt_pitch,
                n_pred=n_pred,
                extra={"note": "proxy: pitch token count vs L4 pitch boxes"},
            )
        else:
            layers["L4"] = _unavailable("L4", "no L4 geometry / pitch GT")
            warnings.append("L4: no geometry GT")

    # ---- L5 pitch sequence ----
    gt_seq = list(gt.get("pitch_sequence") or [])
    pred_seq = list(pred_pitch or [])
    if gt_seq or pred_seq:
        layers["L5"] = pitch_sequence_metrics(gt_seq, pred_seq, layer="L5")
    else:
        layers["L5"] = _unavailable("L5", "no pitch sequence")
        warnings.append("L5: empty pitch sequences")

    return SampleMetrics(
        sample_id=sample_id,
        layers=layers,
        warnings=warnings,
        meta={
            "iou_threshold": iou_threshold,
            "has_geometry": {
                k: bool(geom.get(k)) for k in ("L1", "L2", "L3", "L4")
            },
            "gt_measure_count": gt.get("measure_count"),
            "pred_measure_count": pred_measure_count
            if pred_measure_count is not None
            else len(pred.get("L3")),
            "pred_barlines": len(pred.barline_xs),
        },
    )
