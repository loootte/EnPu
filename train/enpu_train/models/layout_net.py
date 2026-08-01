"""Lightweight L2 (page y-heat) + L3 (row x-heat) networks (#95 / #94 path A)."""

from __future__ import annotations

from dataclasses import dataclass

import torch
import torch.nn as nn
import torch.nn.functional as F


class ConvBNReLU(nn.Module):
    def __init__(self, c_in: int, c_out: int, k: int = 3, s: int = 1) -> None:
        super().__init__()
        p = k // 2
        self.net = nn.Sequential(
            nn.Conv2d(c_in, c_out, k, stride=s, padding=p, bias=False),
            nn.BatchNorm2d(c_out),
            nn.ReLU(inplace=True),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x)


class PageL2Head(nn.Module):
    """Page image → 1D heatmap along height (system row centers)."""

    def __init__(self, heat_len: int = 128, base: int = 16) -> None:
        super().__init__()
        self.heat_len = heat_len
        self.enc = nn.Sequential(
            ConvBNReLU(3, base, 3, 2),
            ConvBNReLU(base, base * 2, 3, 2),
            ConvBNReLU(base * 2, base * 4, 3, 2),
            ConvBNReLU(base * 4, base * 4, 3, 2),
        )
        self.proj = nn.Sequential(
            nn.AdaptiveAvgPool2d((heat_len, 1)),  # (B,C,H',1) roughly then we force
        )
        # After pool we may not get exact heat_len; use linear on flattened H
        self.head = nn.Sequential(
            nn.Conv1d(base * 4, base * 2, 3, padding=1),
            nn.ReLU(inplace=True),
            nn.Conv1d(base * 2, 1, 1),
        )

    def forward(self, page: torch.Tensor) -> torch.Tensor:
        # page: B,3,H,W
        f = self.enc(page)  # B,C,h,w
        # collapse width
        f = f.mean(dim=3)  # B,C,h
        # interpolate along H to heat_len
        f = F.interpolate(
            f.unsqueeze(-1),
            size=(self.heat_len, 1),
            mode="bilinear",
            align_corners=False,
        ).squeeze(-1)  # B,C,heat_len
        logits = self.head(f).squeeze(1)  # B, heat_len
        return logits


class RowL3Head(nn.Module):
    """Row crop → 1D heatmap along width (interior splits)."""

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

    def forward(self, rows: torch.Tensor) -> torch.Tensor:
        if rows.numel() == 0:
            return rows.new_zeros((0, self.heat_len))
        f = self.enc(rows)  # B,C,h,w
        f = f.mean(dim=2)  # B,C,w
        f = F.interpolate(
            f.unsqueeze(2),
            size=(1, self.heat_len),
            mode="bilinear",
            align_corners=False,
        ).squeeze(2)  # B,C,heat_len
        logits = self.head(f).squeeze(1)
        return logits


@dataclass
class LayoutNetConfig:
    l2_heat_len: int = 128
    l3_heat_len: int = 128
    base_channels: int = 16
    tasks: tuple[str, ...] = ("l2", "l3")


class LayoutNet(nn.Module):
    def __init__(self, cfg: LayoutNetConfig | None = None) -> None:
        super().__init__()
        self.cfg = cfg or LayoutNetConfig()
        self.l2 = PageL2Head(self.cfg.l2_heat_len, self.cfg.base_channels)
        self.l3 = RowL3Head(self.cfg.l3_heat_len, self.cfg.base_channels)

    def forward(
        self,
        page: torch.Tensor | None = None,
        rows: torch.Tensor | None = None,
    ) -> dict[str, torch.Tensor]:
        out: dict[str, torch.Tensor] = {}
        if page is not None and "l2" in self.cfg.tasks:
            out["l2_logits"] = self.l2(page)
        if rows is not None and "l3" in self.cfg.tasks:
            out["l3_logits"] = self.l3(rows)
        return out
