"""Pydantic schemas for /v1/evaluation (#86)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class LayerMetricOut(BaseModel):
    layer: str
    precision: float = 0.0
    recall: float = 0.0
    f1: float = 0.0
    tp: int = 0
    fp: int = 0
    fn: int = 0
    mean_iou: float = 0.0
    mode: str = "iou"
    extra: dict[str, Any] = Field(default_factory=dict)
    errors: list[dict[str, Any]] = Field(default_factory=list)


class SampleMetricsOut(BaseModel):
    sample_id: str
    layers: dict[str, LayerMetricOut] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)


class CompareRequest(BaseModel):
    """Compare GT JSON with a recognition / structure payload."""

    sample_id: str = "sample"
    gt: dict[str, Any] = Field(..., description="Score v0.1 GT and optional layers geometry")
    score: dict[str, Any] | None = None
    structure: dict[str, Any] | None = Field(
        default=None,
        description="StructureDebug-like dict with items[] and barlines[]",
    )
    iou_threshold: float = 0.5
    include_errors: bool = True


class CompareResponse(BaseModel):
    metrics: SampleMetricsOut


class BatchEvalRequest(BaseModel):
    """Batch eval over samples/eval (server-side paths relative to repo)."""

    manifest: str = Field(
        default="samples/eval/manifest.json",
        description="Path to manifest JSON relative to repo root or absolute",
    )
    subset: str | None = None
    limit: int | None = Field(default=None, ge=1, le=500)
    engine: str = Field(default="mock", description="mock|paddleocr")
    iou_threshold: float = 0.5
    include_errors: bool = False
    run_recognize: bool = Field(
        default=True,
        description="If false, only load GT (no predictions)",
    )


class BatchEvalResponse(BaseModel):
    report: dict[str, Any]


class TuneParamRequest(BaseModel):
    """Grid-search one L3 parameter against GT metrics."""

    sample_id: str = "tune"
    gt: dict[str, Any] = Field(..., description="Score / layer GT JSON")
    # Image as base64 PNG/JPEG (without data: prefix) OR use multipart endpoint
    image_base64: str | None = Field(
        default=None,
        description="Raw base64 image bytes (optional if using multipart)",
    )
    param: str = Field(
        default="l3_min_measure_width",
        description="l3_min_measure_width | l3_enable_cross_line",
    )
    start: float = 16.0
    stop: float = 64.0
    step: float = 8.0
    layer: str = Field(default="L3", description="Metric layer to optimize (default L3)")


class TuneParamResponse(BaseModel):
    result: dict[str, Any]


class BaselineDiffRequest(BaseModel):
    current: dict[str, Any] = Field(..., description="Current batch report")
    baseline: dict[str, Any] = Field(..., description="Saved baseline report")


class BaselineDiffResponse(BaseModel):
    diff: dict[str, Any]


class TuneLayerRequest(BaseModel):
    """Full single-layer auto-tune loop (#89)."""

    sample_id: str = "tune"
    gt: dict[str, Any]
    image_base64: str | None = None
    layer: str = Field(default="l3", description="l3 | l4")
    max_trials: int = Field(default=40, ge=1, le=500)
    max_seconds: float = Field(default=120.0, ge=1.0, le=3600.0)
    seed: int = 42
    method: str = Field(default="random", description="random | grid")
    apply_best: bool = Field(
        default=False,
        description="If true, write best params into runtime store for next recognize",
    )


class TuneLayerResponse(BaseModel):
    result: dict[str, Any]
