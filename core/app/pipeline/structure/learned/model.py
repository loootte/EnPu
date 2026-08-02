"""Minimal LayoutNet (L2 page y-heat + L3 row x-heat) for core inference (#104).

Architecture mirrors ``train/enpu_train/models/layout_net.py`` so exported
weights load without importing the train package.

Torch is imported lazily so CI (requirements-ci, no torch) can import sibling
modules (adapter/postprocess) without failing collection.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class LayoutNetConfig:
    l2_heat_len: int = 128
    l3_heat_len: int = 128
    base_channels: int = 16
    tasks: tuple[str, ...] = ("l2", "l3")
    page_h: int = 384
    page_w: int = 512
    row_h: int = 64
    row_w: int = 256


def _torch_nn():
    try:
        import torch
        import torch.nn as nn
        import torch.nn.functional as F
    except ImportError as e:
        raise ImportError(
            "torch is required for learned L1–L3 weights. "
            "Install with: pip install torch  (optional; default engine is rule)"
        ) from e
    return torch, nn, F


def build_layout_net(cfg: LayoutNetConfig | None = None) -> Any:
    """Construct LayoutNet (requires torch)."""
    torch, nn, F = _torch_nn()
    cfg = cfg or LayoutNetConfig()

    class ConvBNReLU(nn.Module):
        def __init__(self, c_in: int, c_out: int, k: int = 3, s: int = 1) -> None:
            super().__init__()
            p = k // 2
            self.net = nn.Sequential(
                nn.Conv2d(c_in, c_out, k, stride=s, padding=p, bias=False),
                nn.BatchNorm2d(c_out),
                nn.ReLU(inplace=True),
            )

        def forward(self, x):  # type: ignore[no-untyped-def]
            return self.net(x)

    class PageL2Head(nn.Module):
        def __init__(self, heat_len: int = 128, base: int = 16) -> None:
            super().__init__()
            self.heat_len = heat_len
            self.enc = nn.Sequential(
                ConvBNReLU(3, base, 3, 2),
                ConvBNReLU(base, base * 2, 3, 2),
                ConvBNReLU(base * 2, base * 4, 3, 2),
                ConvBNReLU(base * 4, base * 4, 3, 2),
            )
            self.head = nn.Sequential(
                nn.Conv1d(base * 4, base * 2, 3, padding=1),
                nn.ReLU(inplace=True),
                nn.Conv1d(base * 2, 1, 1),
            )

        def forward(self, page):  # type: ignore[no-untyped-def]
            f = self.enc(page)
            f = f.mean(dim=3)
            f = F.interpolate(
                f.unsqueeze(-1),
                size=(self.heat_len, 1),
                mode="bilinear",
                align_corners=False,
            ).squeeze(-1)
            return self.head(f).squeeze(1)

    class RowL3Head(nn.Module):
        def __init__(self, heat_len: int = 128, base: int = 16) -> None:
            super().__init__()
            self.heat_len = heat_len
            self.enc = nn.Sequential(
                ConvBNReLU(3, base, 3, 2),
                ConvBNReLU(base, base * 2, 3, 2),
                ConvBNReLU(base * 2, base * 4, 3, 2),
                ConvBNReLU(base * 4, base * 4, 3, 2),
            )
            self.head = nn.Sequential(
                nn.Conv1d(base * 4, base * 2, 3, padding=1),
                nn.ReLU(inplace=True),
                nn.Conv1d(base * 2, 1, 1),
            )

        def forward(self, rows):  # type: ignore[no-untyped-def]
            if rows.numel() == 0:
                return rows.new_zeros((0, self.heat_len))
            f = self.enc(rows)
            f = f.mean(dim=2)
            f = F.interpolate(
                f.unsqueeze(2),
                size=(1, self.heat_len),
                mode="bilinear",
                align_corners=False,
            ).squeeze(2)
            return self.head(f).squeeze(1)

    class LayoutNet(nn.Module):
        def __init__(self, net_cfg: LayoutNetConfig) -> None:
            super().__init__()
            self.cfg = net_cfg
            self.l2 = PageL2Head(net_cfg.l2_heat_len, net_cfg.base_channels)
            self.l3 = RowL3Head(net_cfg.l3_heat_len, net_cfg.base_channels)

        def forward(self, page=None, rows=None):  # type: ignore[no-untyped-def]
            out = {}
            if page is not None and "l2" in self.cfg.tasks:
                out["l2_logits"] = self.l2(page)
            if rows is not None and "l3" in self.cfg.tasks:
                out["l3_logits"] = self.l3(rows)
            return out

    return LayoutNet(cfg)


# Back-compat name used by loader
class LayoutNet:  # type: ignore[no-redef]
    """Placeholder type name; construct via ``build_layout_net``."""

    def __new__(cls, cfg: LayoutNetConfig | None = None):
        return build_layout_net(cfg)
