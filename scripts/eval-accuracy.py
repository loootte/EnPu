#!/usr/bin/env python3
"""Eval harness scaffold for issue #29.

Modes:
  --manifest-only   Validate manifest + GT JSON (no OCR)
  --gt-stats        Print pitch-sequence / measure stats for ready entries

Full OCR comparison (call /v1/recognize) lands in a follow-up commit once
manual M01–M05 are filled and paddle/mock baselines are decided.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVAL = ROOT / "samples" / "eval"
MANIFEST = EVAL / "manifest.json"
MANIFEST_LOCAL = EVAL / "manifest.local.json"


def load_manifest() -> dict:
    # Prefer local full import (includes private M01–M05) when present
    path = MANIFEST_LOCAL if MANIFEST_LOCAL.is_file() else MANIFEST
    if not path.is_file():
        raise SystemExit(f"manifest missing: {MANIFEST} (run generate-eval-samples.py)")
    print(f"using {path.name}")
    return json.loads(path.read_text(encoding="utf-8"))


def validate_score_dict(data: dict, path: Path) -> list[str]:
    errs: list[str] = []
    if data.get("schema_version") != "0.1":
        errs.append(f"{path}: schema_version must be '0.1'")
    for k in ("key", "time_signature", "parts"):
        if k not in data:
            errs.append(f"{path}: missing {k}")
    parts = data.get("parts") or []
    if not parts:
        errs.append(f"{path}: parts empty")
    else:
        measures = parts[0].get("measures") or []
        if not measures:
            errs.append(f"{path}: no measures")
    return errs


def cmd_manifest_only() -> int:
    man = load_manifest()
    entries = man.get("entries") or []
    ready = [e for e in entries if e.get("status") == "ready"]
    pending = [e for e in entries if e.get("status") != "ready"]
    print(f"manifest: {MANIFEST}")
    print(f"entries: {len(entries)}  ready={len(ready)}  pending={len(pending)}")

    errors: list[str] = []
    for e in ready:
        img = EVAL / e["image"]
        gt = EVAL / e["gt"]
        if not img.is_file():
            errors.append(f"missing image: {img}")
        if not gt.is_file():
            errors.append(f"missing gt: {gt}")
            continue
        try:
            data = json.loads(gt.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append(f"bad json {gt}: {exc}")
            continue
        errors.extend(validate_score_dict(data, gt))
        # optional pydantic if core on path
        try:
            sys.path.insert(0, str(ROOT / "core"))
            from app.schemas.score import Score  # type: ignore

            Score.model_validate(data)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"Score validate fail {gt.name}: {exc}")

    if errors:
        print("FAIL:")
        for err in errors:
            print(" -", err)
        return 1
    print("OK: all ready entries have valid image + Score GT")
    return 0


def cmd_gt_stats() -> int:
    man = load_manifest()
    print(f"{'id':<36} {'subset':<12} {'bars':>4} {'pitches':>7} key  time")
    for e in man.get("entries") or []:
        if e.get("status") != "ready":
            print(f"{e['id']:<36} {e.get('subset','?'):<12}  — pending")
            continue
        gt_path = EVAL / e["gt"]
        data = json.loads(gt_path.read_text(encoding="utf-8"))
        extra = (data.get("extra") or {}).get("eval") or {}
        seq = extra.get("pitch_sequence") or e.get("pitch_sequence") or []
        bars = extra.get("measure_count") or e.get("measure_count")
        print(
            f"{e['id']:<36} {e.get('subset','?'):<12} {bars!s:>4} {len(seq):>7} "
            f"{data.get('key','?'):<3} {data.get('time_signature','?')}"
        )
    return 0


def main() -> None:
    p = argparse.ArgumentParser(description="EnPu eval harness (#29)")
    p.add_argument(
        "--manifest-only",
        action="store_true",
        help="Validate manifest + GT only",
    )
    p.add_argument(
        "--gt-stats",
        action="store_true",
        help="Print GT pitch/measure stats",
    )
    args = p.parse_args()
    if args.gt_stats:
        raise SystemExit(cmd_gt_stats())
    # default: manifest-only
    raise SystemExit(cmd_manifest_only())


if __name__ == "__main__":
    main()
