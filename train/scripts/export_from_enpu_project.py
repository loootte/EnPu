#!/usr/bin/env python3
"""Thin wrapper: export .enpu.json → layout sample via core layout_gt (#93/#95)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CORE = REPO / "core"
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

from app.layout_gt.export import export_project_to_sample_dir  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", "-p", type=Path, required=True)
    ap.add_argument("--out", "-o", type=Path, required=True)
    ap.add_argument("--sample-id", type=str, default=None)
    args = ap.parse_args()
    sample = export_project_to_sample_dir(
        args.project,
        args.out,
        sample_id=args.sample_id,
    )
    print("exported", args.out / "layout.json", "id=", sample.get("id"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
