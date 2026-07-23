"""Unit tests for OpenCV preprocessing."""

from __future__ import annotations

import numpy as np
import pytest

from app.pipeline.preprocess import ImageDecodeError, decode_image_bytes, preprocess_for_ocr


def test_decode_and_preprocess_png_roundtrip() -> None:
    import cv2

    img = np.full((80, 120, 3), 255, dtype=np.uint8)
    cv2.putText(img, "123", (10, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 0), 2)
    ok, buf = cv2.imencode(".png", img)
    assert ok
    data = buf.tobytes()

    bgr = decode_image_bytes(data)
    assert bgr.shape[0] == 80
    assert bgr.shape[1] == 120

    pre = preprocess_for_ocr(bgr, max_side=2000, denoise=True)
    assert pre.width == 120
    assert pre.height == 80
    assert pre.ocr_bgr.ndim == 3
    assert "grayscale" in pre.steps
    assert "bilateral_denoise" in pre.steps


def test_resize_when_large() -> None:
    big = np.zeros((3000, 1000, 3), dtype=np.uint8)
    pre = preprocess_for_ocr(big, max_side=1000, denoise=False)
    assert max(pre.ocr_bgr.shape[:2]) == 1000
    assert pre.scale < 1.0
    assert any(s.startswith("resize:") for s in pre.steps)


def test_decode_invalid() -> None:
    with pytest.raises(ImageDecodeError):
        decode_image_bytes(b"not-an-image")
