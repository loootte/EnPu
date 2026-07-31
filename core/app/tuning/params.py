"""Layer parameter dataclasses + runtime store (#89)."""

from __future__ import annotations

import copy
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

# core/app/tuning -> parents[3] = repo root EnPu
_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_YAML = _REPO_ROOT / "configs" / "tune" / "default_params.yaml"

# Runtime overrides applied after load (session / apply best)
_RUNTIME: dict[str, dict[str, Any]] = {}


@dataclass
class L3Params:
    min_measure_width: float = 24.0
    min_gap_floor: float = 18.0
    min_gap_ratio: float = 0.03
    enable_cross_line: bool = True
    soft_gap_enabled: bool = True
    open_trailing_enabled: bool = True
    dedup_gap_factor: float = 0.5

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> L3Params:
        if not d:
            return cls()
        known = {f.name for f in fields(cls)}
        kwargs = {k: d[k] for k in known if k in d}
        return cls(**kwargs)


@dataclass
class L4Params:
    min_area: int = 18
    max_aspect: float = 3.5

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> L4Params:
        if not d:
            return cls()
        known = {f.name for f in fields(cls)}
        kwargs = {k: d[k] for k in known if k in d}
        if "min_area" in kwargs:
            kwargs["min_area"] = int(kwargs["min_area"])
        return cls(**kwargs)


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        import yaml  # type: ignore

        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return data if isinstance(data, dict) else {}
    except Exception:
        # Minimal fallback without PyYAML: only support empty / skip
        return {}


def load_default_params_file() -> dict[str, Any]:
    return _load_yaml(_DEFAULT_YAML)


def get_layer_params(layer: str) -> dict[str, Any]:
    """Merged defaults + runtime overrides for a layer (``l3`` / ``l4``)."""
    key = layer.lower()
    if key not in ("l3", "l4"):
        # allow "L3" already lowercased; reject others later when setting
        pass
    defaults = load_default_params_file()
    base = dict(defaults.get(key) or {})
    base.update(_RUNTIME.get(key) or {})
    return base


def get_l3_params() -> L3Params:
    return L3Params.from_dict(get_layer_params("l3"))


def get_l4_params() -> L4Params:
    return L4Params.from_dict(get_layer_params("l4"))


def set_layer_params(layer: str, params: dict[str, Any], *, merge: bool = True) -> dict[str, Any]:
    """Apply runtime params for a layer. Returns the effective dict."""
    key = layer.lower()
    if key not in ("l3", "l4"):
        raise ValueError(f"unsupported layer: {layer}")
    if merge:
        cur = get_layer_params(key)
        cur.update(params)
        _RUNTIME[key] = cur
    else:
        _RUNTIME[key] = dict(params)
    return get_layer_params(key)


def reset_layer_params(layer: str | None = None) -> None:
    """Clear runtime overrides (restore YAML defaults)."""
    if layer is None:
        _RUNTIME.clear()
    else:
        _RUNTIME.pop(layer.lower(), None)


def snapshot_all_params() -> dict[str, Any]:
    return {
        "l3": get_l3_params().to_dict(),
        "l4": get_l4_params().to_dict(),
        "runtime_overrides": copy.deepcopy(_RUNTIME),
    }
