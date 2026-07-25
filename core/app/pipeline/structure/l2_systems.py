"""L2: staff / system detection with pitch+chord+lyric binding (#58 / #61 / #64).

A logical **StaffSystem** is one melody row whose rectangle covers:
  - optional chord label band **above** (chord_above) or **below** (chord_below)
  - pitch (jianpu digits) band
  - optional lyric band below
  - underline / ornament strips between them

Chord and lyric are **not** separate L2 systems.

Pipeline:
  1. Find pitch (jianpu digit) anchors via narrow-digit scoring
  2. Infer a **page-level row layout mode** (chord_above vs chord_below)
  3. Bind aux bands with mode-specific rules so both worship layouts work
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import cv2
import numpy as np

from app.pipeline.structure.ir import Rect, StaffSystem

# "secondary" is temporary until bind assigns chord vs lyric
BandRole = Literal["pitch", "chord", "lyric", "underline", "secondary", "noise"]
# Page-level stack pattern around each melody row
LayoutMode = Literal["chord_above", "chord_below", "pitch_only"]


@dataclass
class _Band:
    """Horizontal ink band in full-image coordinates."""

    y0: int
    y1: int
    role: BandRole
    n_digitish: int
    med_ch: float
    n_wide: int
    staff_score: float
    n_narrow: int = 0  # narrow digit-like (jianpu 1–7)
    n_square: int = 0  # squarer CJK / chord-letter glyphs

    @property
    def height(self) -> int:
        return max(1, self.y1 - self.y0)

    @property
    def cy(self) -> float:
        return 0.5 * (self.y0 + self.y1)

    @property
    def pitchness(self) -> float:
        """How pitch-row-like: taller mid-glyphs + narrow digits + staff score."""
        return (
            float(self.med_ch) * 0.6
            + float(self.staff_score) * 40.0
            + float(self.height) * 0.25
            + float(self.n_narrow) * 1.5
            - float(self.n_square) * 0.4
        )


def detect_staff_systems(
    image_bgr: np.ndarray,
    score_rect: Rect,
    *,
    min_row_gap: int = 8,
    min_row_height: int = 8,
    max_attach_gap_factor: float = 2.6,
) -> tuple[list[StaffSystem], list[str]]:
    """Detect logical staff systems inside the main score ROI.

    1. Horizontal projection → fine ink bands
    2. Coarse classify (underline / content / noise)
    3. Cluster by large vertical gaps (one cluster = one melody system)
    4. Inside cluster: best pitch band + chord/lyric order; system rect = union
    """
    warnings: list[str] = []
    h, w = image_bgr.shape[:2]
    x0 = max(0, int(score_rect.x1))
    y0 = max(0, int(score_rect.y1))
    x1 = min(w, int(score_rect.x2))
    y1 = min(h, int(score_rect.y2))
    if x1 <= x0 or y1 <= y0:
        warnings.append("L2: empty score ROI")
        return [], warnings

    roi = image_bgr[y0:y1, x0:x1]
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    rh, rw = bw.shape[:2]
    row_ink = (bw > 0).sum(axis=1).astype(np.float32)
    if row_ink.max() <= 0:
        warnings.append("L2: no ink in score ROI; single system fallback")
        return [
            StaffSystem(
                index=0,
                rect=Rect(float(x0), float(y0), float(x1), float(y1)),
                confidence=0.3,
            )
        ], warnings

    # Adaptive binarization path for noisy scans (#64): re-threshold if Otsu is noisy
    ink_ratio = float((bw > 0).mean())
    if ink_ratio > 0.28 or ink_ratio < 0.02:
        bw = cv2.adaptiveThreshold(
            gray,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY_INV,
            31,
            12,
        )
        row_ink = (bw > 0).sum(axis=1).astype(np.float32)
        warnings.append("L2: adaptive threshold for scan-like ink density (#64)")

    # Light smooth; keep pitch / chord / lyric as separate bands
    k = 5
    smooth = np.convolve(row_ink, np.ones(k) / k, mode="same")
    # Slightly higher relative thr to separate stacked rows on dense scans
    thr = max(float(smooth.max()) * 0.14, rw * 0.012)
    active = smooth >= thr
    raw_runs = _active_runs(active)
    raw_runs = [(a, b) for a, b in raw_runs if b - a >= max(3, min_row_height // 3)]
    # Keep bands separate: only glue very tight underlines (smaller than before)
    merged_runs = _merge_close_runs(raw_runs, max_gap=min(min_row_gap, 6))

    bands: list[_Band] = []
    for a, b in merged_runs:
        if b - a < min_row_height // 2 and b - a < 6:
            continue
        gy0, gy1 = y0 + a, y0 + b
        stats = _band_component_stats(bw[a:b, :])
        role = _classify_band(height=b - a, **stats)
        if role == "noise":
            continue
        bands.append(
            _Band(
                y0=gy0,
                y1=gy1,
                role=role,
                n_digitish=int(stats["n_digitish"]),
                med_ch=float(stats["med_ch"]),
                n_wide=int(stats["n_wide"]),
                staff_score=float(stats["staff_score"]),
                n_narrow=int(stats.get("n_narrow", 0)),
                n_square=int(stats.get("n_square", 0)),
            )
        )

    if not bands:
        warnings.append("L2: no bands; single system fallback")
        return [
            StaffSystem(
                index=0,
                rect=Rect(float(x0), float(y0), float(x1), float(y1)),
                confidence=0.35,
            )
        ], warnings

    content_hs = [b.height for b in bands if b.role != "underline"]
    med_content_h = float(np.median(content_hs)) if content_hs else 32.0
    # Intra: pitch→chord/lyric. Inter: between systems (usually larger).
    # Use gap quantiles so M04 (~100px inter) and compact scans both work (#64).
    gaps = [
        float(bands[i + 1].y0 - bands[i].y1)
        for i in range(len(bands) - 1)
        if bands[i].role != "underline" or bands[i + 1].role != "underline"
    ]
    max_intra_gap = _adaptive_max_intra_gap(gaps, med_content_h, max_attach_gap_factor)

    systems = _cluster_and_bind(
        bands,
        x0=float(x0),
        x1=float(x1),
        page_h=h,
        max_intra_gap=max_intra_gap,
        med_content_h=med_content_h,
    )

    if not systems:
        warnings.append("L2: bind produced empty; single system fallback")
        systems = [
            StaffSystem(
                index=0,
                rect=Rect(float(x0), float(y0), float(x1), float(y1)),
                confidence=0.35,
            )
        ]
    else:
        n_aux = sum(
            1
            for s in systems
            for band in (s.extra.get("bands") or [])
            if band.get("role") in {"chord", "lyric", "underline"}
        )
        mode = next(
            (str(s.extra.get("layout_mode")) for s in systems if s.extra.get("layout_mode")),
            "unknown",
        )
        warnings.append(
            f"L2: detected {len(systems)} melody system(s), "
            f"{n_aux} attached aux band(s), layout={mode} (#61/#64)"
        )
    return systems, warnings


def _active_runs(active: np.ndarray) -> list[tuple[int, int]]:
    runs: list[tuple[int, int]] = []
    in_run = False
    a0 = 0
    for i, a in enumerate(active):
        if a and not in_run:
            in_run = True
            a0 = i
        elif not a and in_run:
            in_run = False
            runs.append((a0, i))
    if in_run:
        runs.append((a0, len(active)))
    return runs


def _merge_close_runs(
    runs: list[tuple[int, int]],
    *,
    max_gap: int,
) -> list[tuple[int, int]]:
    if not runs:
        return []
    out: list[tuple[int, int]] = [runs[0]]
    for b0, b1 in runs[1:]:
        p0, p1 = out[-1]
        if b0 - p1 <= max_gap:
            out[-1] = (p0, b1)
        else:
            out.append((b0, b1))
    return out


def _band_component_stats(strip: np.ndarray) -> dict[str, float | int]:
    h, w = strip.shape[:2]
    num, _lab, stats, _ = cv2.connectedComponentsWithStats(strip, connectivity=8)
    dig = 0
    wide = 0
    narrow = 0
    square = 0
    chs: list[float] = []
    for i in range(1, num):
        _x, _y, cw, ch, area = stats[i]
        if area < 18:
            continue
        chs.append(float(ch))
        aspect = cw / max(ch, 1)
        if 10 <= ch <= 95 and 0.22 <= aspect <= 2.0:
            dig += 1
        # Jianpu digits are relatively narrow; CJK / chord letters more square
        if 10 <= ch <= 95 and 0.22 <= aspect <= 0.95:
            narrow += 1
        if 10 <= ch <= 95 and 0.75 <= aspect <= 1.55:
            square += 1
        if aspect >= 2.5 and ch <= 18:
            wide += 1
    med_ch = float(np.median(chs)) if chs else float(h)
    staff_score = 0.0
    if dig >= 6 and 14 <= h <= 70:
        staff_score = 0.5 + min(0.4, 0.015 * dig)
        if narrow >= max(4, dig // 2):
            staff_score += 0.08
    elif dig >= 3 and 12 <= h <= 75:
        staff_score = 0.35
    return {
        "n_digitish": dig,
        "n_wide": wide,
        "n_narrow": narrow,
        "n_square": square,
        "med_ch": med_ch,
        "staff_score": staff_score,
        "n_comps": max(0, num - 1),
    }


def _classify_band(
    *,
    height: int,
    n_digitish: int,
    n_wide: int,
    med_ch: float,
    staff_score: float,
    n_comps: int,
    n_narrow: int = 0,
    n_square: int = 0,
) -> BandRole:
    """Coarse label only. Pitch vs chord/lyric is refined inside each cluster (#61)."""
    del n_narrow, n_square  # used only by pitch scoring later
    # Thin horizontal strokes (duration underlines, slur ink strips)
    if height <= 12 and (n_wide >= 1 or n_digitish <= 2):
        return "underline"
    if height <= 10:
        return "underline"

    # Content band: digits / chord labels / lyrics (disambiguate later)
    # Scan/print scales vary — allow smaller med_ch for pitch on compact pages (#64)
    if n_digitish >= 3 and 12 <= height <= 80:
        if med_ch >= 22.0 and height >= 16 and staff_score >= 0.35 and n_digitish >= 5:
            return "pitch"
        if med_ch >= 26.0 and height >= 28 and staff_score >= 0.35:
            return "pitch"
        if med_ch >= 24.0 and height >= 20 and n_digitish >= 8:
            return "pitch"
        return "secondary"
    if n_comps >= 6 and 12 <= height <= 60:
        return "secondary"
    if staff_score >= 0.35 and 14 <= height <= 80:
        return "pitch" if med_ch >= 20 else "secondary"

    if height < 14:
        return "underline"
    return "noise"


def _adaptive_max_intra_gap(
    gaps: list[float],
    med_content_h: float,
    max_attach_gap_factor: float,
) -> float:
    """Choose attach budget: above pitch→chord, below inter-system gaps.

    M04 needs ~50–80px to keep chord under pitch; compact scans need
    subdivision of over-tall clusters rather than a tiny gap alone (#64).
    """
    base = max(48.0, max_attach_gap_factor * med_content_h)
    if not gaps:
        return base
    gs = np.array([g for g in gaps if g >= 0], dtype=np.float32)
    if gs.size == 0:
        return base
    p40 = float(np.percentile(gs, 40))
    p75 = float(np.percentile(gs, 75))
    # Floor: enough for pitch → chord (~1.5–2 staff heights)
    adaptive = max(p40 * 1.5, 1.85 * med_content_h, 48.0)
    # If clearly bimodal, stay under large inter-system gap
    if p75 > p40 * 1.9 and p75 > 60:
        adaptive = min(adaptive, 0.72 * p75)
    return float(np.clip(adaptive, 48.0, max(base, 110.0)))


def _gap_split_clusters(
    bands: list[_Band],
    *,
    max_intra_gap: float,
) -> list[list[_Band]]:
    """Split band list on large vertical gaps."""
    if not bands:
        return []
    clusters: list[list[_Band]] = []
    cur: list[_Band] = [bands[0]]
    for b in bands[1:]:
        gap = b.y0 - cur[-1].y1
        if gap > max_intra_gap:
            clusters.append(cur)
            cur = [b]
        else:
            cur.append(b)
    clusters.append(cur)
    return clusters


def _subdivide_tall_cluster(
    cluster: list[_Band],
    *,
    med_content_h: float,
    max_intra_gap: float,
) -> list[list[_Band]]:
    """If a gap-cluster is taller than ~2 systems, split on pitch-like peaks (#64)."""
    if len(cluster) < 2:
        return [cluster]
    y0 = min(b.y0 for b in cluster)
    y1 = max(b.y1 for b in cluster)
    # One system ≈ pitch + chord + lyric (+ pads) — taller stacks are multi-system
    max_sys_h = max(100.0, 6.2 * med_content_h)
    if (y1 - y0) <= max_sys_h * 1.25:
        return [cluster]

    # Pitch peaks: local max of med_ch among content bands, spaced apart
    content = [(i, b) for i, b in enumerate(cluster) if b.role != "underline"]
    if len(content) < 2:
        return [cluster]

    scores = [
        (i, b.med_ch * 0.7 + b.n_digitish * 0.8 + b.staff_score * 20 + b.height * 0.2)
        for i, b in content
    ]
    max_s = max(s for _, s in scores)
    thr = max_s * 0.72
    peaks = [i for i, s in scores if s >= thr]
    # Local max filter (prefer upper when close)
    min_sep = max(28.0, 2.0 * med_content_h)
    peaks_sorted = sorted(peaks, key=lambda i: cluster[i].y0)
    anchors: list[int] = []
    for i in peaks_sorted:
        if not anchors:
            anchors.append(i)
            continue
        prev = anchors[-1]
        if cluster[i].y0 - cluster[prev].y0 >= min_sep:
            anchors.append(i)
        else:
            # Keep stronger / taller med_ch
            if cluster[i].med_ch > cluster[prev].med_ch * 1.05:
                anchors[-1] = i

    if len(anchors) <= 1:
        return [cluster]

    out: list[list[_Band]] = []
    for k, ai in enumerate(anchors):
        left = ai
        # underlines glued above pitch
        while left > 0 and cluster[left - 1].role == "underline":
            if cluster[ai].y0 - cluster[left - 1].y1 <= max(8.0, 0.35 * med_content_h):
                left -= 1
            else:
                break
        right = anchors[k + 1] if k + 1 < len(anchors) else len(cluster)
        sub = cluster[left:right]
        # Trim by attach budget under this pitch
        pitch_b = cluster[ai]
        trimmed: list[_Band] = []
        for b in sub:
            if b.y0 <= pitch_b.y1 or b is pitch_b:
                trimmed.append(b)
                continue
            ref = trimmed[-1] if trimmed else pitch_b
            if b.y0 - ref.y1 <= max_intra_gap:
                trimmed.append(b)
            else:
                break
        if trimmed:
            out.append(trimmed)
    return out if out else [cluster]


def _melody_pitch_indices(bands: list[_Band], *, med_content_h: float) -> list[int]:
    """Strong jianpu digit rows (melody), not chord-letter or lyric CJK rows.

    Discriminators used on worship charts (#64 勇敢走出去 / M04):
    - Pitch digits: high narrow_ratio, near-zero n_square, taller med_ch
    - Chord letters: shorter med_ch, fewer comps, mixed square
    - Lyric CJK: high square_ratio (aspect ~1), moderate med_ch
    """
    scored: list[tuple[int, float]] = []
    for i, b in enumerate(bands):
        if b.role == "underline":
            continue
        if b.n_digitish < 4:
            continue
        if b.height < max(12.0, 0.45 * med_content_h):
            continue

        narrow_ratio = b.n_narrow / max(b.n_digitish, 1)
        square_ratio = b.n_square / max(b.n_digitish, 1)

        # Hard reject lyric-like CJK: square dominates AND digits are not narrow.
        # (Blurry scans can mark the same glyph as both narrow+square — keep those.)
        if (
            square_ratio >= 0.42
            and b.n_square >= 8
            and b.n_square >= b.n_narrow * 0.85
            and narrow_ratio < 0.72
        ):
            continue
        # Hard reject short sparse chord-letter rows
        if (
            b.med_ch < 0.70 * max(med_content_h, 1.0)
            and b.n_narrow < 12
            and square_ratio > 0.15
            and narrow_ratio < 0.80
        ):
            continue

        score = (
            float(b.med_ch) * 1.25
            + float(b.n_narrow) * 2.0
            + float(b.n_digitish) * 0.35
            + float(b.staff_score) * 30.0
            + float(b.height) * 0.35
            + narrow_ratio * 22.0
            - float(b.n_square) * 1.4
            - square_ratio * 28.0
        )
        if b.role == "pitch":
            score *= 1.06
        # Soft penalty: short glyphs without narrow dominance (chord-ish)
        if b.med_ch < 0.82 * max(med_content_h, 1.0) and narrow_ratio < 0.75:
            score *= 0.62
        # Soft penalty for square-heavy rows (lyric), but mild if also narrow (scan blur)
        if square_ratio >= 0.30 and narrow_ratio < 0.85:
            score *= 0.70
        scored.append((i, score))

    if not scored:
        # Fallback: prefer low-square high-narrow content bands
        for i, b in enumerate(bands):
            if b.role == "underline" or b.n_digitish < 3:
                continue
            square_ratio = b.n_square / max(b.n_digitish, 1)
            if square_ratio >= 0.5 and b.n_square >= 8:
                continue
            scored.append((i, b.pitchness - b.n_square * 0.8))
    if not scored:
        return []

    # Prefer top-tier med_ch so residual chord/lyric lose
    top_n = max(2, len(scored) // 3)
    top = sorted(scored, key=lambda t: -t[1])[:top_n]
    med_top_ch = float(np.median([bands[i].med_ch for i, _ in top]))
    max_s = max(s for _, s in scored)
    thr = max_s * 0.55
    cands = [
        i
        for i, s in scored
        if s >= thr and bands[i].med_ch >= 0.84 * med_top_ch
    ]
    if len(cands) < 2:
        cands = [i for i, s in scored if s >= thr]
    if not cands:
        cands = [max(scored, key=lambda t: t[1])[0]]

    # Vertical spacing: one melody per system (pitch + chord + lyric stack).
    # Compact 2-staff pages (002_scan_like) need ~1.5 staff heights; worship
    # charts with chord+lyric stacks need more — use adaptive floor.
    min_sep = max(28.0, 1.55 * med_content_h)
    cands = sorted(set(cands), key=lambda i: bands[i].y0)
    kept: list[int] = []
    score_map = {i: s for i, s in scored}
    for i in cands:
        if not kept:
            kept.append(i)
            continue
        prev = kept[-1]
        if bands[i].y0 - bands[prev].y0 >= min_sep:
            kept.append(i)
        elif score_map[i] > score_map[prev] * 1.06:
            kept[-1] = i
    return kept


def _infer_layout_mode(
    bands: list[_Band],
    pitch_idxs: list[int],
    *,
    med_content_h: float,
) -> LayoutMode:
    """Detect page-level stack pattern: chord above vs below melody (#64).

    Majority vote over pitch anchors using nearby non-pitch content bands:
      - chord_above: content sits above pitch (E / B/D# …), lyrics below
      - chord_below: no content above; 1–2 content bands under pitch (M04)
    """
    if not pitch_idxs:
        return "pitch_only"

    pitch_set = set(pitch_idxs)
    votes_above = 0
    votes_below = 0
    attach_above = max(48.0, 2.2 * med_content_h)
    attach_below = max(60.0, 3.8 * med_content_h)

    for k, pi in enumerate(pitch_idxs):
        p = bands[pi]
        next_y0 = bands[pitch_idxs[k + 1]].y0 if k + 1 < len(pitch_idxs) else p.y1 + 10_000

        above = [
            b
            for i, b in enumerate(bands)
            if i not in pitch_set
            and b.role != "underline"
            and b.y1 <= p.y0 + 2
            and (p.y0 - b.y1) <= attach_above
        ]
        below = [
            b
            for i, b in enumerate(bands)
            if i not in pitch_set
            and b.role != "underline"
            and b.y0 >= p.y1 - 2
            and b.y0 < next_y0 - 4
            and (b.y0 - p.y1) <= attach_below
        ]

        if above:
            votes_above += 1
        if len(below) >= 1 and not above:
            votes_below += 1
        elif len(below) >= 2:
            # chord_above usually has lyric(s) below as well
            votes_above += 0  # already counted
            if not above:
                votes_below += 1

    if votes_above == 0 and votes_below == 0:
        return "pitch_only"
    # Prefer the dominant page pattern (ties → chord_below is more common in
    # labeled 主/副/词 charts like M04)
    if votes_above > votes_below:
        return "chord_above"
    return "chord_below"


def _own_bands_by_pitch(
    bands: list[_Band],
    pitch_idxs: list[int],
    *,
    max_intra_gap: float,
    med_content_h: float,
    layout_mode: LayoutMode,
) -> dict[int, list[_Band]]:
    """Assign every non-pitch band to a pitch system (#61/#64).

    Mode-aware binding:
      - **chord_below** (M04): all bands between pitch[i] and pitch[i+1]
        belong to system i (pitch → chord → lyric stack).
      - **chord_above** (勇敢走出去): split on the **largest gap** so
        lyric_i stays with pitch_i and chord_{i+1} goes to the next system.
    """
    owned: dict[int, list[_Band]] = {pi: [bands[pi]] for pi in pitch_idxs}
    if not pitch_idxs:
        return owned

    pitch_set = set(pitch_idxs)
    claimed: set[int] = set()

    for k in range(len(pitch_idxs) - 1):
        pi, pj = pitch_idxs[k], pitch_idxs[k + 1]
        p, n = bands[pi], bands[pj]
        mids = [
            i
            for i, b in enumerate(bands)
            if i not in pitch_set
            and b.y0 >= p.y1 - 3
            and b.y1 <= n.y0 + 3
        ]
        mids_sorted = sorted(mids, key=lambda i: bands[i].y0)

        if layout_mode == "chord_below":
            # pitch → chord → lyric all stay with upper melody, but thin
            # ornaments glued just above the *next* pitch (octave dots /
            # underlines) belong to the lower system.
            glue_next = max(10.0, 0.5 * med_content_h)
            for bi in mids_sorted:
                b = bands[bi]
                dist_to_next = n.y0 - b.y1
                near_next = dist_to_next <= glue_next and b.y1 <= n.y0 + 2
                thin = b.role == "underline" or b.height <= max(12, 0.45 * med_content_h)
                if near_next and thin:
                    owned[pj].append(b)
                else:
                    owned[pi].append(b)
                claimed.add(bi)
            continue

        # chord_above / pitch_only: largest-gap split
        sequence = [pi] + mids_sorted + [pj]
        best_gap = -1.0
        best_t = 0
        for t in range(len(sequence) - 1):
            gap = float(bands[sequence[t + 1]].y0 - bands[sequence[t]].y1)
            if gap > best_gap:
                best_gap = gap
                best_t = t
        for t, bi in enumerate(sequence):
            if bi in pitch_set:
                continue
            if t <= best_t:
                owned[pi].append(bands[bi])
            else:
                owned[pj].append(bands[bi])
            claimed.add(bi)

    first, last = pitch_idxs[0], pitch_idxs[-1]
    p_first, p_last = bands[first], bands[last]
    # chord_above: first system chords sit above first pitch
    above_budget = max(max_intra_gap, 2.4 * med_content_h, 70.0)
    # chord_below stacks can be tall (pitch+chord+lyric ~ 3–4 staff heights)
    below_budget = max(max_intra_gap, 4.2 * med_content_h, 120.0)

    for i, b in enumerate(bands):
        if i in pitch_set or i in claimed:
            continue
        attached = False
        for pi in pitch_idxs:
            pb = bands[pi]
            if b.y1 > pb.y0 and b.y0 < pb.y1:
                owned[pi].append(b)
                attached = True
                break
        if attached:
            continue
        if b.y1 <= p_first.y0:
            dist = p_first.y0 - b.y1
            if dist <= above_budget and layout_mode in {"chord_above", "pitch_only"}:
                owned[first].append(b)
            elif dist <= above_budget * 0.6:
                # rare: ornament above pitch even in chord_below
                owned[first].append(b)
            continue
        if b.y0 >= p_last.y1:
            dist = b.y0 - p_last.y1
            if dist <= below_budget:
                owned[last].append(b)
            continue
        best_pi = min(
            pitch_idxs,
            key=lambda pi: (
                bands[pi].y0 - b.y1
                if b.y1 <= bands[pi].y0
                else b.y0 - bands[pi].y1
                if b.y0 >= bands[pi].y1
                else 0.0
            ),
        )
        owned[best_pi].append(b)

    return owned


def _cluster_and_bind(
    bands: list[_Band],
    *,
    x0: float,
    x1: float,
    page_h: int,
    max_intra_gap: float,
    med_content_h: float,
) -> list[StaffSystem]:
    """Pitch-centric systems with page-level layout mode (#61/#64).

    1. Pitch anchors (jianpu digit rows)
    2. Infer chord_above vs chord_below from the whole page
    3. Mode-aware aux bind + role labeling
    """
    if not bands:
        return []

    pitch_idxs = _melody_pitch_indices(bands, med_content_h=med_content_h)
    layout_mode: LayoutMode = "pitch_only"
    if not pitch_idxs:
        raw = _gap_split_clusters(bands, max_intra_gap=max_intra_gap)
        clusters: list[list[_Band]] = []
        for cl in raw:
            clusters.extend(
                _subdivide_tall_cluster(
                    cl, med_content_h=med_content_h, max_intra_gap=max_intra_gap
                )
            )
    else:
        layout_mode = _infer_layout_mode(
            bands, pitch_idxs, med_content_h=med_content_h
        )
        owned = _own_bands_by_pitch(
            bands,
            pitch_idxs,
            max_intra_gap=max_intra_gap,
            med_content_h=med_content_h,
            layout_mode=layout_mode,
        )
        clusters = []
        for pi in pitch_idxs:
            cl = sorted(owned[pi], key=lambda bb: bb.y0)
            clusters.append(cl)

    systems: list[StaffSystem] = []
    med_pitch_h = float(
        np.median([bands[i].height for i in pitch_idxs])
        if pitch_idxs
        else med_content_h
    )
    med_pitch_ch = float(
        np.median([bands[i].med_ch for i in pitch_idxs])
        if pitch_idxs
        else med_content_h
    )
    for cluster in clusters:
        labeled = _label_cluster_roles(cluster, layout_mode=layout_mode)
        if not any(b.role == "pitch" for b in labeled):
            content = [b for b in labeled if b.role != "underline"]
            if content:
                best = max(content, key=lambda b: b.pitchness)
                best.role = "pitch"
                _assign_chord_lyric(labeled, layout_mode=layout_mode)
            else:
                continue
        if _is_weak_meta_system(
            labeled,
            med_pitch_h=med_pitch_h,
            med_pitch_ch=med_pitch_ch,
            page_h=page_h,
        ):
            continue
        systems.append(
            _system_from_bands(
                labeled,
                x0=x0,
                x1=x1,
                page_h=page_h,
                index=len(systems),
                layout_mode=layout_mode,
            )
        )
    # Clip padding so adjacent system rects do not swallow each other
    for i in range(len(systems) - 1):
        a, b = systems[i], systems[i + 1]
        if a.rect.y2 > b.rect.y1:
            mid = 0.5 * (a.rect.y2 + b.rect.y1)
            # Prefer not to cut into actual band content
            a_bands = a.extra.get("bands") or []
            b_bands = b.extra.get("bands") or []
            a_content_y1 = max((bb["y1"] for bb in a_bands), default=a.rect.y2)
            b_content_y0 = min((bb["y0"] for bb in b_bands), default=b.rect.y1)
            split = float(np.clip(mid, a_content_y1, b_content_y0)) if b_content_y0 >= a_content_y1 else mid
            a.rect = Rect(a.rect.x1, a.rect.y1, a.rect.x2, split)
            b.rect = Rect(b.rect.x1, split, b.rect.x2, b.rect.y2)
    return systems


def _is_weak_meta_system(
    cluster: list[_Band],
    *,
    med_pitch_h: float,
    med_pitch_ch: float,
    page_h: int,
) -> bool:
    """Filter key/time or stray header rows mistaken for melody systems."""
    pitch = next((b for b in cluster if b.role == "pitch"), None)
    if pitch is None:
        return True
    content = [b for b in cluster if b.role != "underline"]
    # Near top of page: short / small-glyph row → 1=E · 4/4 / tempo crumbs
    near_top = pitch.y0 < 0.18 * page_h
    small_glyphs = pitch.med_ch < max(18.0, 0.78 * med_pitch_ch)
    short_band = pitch.height < 0.85 * med_pitch_h
    no_lyric = not any(b.role == "lyric" for b in content)
    few_aux = len(content) <= 2
    if near_top and small_glyphs and short_band and no_lyric and few_aux:
        return True
    # Single thin low-med_ch band anywhere near top
    if (
        len(content) == 1
        and pitch.med_ch < 0.80 * med_pitch_ch
        and pitch.height < 0.80 * med_pitch_h
        and pitch.y0 < 0.22 * page_h
    ):
        return True
    # Very few narrow digits vs page median pitch rows → not a real staff
    if pitch.n_narrow < 6 and pitch.med_ch < 0.75 * med_pitch_ch and no_lyric:
        if pitch.y0 < 0.25 * page_h:
            return True
    return False


def _label_cluster_roles(
    cluster: list[_Band],
    *,
    layout_mode: LayoutMode = "chord_below",
) -> list[_Band]:
    """Pick pitch (best digit row); assign chord/lyric from layout mode."""
    content = [b for b in cluster if b.role != "underline"]
    if not content:
        return list(cluster)

    # Prefer narrow jianpu digits over square CJK lyrics / letter chords
    def _pitch_key(b: _Band) -> float:
        narrow_ratio = b.n_narrow / max(b.n_digitish, 1)
        square_ratio = b.n_square / max(b.n_digitish, 1)
        return (
            b.med_ch * 1.3
            + b.n_narrow * 2.2
            + b.n_digitish * 0.35
            + b.staff_score * 22.0
            + b.height * 0.35
            + narrow_ratio * 25.0
            - b.n_square * 1.8
            - square_ratio * 30.0
            + (6.0 if b.role == "pitch" else 0.0)
        )

    best = max(content, key=_pitch_key)
    for b in content:
        b.role = "pitch" if b is best else "secondary"
    _assign_chord_lyric(cluster, layout_mode=layout_mode)
    return cluster


def _assign_chord_lyric(
    cluster: list[_Band],
    *,
    layout_mode: LayoutMode = "chord_below",
) -> None:
    """Label aux bands using the page layout mode (#64).

    chord_above: all content above pitch → chord; all below → lyric
    chord_below: first content below pitch → chord; remaining below → lyric
    """
    pitch = next((b for b in cluster if b.role == "pitch"), None)
    if pitch is None:
        return
    above = sorted(
        [
            b
            for b in cluster
            if b.role in {"secondary", "chord", "lyric"} and b.y1 <= pitch.y0 + 2
        ],
        key=lambda b: b.y0,
    )
    below = sorted(
        [
            b
            for b in cluster
            if b.role in {"secondary", "chord", "lyric"} and b.y0 >= pitch.y1 - 2
        ],
        key=lambda b: b.y0,
    )

    if layout_mode == "chord_above":
        for b in above:
            b.role = "chord"
        for b in below:
            b.role = "lyric"
        return

    # chord_below / pitch_only: chords under melody (M04 副旋律)
    for b in above:
        # Unexpected content above in chord_below → treat as chord ornament
        b.role = "chord"
    for i, b in enumerate(below):
        if i == 0:
            b.role = "chord"
        else:
            b.role = "lyric"


def _system_from_bands(
    bands: list[_Band],
    *,
    x0: float,
    x1: float,
    page_h: int,
    index: int,
    layout_mode: LayoutMode = "chord_below",
) -> StaffSystem:
    y0 = min(b.y0 for b in bands)
    y1 = max(b.y1 for b in bands)
    # Pad for octave dots above pitch and descenders on lyrics
    pad_top = max(4, int(0.12 * (y1 - y0)))
    pad_bot = max(6, int(0.18 * (y1 - y0)))
    # chord_below stacks are taller — keep a bit more bottom pad for lyric
    if layout_mode == "chord_below":
        pad_bot = max(pad_bot, 10)
    if layout_mode == "chord_above":
        pad_top = max(pad_top, 8)
    sy0 = max(0, y0 - pad_top)
    sy1 = min(page_h, y1 + pad_bot)

    band_meta: list[dict[str, Any]] = [
        {
            "role": b.role,
            "y0": b.y0,
            "y1": b.y1,
            "n_digitish": b.n_digitish,
            "med_ch": b.med_ch,
        }
        for b in bands
    ]
    has_pitch = any(b.role == "pitch" for b in bands)
    conf = 0.78 if has_pitch else 0.4
    n_chord = sum(1 for b in bands if b.role == "chord")
    n_lyric = sum(1 for b in bands if b.role == "lyric")
    if n_chord or n_lyric:
        conf = min(0.92, conf + 0.08)

    return StaffSystem(
        index=index,
        rect=Rect(float(x0), float(sy0), float(x1), float(sy1)),
        confidence=conf,
        extra={
            "bands": band_meta,
            "n_pitch_bands": sum(1 for b in bands if b.role == "pitch"),
            "n_chord_bands": n_chord,
            "n_lyric_bands": n_lyric,
            "n_underline_bands": sum(1 for b in bands if b.role == "underline"),
            "layout_mode": layout_mode,
        },
    )
