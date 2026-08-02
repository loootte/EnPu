"""Load EnPu layout weights (#104)."""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.pipeline.structure.learned.model import LayoutNet, LayoutNetConfig

logger = logging.getLogger(__name__)

WEIGHTS_FORMAT = "enpu_layout_net_v0"


class WeightsLoadError(Exception):
    """Missing / corrupt / incompatible weights."""


def _require_torch():
    try:
        import torch
    except ImportError as e:
        raise WeightsLoadError(
            "torch is required for ENPU_STRUCTURE_L1L3_ENGINE=learned. "
            "Install with: pip install torch  (optional; default engine remains rule)"
        ) from e
    return torch


def _cfg_from_payload(payload: dict[str, Any]) -> LayoutNetConfig:
    # Prefer export layout_net_v0 fields; fall back to train TrainConfig blob
    cfg_blob = payload.get("cfg") or {}
    l2_heat = int(
        payload.get("l2_heat_len")
        or cfg_blob.get("l2_heat_len")
        or 128
    )
    l3_heat = int(
        payload.get("l3_heat_len")
        or cfg_blob.get("l3_heat_len")
        or 128
    )
    tasks_raw = payload.get("tasks") or cfg_blob.get("tasks") or ("l2", "l3")
    tasks = tuple(str(t) for t in tasks_raw)
    return LayoutNetConfig(
        l2_heat_len=l2_heat,
        l3_heat_len=l3_heat,
        tasks=tasks if tasks else ("l2", "l3"),
        page_h=int(cfg_blob.get("page_h") or 384),
        page_w=int(cfg_blob.get("page_w") or 512),
        row_h=int(cfg_blob.get("row_h") or 64),
        row_w=int(cfg_blob.get("row_w") or 256),
        base_channels=16,
    )


def load_layout_weights(
    path: str | Path,
    *,
    device: str = "cpu",
) -> tuple[LayoutNet, dict[str, Any]]:
    """Load ``enpu_layout_net_v0`` or train ``best.pt`` / ``last.pt``.

    Returns (model.eval(), meta dict with format/path/cfg fields).
    """
    torch = _require_torch()
    path = Path(path)
    if not path.is_file():
        raise WeightsLoadError(f"weights not found: {path}")

    try:
        payload = torch.load(path, map_location=device, weights_only=False)
    except Exception as e:
        raise WeightsLoadError(f"failed to load weights {path}: {e}") from e

    if not isinstance(payload, dict) or "model" not in payload:
        raise WeightsLoadError(
            f"unsupported weights file (need dict with 'model' state_dict): {path}"
        )

    fmt = str(payload.get("format") or "train_ckpt")
    cfg = _cfg_from_payload(payload)
    model = LayoutNet(cfg)
    try:
        model.load_state_dict(payload["model"], strict=True)
    except Exception as e:
        raise WeightsLoadError(f"state_dict mismatch for {path}: {e}") from e

    model.to(device)
    model.eval()
    meta = {
        "format": fmt,
        "path": str(path.resolve()),
        "tasks": list(cfg.tasks),
        "l2_heat_len": cfg.l2_heat_len,
        "l3_heat_len": cfg.l3_heat_len,
        "page_h": cfg.page_h,
        "page_w": cfg.page_w,
        "row_h": cfg.row_h,
        "row_w": cfg.row_w,
        "device": device,
        "weights_format_expected": WEIGHTS_FORMAT,
    }
    logger.info("loaded layout weights %s format=%s tasks=%s", path, fmt, cfg.tasks)
    return model, meta


@lru_cache(maxsize=4)
def get_cached_layout_model(
    path: str,
    device: str = "cpu",
) -> tuple[LayoutNet, dict[str, Any]]:
    """Process-level cache keyed by path+device."""
    return load_layout_weights(path, device=device)


def clear_layout_model_cache() -> None:
    get_cached_layout_model.cache_clear()
