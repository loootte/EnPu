"""Tests for POST /v1/recognize."""

from __future__ import annotations

import io

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw, ImageFont

from app.main import app

client = TestClient(app)


def _png_bytes(width: int = 32, height: int = 24) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), color=(255, 255, 255)).save(buf, format="PNG")
    return buf.getvalue()


def _digit_sheet_png() -> bytes:
    """Synthetic jianpu-like sheet with digits for preprocess/OCR path tests."""
    img = Image.new("RGB", (320, 120), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arial.ttf", 36)
    except OSError:
        font = ImageFont.load_default()
    draw.text((20, 40), "1 2 3 5 6", fill=(0, 0, 0), font=font)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_recognize_mock_png() -> None:
    data = _png_bytes(40, 30)
    response = client.post(
        "/v1/recognize",
        files={"file": ("sample.png", data, "image/png")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["engine"] == "mock"
    assert body["texts"] == ["1", "2", "3", "主", "恩"]
    assert body["meta"]["width"] == 40
    assert body["meta"]["height"] == 30
    assert body["meta"]["mock"] is True
    assert "decode" in body["meta"]["preprocess_steps"]
    assert body["notes"]  # digits extracted from mock texts
    assert {n["pitch"] for n in body["notes"] if n.get("pitch")} >= {"1", "2", "3"}


def test_recognize_jpeg_by_extension() -> None:
    buf = io.BytesIO()
    Image.new("RGB", (10, 10), color=(0, 0, 0)).save(buf, format="JPEG")
    data = buf.getvalue()
    response = client.post(
        "/v1/recognize",
        files={"file": ("score.jpg", data, "application/octet-stream")},
    )
    assert response.status_code == 200
    assert response.json()["meta"]["width"] == 10


def test_recognize_rejects_empty() -> None:
    response = client.post(
        "/v1/recognize",
        files={"file": ("empty.png", b"", "image/png")},
    )
    assert response.status_code == 400
    assert "Empty" in response.json()["detail"]


def test_recognize_rejects_non_image() -> None:
    response = client.post(
        "/v1/recognize",
        files={"file": ("notes.txt", b"hello", "text/plain")},
    )
    assert response.status_code == 400


def test_recognize_rejects_invalid_image_bytes() -> None:
    response = client.post(
        "/v1/recognize",
        files={"file": ("bad.png", b"not-an-image", "image/png")},
    )
    assert response.status_code == 400


def test_openapi_available() -> None:
    response = client.get("/openapi.json")
    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/health" in paths
    assert "/v1/recognize" in paths


def test_preprocess_pipeline_on_digit_sheet() -> None:
    """Exercise OpenCV path even under mock OCR."""
    data = _digit_sheet_png()
    response = client.post(
        "/v1/recognize",
        files={"file": ("digits.png", data, "image/png")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["meta"]["width"] == 320
    assert body["meta"]["height"] == 120
    assert any("grayscale" in s for s in body["meta"]["preprocess_steps"])
