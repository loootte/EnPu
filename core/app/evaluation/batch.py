"""Batch layered evaluation over samples/eval manifest (#86)."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable

from app.evaluation.compare import compare_sample
from app.evaluation.extract import (
    PredGeometry,
    boxes_from_page_layout,
    boxes_from_structure_debug,
    measure_count_from_score_obj,
    pitch_sequence_from_score_obj,
    system_count_from_layout,
)
from app.evaluation.gt_loader import load_ground_truth
from app.evaluation.types import SampleMetrics


def evaluate_sample(
    *,
    sample_id: str,
    gt_path: Path | str | None = None,
    gt: dict[str, Any] | None = None,
    pred: PredGeometry | None = None,
    pred_pitch: list[str] | None = None,
    pred_measure_count: int | None = None,
    pred_system_count: int | None = None,
    structure: Any = None,
    layout: Any = None,
    score: Any = None,
    iou_threshold: float = 0.5,
) -> SampleMetrics:
    """Evaluate one sample from GT path/dict and prediction artifacts."""
    if gt is None:
        if gt_path is None:
            raise ValueError("gt or gt_path required")
        gt = load_ground_truth(gt_path)

    if pred is None:
        if layout is not None:
            pred = boxes_from_page_layout(layout)
            if pred_system_count is None:
                pred_system_count = system_count_from_layout(layout)
        elif structure is not None:
            pred = boxes_from_structure_debug(structure)
        else:
            pred = PredGeometry()

    if pred_pitch is None and score is not None:
        pred_pitch = pitch_sequence_from_score_obj(score)
    if pred_measure_count is None and score is not None:
        pred_measure_count = measure_count_from_score_obj(score)

    return compare_sample(
        sample_id=sample_id,
        gt=gt,
        pred=pred,
        pred_pitch=pred_pitch,
        pred_measure_count=pred_measure_count,
        pred_system_count=pred_system_count,
        iou_threshold=iou_threshold,
    )


def load_manifest(path: Path | str) -> dict[str, Any]:
    p = Path(path)
    return json.loads(p.read_text(encoding="utf-8"))


def evaluate_manifest(
    manifest_path: Path | str,
    *,
    eval_root: Path | str | None = None,
    recognize_fn: Callable[[Path], dict[str, Any]] | None = None,
    subset: str | None = None,
    limit: int | None = None,
    iou_threshold: float = 0.5,
    include_errors: bool = False,
) -> dict[str, Any]:
    """Run layered eval over a manifest.

    ``recognize_fn(image_path) -> dict`` should return keys:
      score (dict), structure (optional), layout (optional PageLayout)
    If ``recognize_fn`` is None, only GT-side stats are reported (no pred).
    """
    manifest_path = Path(manifest_path)
    root = Path(eval_root) if eval_root else manifest_path.parent
    man = load_manifest(manifest_path)
    entries = list(man.get("entries") or [])
    if subset:
        entries = [e for e in entries if e.get("subset") == subset]
    if limit is not None:
        entries = entries[: max(0, int(limit))]

    samples: list[dict[str, Any]] = []
    layer_sums: dict[str, list[float]] = {}
    started = time.perf_counter()

    for ent in entries:
        if ent.get("status") and ent.get("status") != "ready":
            continue
        sid = str(ent.get("id") or "")
        gt_rel = ent.get("gt")
        img_rel = ent.get("image")
        if not gt_rel:
            continue
        gt_path = root / gt_rel
        if not gt_path.is_file():
            samples.append(
                {
                    "sample_id": sid,
                    "error": f"gt missing: {gt_path}",
                }
            )
            continue

        gt = load_ground_truth(gt_path)
        pred = PredGeometry()
        score = None
        structure = None
        layout = None
        warn: list[str] = []

        if recognize_fn is not None and img_rel:
            img_path = root / img_rel
            if not img_path.is_file():
                samples.append(
                    {
                        "sample_id": sid,
                        "error": f"image missing: {img_path}",
                    }
                )
                continue
            try:
                out = recognize_fn(img_path)
            except Exception as exc:  # noqa: BLE001 — collect per-sample errors
                samples.append(
                    {
                        "sample_id": sid,
                        "error": f"recognize failed: {exc}",
                    }
                )
                continue
            score = out.get("score")
            structure = out.get("structure")
            layout = out.get("layout")
            if layout is not None:
                pred = boxes_from_page_layout(layout)
            elif structure is not None:
                pred = boxes_from_structure_debug(structure)

        metrics = evaluate_sample(
            sample_id=sid,
            gt=gt,
            pred=pred,
            score=score,
            structure=structure,
            layout=layout,
            iou_threshold=iou_threshold,
        )
        metrics.warnings.extend(warn)
        samples.append(metrics.as_dict(include_errors=include_errors))

        for layer_name, lm in metrics.layers.items():
            layer_sums.setdefault(layer_name, []).append(lm.f1)

    mean_f1 = {
        k: (sum(vs) / len(vs) if vs else 0.0) for k, vs in layer_sums.items()
    }
    return {
        "schema": "enpu-layer-metrics-v0.1",
        "issue": 86,
        "manifest": str(manifest_path),
        "n_samples": len(samples),
        "mean_f1": {k: round(v, 4) for k, v in mean_f1.items()},
        "elapsed_sec": round(time.perf_counter() - started, 3),
        "samples": samples,
    }


def write_report_markdown(report: dict[str, Any], path: Path | str) -> None:
    """Write a compact Markdown summary of a batch report."""
    lines = [
        "# Layer metrics report (#86)",
        "",
        f"- manifest: `{report.get('manifest')}`",
        f"- samples: **{report.get('n_samples')}**",
        f"- elapsed: {report.get('elapsed_sec')}s",
        "",
        "## Mean F1 by layer",
        "",
        "| Layer | Mean F1 |",
        "|-------|---------|",
    ]
    for k, v in sorted((report.get("mean_f1") or {}).items()):
        lines.append(f"| {k} | {v:.4f} |")
    lines.append("")
    lines.append("## Per-sample F1")
    lines.append("")
    lines.append("| Sample | L3 | L4 | L5 | notes |")
    lines.append("|--------|----|----|----|-------|")
    for s in report.get("samples") or []:
        if s.get("error"):
            lines.append(f"| {s.get('sample_id')} | ERR | | | {s['error'][:40]} |")
            continue
        layers = s.get("layers") or {}
        def f1(name: str) -> str:
            lm = layers.get(name) or {}
            if not lm:
                return "-"
            return f"{lm.get('f1', 0):.3f}"
        warn = ";".join((s.get("warnings") or [])[:2])
        lines.append(
            f"| {s.get('sample_id')} | {f1('L3')} | {f1('L4')} | {f1('L5')} | {warn[:40]} |"
        )
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
