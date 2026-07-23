"""OCR → EnPu Score parsing MVP (issue #10).

Maps OCR text lines into Score v0.1 (pitch + basic duration + measures).
On failure, falls back to note hints or OCR-text-only without raising.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from app.pipeline.ocr import OcrItem
from app.schemas.recognize import NoteHint
from app.schemas.score import (
    DurationName,
    Measure,
    NoteEvent,
    Part,
    Score,
    ScoreMeta,
)

# Jianpu pitch digits 1-7 (fullwidth digits normalized first).
_DIGIT_RE = re.compile(r"[1-7]")
_FULLWIDTH = str.maketrans("１２３４５６７０．－｜", "12345670.-|")

_KEY_RE = re.compile(
    r"(?:key|调)\s*[:：]?\s*([A-Ga-g][b#]?)|"
    r"1\s*=\s*([A-Ga-g][b#]?)",
    re.IGNORECASE,
)
_TIME_RE = re.compile(
    r"(?:time|拍号)?\s*[:：]?\s*([1-9][0-9]*)\s*/\s*([1-9][0-9]*)",
    re.IGNORECASE,
)
_TEMPO_RE = re.compile(
    r"(?:tempo|bpm|速度)\s*[:：]?\s*([1-9][0-9]{1,2})",
    re.IGNORECASE,
)
# Tokens inside a jianpu stream: pitch, rest-ish 0, bar, dash (sustain), dots
_TOKEN_RE = re.compile(r"[1-7]|0|\||-+|\.+")

ParseMode = Literal["score", "hints", "ocr_only"]


@dataclass
class ParseResult:
    """Structured parse output with graceful degradation."""

    score: Score | None
    notes: list[NoteHint]
    mode: ParseMode
    warnings: list[str] = field(default_factory=list)


def extract_note_hints(items: list[OcrItem]) -> list[NoteHint]:
    """Pull simple pitch digits out of OCR strings (legacy lightweight path)."""
    notes: list[NoteHint] = []
    for item in items:
        text = _normalize(item.text)
        for ch in _DIGIT_RE.findall(text):
            notes.append(
                NoteHint(
                    pitch=ch,
                    text=item.text,
                    extra={"source": "ocr_digit", "score": item.score},
                )
            )
    return notes


def parse_ocr_to_score(
    items: list[OcrItem],
    *,
    filename: str | None = None,
    engine: str | None = None,
    title: str | None = None,
) -> ParseResult:
    """Best-effort Score construction from OCR items.

    Never raises for parse ambiguity — returns mode=ocr_only or hints instead.
    """
    warnings: list[str] = []
    hints = extract_note_hints(items)

    if not items:
        return ParseResult(
            score=None,
            notes=[],
            mode="ocr_only",
            warnings=["empty OCR; no score produced"],
        )

    ordered = _reading_order(items)
    texts = [_normalize(i.text) for i in ordered if i.text and i.text.strip()]

    key = _detect_key(texts) or "C"
    time_sig = _detect_time(texts) or "4/4"
    tempo = _detect_tempo(texts)

    jianpu_lines = [t for t in texts if _looks_like_jianpu_line(t)]
    if not jianpu_lines:
        warnings.append("no jianpu-like pitch line detected; using digit hints only")
        if hints:
            score = _score_from_flat_pitches(
                [h.pitch for h in hints if h.pitch],
                key=key,
                time_sig=time_sig,
                tempo=tempo,
                title=title or _guess_title(texts),
                filename=filename,
                engine=engine,
                warnings=warnings,
            )
            return ParseResult(score=score, notes=hints, mode="score", warnings=warnings)
        return ParseResult(
            score=None,
            notes=[],
            mode="ocr_only",
            warnings=warnings + ["no pitch digits found"],
        )

    try:
        measures = _parse_jianpu_lines(jianpu_lines, warnings)
        if not measures:
            raise ValueError("no measures parsed")
        # Optional lyric attachment from CJK-heavy lines
        lyric_lines = [t for t in texts if _looks_like_lyric_line(t)]
        if lyric_lines:
            _attach_lyrics(measures, lyric_lines[0], warnings)

        score = Score(
            schema_version="0.1",
            title=title or _guess_title(texts) or "",
            key=key,
            time_signature=time_sig,
            tempo_bpm=tempo,
            parts=[Part(id="P1", name="melody", measures=measures)],
            meta=ScoreMeta(
                source_image=filename,
                engine=engine,
                created_by="enpu-parse-mvp-#10",
                comments="MVP parse from OCR; durations are heuristic.",
            ),
        )
        # Validate via pydantic already on construction
        return ParseResult(score=score, notes=hints, mode="score", warnings=warnings)
    except Exception as exc:  # noqa: BLE001 — fall back, never break API
        warnings.append(f"score parse failed: {exc}")
        if hints:
            return ParseResult(
                score=None,
                notes=hints,
                mode="hints",
                warnings=warnings,
            )
        return ParseResult(
            score=None,
            notes=[],
            mode="ocr_only",
            warnings=warnings,
        )


def _normalize(text: str) -> str:
    return text.translate(_FULLWIDTH).strip()


def _reading_order(items: list[OcrItem]) -> list[OcrItem]:
    """Sort by top-to-bottom, then left-to-right when boxes exist."""

    def key(it: OcrItem) -> tuple[float, float]:
        if it.box is None:
            return (0.0, 0.0)
        return (it.box.y1, it.box.x1)

    return sorted(items, key=key)


def _detect_key(texts: list[str]) -> str | None:
    for t in texts:
        m = _KEY_RE.search(t)
        if m:
            raw = m.group(1) or m.group(2)
            if raw:
                # Normalize Bb-style
                return raw[0].upper() + raw[1:].lower()
    return None


def _detect_time(texts: list[str]) -> str | None:
    for t in texts:
        m = _TIME_RE.search(t)
        if m:
            return f"{m.group(1)}/{m.group(2)}"
    return None


def _detect_tempo(texts: list[str]) -> float | None:
    for t in texts:
        m = _TEMPO_RE.search(t)
        if m:
            return float(m.group(1))
    return None


def _guess_title(texts: list[str]) -> str:
    for t in texts:
        if re.search(r"title\s*[:：]", t, re.I):
            return re.split(r"[:：]", t, maxsplit=1)[-1].strip()[:80]
        if "样例" in t or "Sample" in t:
            return t[:80]
    return ""


def _looks_like_jianpu_line(text: str) -> bool:
    """Heuristic: enough pitch digits, not a pure metadata/lyric line."""
    if len(text) < 1:
        return False
    digits = _DIGIT_RE.findall(text)
    if len(digits) < 2:
        return False
    # Reject pure key/time metadata even if contains digits like 4/4
    if re.search(r"\d+\s*/\s*\d+", text) and len(digits) <= 2 and "|" not in text:
        # e.g. "4/4" alone
        if not re.search(r"[1-7]\s+[1-7]", text):
            return False
    cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
    if cjk >= 4 and len(digits) < cjk:
        return False
    return True


def _looks_like_lyric_line(text: str) -> bool:
    cjk = re.findall(r"[\u4e00-\u9fff]", text)
    digits = _DIGIT_RE.findall(text)
    return len(cjk) >= 2 and len(digits) <= 1


def _parse_jianpu_lines(lines: list[str], warnings: list[str]) -> list[Measure]:
    measures: list[Measure] = []
    measure_num = 1
    current_notes: list[NoteEvent] = []

    def flush() -> None:
        nonlocal measure_num, current_notes
        if current_notes:
            measures.append(Measure(number=measure_num, notes=list(current_notes)))
            measure_num += 1
            current_notes = []

    for line in lines:
        tokens = _TOKEN_RE.findall(line.replace("—", "-").replace("–", "-"))
        if not tokens:
            continue
        i = 0
        while i < len(tokens):
            tok = tokens[i]
            if tok == "|":
                flush()
                i += 1
                continue
            if tok in {".", "-"} or tok.startswith("-") or tok.startswith("."):
                # orphan sustain/dot — ignore or attach later
                i += 1
                continue
            if tok == "0":
                # rest
                dur, dots, consumed = _duration_from_following(tokens, i + 1)
                current_notes.append(
                    NoteEvent(
                        is_rest=True,
                        duration=dur,
                        dots=dots,
                        extra={"source": "ocr_parse", "token": tok},
                    )
                )
                i += 1 + consumed
                continue
            if tok in "1234567":
                dur, dots, consumed = _duration_from_following(tokens, i + 1)
                current_notes.append(
                    NoteEvent(
                        pitch=tok,
                        octave=0,
                        duration=dur,
                        dots=dots,
                        extra={"source": "ocr_parse"},
                    )
                )
                i += 1 + consumed
                continue
            i += 1
        # end of visual line: soft bar if we have notes and line had no |
        if "|" not in line and current_notes:
            # keep accumulating across lines unless empty
            pass

    flush()
    if not measures:
        warnings.append("jianpu tokens found but no notes emitted")
    return measures


def _duration_from_following(
    tokens: list[str], start: int
) -> tuple[DurationName, int, int]:
    """Interpret following ``-`` sustain and ``.`` dots.

    MVP mapping:
    - no dash → quarter
    - one ``-`` → half
    - two+ ``-`` → whole
    - ``.`` after pitch/dash → one augmentation dot
    """
    dashes = 0
    dots = 0
    j = start
    while j < len(tokens):
        t = tokens[j]
        if t.startswith("-") or t == "-":
            dashes += t.count("-") if t.startswith("-") else 1
            j += 1
            continue
        if t.startswith(".") or t == ".":
            dots += t.count(".")
            j += 1
            continue
        break
    dots = min(dots, 2)
    # Jianpu: "5" quarter; "5 -" half; "5 - -" dotted half; "5 - - -" whole
    if dashes >= 3:
        dur = DurationName.whole
    elif dashes == 2:
        dur = DurationName.half
        dots = max(dots, 1)
    elif dashes == 1:
        dur = DurationName.half
    else:
        dur = DurationName.quarter
    return dur, dots, j - start


def _attach_lyrics(
    measures: list[Measure], lyric_line: str, warnings: list[str]
) -> None:
    # Split CJK chars and latin syllables roughly
    syllables = re.findall(r"[\u4e00-\u9fff]|[A-Za-z]+", lyric_line)
    if not syllables:
        return
    idx = 0
    for meas in measures:
        for note in meas.notes:
            if note.is_rest:
                continue
            if idx < len(syllables):
                note.lyric = syllables[idx]
                idx += 1
    if idx < len(syllables):
        warnings.append(
            f"lyric syllables remaining unaligned: {len(syllables) - idx}"
        )


def _score_from_flat_pitches(
    pitches: list[str],
    *,
    key: str,
    time_sig: str,
    tempo: float | None,
    title: str,
    filename: str | None,
    engine: str | None,
    warnings: list[str],
) -> Score:
    """Pack flat pitch list into 4/4-ish measures of quarters."""
    try:
        beats = int(time_sig.split("/")[0])
    except Exception:
        beats = 4
    beats = max(1, min(beats, 8))

    measures: list[Measure] = []
    buf: list[NoteEvent] = []
    num = 1
    for p in pitches:
        buf.append(
            NoteEvent(
                pitch=p,
                duration=DurationName.quarter,
                extra={"source": "hint_fallback"},
            )
        )
        if len(buf) >= beats:
            measures.append(Measure(number=num, notes=list(buf)))
            num += 1
            buf = []
    if buf:
        measures.append(Measure(number=num, notes=list(buf)))
    if not measures:
        warnings.append("flat pitch list empty after filter")
    return Score(
        schema_version="0.1",
        title=title or "",
        key=key,
        time_signature=time_sig,
        tempo_bpm=tempo,
        parts=[Part(id="P1", name="melody", measures=measures)],
        meta=ScoreMeta(
            source_image=filename,
            engine=engine,
            created_by="enpu-parse-mvp-#10",
            comments="Built from digit hints (no full jianpu line).",
        ),
    )
