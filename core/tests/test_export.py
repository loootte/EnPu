"""Tests for Score → MusicXML / MIDI export (issue #11)."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.pipeline.export import (
    ExportError,
    export_score,
    export_to_path,
    jianpu_to_midi,
    note_quarter_length,
    parse_key_tonic,
    score_to_music21,
)
from app.schemas.score import (
    DurationName,
    NoteEvent,
    example_minimal_score,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_JSON = REPO_ROOT / "samples" / "scores" / "example-minimal.json"


def test_parse_key_tonic_variants() -> None:
    assert parse_key_tonic("C")[0] == "C"
    assert parse_key_tonic("G")[1] == 67
    assert parse_key_tonic("Bb")[0] == "Bb"
    assert parse_key_tonic("1=F")[0] == "F"
    assert parse_key_tonic("")[0] == "C"


def test_jianpu_to_midi_c_major() -> None:
    # degree 1 @ octave 0 → C4 = 60
    assert jianpu_to_midi("1", 0, "C") == 60
    assert jianpu_to_midi("5", 0, "C") == 67
    assert jianpu_to_midi("1", 1, "C") == 72
    assert jianpu_to_midi("1", -1, "C") == 48
    # G major: 1 = G4 = 67
    assert jianpu_to_midi("1", 0, "G") == 67
    assert jianpu_to_midi("2", 0, "G") == 69


def test_note_quarter_length_dots() -> None:
    n = NoteEvent(pitch="1", duration=DurationName.quarter, dots=0)
    assert note_quarter_length(n) == 1.0
    n.dots = 1
    assert note_quarter_length(n) == 1.5
    n.dots = 2
    assert note_quarter_length(n) == 1.75
    half = NoteEvent(pitch="1", duration=DurationName.half, dots=1)
    assert note_quarter_length(half) == 3.0


def test_export_musicxml_from_example_minimal() -> None:
    score = example_minimal_score()
    result = export_score(score, "musicxml")
    assert result.format == "musicxml"
    assert result.filename.endswith(".musicxml")
    text = result.content.decode("utf-8")
    assert "<?xml" in text or "<score-partwise" in text or "score-partwise" in text
    assert b"part" in result.content.lower() or b"Part" in result.content
    # should mention pitches / notes somehow
    assert len(result.content) > 200


def test_export_midi_from_example_minimal() -> None:
    score = example_minimal_score()
    result = export_score(score, "midi")
    assert result.format == "midi"
    assert result.filename.endswith(".mid")
    # Standard MIDI files start with MThd
    assert result.content[:4] == b"MThd"
    assert len(result.content) > 20


def test_export_from_sample_json_file() -> None:
    raw = json.loads(EXAMPLE_JSON.read_text(encoding="utf-8"))
    from app.schemas.score import Score

    score = Score.model_validate(raw)
    xml = export_score(score, "musicxml")
    mid = export_score(score, "midi")
    assert b"score-partwise" in xml.content.lower() or b"score-partwise" in xml.content
    # case-insensitive search
    assert "score-partwise" in xml.content.decode("utf-8", errors="ignore").lower()
    assert mid.content[:4] == b"MThd"


def test_export_to_path_roundtrip(tmp_path: Path) -> None:
    score = example_minimal_score()
    xml_path = export_to_path(score, tmp_path / "demo.musicxml")
    mid_path = export_to_path(score, tmp_path / "demo.mid")
    assert xml_path.is_file() and xml_path.stat().st_size > 100
    assert mid_path.is_file() and mid_path.read_bytes()[:4] == b"MThd"


def test_score_to_music21_has_notes() -> None:
    score = example_minimal_score()
    s = score_to_music21(score)
    notes = list(s.flatten().notesAndRests)
    assert len(notes) >= 7  # 4 + 2 notes + 1 rest in example


def test_export_empty_parts_raises() -> None:
    from app.schemas.score import Score

    with pytest.raises(ExportError):
        export_score(Score(parts=[]), "musicxml")


def test_api_export_musicxml_json() -> None:
    client = TestClient(create_app())
    body = example_minimal_score().model_dump(mode="json")
    r = client.post("/v1/export?format=musicxml", json=body)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["ok"] is True
    assert data["format"] == "musicxml"
    assert data["byte_length"] > 100
    raw = base64.b64decode(data["content_base64"])
    assert b"score-partwise" in raw.lower() or "score-partwise" in raw.decode(
        "utf-8", errors="ignore"
    ).lower()


def test_api_export_midi_download() -> None:
    client = TestClient(create_app())
    body = example_minimal_score().model_dump(mode="json")
    r = client.post("/v1/export?format=midi&download=true", json=body)
    assert r.status_code == 200, r.text
    assert r.content[:4] == b"MThd"
    cd = r.headers.get("content-disposition", "")
    assert "attachment" in cd
    assert ".mid" in cd


def test_api_export_rejects_empty_score() -> None:
    client = TestClient(create_app())
    r = client.post(
        "/v1/export?format=musicxml",
        json={
            "schema_version": "0.1",
            "title": "empty",
            "key": "C",
            "time_signature": "4/4",
            "parts": [{"id": "P1", "name": "melody", "measures": []}],
        },
    )
    assert r.status_code == 400
