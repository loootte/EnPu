#!/usr/bin/env python3
"""Export EnPu .enpu.json project → L1–L3 layout training sample (#93).

Examples::

    # From a real desktop project (embeds image from source_image_data_url)
    python scripts/export_layout_gt.py ^
      --project "C:\\Users\\...\\song.enpu.json" ^
      --out samples/layout/L001_zuozai

    # Validate an existing layout.json only
    python scripts/export_layout_gt.py --validate-only samples/layout/L001/layout.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "core"
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

from app.layout_gt.export import export_project_to_sample_dir  # noqa: E402
from app.layout_gt.validate import validate_layout_sample  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Export / validate L1–L3 layout GT from EnPu projects (#93)"
    )
    ap.add_argument(
        "--project",
        "-p",
        type=Path,
        help="Path to .enpu.json project",
    )
    ap.add_argument(
        "--out",
        "-o",
        type=Path,
        help="Output sample directory (writes layout.json + image.*)",
    )
    ap.add_argument(
        "--sample-id",
        type=str,
        default=None,
        help="Optional sample id field",
    )
    ap.add_argument(
        "--no-image",
        action="store_true",
        help="Do not extract embedded image",
    )
    ap.add_argument(
        "--no-measures",
        action="store_true",
        help="Omit derived measures from layout.json (splits only)",
    )
    ap.add_argument(
        "--validate-only",
        type=Path,
        default=None,
        help="Only validate an existing layout.json",
    )
    ap.add_argument(
        "--skip-validate",
        action="store_true",
        help="Write even if validation fails (not recommended)",
    )
    args = ap.parse_args(argv)

    if args.validate_only:
        data = json.loads(args.validate_only.read_text(encoding="utf-8"))
        r = validate_layout_sample(data)
        print(f"ok={r.ok}")
        for e in r.errors:
            print(f"ERROR: {e}")
        for w in r.warnings:
            print(f"WARN: {w}")
        return 0 if r.ok else 2

    if not args.project or not args.out:
        ap.error("--project and --out are required (or use --validate-only)")

    if not args.project.is_file():
        print(f"project not found: {args.project}", file=sys.stderr)
        return 1

    try:
        sample = export_project_to_sample_dir(
            args.project,
            args.out,
            sample_id=args.sample_id,
            copy_image=not args.no_image,
            validate=not args.skip_validate,
            include_derived_measures=not args.no_measures,
        )
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2

    n_sys = len((sample.get("l2") or {}).get("systems") or [])
    rows = (sample.get("l3") or {}).get("rows") or []
    n_splits = sum(len(r.get("splits") or []) for r in rows)
    print(f"wrote {args.out / 'layout.json'}")
    print(
        f"  id={sample.get('id')!r} systems={n_sys} "
        f"split_lines={n_splits} image={sample.get('image')}"
    )
    warns = (sample.get("export") or {}).get("validation_warnings") or []
    for w in warns:
        print(f"  WARN: {w}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
