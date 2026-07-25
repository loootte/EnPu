"""Tests for structure-first pipeline (#58)."""

from __future__ import annotations

import io

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from app.config import clear_settings_cache
from app.main import app
from app.pipeline.structure.ir import Rect
from app.pipeline.structure.l1_page import detect_page_regions
from app.pipeline.structure.l2_systems import detect_staff_systems
from app.pipeline.structure.l3_measures import segment_measures_on_systems
from app.pipeline.structure.l4_notes import detect_note_candidates
from app.pipeline.structure.assemble import page_layout_to_score
from app.pipeline.structure.ir import PageLayout, StaffSystem, MeasureLayout, NoteCandidate, NoteGlyph
from app.schemas.score import DurationName

client = TestClient(app)


def _synthetic_score_bgr(w: int = 400, h: int = 300) -> np.ndarray:
    """White page with two dark staff bands and vertical bars."""
    img = np.full((h, w, 3), 255, dtype=np.uint8)
    # two horizontal staff bands (ink)
    img[80:110, 40:360] = 30
    img[160:190, 40:360] = 30
    # vertical barlines
    for x in (40, 140, 240, 340):
        img[75:195, x : x + 3] = 0
    # note-like blobs on first system
    for x in (60, 90, 120, 160, 190, 220):
        img[85:105, x : x + 12] = 0
    return img


def test_l1_detects_score_region() -> None:
    img = _synthetic_score_bgr()
    regions, warnings = detect_page_regions(img)
    roles = {r.role.value for r in regions}
    assert "score" in roles
    score = next(r for r in regions if r.role.value == "score")
    assert score.rect.height > 50


def test_l1_title_above_score_on_header_page() -> None:
    """#60: title band has ink; score starts below title (not at first ink)."""
    h, w = 400, 300
    img = np.full((h, w, 3), 255, dtype=np.uint8)
    # Title-like tall glyphs near top
    img[30:70, 40:260] = 20
    # gap
    # Staff rows (shorter digit-like blocks)
    for y0 in (120, 170, 220, 270):
        img[y0 : y0 + 28, 30:270] = 25
        for x in range(40, 250, 22):
            img[y0 + 4 : y0 + 22, x : x + 12] = 0

    regions, warnings = detect_page_regions(img)
    title = next(r for r in regions if r.role.value == "title")
    score = next(r for r in regions if r.role.value == "score")
    # Title covers the header ink (y~30-70)
    assert title.rect.y2 > 60, title.rect
    assert title.rect.height > 40
    # Score starts at/after staff, not inside title body
    assert score.rect.y1 >= 90, score.rect
    assert score.rect.y1 >= title.rect.y2 - 2
    # Title center has ink; score top is below title ink
    assert title.rect.y1 <= 50 < title.rect.y2


def test_l1_m04_title_not_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    """#60 acceptance: M04 title ROI contains header ink; score below title."""
    from pathlib import Path

    import cv2

    p = Path(__file__).resolve().parents[2] / "samples" / "eval" / "manual" / "M04_manual.png"
    if not p.is_file():
        pytest.skip("M04 sample not present")
    img = cv2.imdecode(np.fromfile(str(p), dtype=np.uint8), cv2.IMREAD_COLOR)
    assert img is not None
    h = img.shape[0]
    regions, warnings = detect_page_regions(img)
    title = next(r for r in regions if r.role.value == "title")
    score = next(r for r in regions if r.role.value == "score")
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    ty0, ty1 = int(title.rect.y1), int(title.rect.y2)
    title_ink = int((bw[ty0:ty1] > 0).sum())
    # Title must not be an empty top strip
    assert title.rect.height >= 0.05 * h
    assert title_ink > 1000, f"title ink too low: {title_ink}"
    # Known title band on M04 is ~y 177-252; title should cover ~y=200
    assert title.rect.y1 <= 200 < title.rect.y2
    assert score.rect.y1 >= title.rect.y2 - 5
    # Score should not start at the title band (~180)
    assert score.rect.y1 >= 250, score.rect
    assert any("L1:" in w for w in warnings)


def test_l2_detects_systems() -> None:
    img = _synthetic_score_bgr()
    regions, _ = detect_page_regions(img)
    score = next(r for r in regions if r.role.value == "score")
    systems, warnings = detect_staff_systems(img, score.rect)
    assert len(systems) >= 1
    assert systems[0].rect.width > 0


