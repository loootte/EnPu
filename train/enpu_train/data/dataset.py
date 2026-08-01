"""Dataset for layout_schema_version 0.1 samples (#95 / #93)."""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

import numpy as np
import torch
from PIL import Image
from torch.utils.data import Dataset


def _load_layout(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def discover_samples(root: str | Path) -> list[Path]:
    """Find directories containing layout.json under root."""
    root = Path(root)
    if not root.is_dir():
        return []
    found = sorted({p.parent for p in root.rglob("layout.json")})
    return found


def build_l2_y_heat(
    systems: list[dict[str, Any]],
    *,
    height: int,
    heat_len: int,
    sigma: float = 2.0,
) -> np.ndarray:
    """1D heatmap along image height: peaks at system vertical centers."""
    heat = np.zeros(heat_len, dtype=np.float32)
    if height <= 0:
        return heat
    for s in systems:
        b = s.get("bbox") or s.get("box") or {}
        cy = 0.5 * (float(b["y1"]) + float(b["y2"]))
        idx = cy / height * (heat_len - 1)
        for t in range(heat_len):
            heat[t] = max(heat[t], float(np.exp(-0.5 * ((t - idx) / sigma) ** 2)))
    return heat


def build_l3_x_heat(
    splits: list[dict[str, Any] | float],
    *,
    x_left: float,
    x_right: float,
    heat_len: int,
    sigma: float = 1.5,
) -> np.ndarray:
    """1D heatmap along row width for interior splits (relative to crop)."""
    heat = np.zeros(heat_len, dtype=np.float32)
    width = max(1e-3, x_right - x_left)
    for sp in splits:
        x = float(sp["x"] if isinstance(sp, dict) else sp)
        # relative position in [0, 1]
        rel = (x - x_left) / width
        if rel <= 0.0 or rel >= 1.0:
            continue
        idx = rel * (heat_len - 1)
        for t in range(heat_len):
            heat[t] = max(heat[t], float(np.exp(-0.5 * ((t - idx) / sigma) ** 2)))
    return np.clip(heat, 0.0, 1.0)


def decode_peaks(
    heat: np.ndarray,
    *,
    min_prominence: float = 0.3,
    min_gap: int = 4,
) -> list[int]:
    """Simple 1D NMS peak indices."""
    h = heat.astype(np.float32)
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


class LayoutDataset(Dataset):
    """Load enpu-layout-gt samples; produce page + per-row L3 crops."""

    def __init__(
        self,
        roots: list[str | Path] | str | Path,
        *,
        page_size: tuple[int, int] = (384, 512),  # (H, W)
        row_size: tuple[int, int] = (64, 256),  # (H, W) L3 crop
        l2_heat_len: int = 128,
        l3_heat_len: int = 128,
        tasks: tuple[str, ...] = ("l2", "l3"),
        augment: bool = False,
        max_rows_per_page: int = 12,
        seed: int = 0,
    ) -> None:
        if isinstance(roots, (str, Path)):
            roots = [roots]
        self.samples: list[Path] = []
        for r in roots:
            self.samples.extend(discover_samples(r))
        if not self.samples:
            raise FileNotFoundError(f"no layout.json under {roots}")

        self.page_h, self.page_w = page_size
        self.row_h, self.row_w = row_size
        self.l2_heat_len = l2_heat_len
        self.l3_heat_len = l3_heat_len
        self.tasks = tuple(tasks)
        self.augment = augment
        self.max_rows = max_rows_per_page
        self.rng = random.Random(seed)

    def __len__(self) -> int:
        return len(self.samples)

    def _load_image(self, sample_dir: Path, layout: dict[str, Any]) -> Image.Image:
        rel = (layout.get("image") or {}).get("path") or "image.png"
        path = sample_dir / rel
        if not path.is_file():
            # fallback any image
            for cand in sample_dir.glob("image.*"):
                path = cand
                break
        img = Image.open(path).convert("RGB")
        return img

    def __getitem__(self, index: int) -> dict[str, Any]:
        sample_dir = self.samples[index]
        layout = _load_layout(sample_dir / "layout.json")
        img = self._load_image(sample_dir, layout)
        orig_w, orig_h = img.size

        # optional light augment (no horizontal flip)
        if self.augment:
            if self.rng.random() < 0.5:
                # brightness
                arr = np.asarray(img).astype(np.float32)
                factor = self.rng.uniform(0.85, 1.15)
                arr = np.clip(arr * factor, 0, 255).astype(np.uint8)
                img = Image.fromarray(arr)
            if self.rng.random() < 0.3:
                # slight scale via resize jitter later
                pass

        # resize page
        page = img.resize((self.page_w, self.page_h), Image.BILINEAR)
        page_t = (
            torch.from_numpy(np.array(page, copy=True).transpose(2, 0, 1)).float()
            / 255.0
        )

        systems = list((layout.get("l2") or {}).get("systems") or [])
        sx = self.page_w / max(1, orig_w)
        sy = self.page_h / max(1, orig_h)

        # L2 boxes in page pixel space
        l2_boxes = []
        for s in systems:
            b = s.get("bbox") or s.get("box") or {}
            l2_boxes.append(
                [
                    float(b["x1"]) * sx,
                    float(b["y1"]) * sy,
                    float(b["x2"]) * sx,
                    float(b["y2"]) * sy,
                ]
            )
        # L2 1D heat along page height (page-space box centers)
        l2_heat = np.zeros(self.l2_heat_len, dtype=np.float32)
        for box in l2_boxes:
            cy = 0.5 * (box[1] + box[3])
            idx = cy / self.page_h * (self.l2_heat_len - 1)
            sigma = 2.0
            for t in range(self.l2_heat_len):
                l2_heat[t] = max(
                    l2_heat[t], float(np.exp(-0.5 * ((t - idx) / sigma) ** 2))
                )

        # L3 rows
        rows_meta = list((layout.get("l3") or {}).get("rows") or [])
        # map system_id -> bbox from systems
        sys_by_id = {str(s.get("id")): s for s in systems}
        sys_by_index = {
            int(s.get("index", i)): s for i, s in enumerate(systems)
        }

        row_images: list[torch.Tensor] = []
        row_heats: list[torch.Tensor] = []
        row_meta: list[dict[str, Any]] = []

        for row in rows_meta[: self.max_rows]:
            sid = row.get("system_id")
            sidx = row.get("system_index")
            sys = None
            if sid is not None and str(sid) in sys_by_id:
                sys = sys_by_id[str(sid)]
            elif sidx is not None:
                try:
                    sys = sys_by_index.get(int(sidx))
                except (TypeError, ValueError):
                    sys = None
            if sys is None:
                continue
            b = sys.get("bbox") or sys.get("box") or {}
            x1, y1, x2, y2 = (
                float(b["x1"]),
                float(b["y1"]),
                float(b["x2"]),
                float(b["y2"]),
            )
            # pad crop
            pad_x = 0.02 * (x2 - x1)
            pad_y = 0.05 * (y2 - y1)
            cx1 = max(0, int(x1 - pad_x))
            cy1 = max(0, int(y1 - pad_y))
            cx2 = min(orig_w, int(x2 + pad_x))
            cy2 = min(orig_h, int(y2 + pad_y))
            if cx2 <= cx1 or cy2 <= cy1:
                continue
            crop = img.crop((cx1, cy1, cx2, cy2)).resize(
                (self.row_w, self.row_h), Image.BILINEAR
            )
            crop_t = (
                torch.from_numpy(np.array(crop, copy=True).transpose(2, 0, 1)).float()
                / 255.0
            )
            # splits in full image → relative to unpadded system x range for heat
            # Use crop full-image coords for peak decode consistency
            heat = build_l3_x_heat(
                row.get("splits") or [],
                x_left=float(cx1),
                x_right=float(cx2),
                heat_len=self.l3_heat_len,
            )
            row_images.append(crop_t)
            row_heats.append(torch.from_numpy(heat))
            row_meta.append(
                {
                    "system_id": sid,
                    "x_left": float(cx1),
                    "x_right": float(cx2),
                    "y1": float(cy1),
                    "y2": float(cy2),
                    "orig_splits": [
                        float(sp["x"] if isinstance(sp, dict) else sp)
                        for sp in (row.get("splits") or [])
                    ],
                    "page_box": [
                        x1 * sx,
                        y1 * sy,
                        x2 * sx,
                        y2 * sy,
                    ],
                }
            )

        # ensure at least one dummy row for collate stability when L3 empty
        if not row_images and "l3" in self.tasks:
            row_images.append(torch.zeros(3, self.row_h, self.row_w))
            row_heats.append(torch.zeros(self.l3_heat_len))
            row_meta.append(
                {
                    "system_id": None,
                    "x_left": 0.0,
                    "x_right": 1.0,
                    "y1": 0.0,
                    "y2": 1.0,
                    "orig_splits": [],
                    "page_box": [0, 0, 1, 1],
                    "dummy": True,
                }
            )

        return {
            "id": layout.get("id") or sample_dir.name,
            "path": str(sample_dir),
            "page": page_t,
            "orig_size": (orig_h, orig_w),
            "l2_heat": torch.from_numpy(l2_heat),
            "l2_boxes": torch.tensor(l2_boxes, dtype=torch.float32)
            if l2_boxes
            else torch.zeros(0, 4),
            "row_images": row_images,
            "row_heats": row_heats,
            "row_meta": row_meta,
            "layout": layout,
        }


def collate_layout(batch: list[dict[str, Any]]) -> dict[str, Any]:
    """Collate variable-length rows by flattening L3 crops across the batch."""
    pages = torch.stack([b["page"] for b in batch], dim=0)
    l2_heats = torch.stack([b["l2_heat"] for b in batch], dim=0)
    ids = [b["id"] for b in batch]
    l2_boxes = [b["l2_boxes"] for b in batch]

    row_images: list[torch.Tensor] = []
    row_heats: list[torch.Tensor] = []
    row_meta: list[dict[str, Any]] = []
    row_batch_idx: list[int] = []
    for bi, b in enumerate(batch):
        for img, heat, meta in zip(b["row_images"], b["row_heats"], b["row_meta"]):
            if meta.get("dummy"):
                continue
            row_images.append(img)
            row_heats.append(heat)
            row_meta.append(meta)
            row_batch_idx.append(bi)

    out: dict[str, Any] = {
        "ids": ids,
        "page": pages,
        "l2_heat": l2_heats,
        "l2_boxes": l2_boxes,
        "paths": [b["path"] for b in batch],
        "orig_sizes": [b["orig_size"] for b in batch],
    }
    if row_images:
        out["row_images"] = torch.stack(row_images, dim=0)
        out["row_heats"] = torch.stack(row_heats, dim=0)
        out["row_meta"] = row_meta
        out["row_batch_idx"] = torch.tensor(row_batch_idx, dtype=torch.long)
    else:
        # empty L3 — create zero batch for model path
        h = batch[0]["row_images"][0].shape[-2] if batch[0]["row_images"] else 64
        w = batch[0]["row_images"][0].shape[-1] if batch[0]["row_images"] else 256
        hl = batch[0]["row_heats"][0].shape[0] if batch[0]["row_heats"] else 128
        out["row_images"] = torch.zeros(0, 3, h, w)
        out["row_heats"] = torch.zeros(0, hl)
        out["row_meta"] = []
        out["row_batch_idx"] = torch.zeros(0, dtype=torch.long)
    return out
