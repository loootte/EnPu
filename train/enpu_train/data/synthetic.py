"""Procedural layout samples for toy training when real data is scarce (#95)."""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw


def make_synthetic_layout_sample(
    out_dir: str | Path,
    *,
    sample_id: str,
    width: int = 640,
    height: int = 800,
    n_systems: int | None = None,
    measures_per_row: int | None = None,
    seed: int | None = None,
) -> dict[str, Any]:
    """Draw a simple jianpu-like page and write layout.json + image.png.

    Geometry is exact so it can act as GT for L2 boxes and L3 interior splits.
    """
    rng = random.Random(seed)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    n_systems = n_systems if n_systems is not None else rng.randint(3, 6)
    measures_per_row = (
        measures_per_row if measures_per_row is not None else rng.randint(3, 5)
    )
    n_splits = measures_per_row - 1

    img = Image.new("RGB", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(img)

    # Title band
    title_box = {
        "x1": width * 0.2,
        "y1": height * 0.04,
        "x2": width * 0.8,
        "y2": height * 0.09,
    }
    draw.rectangle(
        [title_box["x1"], title_box["y1"], title_box["x2"], title_box["y2"]],
        fill=(30, 30, 30),
    )

    score_y0 = height * 0.12
    score_y1 = height * 0.92
    score_region = {"x1": 0.0, "y1": score_y0, "x2": float(width), "y2": score_y1}

    margin_x = width * 0.06
    usable_w = width - 2 * margin_x
    band_h = min(70.0, (score_y1 - score_y0) / (n_systems + 1) * 0.7)
    gap = (score_y1 - score_y0 - n_systems * band_h) / (n_systems + 1)

    systems: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []

    y = score_y0 + gap
    for si in range(n_systems):
        y1 = y
        y2 = y + band_h
        x1, x2 = margin_x, width - margin_x
        # staff ink
        draw.rectangle([x1, y1, x2, y2], fill=(40, 40, 40))
        # digit-like blobs
        for k in range(measures_per_row * 3):
            cx = x1 + (k + 0.5) * usable_w / (measures_per_row * 3)
            draw.rectangle(
                [cx - 4, y1 + band_h * 0.25, cx + 4, y1 + band_h * 0.75],
                fill=(10, 10, 10),
            )

        # interior split lines (white gaps as "barlines")
        splits = []
        for j in range(n_splits):
            # equal measure widths
            sx = x1 + (j + 1) * usable_w / measures_per_row
            draw.line([(sx, y1), (sx, y2)], fill=(255, 255, 255), width=3)
            splits.append(
                {
                    "id": f"s{si}-{j}",
                    "x": float(sx),
                    "y1": float(y1),
                    "y2": float(y2),
                    "source": "synth",
                }
            )

        edges = [x1] + [s["x"] for s in splits] + [x2]
        measures = []
        for mi in range(len(edges) - 1):
            measures.append(
                {
                    "id": f"l3-m{si}-{mi}",
                    "label": f"m{mi + 1}",
                    "box": {
                        "x1": float(edges[mi]),
                        "y1": float(y1),
                        "x2": float(edges[mi + 1]),
                        "y2": float(y2),
                    },
                }
            )

        sid = f"l2-sys{si}"
        systems.append(
            {
                "id": sid,
                "index": si,
                "bbox": {
                    "x1": float(x1),
                    "y1": float(y1),
                    "x2": float(x2),
                    "y2": float(y2),
                },
                "kind": "system",
            }
        )
        rows.append(
            {
                "system_id": sid,
                "system_index": si,
                "splits": splits,
                "measures": measures,
            }
        )
        y = y2 + gap

    layout: dict[str, Any] = {
        "layout_schema_version": "0.1",
        "kind": "enpu-layout-gt",
        "id": sample_id,
        "image": {"path": "image.png", "width": width, "height": height},
        "meta": {"title": sample_id, "source": "synthetic"},
        "l1": {
            "score_region": score_region,
            "title": title_box,
            "regions": [
                {"role": "title", "box": title_box},
                {"role": "score", "box": score_region},
            ],
        },
        "l2": {"systems": systems},
        "l3": {"rows": rows},
        "source": {"type": "synthetic", "seed": seed},
    }

    img_path = out_dir / "image.png"
    img.save(img_path)
    (out_dir / "layout.json").write_text(
        json.dumps(layout, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return layout


def generate_synthetic_set(
    root: str | Path,
    n: int = 8,
    *,
    seed: int = 0,
) -> list[Path]:
    """Write ``root/S001`` … samples; return directories."""
    root = Path(root)
    paths: list[Path] = []
    rng = random.Random(seed)
    for i in range(n):
        sid = f"S{i + 1:03d}_synth"
        d = root / sid
        make_synthetic_layout_sample(
            d,
            sample_id=sid,
            width=rng.choice([512, 640, 720]),
            height=rng.choice([640, 800, 900]),
            seed=seed + i * 17,
        )
        paths.append(d)
    return paths
