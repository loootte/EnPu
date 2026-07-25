"""Image preprocessing with OpenCV (#3 base · #47 toolbox)."""

from __future__ import annotations

from dataclasses import dataclass, field, replace

import cv2
import numpy as np


class ImageDecodeError(ValueError):
    """Raised when bytes cannot be decoded as an image."""


@dataclass(frozen=True)
class PreprocessOptions:
    """User/API-tunable preprocess knobs (#47). All OpenCV-only."""

    max_side: int = 2000
    denoise: bool = True
    deskew: bool = False
    clahe: bool = False
    shadow_remove: bool = False
    adaptive_binary: bool = False
    # brightness additive in [-80, 80]; contrast multiplier in [0.4, 2.5]
    brightness: float = 0.0
    contrast: float = 1.0
    # Optional crop in **input image** pixels (before scale)
    crop_x1: float | None = None
    crop_y1: float | None = None
    crop_x2: float | None = None
    crop_y2: float | None = None

    def has_crop(self) -> bool:
        return (
            self.crop_x1 is not None
            and self.crop_y1 is not None
            and self.crop_x2 is not None
            and self.crop_y2 is not None
        )


@dataclass(frozen=True)
class PreprocessResult:
    """Preprocessed image ready for OCR plus simple stats."""

    original_bgr: np.ndarray
    ocr_bgr: np.ndarray
    width: int
    height: int
    scale: float
    steps: list[str]
    # Output image size (after crop/resize) for UI preview
    out_width: int = 0
    out_height: int = 0
    options: PreprocessOptions = field(default_factory=PreprocessOptions)


def decode_image_bytes(data: bytes) -> np.ndarray:
    """Decode image bytes to BGR ``numpy`` array."""
    if not data:
        raise ImageDecodeError("Empty image bytes.")
    arr = np.frombuffer(data, dtype=np.uint8)
    image = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if image is None:
        raise ImageDecodeError("File is not a valid image.")
    return image


def encode_image_png(image_bgr: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".png", image_bgr)
    if not ok:
        raise ImageDecodeError("Failed to encode PNG.")
    return buf.tobytes()


def preprocess_for_ocr(
    image_bgr: np.ndarray,
    *,
    max_side: int = 2000,
    denoise: bool = True,
    options: PreprocessOptions | None = None,
) -> PreprocessResult:
    """Preprocess for PaddleOCR / structure pipeline.

    Default path matches historical behavior (scale + gray + bilateral).
    Extra steps from ``options`` (#47): crop, deskew, CLAHE, shadow, binary,
    brightness/contrast.
    """
    if image_bgr is None or image_bgr.size == 0:
        raise ImageDecodeError("Empty image array.")

    opts = options or PreprocessOptions(max_side=max_side, denoise=denoise)
    # Allow legacy kwargs to override defaults when options not fully set
    if options is None:
        opts = PreprocessOptions(max_side=max_side, denoise=denoise)
    else:
        opts = replace(
            opts,
            max_side=opts.max_side if opts.max_side else max_side,
        )

    steps: list[str] = ["decode"]
    original = image_bgr
    work = image_bgr.copy()
    h0, w0 = work.shape[:2]
    scale = 1.0

    # --- crop (input coords)
    if opts.has_crop():
        x1 = int(max(0, min(w0 - 1, round(opts.crop_x1 or 0))))
        y1 = int(max(0, min(h0 - 1, round(opts.crop_y1 or 0))))
        x2 = int(max(x1 + 1, min(w0, round(opts.crop_x2 or w0))))
        y2 = int(max(y1 + 1, min(h0, round(opts.crop_y2 or h0))))
        work = work[y1:y2, x1:x2].copy()
        steps.append(f"crop:{x1},{y1},{x2},{y2}")
        h0, w0 = work.shape[:2]

    # --- deskew (before heavy downscale for better angle estimate)
    if opts.deskew:
        work, angle = _deskew_bgr(work)
        if abs(angle) > 0.05:
            steps.append(f"deskew:{angle:.2f}deg")
        else:
            steps.append("deskew:0")

    # --- resize
    height, width = work.shape[:2]
    long_side = max(height, width)
    max_side = opts.max_side
    if max_side > 0 and long_side > max_side:
        scale = max_side / float(long_side)
        new_w = max(1, int(round(width * scale)))
        new_h = max(1, int(round(height * scale)))
        work = cv2.resize(work, (new_w, new_h), interpolation=cv2.INTER_AREA)
        steps.append(f"resize:{width}x{height}->{new_w}x{new_h}")
        height, width = new_h, new_w

    # --- brightness / contrast (on BGR)
    if abs(opts.brightness) > 0.5 or abs(opts.contrast - 1.0) > 0.02:
        work = _adjust_brightness_contrast(work, opts.brightness, opts.contrast)
        steps.append(f"bc:b={opts.brightness:.0f},c={opts.contrast:.2f}")

    gray = cv2.cvtColor(work, cv2.COLOR_BGR2GRAY)
    steps.append("grayscale")

    if opts.shadow_remove:
        gray = _remove_shadows(gray)
        steps.append("shadow_remove")

    if opts.clahe:
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        gray = clahe.apply(gray)
        steps.append("clahe")

    if opts.denoise:
        gray = cv2.bilateralFilter(gray, d=5, sigmaColor=50, sigmaSpace=50)
        steps.append("bilateral_denoise")

    if opts.adaptive_binary:
        # Invert so ink is dark-on-light again after THRESH_BINARY_INV? 
        # Paddle often likes dark text on light — keep black text on white.
        bin_img = cv2.adaptiveThreshold(
            gray,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            31,
            12,
        )
        gray = bin_img
        steps.append("adaptive_binary")

    ocr_bgr = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    steps.append("to_bgr")

    oh, ow = ocr_bgr.shape[:2]
    return PreprocessResult(
        original_bgr=original,
        ocr_bgr=ocr_bgr,
        width=int(original.shape[1]),
        height=int(original.shape[0]),
        scale=scale,
        steps=steps,
        out_width=ow,
        out_height=oh,
        options=opts,
    )