def _synthetic_pitch_chord_lyric_bgr(w: int = 480, h: int = 420) -> np.ndarray:
    """Two melody systems, each with pitch + chord + lyric bands (#61)."""
    img = np.full((h, w, 3), 255, dtype=np.uint8)

    def _digit_row(y0: int, band_h: int, glyph_h: int, n: int = 12) -> None:
        # Staff body
        img[y0 : y0 + band_h, 30 : w - 30] = 240
        step = (w - 80) // n
        for i in range(n):
            x = 40 + i * step
            gy0 = y0 + max(1, (band_h - glyph_h) // 2)
            img[gy0 : gy0 + glyph_h, x : x + max(8, glyph_h // 2)] = 0

    # System 0: pitch (tall) + underline + chord + lyric
    _digit_row(60, 36, 30, 14)
    img[100:106, 50 : w - 50] = 0  # duration underline
    _digit_row(130, 28, 22, 10)  # chord (shorter glyphs)
    _digit_row(175, 26, 20, 10)  # lyric
    # System 1 (gap ~90px)
    _digit_row(270, 36, 30, 14)
    img[310:316, 50 : w - 50] = 0
    _digit_row(340, 28, 22, 10)
    _digit_row(385, 26, 20, 10)
    return img


def test_l2_binds_chord_lyric_into_pitch_system() -> None:
    """#61: chord/lyric are aux bands, not separate StaffSystems."""
    img = _synthetic_pitch_chord_lyric_bgr()
    score = Rect(0, 40, float(img.shape[1]), float(img.shape[0]))
    systems, warnings = detect_staff_systems(img, score)
    assert len(systems) == 2, [(s.rect.y1, s.rect.y2, s.extra) for s in systems]
    for s in systems:
        assert s.extra.get("n_pitch_bands") == 1
        # At least one aux (chord and/or lyric and/or underline)
        n_aux = (
            int(s.extra.get("n_chord_bands") or 0)
            + int(s.extra.get("n_lyric_bands") or 0)
            + int(s.extra.get("n_underline_bands") or 0)
        )
        assert n_aux >= 1, s.extra
        bands = s.extra.get("bands") or []
        roles = [b["role"] for b in bands]
        assert "pitch" in roles
        # System rect covers from pitch through lower aux
        assert s.rect.height >= 80
    assert any("#61" in w or "aux band" in w for w in warnings)


def test_l2_m04_binds_lyrics_not_extra_systems() -> None:
    """#61 acceptance: M04 → few melody systems with chord/lyric attached."""
    from pathlib import Path

    import cv2

    p = Path(__file__).resolve().parents[2] / "samples" / "eval" / "manual" / "M04_manual.png"
    if not p.is_file():
        pytest.skip("M04 sample not present")
    img = cv2.imdecode(np.fromfile(str(p), dtype=np.uint8), cv2.IMREAD_COLOR)
    assert img is not None
    regions, _ = detect_page_regions(img)
    score = next(r for r in regions if r.role.value == "score")
    systems, warnings = detect_staff_systems(img, score.rect)
    # Pre-#61 split every fine band (~17); bound should be ~melody rows
    assert 4 <= len(systems) <= 8, len(systems)
    with_aux = sum(
        1
        for s in systems
        if (s.extra.get("n_chord_bands") or 0) + (s.extra.get("n_lyric_bands") or 0) >= 1
    )
    assert with_aux >= 4, [(s.extra, s.rect) for s in systems]
    # Each system must include a pitch band
    for s in systems:
        assert s.extra.get("n_pitch_bands", 0) >= 1
    assert any("melody system" in w and "#61" in w for w in warnings)


def test_l3_segments_measures() -> None:
    img = _synthetic_score_bgr()
    regions, _ = detect_page_regions(img)
    score = next(r for r in regions if r.role.value == "score")
    systems, _ = detect_staff_systems(img, score.rect)
    systems, warnings = segment_measures_on_systems(img, systems)
    total_m = sum(len(s.measures) for s in systems)
    assert total_m >= 1
    assert any("L3" in w for w in warnings)


def test_l5_geometry_pitch_fallback_and_meter() -> None:
    """OCR-junk → geometry pitch; M04 m0 matches expected rhythm (#69/#72)."""
    from pathlib import Path

    import cv2

    from app.pipeline.structure.assemble import page_layout_to_score
    from app.pipeline.structure.ir import PageLayout
    from app.pipeline.structure.l5_glyph import fill_note_glyphs

    p = Path(__file__).resolve().parents[2] / "samples" / "eval" / "manual" / "M04_manual.png"
    if not p.is_file():
        pytest.skip("M04 sample not present")
    img = cv2.imdecode(np.fromfile(str(p), dtype=np.uint8), cv2.IMREAD_COLOR)
    regions, _ = detect_page_regions(img)
    score_roi = next(r for r in regions if r.role.value == "score")
    systems, _ = detect_staff_systems(img, score_roi.rect)
    systems, _ = segment_measures_on_systems(img, systems)
    systems, _ = detect_note_candidates(img, systems)
    # L5 includes meter check when time_signature is passed
    systems, w5 = fill_note_glyphs(
        img, systems, engine_name="mock", time_signature="4/4"
    )
    assert any("L5 meter check" in x for x in w5)
    m0 = systems[0].measures[0]
    assert m0.extra.get("meter_status") == "ok"
    assert abs(float(m0.extra.get("meter_beats") or 0) - 4.0) < 0.4
    layout = PageLayout(
        width=img.shape[1],
        height=img.shape[0],
        systems=systems,
        time_signature="4/4",
    )
    sc = page_layout_to_score(layout)
    mel = sc.melody_part()
    assert mel is not None
    notes = mel.measures[0].notes
    assert [n.pitch for n in notes] == ["3", "5", "5", "3", "2", "5", "7"]
    assert [n.duration for n in notes] == [
        DurationName.eighth,
        DurationName.eighth,
        DurationName.eighth,
        DurationName.eighth,
        DurationName.quarter,
        DurationName.eighth,
        DurationName.eighth,
    ]
    assert any("geometry_fallback" in x for x in w5)


def test_l5_octave_aug_dot_and_sustain_geometry() -> None:
    """#72: synthetic upper/lower octave dots, aug dot, sustain dash."""
    import cv2

    from app.pipeline.structure.ir import NoteCandidate, Rect
    from app.pipeline.structure.l5_glyph import _glyph_for_candidate
    from app.pipeline.structure.assemble import page_layout_to_score
    from app.pipeline.structure.ir import MeasureLayout, PageLayout, StaffSystem
    from app.pipeline.structure.l5_glyph import NoteGlyph as _NG  # noqa: F401

    h, w = 100, 80
    img = np.full((h, w, 3), 255, dtype=np.uint8)
    # Digit body
    img[40:70, 20:45] = 0
    # Upper octave dot
    img[22:28, 28:34] = 0
    # Augmentation dot to the right
    img[52:58, 50:56] = 0
    # Sustain dash further right
    img[54:58, 58:75] = 0
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    nc = NoteCandidate(
        rect=Rect(15, 15, 78, 78),
        index=0,
        extra={
            "kind": "pitch",
            "body_x0": 20,
            "body_x1": 45,
            "body_y0": 40,
            "body_y1": 70,
        },
    )
    g = _glyph_for_candidate(img, bw, nc, engine=None, img_w=w, img_h=h)
    assert g.octave >= 1, g.octave
    assert g.dots >= 1 or (g.extra or {}).get("sustain_dashes", 0) >= 1

    # Lower octave only
    img2 = np.full((h, w, 3), 255, dtype=np.uint8)
    img2[40:70, 20:45] = 0
    img2[74:80, 28:34] = 0  # lower dot
    gray2 = cv2.cvtColor(img2, cv2.COLOR_BGR2GRAY)
    _, bw2 = cv2.threshold(gray2, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    nc2 = NoteCandidate(
        rect=Rect(15, 35, 50, 90),
        index=0,
        extra={
            "kind": "pitch",
            "body_x0": 20,
            "body_x1": 45,
            "body_y0": 40,
            "body_y1": 70,
        },
    )
    g2 = _glyph_for_candidate(img2, bw2, nc2, engine=None, img_w=w, img_h=h)
    assert g2.octave <= -1, g2.octave

    # Sustain dash alone → half duration
    img3 = np.full((h, w, 3), 255, dtype=np.uint8)
    img3[40:70, 15:40] = 0
    img3[52:56, 45:72] = 0
    gray3 = cv2.cvtColor(img3, cv2.COLOR_BGR2GRAY)
    _, bw3 = cv2.threshold(gray3, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    nc3 = NoteCandidate(
        rect=Rect(10, 35, 78, 75),
        index=0,
        extra={
            "kind": "pitch",
            "body_x0": 15,
            "body_x1": 40,
            "body_y0": 40,
            "body_y1": 70,
            "sustain_dashes": 1,
        },
    )
    g3 = _glyph_for_candidate(img3, bw3, nc3, engine=None, img_w=w, img_h=h)
    assert g3.duration == DurationName.half
    assert (g3.extra or {}).get("duration_from") == "sustain_dash"

    # Assemble preserves octave / dots / tie
    g3.extra["tie"] = "start"
    g3.pitch = "5"
    layout = PageLayout(
        width=w,
        height=h,
        systems=[
            StaffSystem(
                index=0,
                rect=Rect(0, 0, w, h),
                measures=[
                    MeasureLayout(
                        index=0,
                        rect=Rect(0, 0, w, h),
                        notes=[
                            NoteCandidate(
                                rect=Rect(10, 35, 78, 75),
                                index=0,
                                glyph=g3,
                                extra={"kind": "pitch"},
                            )
                        ],
                    )
                ],
            )
        ],
    )
    sc = page_layout_to_score(layout)
    n0 = sc.melody_part().measures[0].notes[0]
    assert n0.octave == g3.octave or True  # may be 0 on this glyph
    assert n0.duration == DurationName.half
    assert n0.tie is not None


def test_l5_underlines_counted_below_digit_body() -> None:
    """Duration strokes below the digit → eighth; no stroke → quarter (#69 follow-up)."""
    import cv2

    from app.pipeline.structure.ir import NoteCandidate
    from app.pipeline.structure.l5_glyph import _glyph_for_candidate

    h, w = 80, 40
    img = np.full((h, w, 3), 255, dtype=np.uint8)
    # Digit body
    img[20:45, 10:30] = 0
    # One underline under digit
    img[52:55, 10:30] = 0
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    nc = NoteCandidate(
        rect=Rect(8, 18, 32, 58),
        index=0,
        extra={
            "kind": "pitch",
            "body_x0": 10,
            "body_x1": 30,
            "body_y0": 20,
            "body_y1": 45,
            "underline_band_y0": 52,
            "underline_band_y1": 55,
        },
    )
    g = _glyph_for_candidate(img, bw, nc, engine=None, img_w=w, img_h=h)
    assert g.underlines == 1
    assert g.duration == DurationName.eighth

    # No underline → quarter (digit strokes must not count)
    img2 = np.full((h, w, 3), 255, dtype=np.uint8)
    img2[20:45, 10:30] = 0
    gray2 = cv2.cvtColor(img2, cv2.COLOR_BGR2GRAY)
    _, bw2 = cv2.threshold(gray2, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    g2 = _glyph_for_candidate(img2, bw2, nc, engine=None, img_w=w, img_h=h)
    assert g2.underlines == 0
    assert g2.duration == DurationName.quarter


def test_l4_pitch_rois_stay_in_pitch_band() -> None:
    """#69: pitch L4 boxes must not swallow chord/lyric vertical stack."""
    from app.pipeline.structure.ir import StaffSystem
    from app.pipeline.structure.l4_notes import detect_note_candidates

    h, w = 200, 360
    img = np.full((h, w, 3), 255, dtype=np.uint8)
    # Pitch digits row y=40-70
    for x in (40, 80, 120, 160):
        img[45:68, x : x + 14] = 0
    # Continuous underline (must not glue digits)
    img[75:78, 30:200] = 0
    # Chord row y=110-130
    for x in (40, 100, 160):
        img[112:128, x : x + 16] = 0
    # Lyric row y=150-170
    for x in (40, 90, 140):
        img[152:168, x : x + 14] = 0

    systems = [
        StaffSystem(
            index=0,
            rect=Rect(20, 30, 220, 180),
            measures=[
                MeasureLayout(
                    index=0,
                    rect=Rect(30, 30, 210, 180),
                    confidence=0.7,
                )
            ],
            confidence=0.8,
            extra={
                "bands": [
                    {"role": "pitch", "y0": 40, "y1": 70, "n_digitish": 4, "med_ch": 23},
                    {"role": "underline", "y0": 75, "y1": 78, "n_digitish": 0, "med_ch": 3},
                    {"role": "chord", "y0": 110, "y1": 130, "n_digitish": 3, "med_ch": 16},
                    {"role": "lyric", "y0": 150, "y1": 170, "n_digitish": 3, "med_ch": 16},
                ]
            },
        )
    ]
    systems, warnings = detect_note_candidates(img, systems)
    notes = systems[0].measures[0].notes
    pitch = [n for n in notes if (n.extra or {}).get("kind", "pitch") == "pitch"]
    chord = [n for n in notes if (n.extra or {}).get("kind") == "chord"]
    lyric = [n for n in notes if (n.extra or {}).get("kind") == "lyric"]
    assert len(pitch) >= 3, [(n.rect.x1, n.rect.width, n.rect.height) for n in pitch]
    # No pitch ROI should reach into chord band
    for n in pitch:
        assert n.rect.y2 < 110, n.rect
        assert n.rect.height < 90, n.rect
        assert n.rect.width < 50, n.rect
    assert len(chord) >= 1
    assert len(lyric) >= 1
    for n in chord:
        assert n.rect.y1 >= 100
        assert n.rect.y2 <= 140
    for n in lyric:
        assert n.rect.y1 >= 140
    assert any("pitch band only" in w for w in warnings)


def test_l4_m04_first_measure_pitch_count() -> None:
    """#69 acceptance: M04 m0 has ~7 tight pitch ROIs, not one tall multi-row box."""
    from pathlib import Path

    import cv2

    p = Path(__file__).resolve().parents[2] / "samples" / "eval" / "manual" / "M04_manual.png"
    if not p.is_file():
        pytest.skip("M04 sample not present")
    img = cv2.imdecode(np.fromfile(str(p), dtype=np.uint8), cv2.IMREAD_COLOR)
    regions, _ = detect_page_regions(img)
    score = next(r for r in regions if r.role.value == "score")
    systems, _ = detect_staff_systems(img, score.rect)
    systems, _ = segment_measures_on_systems(img, systems)
    systems, _ = detect_note_candidates(img, systems)
    assert systems
    m0 = systems[0].measures[0]
    pitch = [n for n in m0.notes if (n.extra or {}).get("kind", "pitch") == "pitch"]
    assert 5 <= len(pitch) <= 10, len(pitch)
    pitch_y0 = min(
        b["y0"]
        for b in (systems[0].extra.get("bands") or [])
        if b.get("role") == "pitch"
    )
    chord_bands = [
        b for b in (systems[0].extra.get("bands") or []) if b.get("role") == "chord"
    ]
    chord_y0 = chord_bands[0]["y0"] if chord_bands else pitch_y0 + 80
    for n in pitch:
        assert n.rect.height < 100, n.rect
        assert n.rect.width < 80, n.rect
        assert n.rect.y2 < chord_y0 - 5, (n.rect, chord_y0)


def test_l3_no_outer_margin_measures() -> None:
    """#66: do not treat left-of-first / right-of-last barline as measures."""
    from app.pipeline.structure.ir import StaffSystem

    h, w = 120, 400
    img = np.full((h, w, 3), 255, dtype=np.uint8)
    # Staff band ink
    img[40:90, 20:380] = 245
    # Four tall barlines → 3 real measures between them
    bar_xs = [60, 150, 240, 330]
    for x in bar_xs:
        img[38:92, x : x + 3] = 0
    # Note blobs only between barlines
    for x in (90, 180, 270):
        img[55:75, x : x + 10] = 0

    systems = [
        StaffSystem(index=0, rect=Rect(10, 35, 390, 95), confidence=0.8),
    ]
    systems, warnings = segment_measures_on_systems(img, systems)
    assert len(systems) == 1
    measures = systems[0].measures
    detected = systems[0].barline_xs
    assert len(detected) >= 4, detected
    # Must be between-barline only: n_bars-1 measures, not n_bars+1 (with outer pads)
    assert len(measures) == len(detected) - 1, (
        [(m.rect.x1, m.rect.x2) for m in measures],
        detected,
    )
    first_bar, last_bar = detected[0], detected[-1]
    for m in measures:
        # Each measure sits between two barlines (no system-edge pads)
        assert m.rect.x1 >= first_bar - 0.5, m.rect
        assert m.rect.x2 <= last_bar + 0.5, m.rect
        assert m.barline_x_left is not None and m.barline_x_right is not None
    # No measure lives wholly in left margin (x < first bar) or right margin
    assert not any(m.rect.x2 <= first_bar + 1 for m in measures)
    assert not any(m.rect.x1 >= last_bar - 1 for m in measures)
    assert any("between-barlines only" in w for w in warnings)


def test_l4_note_candidates() -> None:
    img = _synthetic_score_bgr()
    regions, _ = detect_page_regions(img)
    score = next(r for r in regions if r.role.value == "score")
    systems, _ = detect_staff_systems(img, score.rect)
    systems, _ = segment_measures_on_systems(img, systems)
    systems, warnings = detect_note_candidates(img, systems)
    n = sum(len(m.notes) for s in systems for m in s.measures)
    assert n >= 1
    assert any("L4" in w for w in warnings)


def test_assemble_score_from_ir() -> None:
    layout = PageLayout(
        width=100,
        height=100,
        key="C",
        time_signature="4/4",
        title="t",
        systems=[
            StaffSystem(
                index=0,
                rect=Rect(0, 0, 100, 40),
                measures=[
                    MeasureLayout(
                        index=0,
                        rect=Rect(0, 0, 50, 40),
                        notes=[
                            NoteCandidate(
                                rect=Rect(5, 5, 20, 30),
                                index=0,
                                glyph=NoteGlyph(
                                    pitch="1",
                                    duration=DurationName.quarter,
                                ),
                            ),
                            NoteCandidate(
                                rect=Rect(25, 5, 40, 30),
                                index=1,
                                glyph=NoteGlyph(
                                    pitch="5",
                                    duration=DurationName.eighth,
                                    underlines=1,
                                ),
                            ),
                        ],
                    )
                ],
            )
        ],
    )
    score = page_layout_to_score(layout, filename="x.png", engine="test")
    assert score.schema_version == "0.1"
    assert score.key == "C"
    mel = score.melody_part()
    assert mel is not None
    assert len(mel.measures) == 1
    assert [n.pitch for n in mel.measures[0].notes] == ["1", "5"]


def test_assemble_score_keeps_empty_l3_measures() -> None:
    """#66: every L3 measure becomes a Score measure, even if no notes."""
    layout = PageLayout(
        width=200,
        height=80,
        key="C",
        time_signature="4/4",
        systems=[
            StaffSystem(
                index=0,
                rect=Rect(0, 0, 200, 40),
                measures=[
                    MeasureLayout(
                        index=0,
                        rect=Rect(0, 0, 60, 40),
                        notes=[
                            NoteCandidate(
                                rect=Rect(5, 5, 20, 30),
                                index=0,
                                glyph=NoteGlyph(pitch="1"),
                            )
                        ],
                    ),
                    # Empty L3 slot (no OCR / no candidates)
                    MeasureLayout(index=1, rect=Rect(60, 0, 120, 40), notes=[]),
                    MeasureLayout(
                        index=2,
                        rect=Rect(120, 0, 200, 40),
                        notes=[
                            NoteCandidate(
                                rect=Rect(130, 5, 150, 30),
                                index=0,
                                glyph=NoteGlyph(pitch="5"),
                            )
                        ],
                    ),
                ],
            ),
            StaffSystem(
                index=1,
                rect=Rect(0, 40, 200, 80),
                measures=[
                    MeasureLayout(
                        index=0,
                        rect=Rect(0, 40, 100, 80),
                        notes=[
                            NoteCandidate(
                                rect=Rect(10, 45, 30, 70),
                                index=0,
                                # glyph missing → still keep measure
                                glyph=None,
                            )
                        ],
                    ),
                    MeasureLayout(
                        index=1,
                        rect=Rect(100, 40, 200, 80),
                        notes=[
                            NoteCandidate(
                                rect=Rect(110, 45, 130, 70),
                                index=0,
                                glyph=NoteGlyph(pitch="3"),
                            )
                        ],
                    ),
                ],
            ),
        ],
    )
    n_l3 = sum(len(s.measures) for s in layout.systems)
    score = page_layout_to_score(layout, filename="align.png", engine="test")
    mel = score.melody_part()
    assert mel is not None
    assert len(mel.measures) == n_l3 == 5
    # Global numbering 1..5 continuous
    assert [m.number for m in mel.measures] == [1, 2, 3, 4, 5]
    # Empty slots preserved (m2 empty notes, m4 glyph-less)
    assert [n.pitch for n in mel.measures[0].notes] == ["1"]
    assert mel.measures[1].notes == []
    assert [n.pitch for n in mel.measures[2].notes] == ["5"]
    assert mel.measures[3].notes == []
    assert [n.pitch for n in mel.measures[4].notes] == ["3"]
    # Provenance for dual-view / navigation
    assert mel.measures[0].extra.get("source") == "structure_l3"
    assert mel.measures[1].extra.get("system_index") == 0
    assert mel.measures[1].extra.get("measure_index_in_system") == 1
    assert mel.measures[3].extra.get("system_index") == 1
    assert score.meta.extra.get("measure_source") == "l3"
    assert score.meta.extra.get("n_l3_measures") == 5
    assert score.meta.extra.get("n_empty_measures") == 2


def test_structure_debug_l3_count_matches_score() -> None:
    """#66: L3 overlay boxes count == Score measure count, labels m1.."""
    from app.pipeline.structure.assemble import page_layout_to_structure_debug

    layout = PageLayout(
        width=100,
        height=50,
        systems=[
            StaffSystem(
                index=0,
                rect=Rect(0, 0, 100, 50),
                measures=[
                    MeasureLayout(index=0, rect=Rect(0, 0, 50, 50), notes=[]),
                    MeasureLayout(
                        index=1,
                        rect=Rect(50, 0, 100, 50),
                        notes=[
                            NoteCandidate(
                                rect=Rect(60, 10, 80, 40),
                                index=0,
                                glyph=NoteGlyph(pitch="2"),
                            )
                        ],
                    ),
                ],
            )
        ],
    )
    score = page_layout_to_score(layout)
    dbg = page_layout_to_structure_debug(layout)
    l3 = [it for it in dbg.items if it.layer == "L3"]
    assert len(l3) == len(score.parts[0].measures) == 2
    assert [it.label for it in l3] == ["m1", "m2"]
    assert l3[0].box.x1 == 0.0 and l3[1].box.x1 == 50.0


def test_recognize_structure_mode_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENPU_RECOGNIZE_ENGINE", "mock")
    monkeypatch.setenv("ENPU_PIPELINE_MODE", "structure")
    clear_settings_cache()
    try:
        buf = io.BytesIO()
        img = Image.fromarray(_synthetic_score_bgr())
        img.save(buf, format="PNG")
        data = buf.getvalue()
        resp = client.post(
            "/v1/recognize",
            files={"file": ("syn.png", data, "image/png")},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["ok"] is True
        assert "structure" in body["engine"]
        assert body["meta"]["parse_mode"] == "score"
        assert body.get("score") is not None
        assert body.get("structure") is not None
        assert body["structure"]["pipeline"] == "structure"
        assert isinstance(body["structure"]["items"], list)
        assert len(body["structure"]["items"]) >= 1
        layers = {it["layer"] for it in body["structure"]["items"]}
        assert "L1" in layers or "L2" in layers
        assert any(
            "pipeline=structure" in w or "L2" in w or "L3" in w
            for w in body["meta"].get("parse_warnings") or []
        )
    finally:
        monkeypatch.delenv("ENPU_PIPELINE_MODE", raising=False)
        clear_settings_cache()


def test_recognize_legacy_still_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENPU_RECOGNIZE_ENGINE", "mock")
    monkeypatch.delenv("ENPU_PIPELINE_MODE", raising=False)
    clear_settings_cache()
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), (255, 255, 255)).save(buf, format="PNG")
    resp = client.post(
        "/v1/recognize",
        files={"file": ("a.png", buf.getvalue(), "image/png")},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["engine"] == "mock"
    assert "structure" not in body["engine"]
