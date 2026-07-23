"""Recognition pipeline: preprocess → OCR → parse → export."""

from app.pipeline.runner import PipelineError, run_recognize

__all__ = ["PipelineError", "run_recognize"]
