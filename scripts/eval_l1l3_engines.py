#!/usr/bin/env python3
"""Compare structure L1–L3 rule vs learned engines on layout samples (#104).

Example::

    $env:PYTHONPATH = ".\\core"
    $env:ENPU_L1L3_WEIGHTS = ".\\train\\runs\\mvp_l2_l3\\best.pt"
    python scripts\\eval_l1l3_engines.py --data samples\\layout --out reports\\l1l3_engines.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "core"
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

from app.config import Settings, clear_settings_cache  # noqa: E402
from app.pipeline.structure.pipeline import run_structure_recognize  # noqa: E402


def _split_metrics(gt_xs: list[float], pred_xs: list[float], max_dist: float = 12.0) -> dict:
    gt = sorted(float(x) for x in gt_xs)
    pred = sorted(float(x) for x in pred_xs)
    if not gt and not pred:
        return {
            "split_count_mae": 0.0,
            "split_count_exact": 1.0,
            "split_mean_abs_x_error": 0.0,
            "n_gt": 0,
            "n_pred": 0,
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
        "n_gt": len(gt),
        "n_pred": len(pred),
        "tp": tp,
        "fp": len(pred) - tp,
        "fn": len(gt) - tp,
    }


def _gt_splits(layout: dict) -> list[float]:
    xs: list[float] = []
    for row in (layout.get("l3") or {}).get("rows") or []:
        for sp in row.get("splits") or []:
            xs.append(float(sp["x"] if isinstance(sp, dict) else sp))
    return xs


def _pred_splits(structure) -> list[float]:
    if structure is None:
        return []
    bl = structure.barlines if hasattr(structure, "barlines") else structure.get("barlines")
    out = []
    for b in bl or []:
        if isinstance(b, dict) and b.get("x") is not None:
            out.append(float(b["x"]))
    return out


def _pred_n_systems(structure) -> int:
    if structure is None:
        return 0
    items = structure.items if hasattr(structure, "items") else structure.get("items") or []
    return sum(1 for it in items if (getattr(it, "layer", None) or it.get("layer")) == "L2")


def run_engine(data: bytes, engine: str, weights: str) -> dict:
    clear_settings_cache()
    os.environ["ENPU_PIPELINE_MODE"] = "structure"
    os.environ["ENPU_RECOGNIZE_ENGINE"] = os.environ.get("ENPU_RECOGNIZE_ENGINE", "mock")
    os.environ["ENPU_STRUCTURE_L1L3_ENGINE"] = engine
    os.environ["ENPU_L1L3_FALLBACK"] = "rule"
    if weights:
        os.environ["ENPU_L1L3_WEIGHTS"] = weights
    clear_settings_cache()
    settings = Settings()
    resp = run_structure_recognize(data, settings=settings, filename="eval.png")
    return {
        "ok": resp.ok,
        "warnings": list(resp.meta.parse_warnings or [])[:30],
        "n_systems": _pred_n_systems(resp.structure),
        "splits": _pred_splits(resp.structure),
        "engine_used": engine,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="rule vs learned L1–L3 eval (#104)")
    ap.add_argument("--data", type=Path, default=ROOT / "samples" / "layout")
    ap.add_argument(
        "--weights",
        type=Path,
        default=ROOT / "train" / "runs" / "mvp_l2_l3" / "best.pt",
    )
    ap.add_argument("--out", type=Path, default=ROOT / "reports" / "l1l3_engines.json")
    ap.add_argument("--limit", type=int, default=20)
    args = ap.parse_args()

    samples = sorted({p.parent for p in args.data.rglob("layout.json")})[: args.limit]
    if not samples:
        print("no layout samples under", args.data)
        return 1

    weights = str(args.weights) if args.weights.is_file() else ""
    if not weights:
        print("WARNING: weights missing; learned will fallback to rule:", args.weights)

    per_sample = []
    agg = {
        "rule": {"count_mae": [], "exact": [], "x_err": []},
        "learned": {"count_mae": [], "exact": [], "x_err": []},
    }

    for sdir in samples:
        layout = json.loads((sdir / "layout.json").read_text(encoding="utf-8"))
        img_name = (layout.get("image") or {}).get("path") or "image.png"
        img_path = sdir / img_name
        if not img_path.is_file():
            continue
        data = img_path.read_bytes()
        gt_xs = _gt_splits(layout)
        row = {"id": sdir.name, "n_gt_splits": len(gt_xs), "engines": {}}
        for eng in ("rule", "learned"):
            try:
                pred = run_engine(data, eng, weights)
                m = _split_metrics(gt_xs, pred["splits"])
                row["engines"][eng] = {
                    "n_systems": pred["n_systems"],
                    "n_pred_splits": len(pred["splits"]),
                    **m,
                    "warnings_head": (pred["warnings"] or [])[:5],
                }
                agg[eng]["count_mae"].append(m["split_count_mae"])
                agg[eng]["exact"].append(m["split_count_exact"])
                if m["split_mean_abs_x_error"] == m["split_mean_abs_x_error"]:
                    agg[eng]["x_err"].append(m["split_mean_abs_x_error"])
            except Exception as e:
                row["engines"][eng] = {"error": str(e)}
        per_sample.append(row)
        print(
            sdir.name,
            "rule_mae=",
            row["engines"].get("rule", {}).get("split_count_mae"),
            "learned_mae=",
            row["engines"].get("learned", {}).get("split_count_mae"),
        )

    def mean(xs: list[float]) -> float:
        return float(sum(xs) / len(xs)) if xs else float("nan")

    summary = {
        eng: {
            "mean_split_count_mae": mean(agg[eng]["count_mae"]),
            "mean_split_count_exact": mean(agg[eng]["exact"]),
            "mean_abs_x_error": mean(agg[eng]["x_err"]),
            "n": len(agg[eng]["count_mae"]),
        }
        for eng in ("rule", "learned")
    }
    report = {
        "weights": weights,
        "data": str(args.data),
        "summary": summary,
        "samples": per_sample,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md = args.out.with_suffix(".md")
    md.write_text(
        "# rule vs learned L1–L3 (#104)\n\n"
        f"- weights: `{weights}`\n"
        f"- data: `{args.data}`\n\n"
        "| engine | count_mae | exact | mean |x| err | n |\n"
        "|--------|-----------|-------|----------------|---|\n"
        + "\n".join(
            f"| {e} | {summary[e]['mean_split_count_mae']:.3f} | "
            f"{summary[e]['mean_split_count_exact']:.3f} | "
            f"{summary[e]['mean_abs_x_error']:.3f} | {summary[e]['n']} |"
            for e in ("rule", "learned")
        )
        + "\n",
        encoding="utf-8",
    )
    print("wrote", args.out, "and", md)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
