"""Layered evaluation API (#86)."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException

from app.config import get_settings
from app.evaluation.batch import evaluate_manifest, evaluate_sample
from app.evaluation.gt_loader import load_ground_truth
from app.schemas.evaluation import (
    BatchEvalRequest,
    BatchEvalResponse,
    CompareRequest,
    CompareResponse,
    SampleMetricsOut,
)

router = APIRouter(prefix="/evaluation", tags=["evaluation"])

# repo root: core/app/api/v1 -> parents[4] = EnPu
_REPO_ROOT = Path(__file__).resolve().parents[4]


@router.post(
    "/compare",
    response_model=CompareResponse,
    summary="Compare GT vs structure/score prediction (layered metrics)",
)
def compare_metrics(body: CompareRequest) -> CompareResponse:
    """Compute L1–L5 metrics for one sample payload (no image I/O)."""
    gt = load_ground_truth_from_dict(body.gt)
    metrics = evaluate_sample(
        sample_id=body.sample_id,
        gt=gt,
        score=body.score,
        structure=body.structure,
        iou_threshold=body.iou_threshold,
    )
    data = metrics.as_dict(include_errors=body.include_errors)
    return CompareResponse(metrics=SampleMetricsOut.model_validate(data))


@router.post(
    "/batch",
    response_model=BatchEvalResponse,
    summary="Batch layered evaluation over samples/eval manifest",
)
def batch_eval(body: BatchEvalRequest) -> BatchEvalResponse:
    """Run layered metrics on the eval set.

    With ``run_recognize=true`` uses the configured recognition engine
    (default mock for offline). Geometry IoU needs layer GT in JSON;
    Score GT alone yields count/sequence metrics (L3/L5).
    """
    manifest = Path(body.manifest)
    if not manifest.is_absolute():
        manifest = _REPO_ROOT / manifest
    if not manifest.is_file():
        raise HTTPException(status_code=400, detail=f"manifest not found: {manifest}")

    recognize_fn = None
    if body.run_recognize:
        base = get_settings()
        settings = base.model_copy(
            update={
                "recognize_engine": body.engine or base.recognize_engine,
                # Layer metrics need structure boxes when available
                "pipeline_mode": "structure",
            }
        )

        def _recognize(image_path: Path) -> dict:
            data = image_path.read_bytes()
            from app.pipeline.runner import run_recognize

            resp = run_recognize(
                data,
                settings=settings,
                filename=image_path.name,
            )
            return {
                "score": resp.score.model_dump(mode="json") if resp.score else None,
                "structure": (
                    resp.structure.model_dump(mode="json") if resp.structure else None
                ),
            }

        recognize_fn = _recognize

    try:
        report = evaluate_manifest(
            manifest,
            eval_root=manifest.parent,
            recognize_fn=recognize_fn,
            subset=body.subset,
            limit=body.limit,
            iou_threshold=body.iou_threshold,
            include_errors=body.include_errors,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return BatchEvalResponse(report=report)


def load_ground_truth_from_dict(data: dict) -> dict:
    """Normalize an in-memory GT dict (same fields as load_ground_truth)."""
    from app.evaluation.gt_loader import (
        load_barline_xs,
        load_layer_geometry,
        measure_count_from_score,
        pitch_sequence_from_score,
        system_count_from_score,
    )

    return {
        "raw": data,
        "pitch_sequence": pitch_sequence_from_score(data),
        "measure_count": measure_count_from_score(data),
        "system_count": system_count_from_score(data),
        "geometry": load_layer_geometry(data),
        "barline_xs": load_barline_xs(data),
        "key": data.get("key"),
        "time_signature": data.get("time_signature"),
        "title": data.get("title"),
    }
