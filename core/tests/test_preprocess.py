"""Unit tests for OpenCV preprocessing."""

from __future__ import annotations

import numpy as np
import pytest

from app.pipeline.preprocess import (
    ImageDecodeError,
    PreprocessOptions,
    decode_image_bytes,
    encode_image_png,
    preprocess_for_ocr,
)


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


def test_toolbox_clahe_shadow_binary_crop() -> None:
    """#47 options produce extra steps and crop reduces size."""
    import cv2

    img = np.full((200, 300, 3), 220, dtype=np.uint8)
    # dark gradient "shadow"
    for y in range(200):
        img[y, :, :] = max(40, 220 - y)
    cv2.putText(img, "5 6 7", (40, 100), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 0, 0), 2)
    opts = PreprocessOptions(
        max_side=2000,
        denoise=True,
        clahe=True,
        shadow_remove=True,
        adaptive_binary=True,
        brightness=5,
        contrast=1.1,
        crop_x1=20,
        crop_y1=20,
        crop_x2=280,
        crop_y2=180,
    )
    pre = preprocess_for_ocr(img, options=opts)
    assert any(s.startswith("crop:") for s in pre.steps)
    assert "clahe" in pre.steps
    assert "shadow_remove" in pre.steps
    assert "adaptive_binary" in pre.steps
    assert pre.ocr_bgr.shape[0] <= 160
    assert pre.ocr_bgr.shape[1] <= 260
    png = encode_image_png(pre.ocr_bgr)
    assert len(png) > 50


def test_deskew_small_rotation() -> None:
    import cv2

    img = np.full((300, 400, 3), 255, dtype=np.uint8)
    for x in range(30, 370, 20):
        cv2.rectangle(img, (x, 80), (x + 10, 120), (0, 0, 0), -1)
    # rotate ~5 deg
    m = cv2.getRotationMatrix2D((200, 150), 5, 1.0)
    rot = cv2.warpAffine(img, m, (400, 300), borderValue=(255, 255, 255))
    pre = preprocess_for_ocr(
        rot,
        options=PreprocessOptions(deskew=True, denoise=False, max_side=2000),
    )
    assert any(s.startswith("deskew:") for s in pre.steps)