def _adjust_brightness_contrast(
    bgr: np.ndarray,
    brightness: float,
    contrast: float,
) -> np.ndarray:
    b = float(np.clip(brightness, -80.0, 80.0))
    c = float(np.clip(contrast, 0.4, 2.5))
    # out = c * img + b
    out = cv2.convertScaleAbs(bgr, alpha=c, beta=b)
    return out


def _remove_shadows(gray: np.ndarray) -> np.ndarray:
    """Normalize uneven illumination (page photo shadows)."""
    # Large morphological open approximates background
    k = max(15, (min(gray.shape[:2]) // 25) | 1)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    bg = cv2.morphologyEx(gray, cv2.MORPH_CLOSE, kernel)
    bg = cv2.GaussianBlur(bg, (0, 0), sigmaX=k / 3.0)
    # Divide: gray / bg * 255
    bg_f = bg.astype(np.float32) + 1.0
    norm = (gray.astype(np.float32) / bg_f) * 255.0
    return np.clip(norm, 0, 255).astype(np.uint8)


def _deskew_bgr(bgr: np.ndarray) -> tuple[np.ndarray, float]:
    """Estimate small page tilt and rotate. Returns (image, angle_deg)."""
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape[:2]
    # Binary ink
    thr = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    # Focus on central mass to ignore margins
    coords = cv2.findNonZero(thr)
    if coords is None or len(coords) < 80:
        return bgr, 0.0
    rect = cv2.minAreaRect(coords)
    angle = rect[-1]
    # minAreaRect angle in (-90, 0]
    if angle < -45:
        angle = 90.0 + angle
    # Only correct modest skew (scan/photo)
    if abs(angle) < 0.3 or abs(angle) > 15.0:
        return bgr, 0.0
    # Rotate around center; expand canvas slightly
    m = cv2.getRotationMatrix2D((w / 2.0, h / 2.0), angle, 1.0)
    cos = abs(m[0, 0])
    sin = abs(m[0, 1])
    nw = int(h * sin + w * cos)
    nh = int(h * cos + w * sin)
    m[0, 2] += (nw / 2) - w / 2
    m[1, 2] += (nh / 2) - h / 2
    rotated = cv2.warpAffine(
        bgr,
        m,
        (nw, nh),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(255, 255, 255),
    )
    return rotated, float(angle)


def options_from_form(
    *,
    max_side: int | None = None,
    denoise: bool | None = None,
    deskew: bool | None = None,
    clahe: bool | None = None,
    shadow_remove: bool | None = None,
    adaptive_binary: bool | None = None,
    brightness: float | None = None,
    contrast: float | None = None,
    crop_x1: float | None = None,
    crop_y1: float | None = None,
    crop_x2: float | None = None,
    crop_y2: float | None = None,
    defaults: PreprocessOptions | None = None,
) -> PreprocessOptions:
    """Build options from optional API form fields."""
    base = defaults or PreprocessOptions()
    return PreprocessOptions(
        max_side=int(max_side) if max_side is not None else base.max_side,
        denoise=bool(denoise) if denoise is not None else base.denoise,
        deskew=bool(deskew) if deskew is not None else base.deskew,
        clahe=bool(clahe) if clahe is not None else base.clahe,
        shadow_remove=bool(shadow_remove)
        if shadow_remove is not None
        else base.shadow_remove,
        adaptive_binary=bool(adaptive_binary)
        if adaptive_binary is not None
        else base.adaptive_binary,
        brightness=float(brightness) if brightness is not None else base.brightness,
        contrast=float(contrast) if contrast is not None else base.contrast,
        crop_x1=crop_x1 if crop_x1 is not None else base.crop_x1,
        crop_y1=crop_y1 if crop_y1 is not None else base.crop_y1,
        crop_x2=crop_x2 if crop_x2 is not None else base.crop_x2,
        crop_y2=crop_y2 if crop_y2 is not None else base.crop_y2,
    )
