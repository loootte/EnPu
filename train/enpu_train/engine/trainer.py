"""Train / eval loops for LayoutNet (#95)."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import torch
from torch.utils.data import DataLoader

from enpu_train.losses.heat import heatmap_bce_loss
from enpu_train.metrics.layout_metrics import evaluate_batch
from enpu_train.models.layout_net import LayoutNet, LayoutNetConfig


@dataclass
class TrainConfig:
    tasks: list[str] = field(default_factory=lambda: ["l2", "l3"])
    epochs: int = 3
    batch_size: int = 2
    lr: float = 1e-3
    weight_decay: float = 1e-4
    l2_loss_weight: float = 1.0
    l3_loss_weight: float = 1.5
    device: str = "cpu"
    page_h: int = 384
    page_w: int = 512
    row_h: int = 64
    row_w: int = 256
    l2_heat_len: int = 128
    l3_heat_len: int = 128
    num_workers: int = 0
    out_dir: str = "runs/toy"
    log_every: int = 1


def _move_batch(batch: dict[str, Any], device: torch.device) -> dict[str, Any]:
    out = dict(batch)
    for k in ("page", "l2_heat", "row_images", "row_heats", "row_batch_idx"):
        if k in out and torch.is_tensor(out[k]):
            out[k] = out[k].to(device)
    return out


def compute_loss(
    model: LayoutNet,
    batch: dict[str, Any],
    cfg: TrainConfig,
) -> tuple[torch.Tensor, dict[str, float]]:
    out = model(page=batch["page"], rows=batch["row_images"])
    loss = batch["page"].new_zeros(())
    parts: dict[str, float] = {}

    if "l2" in cfg.tasks and "l2_logits" in out:
        l2 = heatmap_bce_loss(out["l2_logits"], batch["l2_heat"])
        loss = loss + cfg.l2_loss_weight * l2
        parts["l2"] = float(l2.detach().cpu())

    if "l3" in cfg.tasks and "l3_logits" in out and batch["row_heats"].shape[0] > 0:
        l3 = heatmap_bce_loss(out["l3_logits"], batch["row_heats"])
        loss = loss + cfg.l3_loss_weight * l3
        parts["l3"] = float(l3.detach().cpu())
    elif "l3" in cfg.tasks:
        parts["l3"] = 0.0

    parts["total"] = float(loss.detach().cpu())
    return loss, parts


@torch.no_grad()
def evaluate(
    model: LayoutNet,
    loader: DataLoader,
    cfg: TrainConfig,
) -> dict[str, float]:
    model.eval()
    device = torch.device(cfg.device)
    acc: dict[str, list[float]] = {
        "l2_mean_iou": [],
        "l3_split_count_mae": [],
        "l3_split_count_exact": [],
        "l3_mean_abs_x_error": [],
        "loss": [],
    }
    for batch in loader:
        batch = _move_batch(batch, device)
        loss, _ = compute_loss(model, batch, cfg)
        acc["loss"].append(float(loss.cpu()))
        out = model(page=batch["page"], rows=batch["row_images"])
        m = evaluate_batch(
            out, batch, page_h=float(cfg.page_h), page_w=float(cfg.page_w)
        )
        for k in (
            "l2_mean_iou",
            "l3_split_count_mae",
            "l3_split_count_exact",
            "l3_mean_abs_x_error",
        ):
            v = m.get(k)
            if v == v:  # not nan
                acc[k].append(float(v))

    def mean(xs: list[float]) -> float:
        return float(sum(xs) / len(xs)) if xs else float("nan")

    return {k: mean(v) for k, v in acc.items()}


def train_loop(
    model: LayoutNet,
    train_loader: DataLoader,
    val_loader: DataLoader | None,
    cfg: TrainConfig,
) -> dict[str, Any]:
    device = torch.device(cfg.device)
    model = model.to(device)
    opt = torch.optim.AdamW(
        model.parameters(), lr=cfg.lr, weight_decay=cfg.weight_decay
    )
    out_dir = Path(cfg.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    history: list[dict[str, Any]] = []
    best_val = float("inf")
    best_path = out_dir / "best.pt"

    t0 = time.time()
    for epoch in range(1, cfg.epochs + 1):
        model.train()
        epoch_losses: list[float] = []
        for step, batch in enumerate(train_loader, start=1):
            batch = _move_batch(batch, device)
            opt.zero_grad(set_to_none=True)
            loss, parts = compute_loss(model, batch, cfg)
            loss.backward()
            opt.step()
            epoch_losses.append(parts["total"])
            if step % max(1, cfg.log_every) == 0:
                print(
                    f"epoch {epoch} step {step} "
                    f"loss={parts['total']:.4f} "
                    f"l2={parts.get('l2', float('nan')):.4f} "
                    f"l3={parts.get('l3', float('nan')):.4f}"
                )

        record: dict[str, Any] = {
            "epoch": epoch,
            "train_loss": float(sum(epoch_losses) / max(1, len(epoch_losses))),
        }
        if val_loader is not None:
            metrics = evaluate(model, val_loader, cfg)
            record["val"] = metrics
            print(
                f"epoch {epoch} val loss={metrics['loss']:.4f} "
                f"l2_iou={metrics['l2_mean_iou']:.4f} "
                f"l3_x_err={metrics['l3_mean_abs_x_error']:.4f} "
                f"l3_count_mae={metrics['l3_split_count_mae']:.4f}"
            )
            score = metrics["loss"]
            if score < best_val:
                best_val = score
                torch.save(
                    {
                        "model": model.state_dict(),
                        "cfg": asdict(cfg),
                        "layout_net": asdict(model.cfg)
                        if hasattr(model.cfg, "__dataclass_fields__")
                        else {},
                        "epoch": epoch,
                        "metrics": metrics,
                    },
                    best_path,
                )
        # always save last
        torch.save(
            {
                "model": model.state_dict(),
                "cfg": asdict(cfg),
                "epoch": epoch,
            },
            out_dir / "last.pt",
        )
        history.append(record)

    (out_dir / "history.json").write_text(
        json.dumps(history, indent=2) + "\n", encoding="utf-8"
    )
    return {
        "history": history,
        "best_path": str(best_path) if best_path.is_file() else str(out_dir / "last.pt"),
        "seconds": time.time() - t0,
    }


def build_model_from_cfg(cfg: TrainConfig) -> LayoutNet:
    return LayoutNet(
        LayoutNetConfig(
            l2_heat_len=cfg.l2_heat_len,
            l3_heat_len=cfg.l3_heat_len,
            tasks=tuple(cfg.tasks),
        )
    )
