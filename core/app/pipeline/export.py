"""Export EnPu Score → MusicXML / MIDI via music21 (issue #11).

Score JSON is the source of truth; this module is an adapter only.
Jianpu degrees ``1``–``7`` are mapped relative to ``Score.key`` (movable-do).
"""

from __future__ import annotations

import base64
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from app.schemas.score import Accidental, DurationName, NoteEvent, Score, TieType

ExportFormat = Literal["musicxml", "midi"]

# Jianpu degree → semitone offset from tonic (major scale).
_DEGREE_SEMITONES: dict[str, int] = {
    "1": 0,
    "2": 2,
    "3": 4,
    "4": 5,
    "5": 7,
    "6": 9,
    "7": 11,
}

_DURATION_QL: dict[DurationName, float] = {
    DurationName.whole: 4.0,
    DurationName.half: 2.0,
    DurationName.quarter: 1.0,
    DurationName.eighth: 0.5,
    DurationName.sixteenth: 0.25,
    DurationName.thirty_second: 0.125,
}

# Pitch-class letter → MIDI of that PC in octave 4 (C4=60).
_PC_MIDI: dict[str, int] = {
    "C": 60,
    "D": 62,
    "E": 64,
    "F": 65,
    "G": 67,
    "A": 69,
    "B": 71,
}


class ExportError(RuntimeError):
    """Export failed (missing deps, empty score, write error)."""


@dataclass
class ExportResult:
    """Binary export payload with metadata for HTTP responses."""

    format: ExportFormat
    content: bytes
    media_type: str
    filename: str
    warnings: list[str] = field(default_factory=list)

    def content_base64(self) -> str:
        return base64.b64encode(self.content).decode("ascii")


def _require_music21() -> Any:
    try:
        import music21  # noqa: F401
    except ImportError as exc:
        raise ExportError(
            "music21 is not installed. Install with: pip install 'music21>=9.1,<10'"
        ) from exc
    return __import__("music21")


def parse_key_tonic(key_str: str) -> tuple[str, int]:
    """Return (pitch-class letter with accidental, tonic MIDI in octave 4).

    Accepts ``C``, ``G``, ``Bb``, ``F#``, ``1=C`` style fragments.
    Defaults to C when unparseable.
    """
    raw = (key_str or "C").strip()
    m = re.search(r"1\s*=\s*([A-Ga-g][b#♭♯]?)", raw)
    if m:
        raw = m.group(1)
    m = re.match(r"^([A-Ga-g])([b#♭♯]?)$", raw)
    if not m:
        # fall back: first letter A-G
        m2 = re.search(r"([A-Ga-g])([b#♭♯]?)", raw)
        if not m2:
            return "C", 60
        letter, acc = m2.group(1).upper(), m2.group(2)
    else:
        letter, acc = m.group(1).upper(), m.group(2)

    acc = acc.replace("♭", "b").replace("♯", "#")
    base = _PC_MIDI.get(letter, 60)
    if acc in {"b", "flat"}:
        base -= 1
        name = f"{letter}b"
    elif acc in {"#", "sharp"}:
        base += 1
        name = f"{letter}#"
    else:
        name = letter
    return name, base


def note_quarter_length(event: NoteEvent) -> float:
    base = _DURATION_QL.get(event.duration, 1.0)
    dots = max(0, min(2, event.dots))
    if dots == 0:
        return base
    # each dot adds half of the previous addition
    return base * (2.0 - (0.5**dots))


def jianpu_to_midi(
    degree: str,
    octave: int,
    key_str: str,
    accidental: Accidental | None = None,
) -> int:
    """Map jianpu degree + relative octave to absolute MIDI note number."""
    _, tonic_midi = parse_key_tonic(key_str)
    semis = _DEGREE_SEMITONES.get(degree, 0)
    midi = tonic_midi + semis + int(octave) * 12
    if accidental == Accidental.sharp:
        midi += 1
    elif accidental == Accidental.flat:
        midi -= 1
    # natural: leave as scale degree (already major-scale based)
    return max(0, min(127, midi))


