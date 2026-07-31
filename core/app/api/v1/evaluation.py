"""Layered evaluation API (#86)."""

from __future__ import annotations

import base64
import binascii
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.config import get_settings
from app.evaluation.batch import evaluate_manifest, evaluate_sample
from app.evaluation.param_tuner import (
    diff_baselines,
    load_baseline,
    save_baseline,
    tune_param_on_image,
)
from app.pipeline.preprocess import ImageDecodeError, decode_image_bytes
from app.schemas.evaluation import (
    BaselineDiffRequest,
    BaselineDiffResponse,
    BatchEvalRequest,
    BatchEvalResponse,
    CompareRequest,
    CompareResponse,
    SampleMetricsOut,
    TuneLayerRequest,
    TuneLayerResponse,
    TuneParamRequest,
    TuneParamResponse,
)
from app.tuning.params import reset_layer_params, set_layer_params, snapshot_all_params
from app.tuning.search import tune_layer

router = APIRouter(prefix="/evaluation", tags=["evaluation"])

# repo root: core/app/api/v1 -> parents[4] = EnPu
_REPO_ROOT = Path(__file__).resolve().parents[4]
_BASELINE_DIR = _REPO_ROOT / "reports" / "baselines"


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


def _decode_b64_image(b64: str) -> bytes:
    raw = b64.strip()
    if "," in raw and raw.lower().startswith("data:"):
        raw = raw.split(",", 1)[1]
    try:
        return base64.b64decode(raw, validate=False)
    except binascii.Error as exc:
        raise HTTPException(status_code=400, detail=f"invalid image_base64: {exc}") from exc


@router.post(
    "/tune-param",
    response_model=TuneParamResponse,
    summary="Grid-search one L3 parameter (L1/L2 cached)",
)
def tune_param_json(body: TuneParamRequest) -> TuneParamResponse:
    """JSON body with base64 image + GT. Prefer multipart for large images."""
    if not body.image_base64:
        raise HTTPException(
            status_code=400,
            detail="image_base64 required (or use /tune-param/upload)",
        )
    try:
        image_bgr = decode_image_bytes(_decode_b64_image(body.image_base64))
    except ImageDecodeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    gt = load_ground_truth_from_dict(body.gt)
    try:
        result = tune_param_on_image(
            image_bgr,
            gt=gt,
            param=body.param,  # type: ignore[arg-type]
            start=body.start,
            stop=body.stop,
            step=body.step,
            sample_id=body.sample_id,
            layer_metric=body.layer,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return TuneParamResponse(result=result.as_dict())


@router.post(
    "/tune-param/upload",
    response_model=TuneParamResponse,
    summary="Grid-search L3 param with multipart image + GT JSON string",
)
async def tune_param_upload(
    file: UploadFile = File(..., description="Score image"),
    gt_json: str = Form(..., description="GT JSON string"),
    param: str = Form("l3_min_measure_width"),
    start: float = Form(16.0),
    stop: float = Form(64.0),
    step: float = Form(8.0),
    layer: str = Form("L3"),
    sample_id: str = Form("tune"),
) -> TuneParamResponse:
    import json

    data = await file.read()
    try:
        image_bgr = decode_image_bytes(data)
    except ImageDecodeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        gt_raw = json.loads(gt_json)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"gt_json invalid: {exc}") from exc
    gt = load_ground_truth_from_dict(gt_raw)
    try:
        result = tune_param_on_image(
            image_bgr,
            gt=gt,
            param=param,  # type: ignore[arg-type]
            start=start,
            stop=stop,
            step=step,
            sample_id=sample_id,
            layer_metric=layer,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return TuneParamResponse(result=result.as_dict())


@router.post(
    "/baseline/diff",
    response_model=BaselineDiffResponse,
    summary="Diff mean_f1 between current report and a baseline",
)
def baseline_diff(body: BaselineDiffRequest) -> BaselineDiffResponse:
    return BaselineDiffResponse(diff=diff_baselines(body.current, body.baseline))


@router.post(
    "/baseline/save",
    summary="Save batch report as named baseline under reports/baselines/",
)
def baseline_save(
    name: str = Form("latest"),
    report_json: str = Form(..., description="Full batch report JSON"),
) -> dict:
    import json
    import re

    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("_") or "latest"
    try:
        report = json.loads(report_json)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"report_json invalid: {exc}") from exc
    path = _BASELINE_DIR / f"{safe}.json"
    save_baseline(report, path)
    return {"ok": True, "path": str(path.relative_to(_REPO_ROOT))}


