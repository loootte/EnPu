"""Decode heatmaps → system bands + interior split xs (#104)."""

from __future__ import annotations

from typing import Any

import numpy as np


def decode_peaks(
    heat: np.ndarray,
    *,
    min_prominence: float = 0.25,
    min_gap: int = 4,
) -> list[int]:
    h = np.asarray(heat, dtype=np.float32).reshape(-1)
    peaks: list[tuple[float, int]] = []
    for i in range(1, len(h) - 1):
        if h[i] >= min_prominence and h[i] >= h[i - 1] and h[i] >= h[i + 1]:
            peaks.append((float(h[i]), i))
    peaks.sort(reverse=True)
    chosen: list[int] = []
    for _, i in peaks:
        if all(abs(i - j) >= min_gap for j in chosen):
            chosen.append(i)
    return sorted(chosen)


def l2_heat_to_system_boxes(
    heat: np.ndarray,
    *,
    orig_h: int,
    orig_w: int,
    page_h: int,
    page_w: int,
    band_frac: float = 0.09,
    min_prominence: float = 0.22,
    x_margin_frac: float = 0.02,
) -> list[dict[str, float]]:
    """Map L2 y-heat peaks to full-width-ish horizontal system bboxes (orig pixels)."""
    heat = np.asarray(heat, dtype=np.float32).reshape(-1)
    gap = max(3, len(heat) // 40)
    peaks = decode_peaks(heat, min_prominence=min_prominence, min_gap=gap)
    if not peaks:
        # fallback: single mid band
        cy = orig_h * 0.5
        half = orig_h * band_frac * 0.5
        xm = orig_w * x_margin_frac
        return [
            {
                "x1": xm,
                "y1": max(0.0, cy - half),
                "x2": float(orig_w) - xm,
                "y2": min(float(orig_h), cy + half),
            }
        ]

    # estimate band height from peak spacing
    if len(peaks) >= 2:
        spacings = [
            (peaks[i + 1] - peaks[i]) / max(1, len(heat) - 1) * orig_h
            for i in range(len(peaks) - 1)
        ]
        half = 0.35 * float(np.median(spacings))
    else:
        half = orig_h * band_frac * 0.5
    half = max(half, orig_h * 0.03)
    half = min(half, orig_h * 0.12)

    xm = orig_w * x_margin_frac
    boxes: list[dict[str, float]] = []
    for p in peaks:
        cy = p / max(1, len(heat) - 1) * orig_h
        boxes.append(
            {
                "x1": float(xm),
                "y1": float(max(0.0, cy - half)),
                "x2": float(orig_w - xm),
                "y2": float(min(float(orig_h), cy + half)),
            }
        )
    # sort top→bottom, drop heavy overlaps
    boxes.sort(key=lambda b: b["y1"])
    cleaned: list[dict[str, float]] = []
    for b in boxes:
        if cleaned and b["y1"] < cleaned[-1]["y2"] - 0.3 * (cleaned[-1]["y2"] - cleaned[-1]["y1"]):
            # merge into previous by expanding
            cleaned[-1]["y2"] = max(cleaned[-1]["y2"], b["y2"])
            cleaned[-1]["y1"] = min(cleaned[-1]["y1"], b["y1"])
        else:
            cleaned.append(b)
    return cleaned


def l3_heat_to_split_xs(
    heat: np.ndarray,
    *,
    x_left: float,
    x_right: float,
    min_prominence: float = 0.28,
) -> list[float]:
    """Map L3 x-heat peaks to full-image interior split x positions."""
    heat = np.asarray(heat, dtype=np.float32).reshape(-1)
    gap = max(3, len(heat) // 32)
    peaks = decode_peaks(heat, min_prominence=min_prominence, min_gap=gap)
    width = max(1e-3, x_right - x_left)
    xs: list[float] = []
    for p in peaks:
        rel = p / max(1, len(heat) - 1)
        x = x_left + rel * width
        if x_left + 1.0 < x < x_right - 1.0:
            xs.append(float(x))
    return sorted(xs)


def bgr_to_model_tensor(
    bgr: Any,
    *,
    out_h: int,
    out_w: int,
) -> Any:
    """Resize BGR uint8 → float CHW tensor in [0,1] RGB order (torch)."""
    import cv2
    import torch

    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    resized = cv2.resize(rgb, (out_w, out_h), interpolation=cv2.INTER_LINEAR)
    t = torch.from_numpy(np.ascontiguousarray(resized)).float() / 255.0
    return t.permute(2, 0, 1).unsqueeze(0)  # 1,3,H,W
