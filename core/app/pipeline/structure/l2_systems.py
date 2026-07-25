"""L2: staff / system detection with pitch+chord+lyric binding (#58 / #61).

A logical **StaffSystem** is one melody row whose rectangle covers:
  - pitch (jianpu digits) band
  - optional chord label band below
  - optional lyric band below
  - underline / ornament strips between them

Chord and lyric are **not** separate L2 systems.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import cv2
import numpy as np

from app.pipeline.structure.ir import Rect, StaffSystem

# "secondary" is temporary until bind assigns chord vs lyric
BandRole = Literal["pitch", "chord", "lyric", "underline", "secondary", "noise"]


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

    @property
    def height(self) -> int:
        return max(1, self.y1 - self.y0)

    @property
    def pitchness(self) -> float:
        """How pitch-row-like: taller mid-glyphs + staff score."""
        return float(self.med_ch) * 0.6 + float(self.staff_score) * 40.0 + float(self.height) * 0.25


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

    # Light smooth; keep pitch / chord / lyric as separate bands
    k = 5
    smooth = np.convolve(row_ink, np.ones(k) / k, mode="same")
    thr = max(float(smooth.max()) * 0.12, rw * 0.015)
    active = smooth >= thr
    raw_runs = _active_runs(active)
    raw_runs = [(a, b) for a, b in raw_runs if b - a >= max(3, min_row_height // 3)]
    merged_runs = _merge_close_runs(raw_runs, max_gap=min_row_gap)

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
    # Intra-system: underline ~10px, chord ~45px under pitch; inter-system often >90px
    max_intra_gap = max(48.0, max_attach_gap_factor * med_content_h)

    systems = _cluster_and_bind(
        bands,
        x0=float(x0),
        x1=float(x1),
        page_h=h,
        max_intra_gap=max_intra_gap,
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
        warnings.append(
            f"L2: detected {len(systems)} melody system(s), "
            f"{n_aux} attached aux band(s) (#61)"
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
    chs: list[float] = []
    for i in range(1, num):
        _x, _y, cw, ch, area = stats[i]
        if area < 18:
            continue
        chs.append(float(ch))
        aspect = cw / max(ch, 1)
        if 10 <= ch <= 95 and 0.22 <= aspect <= 2.0:
            dig += 1
        if aspect >= 2.5 and ch <= 18:
            wide += 1
    med_ch = float(np.median(chs)) if chs else float(h)
    staff_score = 0.0
    if dig >= 6 and 14 <= h <= 70:
        staff_score = 0.5 + min(0.4, 0.015 * dig)
    elif dig >= 3 and 12 <= h <= 75:
        staff_score = 0.35
    return {
        "n_digitish": dig,
        "n_wide": wide,
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
) -> BandRole:
    """Coarse label only. Pitch vs chord/lyric is refined inside each cluster (#61)."""
    # Thin horizontal strokes (duration underlines, slur ink strips)
    if height <= 12 and (n_wide >= 1 or n_digitish <= 2):
        return "underline"
    if height <= 10:
        return "underline"

    # Content band: digits / chord labels / lyrics (disambiguate later)
    if n_digitish >= 3 and 12 <= height <= 80:
        # Prefer "pitch" only for taller mid-glyphs; shorter → secondary
        if med_ch >= 28.0 and height >= 30 and staff_score >= 0.35:
            return "pitch"
        if med_ch >= 26.0 and height >= 32 and n_digitish >= 6:
            return "pitch"
        return "secondary"
    if n_comps >= 6 and 12 <= height <= 60:
        return "secondary"
    if staff_score >= 0.35 and 16 <= height <= 80:
        return "pitch" if med_ch >= 26 else "secondary"

    if height < 14:
        return "underline"
    return "noise"


def _cluster_and_bind(
    bands: list[_Band],
    *,
    x0: float,
    x1: float,
    page_h: int,
    max_intra_gap: float,
) -> list[StaffSystem]:
    """Split on large gaps; each cluster becomes at most one StaffSystem."""
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

    systems: list[StaffSystem] = []
    for cluster in clusters:
        labeled = _label_cluster_roles(cluster)
        # Skip pure-underline / no-content clusters
        if not any(b.role == "pitch" for b in labeled) and not any(
            b.role in {"chord", "lyric", "secondary"} for b in labeled
        ):
            # Only underlines — skip
            if all(b.role == "underline" for b in labeled):
                continue
        # Promote lone secondary cluster to pitch (no parent above)
        if not any(b.role == "pitch" for b in labeled):
            content = [b for b in labeled if b.role != "underline"]
            if content:
                best = max(content, key=lambda b: b.pitchness)
                best.role = "pitch"
                _assign_chord_lyric(labeled)
            else:
                continue
        systems.append(
            _system_from_bands(
                labeled,
                x0=x0,
                x1=x1,
                page_h=page_h,
                index=len(systems),
            )
        )
    return systems


def _label_cluster_roles(cluster: list[_Band]) -> list[_Band]:
    """Pick the pitch band (best pitchness); order remaining content as chord then lyric."""
    content = [b for b in cluster if b.role != "underline"]
    if not content:
        return list(cluster)

    # True pitch row: highest pitchness; on jianpu usually the top content band
    # Prefer top band when pitchness is close (chord/lyric sit below)
    best = content[0]
    for b in content[1:]:
        # Require clear gain to steal pitch from a higher band
        if b.pitchness > best.pitchness * 1.08 and b.med_ch >= best.med_ch:
            best = b
        elif b.pitchness > best.pitchness and b.y0 < best.y0:
            best = b

    for b in content:
        b.role = "pitch" if b is best else "secondary"
    _assign_chord_lyric(cluster)
    return cluster


def _assign_chord_lyric(cluster: list[_Band]) -> None:
    """First secondary under pitch → chord; later secondaries → lyric."""
    seen_pitch = False
    n_sec = 0
    for b in cluster:
        if b.role == "pitch":
            seen_pitch = True
            continue
        if b.role == "underline":
            continue
        if b.role in {"secondary", "chord", "lyric"}:
            if not seen_pitch:
                # Content above pitch in cluster (rare): treat as noise strip → keep secondary
                # will be folded into system rect still
                b.role = "secondary"
                continue
            b.role = "chord" if n_sec == 0 else "lyric"
            n_sec += 1


def _system_from_bands(
    bands: list[_Band],
    *,
    x0: float,
    x1: float,
    page_h: int,
    index: int,
) -> StaffSystem:
    y0 = min(b.y0 for b in bands)
    y1 = max(b.y1 for b in bands)
    # Pad for octave dots above pitch and descenders on lyrics
    pad_top = max(4, int(0.12 * (y1 - y0)))
    pad_bot = max(6, int(0.18 * (y1 - y0)))
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
        },
    )
