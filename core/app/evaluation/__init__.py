"""Layered recognition evaluation (#86).

Compute per-layer Precision / Recall / F1 (and count-based metrics when
geometry GT is unavailable). Used by batch CLI and ``/v1/evaluation/*`` APIs.
"""

from app.evaluation.batch import evaluate_manifest, evaluate_sample
from app.evaluation.compare import compare_sample
from app.evaluation.metrics import box_match_metrics, count_metrics, pitch_sequence_metrics
from app.evaluation.types import Box, ErrorBox, LayerMetric, SampleMetrics

__all__ = [
    "Box",
    "ErrorBox",
    "LayerMetric",
    "SampleMetrics",
    "box_match_metrics",
    "count_metrics",
    "pitch_sequence_metrics",
    "compare_sample",
    "evaluate_sample",
    "evaluate_manifest",
]
