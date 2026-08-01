#!/usr/bin/env python3
"""Train L2+L3 layout model (toy MVP) — #95."""

from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

import torch
import yaml
from torch.utils.data import DataLoader, Subset

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from enpu_train.data.dataset import LayoutDataset, collate_layout
from enpu_train.data.synthetic import generate_synthetic_set
from enpu_train.engine.trainer import TrainConfig, build_model_from_cfg, train_loop
from enpu_train.export.weights import export_onnx, export_state_dict


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="EnPu layout train (#95)")
    ap.add_argument(
        "--config",
        type=Path,
        default=ROOT / "configs" / "mvp_l2_l3.yaml",
    )
    ap.add_argument("--device", type=str, default=None)
    ap.add_argument("--epochs", type=int, default=None)
    ap.add_argument("--skip-export", action="store_true")
    args = ap.parse_args(argv)

    cfg_raw = load_yaml(args.config)
    data_c = cfg_raw.get("data") or {}
    train_c = cfg_raw.get("train") or {}
    export_c = cfg_raw.get("export") or {}
    tasks = list(cfg_raw.get("tasks") or ["l2", "l3"])

    # resolve roots relative to config / train dir
    roots = []
    for r in data_c.get("roots") or []:
        p = Path(r)
        if not p.is_absolute():
            p = (args.config.parent / p).resolve()
            if not p.exists():
                p = (ROOT / r).resolve()
            if not p.exists():
                p = (ROOT.parent / Path(r).name).resolve()  # repo samples/layout
            if not p.exists() and "samples" in r.replace("\\", "/"):
                p = (ROOT.parent / "samples" / "layout").resolve()
        roots.append(p)

    # always try repo samples/layout
    repo_layout = ROOT.parent / "samples" / "layout"
    if repo_layout.is_dir() and repo_layout not in roots:
        roots.insert(0, repo_layout)

    synth_count = int(data_c.get("synth_count") or 0)
    if synth_count > 0:
        synth_dir = Path(data_c.get("synth_dir") or "data_cache/synth")
        if not synth_dir.is_absolute():
            synth_dir = ROOT / synth_dir
        print(f"generating {synth_count} synthetic samples → {synth_dir}")
        generate_synthetic_set(synth_dir, n=synth_count, seed=42)
        roots.append(synth_dir)

    page_size = tuple(data_c.get("page_size") or [384, 512])
    row_size = tuple(data_c.get("row_size") or [64, 256])
    l2_heat = int(data_c.get("l2_heat_len") or 128)
    l3_heat = int(data_c.get("l3_heat_len") or 128)

    device = args.device or train_c.get("device") or "cpu"
    if device == "cuda" and not torch.cuda.is_available():
        print("cuda not available, using cpu")
        device = "cpu"

    out_dir = Path(train_c.get("out_dir") or "runs/mvp_l2_l3")
    if not out_dir.is_absolute():
        out_dir = ROOT / out_dir

    tcfg = TrainConfig(
        tasks=tasks,
        epochs=int(args.epochs or train_c.get("epochs") or 3),
        batch_size=int(train_c.get("batch_size") or 2),
        lr=float(train_c.get("lr") or 1e-3),
        weight_decay=float(train_c.get("weight_decay") or 1e-4),
        l2_loss_weight=float(train_c.get("l2_loss_weight") or 1.0),
        l3_loss_weight=float(train_c.get("l3_loss_weight") or 1.5),
        device=device,
        page_h=int(page_size[0]),
        page_w=int(page_size[1]),
        row_h=int(row_size[0]),
        row_w=int(row_size[1]),
        l2_heat_len=l2_heat,
        l3_heat_len=l3_heat,
        num_workers=int(train_c.get("num_workers") or 0),
        out_dir=str(out_dir),
        log_every=int(train_c.get("log_every") or 1),
    )

    print("data roots:", [str(r) for r in roots])
    ds = LayoutDataset(
        roots,
        page_size=(tcfg.page_h, tcfg.page_w),
        row_size=(tcfg.row_h, tcfg.row_w),
        l2_heat_len=tcfg.l2_heat_len,
        l3_heat_len=tcfg.l3_heat_len,
        tasks=tuple(tasks),
        augment=bool(data_c.get("augment", False)),
    )
    print(f"samples: {len(ds)}")

    n = len(ds)
    indices = list(range(n))
    random.Random(0).shuffle(indices)
    val_ratio = float(data_c.get("val_ratio") or 0.25)
    n_val = max(1, int(n * val_ratio)) if n > 1 else 0
    if n_val > 0 and n_val < n:
        val_idx = indices[:n_val]
        train_idx = indices[n_val:]
    else:
        train_idx = indices
        val_idx = indices[:1]  # toy: evaluate on one sample

    train_loader = DataLoader(
        Subset(ds, train_idx),
        batch_size=tcfg.batch_size,
        shuffle=True,
        num_workers=tcfg.num_workers,
        collate_fn=collate_layout,
    )
    val_loader = DataLoader(
        Subset(ds, val_idx),
        batch_size=1,
        shuffle=False,
        num_workers=0,
        collate_fn=collate_layout,
    )

    model = build_model_from_cfg(tcfg)
    result = train_loop(model, train_loader, val_loader, tcfg)
    print("done:", result)

    if not args.skip_export:
        ckpt = Path(result["best_path"])
        sd_out = Path(export_c.get("state_dict") or (out_dir / "export" / "layout_net.pt"))
        if not sd_out.is_absolute():
            sd_out = ROOT / sd_out
        export_state_dict(ckpt, sd_out)
        print("exported state_dict:", sd_out)
        try:
            onnx_dir = Path(export_c.get("onnx_dir") or (out_dir / "export" / "onnx"))
            if not onnx_dir.is_absolute():
                onnx_dir = ROOT / onnx_dir
            paths = export_onnx(
                ckpt,
                onnx_dir,
                page_h=tcfg.page_h,
                page_w=tcfg.page_w,
                row_h=tcfg.row_h,
                row_w=tcfg.row_w,
            )
            print("exported onnx:", paths)
        except Exception as e:
            print("onnx export skipped:", e)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
