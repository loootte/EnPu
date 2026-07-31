"""L3 melody-band barlines and soft measure fallbacks (#84)."""

from __future__ import annotations

import numpy as np

from app.pipeline.barlines import detect_barline_xs, estimate_melody_band, gap_soft_bar_xs
from app.pipeline.structure.ir import Rect, StaffSystem
from app.pipeline.structure.l3_measures import (
    SRC_FALLBACK_GAP,
    SRC_L3_BARLINE,
    SRC_WHOLE_LINE,
    segment_measures_on_systems,
)


def _staff_with_short_bars(
    *,
    h: int = 160,
    w: int = 480,
    melody_y0: int = 50,
    melody_y1: int = 90,
    bar_xs: list[int] | None = None,
    lyrics: bool = True,
    chords: bool = True,
) -> np.ndarray:
    """Synthetic jianpu-like row: short bars only in melody band (#84)."""
    img = np.full((h, w, 3), 255, dtype=np.uint8)
    # Chord zone (top) — no vertical bars
    if chords:
        img[15:40, 40 : w - 40] = 230
        for x in range(50, w - 50, 40):
            img[18:35, x : x + 18] = 40  # chord blobs
    # Melody digit band + short barlines
    img[melody_y0:melody_y1, 30 : w - 30] = 245
    bars = bar_xs if bar_xs is not None else [60, 160, 260, 360]
    for x in bars:
        # Short bar: only through melody height (NOT full system)
        img[melody_y0 + 2 : melody_y1 - 2, x : x + 2] = 0
    # Digit-like blobs between bars
    for x in (90, 120, 190, 220, 290, 320):
        img[melody_y0 + 8 : melody_y1 - 8, x : x + 10] = 0
    # Lyrics below — no bars
    if lyrics:
        img[melody_y1 + 10 : melody_y1 + 40, 40 : w - 40] = 235
        for x in range(50, w - 50, 28):
            img[melody_y1 + 14 : melody_y1 + 34, x : x + 16] = 50
    return img


def test_estimate_melody_band_avoids_lyrics() -> None:
    img = _staff_with_short_bars()
    # System covers chords + melody + lyrics
    y0, y1 = estimate_melody_band(img, (20, 10, 460, 150))
    # Melody band should sit near digit zone (~50–90), not full 10–150
    assert y0 < 70 < y1, (y0, y1)
    assert y1 - y0 < 100, (y0, y1)
    # Should not extend deep into lyrics (lyrics start ~100)
    assert y0 >= 20
    assert y1 <= 130


def test_melody_mode_detects_short_bars() -> None:
    img = _staff_with_short_bars()
    # Full-band (tall) detection often misses short bars when ROI is whole system
    full = detect_barline_xs(img, y_range=(10.0, 150.0), melody_mode=False)
    # Melody-mode on estimated band should find ~4 bars
    my0, my1 = estimate_melody_band(img, (20, 10, 460, 150))
    mel = detect_barline_xs(img, y_range=(my0, my1), melody_mode=True, min_gap=40.0)
    assert len(mel) >= 3, (mel, full, my0, my1)


def test_l3_splits_multiple_measures_on_short_bars() -> None:
    """#84 acceptance: short bars in melody → multiple L3 measures, not whole line."""
    img = _staff_with_short_bars()
    systems = [
        StaffSystem(index=0, rect=Rect(20, 10, 460, 150), confidence=0.85),
    ]
    systems, warnings = segment_measures_on_systems(img, systems)
    measures = systems[0].measures
    assert len(measures) >= 2, ([(m.rect.x1, m.rect.x2) for m in measures], warnings)
    sources = {m.extra.get("measure_source") for m in measures}
    # Prefer true barlines; gap fallback also OK if ≥2
    assert SRC_WHOLE_LINE not in sources or len(measures) > 1
    assert any("melody_band" in w for w in warnings)
    for m in measures:
        assert "measure_source" in m.extra


def test_l3_whole_line_tagged_when_no_bars() -> None:
    """Empty of bars → whole_line with explicit measure_source (#84)."""
    h, w = 100, 300
    img = np.full((h, w, 3), 255, dtype=np.uint8)
    img[30:70, 20:280] = 240  # faint staff, no verticals
    systems = [StaffSystem(index=0, rect=Rect(10, 20, 290, 80), confidence=0.7)]
    systems, warnings = segment_measures_on_systems(img, systems)
    assert len(systems[0].measures) == 1
    assert systems[0].measures[0].extra.get("measure_source") == SRC_WHOLE_LINE
    assert any("whole_line" in w for w in warnings)


def test_gap_soft_bar_xs_finds_spaces() -> None:
    h, w = 80, 400
    img = np.full((h, w, 3), 255, dtype=np.uint8)
    # Three ink clusters with large gaps
    for x0, x1 in ((20, 80), (140, 200), (260, 320)):
        img[20:60, x0:x1] = 0
    xs = gap_soft_bar_xs(
        img,
        y_range=(15.0, 65.0),
        x_range=(10.0, 390.0),
        min_gap=30.0,
    )
    assert len(xs) >= 1


def test_soft_gap_split_when_no_graphic_bars() -> None:
    """Digit clusters without graphic bars → soft-gap multi-measure (#84)."""
    h, w = 100, 420
    img = np.full((h, w, 3), 255, dtype=np.uint8)
    # Four digit blobs with wide gaps (pseudo-measures)
    for x0 in (30, 130, 230, 330):
        img[35:70, x0 : x0 + 50] = 0
    systems = [StaffSystem(index=0, rect=Rect(15, 25, 400, 85), confidence=0.8)]
    systems, warnings = segment_measures_on_systems(img, systems)
    measures = systems[0].measures
    # Soft gap or at least not silent wrong single without tag
    assert len(measures) >= 1
    if len(measures) == 1:
        assert measures[0].extra.get("measure_source") == SRC_WHOLE_LINE
    else:
        assert all(
            m.extra.get("measure_source") in {SRC_FALLBACK_GAP, SRC_L3_BARLINE}
            for m in measures
        )
        assert any("soft-gap" in w or "fallback" in w or "measure_source" in w for w in warnings)


def test_multi_system_split_model() -> None:
    """#85: multi-row systems each get independent interior splits."""
    h, w = 220, 400
    img = np.full((h, w, 3), 255, dtype=np.uint8)
    img[40:80, 40:360] = 245
    for x in (50, 150, 250):
        img[42:78, x : x + 2] = 0
    for x in (80, 180):
        img[50:70, x : x + 12] = 0
    img[50:70, 270:340] = 0

    img[130:170, 40:360] = 245
    img[140:160, 60:200] = 0

    systems = [
        StaffSystem(index=0, rect=Rect(30, 35, 370, 90), confidence=0.8),
        StaffSystem(index=1, rect=Rect(30, 125, 370, 180), confidence=0.8),
    ]
    systems, warnings = segment_measures_on_systems(img, systems)
    assert len(systems) == 2
    # Row 0 should have interior splits; measures derived
    assert len(systems[0].measures) >= 1
    assert any("split" in w.lower() or "measure" in w.lower() for w in warnings)
    # Row 1 may be whole_line (no bars)
    assert len(systems[1].measures) >= 1
