#!/usr/bin/env python3
"""Evaluate a checkpoint on layout samples — L2 IoU + L3 split x metrics (#95)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import torch
import yaml
from torch.utils.data import DataLoader

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from enpu_train.data.dataset import LayoutDataset, collate_layout
from enpu_train.engine.trainer import TrainConfig, evaluate
from enpu_train.export.weights import load_checkpoint


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt", type=Path, required=True)
    ap.add_argument("--data", type=Path, default=ROOT.parent / "samples" / "layout")
    ap.add_argument("--device", type=str, default="cpu")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args(argv)

    model, ckpt = load_checkpoint(args.ckpt, device=args.device)
    cfg_d = ckpt.get("cfg") or {}
    tcfg = TrainConfig(
        tasks=list(cfg_d.get("tasks") or ["l2", "l3"]),
        device=args.device,
        page_h=int(cfg_d.get("page_h", 384)),
        page_w=int(cfg_d.get("page_w", 512)),
        row_h=int(cfg_d.get("row_h", 64)),
        row_w=int(cfg_d.get("row_w", 256)),
        l2_heat_len=int(cfg_d.get("l2_heat_len", 128)),
        l3_heat_len=int(cfg_d.get("l3_heat_len", 128)),
        batch_size=1,
    )
    # rebuild model is already loaded; ensure cfg match
    ds = LayoutDataset(
        args.data,
        page_size=(tcfg.page_h, tcfg.page_w),
        row_size=(tcfg.row_h, tcfg.row_w),
        l2_heat_len=tcfg.l2_heat_len,
        l3_heat_len=tcfg.l3_heat_len,
        tasks=tuple(tcfg.tasks),
        augment=False,
    )
    loader = DataLoader(ds, batch_size=1, shuffle=False, collate_fn=collate_layout)
    metrics = evaluate(model, loader, tcfg)
    print(json.dumps(metrics, indent=2))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
