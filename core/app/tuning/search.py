"""Random / grid search for single-layer params (#89)."""

from __future__ import annotations

import json
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import numpy as np

from app.evaluation.extract import boxes_from_page_layout
from app.evaluation.types import Box
from app.pipeline.structure.ir import PageLayout, StaffSystem
from app.pipeline.structure.l1_page import detect_page_regions
from app.pipeline.structure.l2_systems import detect_staff_systems
from app.pipeline.structure.l3_measures import segment_measures_on_systems
from app.pipeline.structure.l4_notes import detect_note_candidates
from app.tuning.layer_objective import layer_loss
from app.tuning.params import (
    get_layer_params,
    load_default_params_file,
    set_layer_params,
)

_REPO = Path(__file__).resolve().parents[3]


@dataclass
class TrialRecord:
    trial: int
    params: dict[str, Any]
    loss: float
    score: float
    mean_iou: float
    tp: int
    fp: int
    fn: int
    elapsed_ms: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "trial": self.trial,
            "params": self.params,
            "loss": round(self.loss, 6),
            "score": round(self.score, 6),
            "mean_iou": round(self.mean_iou, 4),
            "tp": self.tp,
            "fp": self.fp,
            "fn": self.fn,
            "elapsed_ms": round(self.elapsed_ms, 2),
        }


@dataclass
class TuneLayerResult:
    layer: str
    best_params: dict[str, Any]
    best_loss: float
    best_score: float
    baseline_loss: float
    baseline_score: float
    improved: bool
    trials: list[TrialRecord]
    n_trials: int
    seed: int
    elapsed_sec: float
    warnings: list[str] = field(default_factory=list)
    objective: dict[str, float] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "layer": self.layer,
            "best_params": self.best_params,
            "best_loss": round(self.best_loss, 6),
            "best_score": round(self.best_score, 6),
            "baseline_loss": round(self.baseline_loss, 6),
            "baseline_score": round(self.baseline_score, 6),
            "improved": self.improved,
            "n_trials": self.n_trials,
            "seed": self.seed,
            "elapsed_sec": round(self.elapsed_sec, 3),
            "warnings": self.warnings,
            "objective": self.objective,
            "trials": [t.as_dict() for t in self.trials],
        }


