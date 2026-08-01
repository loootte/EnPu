"""Visualize layout GT / predictions: page boxes + L3 vertical lines."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw


def draw_layout_overlay(
    image: Image.Image | np.ndarray | str | Path,
    layout: dict[str, Any],
    *,
    out_path: str | Path | None = None,
) -> Image.Image:
    if isinstance(image, (str, Path)):
        img = Image.open(image).convert("RGB")
    elif isinstance(image, np.ndarray):
        img = Image.fromarray(image.astype(np.uint8)).convert("RGB")
    else:
        img = image.convert("RGB")
    draw = ImageDraw.Draw(img)

    l1 = layout.get("l1") or {}
    for key, color in (
        ("score_region", (0, 180, 0)),
        ("title", (0, 0, 220)),
        ("key_time", (180, 0, 180)),
    ):
        box = l1.get(key)
        if box:
            draw.rectangle(
                [box["x1"], box["y1"], box["x2"], box["y2"]],
                outline=color,
                width=3,
            )

    for s in (layout.get("l2") or {}).get("systems") or []:
        b = s.get("bbox") or s.get("box") or {}
        draw.rectangle(
            [b["x1"], b["y1"], b["x2"], b["y2"]],
            outline=(220, 120, 0),
            width=2,
        )

    for row in (layout.get("l3") or {}).get("rows") or []:
        for sp in row.get("splits") or []:
            x = float(sp["x"] if isinstance(sp, dict) else sp)
            y1 = float(sp.get("y1", 0) if isinstance(sp, dict) else 0)
            y2 = float(sp.get("y2", img.height) if isinstance(sp, dict) else img.height)
            if y2 <= y1:
                y1, y2 = 0, img.height
            draw.line([(x, y1), (x, y2)], fill=(220, 30, 30), width=2)

    if out_path is not None:
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        img.save(out_path)
    return img
