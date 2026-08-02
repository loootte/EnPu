"""Tests for learned L1–L3 structure engine (#104)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from app.config import Settings, clear_settings_cache
from app.pipeline.structure.learned.adapter import systems_splits_to_page_layout
from app.pipeline.structure.learned.loader import (
    WeightsLoadError,
    clear_layout_model_cache,
    load_layout_weights,
)
from app.pipeline.structure.learned.postprocess import (
    decode_peaks,
    l2_heat_to_system_boxes,
    l3_heat_to_split_xs,
)
from app.pipeline.structure.pipeline import run_structure_recognize


def test_decode_peaks_and_boxes() -> None:
    heat = np.zeros(64, dtype=np.float32)
    heat[10] = 0.9
    heat[40] = 0.8
    peaks = decode_peaks(heat, min_prominence=0.3, min_gap=5)
    assert 10 in peaks and 40 in peaks
    boxes = l2_heat_to_system_boxes(
        heat, orig_h=400, orig_w=300, page_h=384, page_w=512
    )
    assert len(boxes) >= 1
    xs = l3_heat_to_split_xs(heat, x_left=10, x_right=290)
    assert all(10 < x < 290 for x in xs)


def test_adapter_normalize_splits() -> None:
    layout = systems_splits_to_page_layout(
        width=400,
        height=300,
        system_boxes=[{"x1": 20, "y1": 80, "x2": 380, "y2": 140}],
        splits_per_system=[[100, 200, 300]],
    )
    assert len(layout.systems) == 1
    sys = layout.systems[0]
    assert len(sys.splits) == 3
    assert len(sys.measures) == 4
    assert sys.measures[0].rect.x1 == pytest.approx(20)


def test_load_missing_weights() -> None:
    with pytest.raises(WeightsLoadError):
        load_layout_weights(Path("does_not_exist.pt"))


def test_load_real_weights_if_present() -> None:
    root = Path(__file__).resolve().parents[2]
    candidates = [
        root / "train" / "runs" / "mvp_l2_l3" / "export" / "layout_net.pt",
        root / "train" / "runs" / "mvp_l2_l3" / "best.pt",
    ]
    path = next((p for p in candidates if p.is_file()), None)
    if path is None:
        pytest.skip("no train weights in repo")
    clear_layout_model_cache()
    model, meta = load_layout_weights(path, device="cpu")
    assert "l2" in meta["tasks"]
    # forward smoke
    import torch

    page = torch.rand(1, 3, model.cfg.page_h, model.cfg.page_w)
    with torch.no_grad():
        out = model(page=page)
    assert out["l2_logits"].shape[-1] == model.cfg.l2_heat_len


def test_pipeline_rule_default_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_settings_cache()
    monkeypatch.setenv("ENPU_RECOGNIZE_ENGINE", "mock")
    monkeypatch.setenv("ENPU_PIPELINE_MODE", "structure")
    monkeypatch.setenv("ENPU_STRUCTURE_L1L3_ENGINE", "rule")
    clear_settings_cache()
    # synthetic-ish page
    img = np.full((200, 300, 3), 255, dtype=np.uint8)
    img[60:90, 20:280] = 30
    img[120:150, 20:280] = 30
    for x in (40, 100, 160, 220):
        img[55:155, x : x + 2] = 0
    import cv2

    ok, buf = cv2.imencode(".png", img)
    assert ok
    settings = Settings()
    resp = run_structure_recognize(buf.tobytes(), settings=settings, filename="t.png")
    assert resp.ok
    assert resp.structure is not None
    assert any("l1l3_engine=rule" in w for w in (resp.meta.parse_warnings or []))


def test_pipeline_learned_fallback_when_no_weights(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_settings_cache()
    clear_layout_model_cache()
    monkeypatch.setenv("ENPU_RECOGNIZE_ENGINE", "mock")
    monkeypatch.setenv("ENPU_PIPELINE_MODE", "structure")
    monkeypatch.setenv("ENPU_STRUCTURE_L1L3_ENGINE", "learned")
    monkeypatch.setenv("ENPU_L1L3_WEIGHTS", "")
    monkeypatch.setenv("ENPU_L1L3_FALLBACK", "rule")
    clear_settings_cache()
    img = np.full((200, 300, 3), 255, dtype=np.uint8)
    img[60:90, 20:280] = 30
    import cv2

    ok, buf = cv2.imencode(".png", img)
    assert ok
    settings = Settings()
    resp = run_structure_recognize(buf.tobytes(), settings=settings, filename="t.png")
    assert resp.ok
    warns = resp.meta.parse_warnings or []
    assert any("fallback" in w.lower() or "failed" in w.lower() for w in warns)


def test_pipeline_learned_with_weights_if_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = Path(__file__).resolve().parents[2]
    path = root / "train" / "runs" / "mvp_l2_l3" / "best.pt"
    if not path.is_file():
        pytest.skip("no weights")
    clear_settings_cache()
    clear_layout_model_cache()
    monkeypatch.setenv("ENPU_RECOGNIZE_ENGINE", "mock")
    monkeypatch.setenv("ENPU_PIPELINE_MODE", "structure")
    monkeypatch.setenv("ENPU_STRUCTURE_L1L3_ENGINE", "learned")
    monkeypatch.setenv("ENPU_L1L3_WEIGHTS", str(path))
    monkeypatch.setenv("ENPU_L1L3_DEVICE", "cpu")
    monkeypatch.setenv("ENPU_L1L3_FALLBACK", "rule")
    clear_settings_cache()

    # use real layout sample if available
    sample = root / "samples" / "layout" / "L001_zuozai_baozuo" / "image.png"
    if sample.is_file():
        data = sample.read_bytes()
    else:
        img = np.full((400, 600, 3), 255, dtype=np.uint8)
        for y0 in (80, 160, 240, 320):
            img[y0 : y0 + 40, 30:570] = 40
            for x in range(80, 560, 90):
                img[y0 : y0 + 40, x : x + 3] = 255
        import cv2

        ok, buf = cv2.imencode(".png", img)
        assert ok
        data = buf.tobytes()

    settings = Settings()
    resp = run_structure_recognize(data, settings=settings, filename="learned.png")
    assert resp.ok
    assert resp.structure is not None
    assert resp.structure.items
    warns = " ".join(resp.meta.parse_warnings or [])
    # either learned succeeded or fell back
    assert "l1l3" in warns.lower() or "learned" in warns.lower() or "rule" in warns.lower()