@router.get(
    "/baseline/{name}",
    summary="Load a saved baseline by name",
)
def baseline_get(name: str) -> dict:
    import re

    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("_") or "latest"
    path = _BASELINE_DIR / f"{safe}.json"
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"baseline not found: {safe}")
    return load_baseline(path)


@router.post(
    "/tune-layer",
    response_model=TuneLayerResponse,
    summary="Single-layer auto-tune loop (#89): random/grid search on L3 or L4",
)
def tune_layer_json(body: TuneLayerRequest) -> TuneLayerResponse:
    """JSON body with base64 image + GT. Prefer multipart for large images."""
    if not body.image_base64:
        raise HTTPException(
            status_code=400,
            detail="image_base64 required (or use /tune-layer/upload)",
        )
    try:
        image_bgr = decode_image_bytes(_decode_b64_image(body.image_base64))
    except ImageDecodeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    gt = load_ground_truth_from_dict(body.gt)
    try:
        result = tune_layer(
            image_bgr,
            gt=gt,
            layer=body.layer,  # type: ignore[arg-type]
            max_trials=body.max_trials,
            max_seconds=body.max_seconds,
            seed=body.seed,
            method=body.method,  # type: ignore[arg-type]
            apply_best=body.apply_best,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return TuneLayerResponse(result=result.as_dict())


@router.post(
    "/tune-layer/upload",
    response_model=TuneLayerResponse,
    summary="Single-layer auto-tune with multipart image + GT (#89)",
)
async def tune_layer_upload(
    file: UploadFile = File(...),
    gt_json: str = Form(...),
    layer: str = Form("l3"),
    max_trials: int = Form(40),
    max_seconds: float = Form(120.0),
    seed: int = Form(42),
    method: str = Form("random"),
    apply_best: bool = Form(False),
) -> TuneLayerResponse:
    import json

    data = await file.read()
    try:
        image_bgr = decode_image_bytes(data)
    except ImageDecodeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        gt_raw = json.loads(gt_json)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"gt_json invalid: {exc}") from exc
    gt = load_ground_truth_from_dict(gt_raw)
    try:
        result = tune_layer(
            image_bgr,
            gt=gt,
            layer=layer,  # type: ignore[arg-type]
            max_trials=max_trials,
            max_seconds=max_seconds,
            seed=seed,
            method=method,  # type: ignore[arg-type]
            apply_best=apply_best,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return TuneLayerResponse(result=result.as_dict())


@router.post(
    "/params/apply",
    summary="Apply layer params to runtime store (#89)",
)
def params_apply(
    layer: str = Form("l3"),
    params_json: str = Form(...),
    merge: bool = Form(True),
) -> dict:
    import json

    try:
        params = json.loads(params_json)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not isinstance(params, dict):
        raise HTTPException(status_code=400, detail="params must be object")
    try:
        effective = set_layer_params(layer, params, merge=merge)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "layer": layer.lower(), "params": effective}


@router.post(
    "/params/reset",
    summary="Reset runtime layer params to YAML defaults (#89)",
)
def params_reset(layer: str | None = Form(default=None)) -> dict:
    reset_layer_params(layer if layer else None)
    return {"ok": True, "params": snapshot_all_params()}


@router.get(
    "/params",
    summary="Snapshot effective layer params (#89)",
)
def params_get() -> dict:
    return snapshot_all_params()
