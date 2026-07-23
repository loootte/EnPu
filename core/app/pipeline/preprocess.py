"""Image preprocessing with OpenCV."""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


class ImageDecodeError(ValueError):
    """Raised when bytes cannot be decoded as an image."""


@dataclass(frozen=True)
class PreprocessResult:
    """Preprocessed image ready for OCR plus simple stats."""

    original_bgr: np.ndarray
    ocr_bgr: np.ndarray
    width: int
    height: int
    scale: float
    steps: list[str]


def decode_image_bytes(data: bytes) -> np.ndarray:
    """Decode image bytes to BGR ``numpy`` array."""
    if not data:
        raise ImageDecodeError("Empty image bytes.")
    arr = np.frombuffer(data, dtype=np.uint8)
    image = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if image is None:
        raise ImageDecodeError("File is not a valid image.")
    return image


def preprocess_for_ocr(
    image_bgr: np.ndarray,
    *,
    max_side: int = 2000,
    denoise: bool = True,
) -> PreprocessResult:
    """Light preprocessing suitable for PaddleOCR on jianpu scans.

    Steps (PoC — accuracy not the goal):
    1. Optional downscale if the long side exceeds ``max_side``
    2. Grayscale + (optional) bilateral denoise
    3. Convert back to 3-channel BGR for PaddleOCR
    """
    if image_bgr is None or image_bgr.size == 0:
        raise ImageDecodeError("Empty image array.")

    steps: list[str] = ["decode"]
    height, width = image_bgr.shape[:2]
    work = image_bgr
    scale = 1.0

    long_side = max(height, width)
    if max_side > 0 and long_side > max_side:
        scale = max_side / float(long_side)
        new_w = max(1, int(round(width * scale)))
        new_h = max(1, int(round(height * scale)))
        work = cv2.resize(work, (new_w, new_h), interpolation=cv2.INTER_AREA)
        steps.append(f"resize:{width}x{height}->{new_w}x{new_h}")
        height, width = new_h, new_w

    gray = cv2.cvtColor(work, cv2.COLOR_BGR2GRAY)
    steps.append("grayscale")

    if denoise:
        # Mild denoise; keeps strokes better than heavy blur for sheet music.
        gray = cv2.bilateralFilter(gray, d=5, sigmaColor=50, sigmaSpace=50)
        steps.append("bilateral_denoise")

    # Adaptive threshold can help washed-out scans; keep as optional branch.
    # For PoC we feed a 3-channel image (OCR models often expect color input).
    ocr_bgr = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    steps.append("to_bgr")

    return PreprocessResult(
        original_bgr=image_bgr,
        ocr_bgr=ocr_bgr,
        width=int(image_bgr.shape[1]),
        height=int(image_bgr.shape[0]),
        scale=scale,
        steps=steps,
    )
