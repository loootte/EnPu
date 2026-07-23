"""OCR engine abstraction (PaddleOCR + mock)."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Any

import numpy as np

from app.schemas.recognize import BoundingBox

logger = logging.getLogger(__name__)

MOCK_TEXTS = ["1", "2", "3", "主", "恩"]


@dataclass(frozen=True)
class OcrItem:
    text: str
    score: float | None
    box: BoundingBox | None


@dataclass(frozen=True)
class OcrResult:
    engine: str
    items: list[OcrItem]
    mock: bool

    @property
    def texts(self) -> list[str]:
        return [item.text for item in self.items if item.text]

    @property
    def boxes(self) -> list[BoundingBox]:
        return [item.box for item in self.items if item.box is not None]


class OcrEngineError(RuntimeError):
    """OCR backend failed to initialize or run."""


def _polygon_to_box(poly: Any, score: float | None = None) -> BoundingBox | None:
    try:
        pts = np.asarray(poly, dtype=np.float32).reshape(-1, 2)
        if pts.size == 0:
            return None
        x1 = float(pts[:, 0].min())
        y1 = float(pts[:, 1].min())
        x2 = float(pts[:, 0].max())
        y2 = float(pts[:, 1].max())
        return BoundingBox(x1=x1, y1=y1, x2=x2, y2=y2, score=score)
    except (TypeError, ValueError):
        return None


class MockOcrEngine:
    """Deterministic OCR for tests and offline UI wiring."""

    def run(self, image_bgr: np.ndarray) -> OcrResult:  # noqa: ARG002
        items = [
            OcrItem(text=t, score=1.0, box=None) for t in MOCK_TEXTS
        ]
        return OcrResult(engine="mock", items=items, mock=True)


class PaddleOcrEngine:
    """Lazy singleton wrapper around PaddleOCR."""

    _lock = threading.Lock()
    _shared: Any | None = None
    _init_error: str | None = None

    def __init__(
        self,
        *,
        lang: str = "ch",
        use_angle_cls: bool = True,
        use_gpu: bool = False,
    ) -> None:
        self.lang = lang
        self.use_angle_cls = use_angle_cls
        self.use_gpu = use_gpu

    def _get_client(self) -> Any:
        cls = type(self)
        if cls._shared is not None:
            return cls._shared
        with cls._lock:
            if cls._shared is not None:
                return cls._shared
            if cls._init_error is not None:
                raise OcrEngineError(cls._init_error)
            try:
                from paddleocr import PaddleOCR  # type: ignore import-not-found
            except Exception as exc:  # noqa: BLE001 — surface as engine error
                cls._init_error = (
                    "PaddleOCR is not installed or failed to import. "
                    f"Install OCR deps (see core/README.md). Detail: {exc}"
                )
                raise OcrEngineError(cls._init_error) from exc

            try:
                # PaddleOCR 2.x API; kwargs vary slightly by version.
                kwargs: dict[str, Any] = {
                    "lang": self.lang,
                    "use_angle_cls": self.use_angle_cls,
                    "show_log": False,
                }
                # use_gpu deprecated in some builds; try, then fall back.
                try:
                    cls._shared = PaddleOCR(use_gpu=self.use_gpu, **kwargs)
                except TypeError:
                    kwargs.pop("show_log", None)
                    try:
                        cls._shared = PaddleOCR(
                            use_angle_cls=self.use_angle_cls,
                            lang=self.lang,
                        )
                    except TypeError:
                        cls._shared = PaddleOCR(lang=self.lang)
            except Exception as exc:  # noqa: BLE001
                cls._init_error = f"Failed to initialize PaddleOCR: {exc}"
                logger.exception("PaddleOCR init failed")
                raise OcrEngineError(cls._init_error) from exc

            logger.info("PaddleOCR initialized (lang=%s)", self.lang)
            return cls._shared

    @classmethod
    def reset_shared(cls) -> None:
        """Test helper: drop cached engine."""
        with cls._lock:
            cls._shared = None
            cls._init_error = None

    def run(self, image_bgr: np.ndarray) -> OcrResult:
        client = self._get_client()
        try:
            raw = client.ocr(image_bgr, cls=self.use_angle_cls)
        except TypeError:
            # Newer paddleocr may not accept cls=
            try:
                raw = client.ocr(image_bgr)
            except Exception as exc:  # noqa: BLE001
                raise OcrEngineError(f"PaddleOCR inference failed: {exc}") from exc
        except Exception as exc:  # noqa: BLE001
            raise OcrEngineError(f"PaddleOCR inference failed: {exc}") from exc

        items = self._parse_raw(raw)
        return OcrResult(engine="paddleocr", items=items, mock=False)

    def _parse_raw(self, raw: Any) -> list[OcrItem]:
        """Normalize PaddleOCR 2.x / some 3.x result shapes."""
        items: list[OcrItem] = []
        if raw is None:
            return items

        # Classic: list per image → list of [box, (text, conf)]
        pages = raw
        if isinstance(raw, dict):
            # Some 3.x predict APIs return dicts; best-effort extraction.
            pages = [raw]

        if not isinstance(pages, list):
            return items

        lines = pages[0] if pages else None
        if lines is None:
            return items

        # If first element looks like OCR line pairs
        if isinstance(lines, list):
            for line in lines:
                item = self._parse_line(line)
                if item is not None:
                    items.append(item)
            return items

        if isinstance(lines, dict):
            # e.g. {"rec_texts": [...], "rec_scores": [...], "dt_polys": [...]}
            texts = lines.get("rec_texts") or lines.get("texts") or []
            scores = lines.get("rec_scores") or lines.get("scores") or []
            polys = lines.get("dt_polys") or lines.get("rec_polys") or lines.get("boxes") or []
            for idx, text in enumerate(texts):
                score = None
                if idx < len(scores):
                    try:
                        score = float(scores[idx])
                    except (TypeError, ValueError):
                        score = None
                poly = polys[idx] if idx < len(polys) else None
                text_s = str(text).strip()
                if not text_s:
                    continue
                items.append(
                    OcrItem(
                        text=text_s,
                        score=score,
                        box=_polygon_to_box(poly, score),
                    )
                )
        return items

    def _parse_line(self, line: Any) -> OcrItem | None:
        # Expected: [box, (text, conf)]
        try:
            if not line or len(line) < 2:
                return None
            box_raw, rec = line[0], line[1]
            text = ""
            score: float | None = None
            if isinstance(rec, (list, tuple)):
                text = str(rec[0]) if rec else ""
                if len(rec) > 1:
                    try:
                        score = float(rec[1])
                    except (TypeError, ValueError):
                        score = None
            else:
                text = str(rec)
            text = text.strip()
            if not text:
                return None
            return OcrItem(text=text, score=score, box=_polygon_to_box(box_raw, score))
        except (TypeError, ValueError, IndexError):
            return None


def get_ocr_engine(engine_name: str, **kwargs: Any) -> MockOcrEngine | PaddleOcrEngine:
    name = (engine_name or "paddleocr").strip().lower()
    if name == "mock":
        return MockOcrEngine()
    if name in {"paddleocr", "paddle"}:
        return PaddleOcrEngine(
            lang=str(kwargs.get("lang", "ch")),
            use_angle_cls=bool(kwargs.get("use_angle_cls", True)),
            use_gpu=bool(kwargs.get("use_gpu", False)),
        )
    raise OcrEngineError(
        f"Unknown recognize engine {engine_name!r}. Use 'mock' or 'paddleocr'."
    )
