"""Tests for EnPu Score schema v0.1 (issue #9)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.schemas.score import (
    SCHEMA_VERSION,
    DurationName,
    Measure,
    NoteEvent,
    Part,
    Score,
    example_minimal_score,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_JSON = REPO_ROOT / "samples" / "scores" / "example-minimal.json"
JSON_SCHEMA_FILE = (
    Path(__file__).resolve().parents[1] / "schemas" / "enpu-score-v0.1.json"
)


def test_schema_version_constant() -> None:
    assert SCHEMA_VERSION == "0.1"


def test_example_minimal_score_valid() -> None:
    score = example_minimal_score()
    assert score.schema_version == "0.1"
    assert score.title
    assert score.key == "C"
    assert score.time_signature == "4/4"
    part = score.melody_part()
    assert part is not None
    assert part.name == "melody"
    assert len(part.measures) >= 2
    # lyrics present on first measure
    lyrics = [n.lyric for n in part.measures[0].notes if n.lyric]
    assert "主" in lyrics
    # rest in second measure
    assert any(n.is_rest for n in part.measures[1].notes)


def test_roundtrip_dump_validate() -> None:
    score = example_minimal_score()
    data = score.model_dump(mode="json")
    again = Score.model_validate(data)
    assert again.model_dump(mode="json") == data


def test_load_repo_example_json() -> None:
    assert EXAMPLE_JSON.is_file(), f"missing {EXAMPLE_JSON}"
    raw = json.loads(EXAMPLE_JSON.read_text(encoding="utf-8"))
    score = Score.model_validate(raw)
    assert score.schema_version == "0.1"
    assert score.melody_part() is not None
    notes = score.melody_part().measures[0].notes  # type: ignore[union-attr]
    assert all(n.lyric for n in notes if not n.is_rest)


def test_reject_bad_pitch() -> None:
    with pytest.raises(ValidationError):
        NoteEvent(pitch="8", duration=DurationName.quarter)


def test_reject_rest_with_pitch() -> None:
    with pytest.raises(ValidationError):
        NoteEvent(pitch="1", is_rest=True, duration=DurationName.quarter)


def test_reject_non_rest_without_pitch() -> None:
    with pytest.raises(ValidationError):
        NoteEvent(pitch=None, is_rest=False, duration=DurationName.quarter)


def test_reject_bad_time_signature() -> None:
    with pytest.raises(ValidationError):
        Score(time_signature="four-four", parts=[])


def test_single_voice_plus_lyrics_minimal_song() -> None:
    """Acceptance: express single-voice melody + lyrics."""
    score = Score(
        schema_version="0.1",
        title="验收曲",
        key="G",
        time_signature="3/4",
        tempo_bpm=72,
        parts=[
            Part(
                name="melody",
                measures=[
                    Measure(
                        number=1,
                        notes=[
                            NoteEvent(pitch="5", duration=DurationName.quarter, lyric="奇"),
                            NoteEvent(pitch="5", duration=DurationName.quarter, lyric="妙"),
                            NoteEvent(pitch="6", duration=DurationName.quarter, lyric="主"),
                        ],
                    )
                ],
            )
        ],
    )
    assert score.schema_version == "0.1"
    mel = score.melody_part()
    assert mel is not None
    assert len(mel.measures[0].notes) == 3
    assert "".join(n.lyric or "" for n in mel.measures[0].notes) == "奇妙主"


def test_json_schema_file_exists_and_mentions_version() -> None:
    assert JSON_SCHEMA_FILE.is_file()
    doc = json.loads(JSON_SCHEMA_FILE.read_text(encoding="utf-8"))
    assert doc["properties"]["schema_version"]["const"] == "0.1"
