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

from app.pipeline.duration import (
    annotate_digit_text_with_underlines,
    fit_notes_to_capacity,
    underlines_to_duration,
)
from app.pipeline.duration import (
    UnderlineHit,
    note_beats as _duration_note_beats,
)
from app.pipeline.layout import (
    classify_items,
    lyric_items,
    meta_items,
    pitch_items,
    summarize_classification,
)
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

# Pitch / rest / bar / sustain / dots / underlines (#54).
# Underline `_` (OCR) shortens duration; dashes `-` lengthen.
_TOKEN_RE = re.compile(r"[1-7]|0|\||-+|\.+|_+")

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


def extract_note_hints(
    items: list[OcrItem],
    *,
    pitch_only: bool = False,
) -> list[NoteHint]:
    """Pull simple pitch digits out of OCR strings.

    When ``pitch_only`` is True, layout classification drops title/footer/lyric
    digits (issue #34).
    """
    use_items = items
    if pitch_only and items:
        classified = classify_items(items)
        use_items = pitch_items(classified)
    notes: list[NoteHint] = []
    for item in use_items:
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
    underline_hits: list[UnderlineHit] | None = None,
) -> ParseResult:
    """Best-effort Score construction from OCR items.

    Never raises for parse ambiguity — returns mode=ocr_only or hints instead.

    ``underline_hits`` — optional CV underline counts per digit box (#54).
    """
    warnings: list[str] = []

    if not items:
        return ParseResult(
            score=None,
            notes=[],
            mode="ocr_only",
            warnings=["empty OCR; no score produced"],
        )

    # --- Layout gate (#34): classify regions, only staff lines → pitch stream
    classified = classify_items(items)
    staff_items = pitch_items(classified)
    meta_its = meta_items(classified)
    lyric_its = lyric_items(classified)
    warnings.append(f"layout: {summarize_classification(classified)}")
    dropped = len(items) - len(staff_items)
    if dropped > 0:
        warnings.append(
            f"layout filter: using {len(staff_items)}/{len(items)} OCR boxes for pitch "
            f"(dropped {dropped} non-staff region(s))"
        )

    hints = extract_note_hints(staff_items if staff_items else items)

    ordered_staff = _reading_order(staff_items if staff_items else items)
    ordered_meta = _reading_order(meta_its if meta_its else items)
    ordered_all = _reading_order(items)

    # Pitch lines only from staff boxes (inject `_` from geometry underlines)
    pitch_texts = _lines_from_items(
        ordered_staff,
        warnings,
        underline_hits=underline_hits,
    )
    pitch_texts = [_normalize_bars(t) for t in pitch_texts]

    # Key / time / tempo from meta + all (meta lines often lack boxes grouping)
    meta_texts = _lines_from_items(ordered_meta, warnings)
    all_texts = _lines_from_items(ordered_all, warnings)
    meta_texts = [_normalize(t) for t in meta_texts]
    all_texts_n = [_normalize(t) for t in all_texts]

    key = _detect_key(meta_texts + all_texts_n) or "C"
    time_sig = _detect_time(meta_texts + all_texts_n) or "4/4"
    tempo = _detect_tempo(meta_texts + all_texts_n)

    jianpu_lines = [t for t in pitch_texts if _looks_like_jianpu_line(t)]
    # If layout over-filtered, fall back to all texts with jianpu heuristic only
    if not jianpu_lines:
        fallback_lines = [_normalize_bars(t) for t in all_texts_n]
        jianpu_lines = [t for t in fallback_lines if _looks_like_jianpu_line(t)]
        if jianpu_lines:
            warnings.append(
                "layout: no pitch-region jianpu line; fell back to text heuristic"
            )

    if not jianpu_lines:
        warnings.append("no jianpu-like pitch line detected; using digit hints only")
        if hints:
            score = _score_from_flat_pitches(
                [h.pitch for h in hints if h.pitch],
                key=key,
                time_sig=time_sig,
                tempo=tempo,
                title=title or _guess_title(all_texts_n),
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
            len(measures) == 1
            and len(measures[0].notes) > _beats_per_measure(time_sig)
        ):
            flat = [n for m in measures for n in m.notes]
            flat = _preassign_stream_durations(flat, time_sig, warnings)
            measures = _split_notes_by_meter(flat, time_sig, warnings)
            if not had_bar:
                warnings.append(
                    "no barline tokens in OCR; measures inferred from time signature"
                )
        else:
            # Soft rebalance: overfull measures (missing '|') split by meter (#35)
            measures, rebalanced = _rebalance_overfull_measures(
                measures, time_sig, warnings
            )
            if rebalanced:
                warnings.append(
                    "rebalanced overfull measure(s) using time signature (#35)"
                )

        # #54: shrink default quarters → eighth/sixteenth so bars fit meter
        measures, dur_fit = _fit_durations_in_measures(measures, time_sig)
        if dur_fit:
            warnings.append(
                "fitted note durations to time signature (eighth/sixteenth soft-fit #54)"
            )

        lyric_lines = [
            _normalize(t)
            for t in _lines_from_items(_reading_order(lyric_its), warnings)
            if _looks_like_lyric_line(_normalize(t))
        ]
        if not lyric_lines:
            lyric_lines = [t for t in all_texts_n if _looks_like_lyric_line(t)]
        if lyric_lines:
            _attach_lyrics(measures, lyric_lines[0], warnings)

        score = Score(
            schema_version="0.1",
            title=title or _guess_title(all_texts_n) or "",
            key=key,
            time_signature=time_sig,
            tempo_bpm=tempo,
            parts=[Part(id="P1", name="melody", measures=measures)],
            meta=ScoreMeta(
                source_image=filename,
                engine=engine,
                created_by="enpu-parse-#10+#34+#35+#54",
                comments=(
                    "OCR parse with layout filter + multi-line/bar rebalance "
                    "(#34/#35) + duration underline/meter-fit (#54)."
                ),
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


def _item_text_for_line(
    item: OcrItem,
    underline_hits: list[UnderlineHit] | None,
) -> str:
    raw = _normalize(item.text)
    if not underline_hits or item.box is None:
        return raw
    return annotate_digit_text_with_underlines(raw, item.box, underline_hits)


def _lines_from_items(
    items: list[OcrItem],
    warnings: list[str],
    *,
    underline_hits: list[UnderlineHit] | None = None,
) -> list[str]:
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
        # Multiple boxes on one staff: only insert ``|`` on **large** horizontal
        # gaps (measure boundaries). Joining every box with ``|`` was turning each
        # OCR fragment into its own bar (M04: m2 became 17146 = real m3).
        line, n_bars = _join_staff_row_with_gap_bars(
            row_sorted, underline_hits=underline_hits
        )
        if line:
            lines.append(line)
        if n_bars > 0:
            warnings.append(
                f"inserted {n_bars} barline(s) from large horizontal OCR gaps"
            )

    return lines


def _join_staff_row_with_gap_bars(
    row_sorted: list[OcrItem],
    *,
    underline_hits: list[UnderlineHit] | None = None,
) -> tuple[str, int]:
    """Join same-row OCR boxes L→R; insert ``|`` only on large x-gaps."""
    if not row_sorted:
        return "", 0

    texts = [_item_text_for_line(r, underline_hits) for r in row_sorted]
    # Non-digit-heavy fragments (lyrics mixed in) still included but don't force bars
    if len(row_sorted) == 1:
        return texts[0], 0

    widths = [
        max(4.0, (r.box.x2 - r.box.x1))  # type: ignore[union-attr]
        for r in row_sorted
        if r.box is not None
    ]
    med_w = sorted(widths)[len(widths) // 2] if widths else 20.0
    # Inter-note gaps usually << one digit; measure gaps are larger.
    # Base threshold from digit width only — never inflate using the same gaps
    # we will classify (a single large gap must remain a bar, M04 3553|17146).
    bar_gap = max(10.0, 0.55 * med_w)

    gaps: list[float] = []
    for a, b in zip(row_sorted, row_sorted[1:]):
        if a.box is None or b.box is None:
            gaps.append(0.0)
        else:
            gaps.append(float(b.box.x1 - a.box.x2))

    # Adaptive note-gap only when we have enough small spacings to estimate.
    positive = sorted(g for g in gaps if g > 0)
    if len(positive) >= 3:
        # Typical inter-note gap ≈ lower half median; bar ≫ that
        low = positive[: max(1, len(positive) // 2)]
        note_gap = low[len(low) // 2]
        bar_gap = max(bar_gap, note_gap * 2.5)
    elif len(positive) == 2:
        bar_gap = max(bar_gap, min(positive) * 2.0 + 1.0)

    parts: list[str] = [texts[0]]
    n_bars = 0
    for i, g in enumerate(gaps):
        nxt = texts[i + 1]
        # Only bar between digit-like fragments
        left_dig = bool(_DIGIT_RE.search(parts[-1].split("|")[-1]))
        right_dig = bool(_DIGIT_RE.search(nxt))
        if g >= bar_gap and left_dig and right_dig:
            parts.append("|")
            n_bars += 1
        parts.append(nxt)

    # Collapse to spaced string: "3 5 | 1 7"
    out: list[str] = []
    for p in parts:
        if p == "|":
            out.append("|")
        else:
            out.append(p)
    # Build: join non-bar with space, bars as separators
    chunks: list[str] = []
    buf: list[str] = []
    for p in out:
        if p == "|":
            if buf:
                chunks.append(" ".join(buf))
                buf = []
            chunks.append("|")
        else:
            buf.append(p)
    if buf:
        chunks.append(" ".join(buf))
    # "a b | c" style
    s = " ".join(chunks)
    s = re.sub(r"\s*\|\s*", " | ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s, n_bars


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
    # Metadata / titles / eval annotations — never treat as pitch stream
    if re.search(
        r"(key|time|tempo|bpm|拍号|调\s*[:：]|速度|title|样例|sample|授权|来源|"
        r"音高序列|pitch\s*sequence|\bgt\b|子集|enpu\s*eval)",
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
    """Parse one or more jianpu systems.

    Issue #35: flush at **end of each staff line** so the last measure of line N
    never absorbs the first notes of line N+1 when the trailing ``|`` is omitted
    (common in engraving and OCR of ``001_poc_digits.png``).
    """
    measures: list[Measure] = []
    measure_num = 1
    current_notes: list[NoteEvent] = []
    line_breaks = 0

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
                # Standalone duration marks already consumed via _duration_from_following
                # when attached; if orphaned after a bar, skip.
                i += 1
                continue
            if tok == "0":
                dur, dots, consumed, dur_from = _duration_from_following(tokens, i + 1)
                current_notes.append(
                    NoteEvent(
                        is_rest=True,
                        duration=dur,
                        dots=dots,
                        extra={
                            "source": "ocr_parse",
                            "token": tok,
                            "duration_from": dur_from,
                        },
                    )
                )
                i += 1 + consumed
                continue
            if tok in "1234567":
                dur, dots, consumed, dur_from = _duration_from_following(tokens, i + 1)
                current_notes.append(
                    NoteEvent(
                        pitch=tok,
                        octave=0,
                        duration=dur,
                        dots=dots,
                        extra={
                            "source": "ocr_parse",
                            "duration_from": dur_from,
                        },
                    )
                )
                i += 1 + consumed
                continue
            i += 1
        # System / staff-line break — close open measure before next row
        if current_notes:
            flush()
            line_breaks += 1

    flush()
    if line_breaks and len(lines) > 1:
        warnings.append(
            f"flushed measure at {line_breaks} staff-line break(s) (#35 multi-line)"
        )
    if not measures:
        warnings.append("jianpu tokens found but no notes emitted")
    return measures


def _measure_beats(measure: Measure) -> float:
    return sum(_note_beats(n) for n in measure.notes)


def _fit_durations_in_measures(
    measures: list[Measure],
    time_sig: str,
) -> tuple[list[Measure], bool]:
    """Apply #54 soft duration fit per measure; renumber if unchanged structure."""
    capacity = _beats_per_measure(time_sig)
    if capacity <= 0 or not measures:
        return measures, False
    any_changed = False
    out: list[Measure] = []
    for meas in measures:
        fitted, ch = fit_notes_to_capacity(list(meas.notes), capacity)
        if ch:
            any_changed = True
        out.append(
            Measure(number=meas.number, notes=fitted, extra=dict(meas.extra or {}))
        )
    return out, any_changed


def _rebalance_overfull_measures(
    measures: list[Measure],
    time_sig: str,
    warnings: list[str],
) -> tuple[list[Measure], bool]:
    """Split measures whose beat total exceeds the time signature capacity.

    Tries duration soft-fit (#54) first so eighths/sixteenths reduce inflation
    before cutting the bar into more measures.
    """
    capacity = _beats_per_measure(time_sig)
    if capacity <= 0:
        return measures, False
    eps = 0.35  # allow slight overfill from dotted heuristics
    out: list[Measure] = []
    changed = False
    for meas in measures:
        # Prefer shortening notes over splitting the measure
        fitted, fit_ch = fit_notes_to_capacity(list(meas.notes), capacity, eps=eps)
        if fit_ch:
            changed = True
        beats = sum(_note_beats(n) for n in fitted)
        if beats <= capacity + eps or len(fitted) <= 1:
            out.append(
                Measure(number=meas.number, notes=fitted, extra=dict(meas.extra or {}))
            )
            continue
        # Pack notes of this measure into sub-measures by meter
        sub = _split_notes_by_meter(list(fitted), time_sig, warnings)
        if len(sub) <= 1:
            out.append(
                Measure(number=meas.number, notes=fitted, extra=dict(meas.extra or {}))
            )
            continue
        changed = True
        out.extend(sub)
    if not changed:
        return measures, False
    # Renumber
    renum = [
        Measure(number=i, notes=m.notes, extra=m.extra)
        for i, m in enumerate(out, start=1)
    ]
    return renum, True


def _tokenize_jianpu(line: str) -> list[str]:
    """Tokenize a jianpu line; support glued digit runs ``123|55``."""
    line = line.replace("—", "-").replace("–", "-")
    # OCR underlines sometimes as fullwidth underscore
    line = line.replace("＿", "_").replace("—", "-")
    # Ensure bars are standalone
    line = re.sub(r"\|", " | ", line)
    tokens = _TOKEN_RE.findall(line)
    if tokens:
        return tokens
    # Fallback: char-wise for pure glued strings
    out: list[str] = []
    for ch in line:
        if ch in "12345670|.-_":
            out.append(ch)
    return out


def _duration_from_following(
    tokens: list[str], start: int
) -> tuple[DurationName, int, int, str]:
    """Return (duration, dots, consumed, duration_from).

    Priority: dashes (longer) override underlines; underlines shorten base.
    """
    dashes = 0
    dots = 0
    underlines = 0
    j = start
    while j < len(tokens):
        t = tokens[j]
        if t.startswith("_") or t == "_":
            underlines += t.count("_") if t.startswith("_") else 1
            j += 1
            continue
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
    consumed = j - start

    if dashes >= 3:
        return DurationName.whole, dots, consumed, "dash"
    if dashes == 2:
        return DurationName.half, max(dots, 1), consumed, "dash"
    if dashes == 1:
        return DurationName.half, dots, consumed, "dash"

    if underlines >= 2:
        return (
            underlines_to_duration(underlines),
            dots,
            consumed,
            "ocr_underscore",
        )
    if underlines == 1:
        return DurationName.eighth, dots, consumed, "ocr_underscore"

    return DurationName.quarter, dots, consumed, "default"


def _note_beats(note: NoteEvent) -> float:
    return _duration_note_beats(note)


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


def _preassign_stream_durations(
    notes: list[NoteEvent],
    time_sig: str,
    warnings: list[str],
) -> list[NoteEvent]:
    """Dense short runs (one bar of eighths) without underline OCR (#54).

    Only when all default quarters would form **exactly one overfull bar**
    that fits as eighths (e.g. 5–8 notes in 4/4). Longer streams keep quarters
    and pack into multiple measures (existing no-barline behavior).
    """
    if not notes:
        return notes
    capacity = _beats_per_measure(time_sig)
    if capacity <= 0:
        return notes
    defaults = [
        n
        for n in notes
        if (n.extra or {}).get("duration_from", "default") == "default"
        and n.duration == DurationName.quarter
        and n.dots == 0
    ]
    if len(defaults) < len(notes) * 0.8:
        return notes

    n = len(notes)
    # One bar of eighths: capacity < n*quarter but n*eighth <= capacity
    if n * 1.0 <= capacity + 0.35:
        return notes  # already fits as quarters
    if n * 0.5 <= capacity + 0.35 and n * 1.0 > capacity + 0.35:
        out = [x.model_copy(deep=True) for x in notes]
        for note in out:
            if (note.extra or {}).get("duration_from", "default") != "default":
                continue
            if note.duration == DurationName.quarter and note.dots == 0:
                note.duration = DurationName.eighth
                note.extra = {**(note.extra or {}), "duration_from": "meter_fit"}
        warnings.append(
            f"preassigned stream durations to eighth for {n} notes (#54)"
        )
        return out
    return notes


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
            extra={"source": "hint_fallback", "duration_from": "default"},
        )
        for p in pitches
    ]
    notes = _preassign_stream_durations(notes, time_sig, warnings)
    measures = _split_notes_by_meter(notes, time_sig, warnings)
    measures, fit = _fit_durations_in_measures(measures, time_sig)
    if fit:
        warnings.append("fitted flat-pitch measure durations (#54)")
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
            created_by="enpu-parse-mvp-#10+#54",
            comments="Built from digit hints (no full jianpu line).",
        ),
    )
