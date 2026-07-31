"""Single-node parameter grid search for layered metrics (#86)."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np

from app.evaluation.batch import evaluate_sample
from app.evaluation.extract import boxes_from_page_layout
from app.evaluation.gt_loader import load_ground_truth
from app.pipeline.structure.ir import PageLayout, StaffSystem
from app.pipeline.structure.l1_page import detect_page_regions
from app.pipeline.structure.l2_systems import detect_staff_systems
from app.pipeline.structure.l3_measures import segment_measures_on_systems
from app.pipeline.structure.l4_notes import detect_note_candidates

TunableParam = Literal[
    "l3_min_measure_width",
    "l3_enable_cross_line",
]


@dataclass
class TunePoint:
    param: str
    value: float | bool | str
    f1: float
    precision: float
    recall: float
    extra: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "param": self.param,
            "value": self.value,
            "f1": round(self.f1, 4),
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "extra": self.extra,
        }


@dataclass
class TuneResult:
    param: str
    layer: str
    points: list[TunePoint]
    best_value: float | bool | str | None
    best_f1: float
    elapsed_sec: float
    n_runs: int
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "param": self.param,
            "layer": self.layer,
            "points": [p.as_dict() for p in self.points],
            "best_value": self.best_value,
            "best_f1": round(self.best_f1, 4),
            "elapsed_sec": round(self.elapsed_sec, 3),
            "n_runs": self.n_runs,
            "warnings": self.warnings,
        }


def _float_grid(start: float, stop: float, step: float) -> list[float]:
    if step <= 0:
        raise ValueError("step must be > 0")
    if stop < start:
        start, stop = stop, start
    vals: list[float] = []
    x = start
    # inclusive stop with float safety
    while x <= stop + step * 1e-9:
        vals.append(round(x, 6))
        x += step
    return vals or [start]


def build_l1_l2_cache(image_bgr: np.ndarray) -> tuple[PageLayout, list[str]]:
    """Run L1+L2 once; reuse systems for L3 parameter sweeps."""
    warnings: list[str] = []
    h, w = image_bgr.shape[:2]
    regions, w1 = detect_page_regions(image_bgr)
    warnings.extend(w1)
    score = next((r for r in regions if r.role.value == "score"), None)
    if score is None:
        # whole page fallback
        from app.pipeline.structure.ir import Rect, RegionRole, PageRegion

        score_rect = Rect(0, 0, float(w), float(h))
        regions = [
            PageRegion(role=RegionRole.score, rect=score_rect, confidence=0.3)
        ]
        warnings.append("tune: no score region — using full page")
        score_rect_use = score_rect
    else:
        score_rect_use = score.rect

    systems, w2 = detect_staff_systems(image_bgr, score_rect_use)
    warnings.extend(w2)
    layout = PageLayout(
        width=w,
        height=h,
        regions=regions,
        systems=systems,
        warnings=list(warnings),
    )
    return layout, warnings


def _clone_systems(systems: list[StaffSystem]) -> list[StaffSystem]:
    out: list[StaffSystem] = []
    for s in systems:
        out.append(
            StaffSystem(
                index=s.index,
                rect=s.rect,
                measures=[],
                barline_xs=[],
                confidence=s.confidence,
                extra=dict(s.extra or {}),
            )
        )
    return out


def tune_param_on_image(
    image_bgr: np.ndarray,
    *,
    gt: dict[str, Any],
    param: TunableParam = "l3_min_measure_width",
    start: float = 16.0,
    stop: float = 64.0,
    step: float = 8.0,
    sample_id: str = "tune",
    layer_metric: str = "L3",
) -> TuneResult:
    """Grid-search one L3 parameter against layered metrics.

    Upstream L1/L2 run once; only L3 (and light L4 for box counts) re-runs.
    """
    started = time.perf_counter()
    warnings: list[str] = []
    base_layout, w0 = build_l1_l2_cache(image_bgr)
    warnings.extend(w0)

    points: list[TunePoint] = []
    best_f1 = -1.0
    best_value: float | bool | str | None = None

    if param == "l3_min_measure_width":
        grid: list[float | bool] = list(_float_grid(start, stop, step))
    elif param == "l3_enable_cross_line":
        grid = [False, True]
    else:
        raise ValueError(f"unsupported param: {param}")

    for val in grid:
        systems = _clone_systems(base_layout.systems)
        if param == "l3_min_measure_width":
            systems, w3 = segment_measures_on_systems(
                image_bgr,
                systems,
                min_measure_width=float(val),
            )
        else:
            systems, w3 = segment_measures_on_systems(
                image_bgr,
                systems,
                enable_cross_line=bool(val),
            )
        # Optional L4 so L4 proxy metrics stay available
        try:
            systems, w4 = detect_note_candidates(image_bgr, systems)
        except Exception:  # noqa: BLE001
            w4 = []
        layout = PageLayout(
            width=base_layout.width,
            height=base_layout.height,
            regions=list(base_layout.regions),
            systems=systems,
            warnings=list(w3) + list(w4),
        )
        pred = boxes_from_page_layout(layout)
        metrics = evaluate_sample(
            sample_id=sample_id,
            gt=gt,
            pred=pred,
            pred_measure_count=len(pred.get("L3")),
            pred_system_count=len(pred.get("L2")),
            pred_pitch=None,
        )
        lm = metrics.layers.get(layer_metric) or metrics.layers.get("L3")
        if lm is None:
            f1 = p = r = 0.0
        else:
            f1, p, r = lm.f1, lm.precision, lm.recall
        pt = TunePoint(
            param=param,
            value=val,
            f1=f1,
            precision=p,
            recall=r,
            extra={
                "n_measures": len(pred.get("L3")),
                "n_barlines": len(pred.barline_xs),
                "layer_mode": lm.mode if lm else None,
                "abs_delta_bars": (lm.extra or {}).get("abs_delta_bars")
                if lm
                else None,
            },
        )
        points.append(pt)
        if f1 > best_f1:
            best_f1 = f1
            best_value = val

    return TuneResult(
        param=param,
        layer=layer_metric,
        points=points,
        best_value=best_value,
        best_f1=max(best_f1, 0.0),
        elapsed_sec=time.perf_counter() - started,
        n_runs=len(points),
        warnings=warnings[:20],
    )


def save_baseline(report: dict[str, Any], path: str | Any) -> None:
    """Persist a batch report as a baseline JSON."""
    from pathlib import Path
    import json

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "enpu-layer-baseline-v0.1",
        "saved_from": report.get("schema"),
        "mean_f1": report.get("mean_f1"),
        "n_samples": report.get("n_samples"),
        "samples": report.get("samples"),
        "meta": {
            "manifest": report.get("manifest"),
            "elapsed_sec": report.get("elapsed_sec"),
        },
    }
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_baseline(path: str | Any) -> dict[str, Any]:
    from pathlib import Path
    import json

    return json.loads(Path(path).read_text(encoding="utf-8"))


def diff_baselines(
    current: dict[str, Any],
    baseline: dict[str, Any],
) -> dict[str, Any]:
    """Compare mean_f1 maps: positive delta = improvement."""
    cur = current.get("mean_f1") or {}
    base = baseline.get("mean_f1") or {}
    keys = sorted(set(cur) | set(base))
    deltas: dict[str, float] = {}
    for k in keys:
        deltas[k] = round(float(cur.get(k, 0.0)) - float(base.get(k, 0.0)), 4)
    improved = [k for k, d in deltas.items() if d > 1e-6]
    regressed = [k for k, d in deltas.items() if d < -1e-6]
    return {
        "deltas": deltas,
        "improved": improved,
        "regressed": regressed,
        "unchanged": [k for k, d in deltas.items() if abs(d) <= 1e-6],
    }
