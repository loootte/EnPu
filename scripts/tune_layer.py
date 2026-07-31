#!/usr/bin/env python3
"""Single-layer auto-tune CLI (#89).

Example:
  core\\.venv\\Scripts\\python.exe scripts\\tune_layer.py ^
    --image samples/eval/images/E01_print_c_4_4_grace_demo.png ^
    --gt samples/eval/gt/E01_print_c_4_4_grace_demo.json ^
    --layer l3 --trials 20 --seed 42 --method random --apply
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "core"
sys.path.insert(0, str(CORE))


def main() -> int:
    ap = argparse.ArgumentParser(description="Tune one structure layer (#89)")
    ap.add_argument("--image", type=Path, required=True)
    ap.add_argument("--gt", type=Path, required=True, help="GT JSON (Score and/or layers)")
    ap.add_argument("--layer", default="l3", choices=["l3", "l4"])
    ap.add_argument("--trials", type=int, default=40)
    ap.add_argument("--max-seconds", type=float, default=120.0)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--method", default="random", choices=["random", "grid"])
    ap.add_argument("--apply", action="store_true", help="Apply best to runtime store")
    ap.add_argument("--out", type=Path, default=None, help="Write trials.jsonl + summary")
    ap.add_argument("--write-yaml", type=Path, default=None, help="Write best into YAML")
    args = ap.parse_args()

    import cv2
    from app.evaluation.gt_loader import load_ground_truth
    from app.tuning.search import tune_layer, write_best_params_yaml

    if not args.image.is_file():
        print(f"image missing: {args.image}", file=sys.stderr)
        return 2
    if not args.gt.is_file():
        print(f"gt missing: {args.gt}", file=sys.stderr)
        return 2

    data = args.image.read_bytes()
    # decode via opencv
    import numpy as np

    arr = np.frombuffer(data, dtype=np.uint8)
    image_bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if image_bgr is None:
        print("failed to decode image", file=sys.stderr)
        return 2

    gt = load_ground_truth(args.gt)
    log_path = args.out
    result = tune_layer(
        image_bgr,
        gt=gt,
        layer=args.layer,
        max_trials=args.trials,
        max_seconds=args.max_seconds,
        seed=args.seed,
        method=args.method,
        apply_best=args.apply,
        log_path=log_path,
    )
    summary = {
        "layer": result.layer,
        "baseline_loss": result.baseline_loss,
        "best_loss": result.best_loss,
        "best_score": result.best_score,
        "improved": result.improved,
        "best_params": result.best_params,
        "n_trials": result.n_trials,
        "elapsed_sec": result.elapsed_sec,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if args.write_yaml:
        write_best_params_yaml(
            result.best_params, layer=args.layer, path=args.write_yaml
        )
        print(f"wrote {args.write_yaml}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
