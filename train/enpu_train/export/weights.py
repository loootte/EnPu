"""Export trained weights for later core integration (#95)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import torch

from enpu_train.models.layout_net import LayoutNet, LayoutNetConfig


def load_checkpoint(path: str | Path, device: str = "cpu") -> tuple[LayoutNet, dict]:
    ckpt = torch.load(path, map_location=device, weights_only=False)
    cfg_d = ckpt.get("cfg") or {}
    net_cfg = LayoutNetConfig(
        l2_heat_len=int(cfg_d.get("l2_heat_len", 128)),
        l3_heat_len=int(cfg_d.get("l3_heat_len", 128)),
        tasks=tuple(cfg_d.get("tasks") or ("l2", "l3")),
    )
    model = LayoutNet(net_cfg)
    model.load_state_dict(ckpt["model"])
    model.to(device)
    model.eval()
    return model, ckpt


def export_state_dict(ckpt_path: str | Path, out_path: str | Path) -> Path:
    """Copy/slim to a portable state_dict file."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    model, ckpt = load_checkpoint(ckpt_path)
    payload: dict[str, Any] = {
        "format": "enpu_layout_net_v0",
        "model": model.state_dict(),
        "tasks": list(model.cfg.tasks),
        "l2_heat_len": model.cfg.l2_heat_len,
        "l3_heat_len": model.cfg.l3_heat_len,
        "source_ckpt": str(ckpt_path),
        "train_metrics": ckpt.get("metrics"),
        "note": (
            "Load in core via future engine=learned_l1l3 (P2). "
            "Map L2 y-peaks → system bands; L3 x-peaks → barlines/splits; "
            "then normalize_splits + splits_to_measures."
        ),
    }
    torch.save(payload, out_path)
    return out_path


def export_onnx(
    ckpt_path: str | Path,
    out_dir: str | Path,
    *,
    page_h: int = 384,
    page_w: int = 512,
    row_h: int = 64,
    row_w: int = 256,
    opset: int = 17,
) -> dict[str, str]:
    """Export separate ONNX graphs for L2 page head and L3 row head."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    model, _ = load_checkpoint(ckpt_path)
    paths: dict[str, str] = {}

    # L2
    if "l2" in model.cfg.tasks:
        class _L2(torch.nn.Module):
            def __init__(self, m: LayoutNet) -> None:
                super().__init__()
                self.m = m

            def forward(self, page: torch.Tensor) -> torch.Tensor:
                return self.m.l2(page)

        l2 = _L2(model).eval()
        dummy = torch.randn(1, 3, page_h, page_w)
        p = out_dir / "l2_page.onnx"
        torch.onnx.export(
            l2,
            dummy,
            str(p),
            input_names=["page"],
            output_names=["l2_logits"],
            dynamic_axes={"page": {0: "batch"}, "l2_logits": {0: "batch"}},
            opset_version=opset,
        )
        paths["l2"] = str(p)

    # L3
    if "l3" in model.cfg.tasks:
        class _L3(torch.nn.Module):
            def __init__(self, m: LayoutNet) -> None:
                super().__init__()
                self.m = m

            def forward(self, rows: torch.Tensor) -> torch.Tensor:
                return self.m.l3(rows)

        l3 = _L3(model).eval()
        dummy = torch.randn(1, 3, row_h, row_w)
        p = out_dir / "l3_row.onnx"
        torch.onnx.export(
            l3,
            dummy,
            str(p),
            input_names=["row"],
            output_names=["l3_logits"],
            dynamic_axes={"row": {0: "batch"}, "l3_logits": {0: "batch"}},
            opset_version=opset,
        )
        paths["l3"] = str(p)

    (out_dir / "README_export.txt").write_text(
        "EnPu layout ONNX export (#95)\n"
        "l2_page.onnx: input page NCHW float0-1 → l2_logits (N, heat_len)\n"
        "l3_row.onnx: input row crop NCHW → l3_logits (N, heat_len)\n"
        "Post-process: peak decode → structure.barlines / L2 items; see train/README.md\n",
        encoding="utf-8",
    )
    return paths
