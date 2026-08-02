"""Learned L1–L3 layout inference for structure pipeline (#104).

Torch is **optional**. Importing this package must not require torch;
only ``run_learned_l2_l3`` / weight loading need it.
"""

from __future__ import annotations

__all__ = ["LearnedL1L3Error", "run_learned_l2_l3"]


def __getattr__(name: str):
    if name in ("LearnedL1L3Error", "run_learned_l2_l3"):
        from app.pipeline.structure.learned.infer_l1l3 import (
            LearnedL1L3Error,
            run_learned_l2_l3,
        )

        return LearnedL1L3Error if name == "LearnedL1L3Error" else run_learned_l2_l3
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