def score_to_music21(score: Score) -> Any:
    """Build a ``music21.stream.Score`` from EnPu Score v0.1."""
    m21 = _require_music21()
    from music21 import (
        key as m21_key,
        meter,
        metadata,
        note,
        stream,
        tempo,
        tie,
    )

    warnings: list[str] = []
    s = stream.Score()
    md = metadata.Metadata()
    md.title = score.title or "EnPu Score"
    if score.meta and score.meta.created_by:
        md.composer = str(score.meta.created_by)
    s.metadata = md

    parts = score.parts or []
    if not parts:
        raise ExportError("Score has no parts to export")

    key_name, _ = parse_key_tonic(score.key)
    try:
        # music21 Key accepts 'C', 'G', 'B-', 'F#' etc.
        kn = key_name.replace("b", "-")
        key_obj = m21_key.Key(kn)
    except Exception:  # noqa: BLE001
        key_obj = m21_key.Key("C")
        warnings.append(f"unrecognized key {score.key!r}; defaulted to C")

    try:
        ts = meter.TimeSignature(score.time_signature or "4/4")
    except Exception:  # noqa: BLE001
        ts = meter.TimeSignature("4/4")
        warnings.append(
            f"unrecognized time_signature {score.time_signature!r}; defaulted to 4/4"
        )

    for part_model in parts:
        p = stream.Part(id=part_model.id)
        p.partName = part_model.name or part_model.id
        # put key/meter once at the start of the part
        p.append(ts)
        p.append(key_obj)
        if score.tempo_bpm is not None and score.tempo_bpm > 0:
            p.append(tempo.MetronomeMark(number=float(score.tempo_bpm)))

        measures = part_model.measures or []
        if not measures:
            warnings.append(f"part {part_model.id!r} has no measures")
        for meas in measures:
            m = stream.Measure(number=meas.number)
            for ev in meas.notes:
                ql = note_quarter_length(ev)
                if ev.is_rest:
                    el: note.GeneralNote = note.Rest(quarterLength=ql)
                else:
                    midi = jianpu_to_midi(
                        ev.pitch or "1",
                        ev.octave,
                        score.key,
                        ev.accidental,
                    )
                    el = note.Note(midi, quarterLength=ql)
                    if ev.lyric:
                        el.lyric = ev.lyric
                    if ev.tie is not None:
                        try:
                            if ev.tie == TieType.start:
                                el.tie = tie.Tie("start")
                            elif ev.tie == TieType.stop:
                                el.tie = tie.Tie("stop")
                            elif ev.tie == TieType.continue_:
                                el.tie = tie.Tie("continue")
                        except Exception:  # noqa: BLE001
                            warnings.append(f"tie {ev.tie!r} ignored")
                m.append(el)
            p.append(m)
        s.insert(0, p)

    # stash warnings on the stream for callers
    s.enpu_export_warnings = warnings  # type: ignore[attr-defined]
    return s


def export_score(
    score: Score,
    fmt: ExportFormat,
    *,
    filename_stem: str | None = None,
) -> ExportResult:
    """Export a Score to MusicXML or MIDI bytes."""
    fmt_n = (fmt or "musicxml").strip().lower()
    if fmt_n not in {"musicxml", "midi"}:
        raise ExportError(f"Unsupported export format: {fmt!r}")

    s = score_to_music21(score)
    warnings: list[str] = list(getattr(s, "enpu_export_warnings", []) or [])
    stem = _safe_stem(filename_stem or score.title or "enpu-score")

    if fmt_n == "musicxml":
        content = _write_musicxml_bytes(s)
        return ExportResult(
            format="musicxml",
            content=content,
            media_type="application/vnd.recordare.musicxml+xml",
            filename=f"{stem}.musicxml",
            warnings=warnings,
        )

    content = _write_midi_bytes(s)
    return ExportResult(
        format="midi",
        content=content,
        media_type="audio/midi",
        filename=f"{stem}.mid",
        warnings=warnings,
    )


def _safe_stem(name: str) -> str:
    cleaned = re.sub(r"[^\w\-]+", "_", name.strip(), flags=re.UNICODE)
    cleaned = cleaned.strip("_")[:64]
    return cleaned or "enpu-score"


def _write_musicxml_bytes(s: Any) -> bytes:
    from music21.musicxml.m21ToXml import GeneralObjectExporter

    try:
        exporter = GeneralObjectExporter(s)
        raw = exporter.parse()
        if isinstance(raw, bytes):
            return raw
        return str(raw).encode("utf-8")
    except Exception as exc:  # noqa: BLE001
        # Fallback: write via temp file
        try:
            with tempfile.TemporaryDirectory() as td:
                path = Path(td) / "out.musicxml"
                s.write("musicxml", fp=str(path))
                return path.read_bytes()
        except Exception as exc2:  # noqa: BLE001
            raise ExportError(f"MusicXML export failed: {exc2}") from exc


def _write_midi_bytes(s: Any) -> bytes:
    try:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "out.mid"
            s.write("midi", fp=str(path))
            data = path.read_bytes()
            if not data:
                raise ExportError("MIDI export produced empty file")
            return data
    except ExportError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ExportError(f"MIDI export failed: {exc}") from exc


def export_to_path(
    score: Score,
    path: str | Path,
    fmt: ExportFormat | None = None,
) -> Path:
    """Write export to a filesystem path (infers format from suffix if needed)."""
    p = Path(path)
    if fmt is None:
        suf = p.suffix.lower()
        if suf in {".mid", ".midi"}:
            fmt = "midi"
        else:
            fmt = "musicxml"
    result = export_score(score, fmt, filename_stem=p.stem)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(result.content)
    return p