def _load_space(layer: str) -> dict[str, Any]:
    path = _REPO / "configs" / "tune" / f"space_{layer}.yaml"
    try:
        import yaml

        data = yaml.safe_load(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except Exception:
        data = {}
    return data if isinstance(data, dict) else {}


def _sample_params(
    space: dict[str, Any],
    rng: random.Random,
    *,
    fixed: dict[str, Any],
) -> dict[str, Any]:
    """Draw one candidate from space (random search)."""
    params_spec = space.get("params") or {}
    out = dict(fixed)
    for key, spec in params_spec.items():
        if not isinstance(spec, dict):
            continue
        t = str(spec.get("type") or "float")
        if t == "bool":
            out[key] = bool(rng.choice([False, True]))
        elif t == "int":
            lo = int(spec.get("low", 0))
            hi = int(spec.get("high", lo))
            out[key] = int(rng.randint(lo, hi))
        else:
            lo = float(spec.get("low", 0.0))
            hi = float(spec.get("high", lo))
            out[key] = float(rng.uniform(lo, hi))
    return out


def _clone_systems(systems: list[StaffSystem]) -> list[StaffSystem]:
    out: list[StaffSystem] = []
    for s in systems:
        out.append(
            StaffSystem(
                index=s.index,
                rect=s.rect,
                measures=list(s.measures),
                barline_xs=list(s.barline_xs),
                confidence=s.confidence,
                extra=dict(s.extra or {}),
            )
        )
    return out


def _build_upstream(
    image_bgr: np.ndarray,
    *,
    layer: str,
) -> tuple[PageLayout, list[str]]:
    """Cache L1/L2 (and L3 if tuning L4)."""
    warnings: list[str] = []
    h, w = image_bgr.shape[:2]
    regions, w1 = detect_page_regions(image_bgr)
    warnings.extend(w1)
    from app.pipeline.structure.ir import Rect, RegionRole

    score = next((r for r in regions if r.role == RegionRole.score), None)
    score_rect = score.rect if score else Rect(0, 0, float(w), float(h))
    systems, w2 = detect_staff_systems(image_bgr, score_rect)
    warnings.extend(w2)
    if layer == "l4":
        systems, w3 = segment_measures_on_systems(image_bgr, systems)
        warnings.extend(w3)
    layout = PageLayout(
        width=w,
        height=h,
        regions=regions,
        systems=systems,
        warnings=list(warnings),
    )
    return layout, warnings


def _pred_boxes_for_layer(
    image_bgr: np.ndarray,
    base: PageLayout,
    *,
    layer: str,
    params: dict[str, Any],
) -> list[Box]:
    systems = _clone_systems(base.systems)
    if layer == "l3":
        # Clear measures; re-segment
        systems = [
            StaffSystem(
                index=s.index,
                rect=s.rect,
                measures=[],
                barline_xs=[],
                confidence=s.confidence,
                extra=dict(s.extra or {}),
            )
            for s in systems
        ]
        systems, _ = segment_measures_on_systems(
            image_bgr, systems, params=params
        )
        layout = PageLayout(
            width=base.width,
            height=base.height,
            regions=list(base.regions),
            systems=systems,
        )
        return boxes_from_page_layout(layout).get("L3")

    if layer == "l4":
        # Keep L3 measures from cache; re-run L4 only
        systems, _ = detect_note_candidates(image_bgr, systems, params=params)
        layout = PageLayout(
            width=base.width,
            height=base.height,
            regions=list(base.regions),
            systems=systems,
        )
        return [
            b
            for b in boxes_from_page_layout(layout).get("L4")
            if (b.kind or "pitch") == "pitch"
        ]

    raise ValueError(f"unsupported layer: {layer}")


def gt_boxes_for_layer(gt: dict[str, Any], layer: str) -> list[Box]:
    """Extract GT boxes for L3/L4 from normalized GT dict."""
    geom = gt.get("geometry") or {}
    key = "L3" if layer == "l3" else "L4"
    boxes = list(geom.get(key) or [])
    if key == "L4":
        boxes = [b for b in boxes if (b.kind or "pitch") == "pitch"]
    return boxes


def tune_layer(
    image_bgr: np.ndarray,
    *,
    gt: dict[str, Any],
    layer: Literal["l3", "l4"] = "l3",
    max_trials: int = 40,
    max_seconds: float = 120.0,
    seed: int = 42,
    method: Literal["random", "grid"] = "random",
    apply_best: bool = False,
    log_path: Path | str | None = None,
) -> TuneLayerResult:
    """
    Search layer params to minimize layer_loss(pred, gt).

    Upstream layout is cached once. GT is never modified.
    """
    layer = layer.lower()  # type: ignore[assignment]
    if layer not in ("l3", "l4"):
        raise ValueError("layer must be l3 or l4")

    started = time.perf_counter()
    warnings: list[str] = []
    space = _load_space(layer)
    obj = space.get("objective") or {}
    w_iou = float(obj.get("w_iou", 1.0))
    w_cnt = float(obj.get("w_cnt", 0.5))
    w_fn = float(obj.get("w_fn", 0.35))
    w_fp = float(obj.get("w_fp", 0.25))
    iou_thr = float(obj.get("iou_threshold", 0.5))

    gt_boxes = gt_boxes_for_layer(gt, layer)
    if not gt_boxes:
        warnings.append(
            f"tune_layer: no geometry GT for {layer.upper()} — "
            "loss uses empty-GT matching (prefer edit-as-GT)"
        )

    base_layout, w0 = _build_upstream(image_bgr, layer=layer)
    warnings.extend(w0[:12])

    fixed = get_layer_params(layer)
    rng = random.Random(seed)

    def eval_params(params: dict[str, Any]) -> tuple[float, float, Any, float]:
        t0 = time.perf_counter()
        pred = _pred_boxes_for_layer(
            image_bgr, base_layout, layer=layer, params=params
        )
        loss_obj = layer_loss(
            pred,
            gt_boxes,
            w_iou=w_iou,
            w_cnt=w_cnt,
            w_fn=w_fn,
            w_fp=w_fp,
            iou_threshold=iou_thr,
        )
        return loss_obj.loss, loss_obj.score, loss_obj, (time.perf_counter() - t0) * 1000

    # Baseline with current params
    base_loss, base_score, base_obj, base_ms = eval_params(fixed)
    trials: list[TrialRecord] = [
        TrialRecord(
            trial=0,
            params=dict(fixed),
            loss=base_loss,
            score=base_score,
            mean_iou=base_obj.match.mean_iou,
            tp=base_obj.match.tp,
            fp=base_obj.match.fp,
            fn=base_obj.match.fn,
            elapsed_ms=base_ms,
        )
    ]

    best_params = dict(fixed)
    best_loss = base_loss
    best_score = base_score

    # Candidate generation
    candidates: list[dict[str, Any]] = []
    if method == "grid" and layer == "l3":
        # Small grid on min_measure_width only for MVP determinism
        for w in np.linspace(16, 64, num=min(max_trials, 13)):
            p = dict(fixed)
            p["min_measure_width"] = float(round(w, 2))
            candidates.append(p)
    else:
        for _ in range(max(0, max_trials - 1)):
            candidates.append(_sample_params(space, rng, fixed=fixed))

    for i, cand in enumerate(candidates, start=1):
        if time.perf_counter() - started > max_seconds:
            warnings.append(
                f"tune_layer: stopped by max_seconds={max_seconds} at trial {i}"
            )
            break
        if i >= max_trials:
            break
        loss, score, obj_r, ms = eval_params(cand)
        trials.append(
            TrialRecord(
                trial=i,
                params=dict(cand),
                loss=loss,
                score=score,
                mean_iou=obj_r.match.mean_iou,
                tp=obj_r.match.tp,
                fp=obj_r.match.fp,
                fn=obj_r.match.fn,
                elapsed_ms=ms,
            )
        )
        if loss < best_loss - 1e-12:
            best_loss = loss
            best_score = score
            best_params = dict(cand)

    if apply_best:
        set_layer_params(layer, best_params, merge=False)
        warnings.append(f"tune_layer: applied best params to runtime {layer}")

    result = TuneLayerResult(
        layer=layer,
        best_params=best_params,
        best_loss=best_loss,
        best_score=best_score,
        baseline_loss=base_loss,
        baseline_score=base_score,
        improved=best_loss <= base_loss + 1e-12,
        trials=trials,
        n_trials=len(trials),
        seed=seed,
        elapsed_sec=time.perf_counter() - started,
        warnings=warnings,
        objective={
            "w_iou": w_iou,
            "w_cnt": w_cnt,
            "w_fn": w_fn,
            "w_fp": w_fp,
            "iou_threshold": iou_thr,
        },
    )

    if log_path:
        path = Path(log_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            for t in trials:
                f.write(json.dumps(t.as_dict(), ensure_ascii=False) + "\n")
        summary_path = path.with_suffix(".summary.json")
        summary_path.write_text(
            json.dumps(result.as_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    return result


def write_best_params_yaml(
    best: dict[str, Any],
    *,
    layer: str,
    path: Path | str,
) -> None:
    """Write best params merged into default file structure."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    defaults = load_default_params_file()
    defaults[layer.lower()] = {
        **(defaults.get(layer.lower()) or {}),
        **best,
    }
    try:
        import yaml

        path.write_text(
            yaml.safe_dump(defaults, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
    except Exception:
        path.write_text(json.dumps(defaults, ensure_ascii=False, indent=2), encoding="utf-8")
