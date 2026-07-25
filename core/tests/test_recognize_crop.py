"""Tests for POST /v1/recognize/crop (issue #49)."""

from __future__ import annotations

import io
import json

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw, ImageFont

from app.main import app

client = TestClient(app)


def _digit_sheet_png() -> bytes:
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


def _base_score_json() -> str:
    return json.dumps(
        {
            "schema_version": "0.1",
            "title": "hand",
            "key": "G",
            "time_signature": "4/4",
            "parts": [
                {
                    "id": "P1",
                    "name": "melody",
                    "measures": [
                        {
                            "number": 1,
                            "notes": [
                                {
                                    "pitch": "1",
                                    "duration": "quarter",
                                    "octave": 0,
                                    "dots": 0,
                                    "is_rest": False,
                                    "lyric": "保留",
                                }
                            ],
                        },
                        {
                            "number": 2,
                            "notes": [
                                {
                                    "pitch": "2",
                                    "duration": "quarter",
                                    "octave": 0,
                                    "dots": 0,
                                    "is_rest": False,
                                }
                            ],
                        },
                        {
                            "number": 3,
                            "notes": [
                                {
                                    "pitch": "3",
                                    "duration": "quarter",
                                    "octave": 0,
                                    "dots": 0,
                                    "is_rest": False,
                                    "lyric": "手改",
                                }
                            ],
                        },
                    ],
                }
            ],
        }
    )


def test_recognize_crop_mock() -> None:
    data = _digit_sheet_png()
    response = client.post(
        "/v1/recognize/crop",
        data={"x1": 10, "y1": 20, "x2": 200, "y2": 100},
        files={"file": ("digits.png", data, "image/png")},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is True
    assert body["engine"] == "mock"
    assert "crop" in body
    assert body["crop"]["x1"] == 10
    assert body["meta"]["width"] == 320
    assert body["meta"]["height"] == 120
    assert any("crop:" in s for s in body["meta"]["preprocess_steps"])
    # boxes remapped into full image space (offset by crop origin)
    if body["boxes"]:
        assert body["boxes"][0]["x1"] >= 10
        assert body["boxes"][0]["y1"] >= 20


def test_recognize_crop_merge_preserves_outside() -> None:
    data = _digit_sheet_png()
    response = client.post(
        "/v1/recognize/crop",
        data={
            "x1": 0,
            "y1": 0,
            "x2": 160,
            "y2": 60,
            "base_score": _base_score_json(),
            "measure_from": "2",
            "measure_to": "2",
        },
        files={"file": ("digits.png", data, "image/png")},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["merged_score"] is not None
    assert body["merge"]["preserved_outside"] is True
    measures = body["merged_score"]["parts"][0]["measures"]
    # First measure kept with hand lyric
    assert measures[0]["notes"][0]["lyric"] == "保留"
    # Last measure (was #3) still has hand lyric somewhere if still present
    lyrics = [m["notes"][0].get("lyric") for m in measures]
    assert "手改" in lyrics
    # Key from base preserved
    assert body["merged_score"]["key"] == "G"


def test_recognize_crop_rejects_tiny_rect() -> None:
    data = _digit_sheet_png()
    response = client.post(
        "/v1/recognize/crop",
        data={"x1": 1, "y1": 1, "x2": 3, "y2": 3},
        files={"file": ("digits.png", data, "image/png")},
    )
    assert response.status_code == 400


def test_recognize_crop_bad_base_score() -> None:
    data = _digit_sheet_png()
    response = client.post(
        "/v1/recognize/crop",
        data={
            "x1": 0,
            "y1": 0,
            "x2": 100,
            "y2": 80,
            "base_score": "{not-json",
        },
        files={"file": ("digits.png", data, "image/png")},
    )
    assert response.status_code == 400


def test_openapi_has_crop() -> None:
    response = client.get("/openapi.json")
    assert response.status_code == 200
    assert "/v1/recognize/crop" in response.json()["paths"]
