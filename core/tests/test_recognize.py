"""Tests for POST /v1/recognize (mock)."""

from __future__ import annotations

import io

from fastapi.testclient import TestClient
from PIL import Image

from app.main import app

client = TestClient(app)


def _png_bytes(width: int = 32, height: int = 24) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), color=(255, 255, 255)).save(buf, format="PNG")
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
    assert body["boxes"] == []
    assert body["notes"] == []
    assert body["meta"]["width"] == 40
    assert body["meta"]["height"] == 30
    assert body["meta"]["mock"] is True
    assert body["meta"]["filename"] == "sample.png"
    assert isinstance(body["meta"]["elapsed_ms"], int)


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
