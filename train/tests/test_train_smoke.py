"""Smoke tests for train framework (#95) — no long GPU runs."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import torch
from torch.utils.data import DataLoader

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from enpu_train.data.dataset import LayoutDataset, collate_layout, decode_peaks
from enpu_train.data.synthetic import make_synthetic_layout_sample
from enpu_train.engine.trainer import TrainConfig, build_model_from_cfg, train_loop
from enpu_train.metrics.layout_metrics import split_x_metrics
from enpu_train.viz import draw_layout_overlay


def test_synthetic_and_dataset(tmp_path: Path) -> None:
    d = tmp_path / "S001"
    layout = make_synthetic_layout_sample(d, sample_id="S001", seed=1)
    assert (d / "layout.json").is_file()
    assert len(layout["l2"]["systems"]) >= 1

    ds = LayoutDataset(
        tmp_path,
        page_size=(192, 256),
        row_size=(32, 128),
        l2_heat_len=64,
        l3_heat_len=64,
        augment=False,
    )
    assert len(ds) == 1
    item = ds[0]
    assert item["page"].shape[0] == 3
    assert item["l2_heat"].shape[0] == 64
    assert len(item["row_images"]) >= 1

    batch = collate_layout([item, item])
    assert batch["page"].shape[0] == 2
    assert batch["row_images"].shape[0] >= 1


def test_split_metrics_and_peaks() -> None:
    heat = torch.zeros(64)
    heat[10] = 1.0
    heat[40] = 0.9
    peaks = decode_peaks(heat.numpy(), min_prominence=0.5, min_gap=5)
    assert 10 in peaks and 40 in peaks
    m = split_x_metrics([100.0, 200.0], [102.0, 198.0], max_dist=12)
    assert m["split_count_exact"] == 1.0
    assert m["split_mean_abs_x_error"] <= 3.0


def test_one_epoch_train(tmp_path: Path) -> None:
    for i in range(3):
        make_synthetic_layout_sample(
            tmp_path / f"S{i:03d}",
            sample_id=f"S{i:03d}",
            seed=10 + i,
            width=320,
            height=400,
        )
    ds = LayoutDataset(
        tmp_path,
        page_size=(192, 256),
        row_size=(32, 128),
        l2_heat_len=64,
        l3_heat_len=64,
    )
    loader = DataLoader(ds, batch_size=1, collate_fn=collate_layout, shuffle=True)
    cfg = TrainConfig(
        tasks=["l2", "l3"],
        epochs=1,
        batch_size=1,
        device="cpu",
        page_h=192,
        page_w=256,
        row_h=32,
        row_w=128,
        l2_heat_len=64,
        l3_heat_len=64,
        out_dir=str(tmp_path / "run"),
        log_every=10,
    )
    model = build_model_from_cfg(cfg)
    result = train_loop(model, loader, loader, cfg)
    assert Path(result["best_path"]).is_file()
    hist = json.loads((tmp_path / "run" / "history.json").read_text(encoding="utf-8"))
    assert hist[0]["train_loss"] == hist[0]["train_loss"]  # not nan


def test_viz(tmp_path: Path) -> None:
    d = tmp_path / "S"
    layout = make_synthetic_layout_sample(d, sample_id="S", seed=0)
    out = tmp_path / "ov.png"
    draw_layout_overlay(d / "image.png", layout, out_path=out)
    assert out.is_file()
