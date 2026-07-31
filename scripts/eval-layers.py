#!/usr/bin/env python3
"""Layered metrics eval harness (#86).

Examples:
  # GT-only sanity (no OCR)
  python scripts/eval-layers.py --manifest-only

  # Mock recognize batch (fast)
  python scripts/eval-layers.py --run --engine mock --limit 3

  # Structure pipeline + paddle (slow)
  python scripts/eval-layers.py --run --engine paddleocr --subset print_clear

  # Write JSON + Markdown report
  python scripts/eval-layers.py --run --engine mock --out reports/layer-metrics.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "core"
EVAL = ROOT / "samples" / "eval"
MANIFEST = EVAL / "manifest.json"
MANIFEST_LOCAL = EVAL / "manifest.local.json"

sys.path.insert(0, str(CORE))


def main() -> int:
    ap = argparse.ArgumentParser(description="EnPu layered metrics (#86)")
    ap.add_argument("--manifest-only", action="store_true", help="Validate manifest only")
    ap.add_argument("--run", action="store_true", help="Run recognition + metrics")
    ap.add_argument("--engine", default="mock", choices=["mock", "paddleocr"])
    ap.add_argument("--subset", default=None)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--out", type=Path, default=None, help="Write JSON report")
    ap.add_argument("--md", type=Path, default=None, help="Write Markdown summary")
    ap.add_argument("--iou", type=float, default=0.5)
    args = ap.parse_args()

    man_path = MANIFEST_LOCAL if MANIFEST_LOCAL.is_file() else MANIFEST
    if not man_path.is_file():
        print(f"manifest missing: {man_path}", file=sys.stderr)
        return 2

    if args.manifest_only and not args.run:
        data = json.loads(man_path.read_text(encoding="utf-8"))
        n = len(data.get("entries") or [])
        print(f"manifest OK: {man_path.name} entries={n}")
        return 0

    from app.evaluation.batch import evaluate_manifest, write_report_markdown

    recognize_fn = None
    if args.run:
        os.environ.setdefault("ENPU_RECOGNIZE_ENGINE", args.engine)
        os.environ.setdefault("ENPU_PIPELINE_MODE", "structure")
        from app.config import Settings, clear_settings_cache
        from app.pipeline.runner import run_recognize

        clear_settings_cache()
        settings = Settings(recognize_engine=args.engine, pipeline_mode="structure")

        def recognize_fn(image_path: Path) -> dict:  # noqa: F811
            resp = run_recognize(
                image_path.read_bytes(),
                settings=settings,
                filename=image_path.name,
            )
            return {
                "score": resp.score.model_dump(mode="json") if resp.score else None,
                "structure": (
                    resp.structure.model_dump(mode="json") if resp.structure else None
                ),
            }

    report = evaluate_manifest(
        man_path,
        eval_root=man_path.parent,
        recognize_fn=recognize_fn,
        subset=args.subset,
        limit=args.limit,
        iou_threshold=args.iou,
        include_errors=False,
    )

    print(json.dumps({"mean_f1": report["mean_f1"], "n_samples": report["n_samples"]}, indent=2))
    for sid, f1s in [
        (
            s.get("sample_id"),
            {k: (s.get("layers") or {}).get(k, {}).get("f1") for k in ("L3", "L4", "L5")},
        )
        for s in (report.get("samples") or [])[:10]
    ]:
        if isinstance(f1s, dict):
            print(f"  {sid}: L3={f1s.get('L3')} L4={f1s.get('L4')} L5={f1s.get('L5')}")

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"wrote {args.out}")
    if args.md:
        args.md.parent.mkdir(parents=True, exist_ok=True)
        write_report_markdown(report, args.md)
        print(f"wrote {args.md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
