"""OCR → EnPu Score parsing MVP (issue #10).

Maps OCR text lines into Score v0.1 (pitch + basic duration + measures).
On failure, falls back to note hints or OCR-text-only without raising.

Bar-line handling:
- Accept ``|``, fullwidth/unicode vertical bars, and common OCR confusions
  (``I`` / ``l`` / ``丨`` between pitch tokens).
- If no bar-lines survive OCR, split the note stream by time-signature beats.
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

_DIGIT_RE = re.compile(r"[1-7]")
_FULLWIDTH = str.maketrans(
    "１２３４５６７０．－｜丨│",
    "12345670.-|||",
)

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

# Pitch / rest / bar / sustain / dots. Bar includes OCR confusions I/l when tokenized
# carefully in _tokenizeize / _normalize_bars.
_TOKEN_RE = re.compile(r"[1-7]|0|\||-+|\.+")

_BEATS: dict[DurationName, float] = {
    DurationName.whole: 4.0,
    DurationName.half: 2.0,
    DurationName.quarter: 1.0,
    DurationName.eighth: 0.5,
    DurationName.sixteenth: 0.25,
    DurationName.thirty_second: 0.125,
}

ParseMode = Literal["score", "hints", "ocr_only"]


@dataclass
class ParseResult:
    """Structured parse output with graceful degradation."""

    score: Score | None
    notes: list[NoteHint]
    mode: ParseMode
    warnings: list[str] = field(default_factory=list)


def extract_note_hints(items: list[OcrItem]) -> list[NoteHint]:
    """Pull simple pitch digits out of OCR strings."""
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
    # Join same-row OCR boxes with explicit bar tokens — graphic barlines often
    # cause PaddleOCR to emit separate boxes without a '|' character.
    texts = _lines_from_items(ordered, warnings)
    texts = [_normalize_bars(t) for t in texts]

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
        had_bar = any("|" in line for line in jianpu_lines)
        measures = _parse_jianpu_lines(jianpu_lines, warnings)
        if not measures:
            raise ValueError("no measures parsed")

        # OCR often drops barlines and glues digits; re-slice by meter if needed.
        if not had_bar or (
            len(measures) == 1 and len(measures[0].notes) > _beats_per_measure(time_sig)
        ):
            flat = [n for m in measures for n in m.notes]
            measures = _split_notes_by_meter(flat, time_sig, warnings)
            if not had_bar:
                warnings.append(
                    "no barline tokens in OCR; measures inferred from time signature"
                )

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
                comments="MVP parse from OCR; durations/barlines are heuristic.",
            ),
        )
        return ParseResult(score=score, notes=hints, mode="score", warnings=warnings)
    except Exception as exc:  # noqa: BLE001
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


def _normalize_bars(text: str) -> str:
    """Recover barlines lost or confused by OCR.

    - Map unicode bars already handled in fullwidth table.
    - ``I`` / ``l`` between pitch tokens → ``|`` (common OCR confusion).
    - Do **not** treat ``/`` as a bar (breaks ``4/4`` time signatures).
    """
    # vertical-ish glyphs often misread as I/l (not slash — that is meter)
    text = re.sub(r"(?<=[0-7])\s*[Il丨│]\s*(?=[0-7\-])", " | ", text)
    text = re.sub(r"\|{2,}", "|", text)
    return text


def _reading_order(items: list[OcrItem]) -> list[OcrItem]:
    def key(it: OcrItem) -> tuple[float, float]:
        if it.box is None:
            return (0.0, 0.0)
        return (it.box.y1, it.box.x1)

    return sorted(items, key=key)


def _lines_from_items(items: list[OcrItem], warnings: list[str]) -> list[str]:
    """Build text lines; insert ``|`` between same-row boxes (implicit bars)."""
    with_box = [i for i in items if i.box is not None and i.text.strip()]
    without = [i for i in items if i.box is None and i.text.strip()]

    lines: list[str] = []
    if without:
        lines.extend(_normalize(i.text) for i in without)

    if not with_box:
        return lines

    # Cluster by vertical center proximity
    rows: list[list[OcrItem]] = []
    for it in sorted(with_box, key=lambda x: (x.box.y1 + x.box.y2) / 2):  # type: ignore[union-attr]
        cy = (it.box.y1 + it.box.y2) / 2  # type: ignore[union-attr]
        placed = False
        for row in rows:
            rcy = sum((r.box.y1 + r.box.y2) / 2 for r in row) / len(row)  # type: ignore[union-attr]
            # same line if centers within ~ half of average box height
            heights = [(r.box.y2 - r.box.y1) for r in row]  # type: ignore[union-attr]
            thr = max(18.0, 0.6 * (sum(heights) / len(heights)))
            if abs(cy - rcy) <= thr:
                row.append(it)
                placed = True
                break
        if not placed:
            rows.append([it])

    for row in rows:
        row_sorted = sorted(row, key=lambda x: x.box.x1)  # type: ignore[union-attr]
        # If multiple jianpu-like fragments on one row, treat gaps as barlines
        parts = [_normalize(r.text) for r in row_sorted]
        jianpu_parts = [p for p in parts if _looks_like_jianpu_line(p) or _DIGIT_RE.search(p)]
        if len(jianpu_parts) >= 2 and all(
            _DIGIT_RE.search(p) and not re.search(r"[\u4e00-\u9fff]{3,}", p)
            for p in jianpu_parts
        ):
            joined = " | ".join(jianpu_parts)
            warnings.append(
                f"inserted {len(jianpu_parts) - 1} barline(s) from horizontal OCR boxes"
            )
            lines.append(joined)
            # also keep non-jianpu fragments from this row
            for p in parts:
                if p not in jianpu_parts:
                    lines.append(p)
        else:
            # single box or mixed content — keep left-to-right join with spaces
            lines.append(" ".join(parts))

    return lines


def _detect_key(texts: list[str]) -> str | None:
    for t in texts:
        m = _KEY_RE.search(t)
        if m:
            raw = m.group(1) or m.group(2)
            if raw:
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
    if len(text) < 1:
        return False
    # Metadata / titles — never treat as pitch stream
    if re.search(
        r"(key|time|tempo|bpm|拍号|调\s*[:：]|速度|title|样例|sample|授权|来源)",
        text,
        re.I,
    ):
        # unless it also has a clear multi-pitch run with bars
        if not (re.search(r"[1-7].*[1-7].*[1-7]", text) and "|" in text):
            return False
    digits = _DIGIT_RE.findall(text)
    if len(digits) < 2:
        return False
    # Reject pure time signature lines like "4/4"
    if re.fullmatch(r"\s*[1-9][0-9]*\s*/\s*[1-9][0-9]*\s*", text):
        return False
    if re.search(r"\d+\s*/\s*\d+", text) and len(digits) <= 2 and "|" not in text:
        if not re.search(r"[1-7]\s*[1-7]", text) and not re.search(
            r"[1-7]{2,}", text
        ):
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
        line = _normalize_bars(line)
        tokens = _tokenize_jianpu(line)
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
                i += 1
                continue
            if tok == "0":
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

    flush()
    if not measures:
        warnings.append("jianpu tokens found but no notes emitted")
    return measures


def _tokenize_jianpu(line: str) -> list[str]:
    """Tokenize a jianpu line; support glued digit runs ``123|55``."""
    line = line.replace("—", "-").replace("–", "-")
    # Ensure bars are standalone
    line = re.sub(r"\|", " | ", line)
    tokens = _TOKEN_RE.findall(line)
    if tokens:
        return tokens
    # Fallback: char-wise for pure glued strings
    out: list[str] = []
    for ch in line:
        if ch in "12345670|.-":
            out.append(ch)
    return out


def _duration_from_following(
    tokens: list[str], start: int
) -> tuple[DurationName, int, int]:
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


def _note_beats(note: NoteEvent) -> float:
    base = _BEATS.get(note.duration, 1.0)
    if note.dots == 1:
        return base * 1.5
    if note.dots >= 2:
        return base * 1.75
    return base


def _beats_per_measure(time_sig: str) -> float:
    """MVP: treat numerator as quarter-note beats (OK for 2/4,3/4,4/4)."""
    try:
        num, den = time_sig.split("/")
        num_i, den_i = int(num), int(den)
        # Convert to quarter-note units: e.g. 6/8 → 3.0 quarters
        return num_i * (4.0 / den_i)
    except Exception:
        return 4.0


def _split_notes_by_meter(
    notes: list[NoteEvent],
    time_sig: str,
    warnings: list[str],
) -> list[Measure]:
    """Pack a flat note stream into measures using duration beats."""
    if not notes:
        return []
    capacity = _beats_per_measure(time_sig)
    if capacity <= 0:
        capacity = 4.0

    measures: list[Measure] = []
    buf: list[NoteEvent] = []
    acc = 0.0
    num = 1
    eps = 1e-6

    for note in notes:
        b = _note_beats(note)
        # If single note longer than a bar, put it alone
        if b > capacity + eps and not buf:
            measures.append(Measure(number=num, notes=[note]))
            num += 1
            continue
        if acc + b > capacity + eps and buf:
            measures.append(Measure(number=num, notes=list(buf)))
            num += 1
            buf = []
            acc = 0.0
        buf.append(note)
        acc += b
        if acc >= capacity - eps:
            measures.append(Measure(number=num, notes=list(buf)))
            num += 1
            buf = []
            acc = 0.0

    if buf:
        measures.append(Measure(number=num, notes=list(buf)))
        warnings.append(
            f"last measure may be incomplete ({acc:.2f}/{capacity:.2f} beats)"
        )

    return measures


def _attach_lyrics(
    measures: list[Measure], lyric_line: str, warnings: list[str]
) -> None:
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
    notes = [
        NoteEvent(
            pitch=p,
            duration=DurationName.quarter,
            extra={"source": "hint_fallback"},
        )
        for p in pitches
    ]
    measures = _split_notes_by_meter(notes, time_sig, warnings)
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
