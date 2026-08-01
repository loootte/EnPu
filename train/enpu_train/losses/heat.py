"""Heatmap losses for L2/L3 1D heads."""

from __future__ import annotations

import torch
import torch.nn.functional as F


def heatmap_bce_loss(
    logits: torch.Tensor,
    target: torch.Tensor,
    *,
    pos_weight: float = 3.0,
) -> torch.Tensor:
    """BCE with logits; upweight positives (sparse peaks)."""
    if logits.numel() == 0:
        return logits.sum() * 0.0
    # target in [0,1]
    pw = torch.tensor(pos_weight, device=logits.device, dtype=logits.dtype)
    return F.binary_cross_entropy_with_logits(logits, target, pos_weight=pw)
