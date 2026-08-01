#!/usr/bin/env python3
"""Draw L1/L2 boxes + L3 splits on a layout sample (#95)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from enpu_train.viz import draw_layout_overlay


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("sample_dir", type=Path, help="dir with layout.json + image")
    ap.add_argument("-o", "--out", type=Path, default=None)
    args = ap.parse_args()
    layout = json.loads((args.sample_dir / "layout.json").read_text(encoding="utf-8"))
    img_name = (layout.get("image") or {}).get("path") or "image.png"
    out = args.out or (args.sample_dir / "overlay_preview.png")
    draw_layout_overlay(args.sample_dir / img_name, layout, out_path=out)
    print("wrote", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
