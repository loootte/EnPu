#!/usr/bin/env python3
"""Import user .jianpu + matching PDF into samples/eval/manual (issue #29).

Default sources under %%USERPROFILE%%/Documents:
  Fur Elise
  卡农 Canon in D
  预备雨露甘霖
  坐在宝座上圣洁羔羊 A调
  坐在宝座上圣洁羔羊 C调

Outputs (gitignored by default):
  samples/eval/manual/M0N_manual.png  (+ page2+ if multi-page PDF)
  samples/eval/manual/M0N_manual.gt.json
  updates samples/eval/manifest.json ready flags

Usage:
  python scripts/import-manual-scores.py
  python scripts/import-manual-scores.py --docs-dir "C:/Users/.../Documents"
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
EVAL = ROOT / "samples" / "eval"
MANUAL = EVAL / "manual"
MANIFEST = EVAL / "manifest.json"

# Fixed mapping M01–M05 (user list)
DEFAULT_PAIRS: list[tuple[str, str, str]] = [
    # mid, jianpu filename stem match, display title
    ("M01_manual", "Fur Elise", "Fur Elise"),
    ("M02_manual", "卡农 Canon in D", "卡农 Canon in D"),
    ("M03_manual", "预备雨露甘霖.jianpu", "预备雨露甘霖"),  # exact file, not G调
    ("M04_manual", "坐在宝座上圣洁羔羊 A调", "坐在宝座上圣洁羔羊 A调"),
    ("M05_manual", "坐在宝座上圣洁羔羊 C调", "坐在宝座上圣洁羔羊 C调"),
]


def find_file(docs: Path, stem_hint: str, ext: str) -> Path | None:
    """Resolve a file by exact name or unique prefix match."""
    if stem_hint.endswith(ext):
        p = docs / stem_hint
        return p if p.is_file() else None
    exact = docs / f"{stem_hint}{ext}"
    if exact.is_file():
        return exact
    # unique startswith
    hits = [
        p
        for p in docs.glob(f"*{ext}")
        if p.stem == stem_hint or p.name.startswith(stem_hint)
    ]
    # prefer exact stem
    for p in hits:
        if p.stem == stem_hint:
            return p
    if len(hits) == 1:
        return hits[0]
    # filter out longer variants (e.g. G调) when looking for base name
    if ext == ".jianpu" and stem_hint == "预备雨露甘霖.jianpu":
        p = docs / "预备雨露甘霖.jianpu"
        return p if p.is_file() else None
    if hits:
        # shortest name wins (base over " -G调")
        hits.sort(key=lambda x: len(x.name))
        return hits[0]
    return None


def parse_key(key_sig: str | None) -> str:
    if not key_sig:
        return "C"
    m = re.search(r"1\s*=\s*([A-Ga-g][b#♭♯]?)", key_sig.strip())
    if m:
        k = m.group(1)
        return k[0].upper() + k[1:].replace("♭", "b").replace("♯", "#")
    m = re.search(r"([A-Ga-g][b#]?)", key_sig)
    if m:
        k = m.group(1)
        return k[0].upper() + k[1:]
    return "C"


def parse_time_and_bpm(tempo: Any, bpm: Any) -> tuple[str, float | None]:
    time_sig = "4/4"
    tempo_bpm: float | None = None
    if bpm is not None:
        try:
            tempo_bpm = float(bpm)
        except (TypeError, ValueError):
            pass
    t = str(tempo or "")
    m = re.search(r"(\d+)\s*/\s*(\d+)", t)
    if m:
        time_sig = f"{m.group(1)}/{m.group(2)}"
    m2 = re.search(r"(\d+)\s*BPM", t, re.I)
    if m2 and tempo_bpm is None:
        tempo_bpm = float(m2.group(1))
    return time_sig, tempo_bpm


def map_duration(note: dict[str, Any]) -> tuple[str, int]:
    """Map Underlines/Dashes/Dotted → (DurationName, dots)."""
    ul = int(note.get("Underlines") or 0)
    dashes = int(note.get("Dashes") or 0)
    dotted = bool(note.get("Dotted"))

    if ul >= 2:
        base_name, base_beats = "sixteenth", 0.25
    elif ul == 1:
        base_name, base_beats = "eighth", 0.5
    else:
        base_name, base_beats = "quarter", 1.0

    # Traditional jianpu: each dash extends by one quarter-beat
    beats = base_beats + dashes * 1.0
    if dotted:
        beats *= 1.5

    # Nearest Western duration for EnPu enum
    table = [
        (4.0, "whole", 0),
        (3.0, "half", 1),  # dotted half
        (2.0, "half", 0),
        (1.5, "quarter", 1),
        (1.0, "quarter", 0),
        (0.75, "eighth", 1),
        (0.5, "eighth", 0),
        (0.375, "sixteenth", 1),
        (0.25, "sixteenth", 0),
    ]
    best = min(table, key=lambda row: abs(row[0] - beats))
    return best[1], best[2]


def map_pitch(note: dict[str, Any]) -> tuple[str | None, str | None, int, bool]:
    """Return (pitch, accidental, octave, is_rest)."""
    ntype = note.get("Type")
    if ntype == 1:
        return None, None, 0, True

    raw = note.get("Pitch")
    if raw is None:
        return None, None, 0, True
    try:
        pf = float(raw)
    except (TypeError, ValueError):
        return None, None, 0, True

    if pf == 0 and ntype == 1:
        return None, None, 0, True

    # Chromatic float degrees (e.g. 5.5) → nearest scale degree + accidental
    acc_field = note.get("Accidental")
    accidental: str | None = None
    if acc_field == 1 or acc_field == "1":
        accidental = "sharp"
    elif acc_field == -1 or acc_field == 2 or acc_field == "flat":
        # some apps use 2 for flat
        accidental = "flat"

    if abs(pf - round(pf)) < 0.05:
        deg = int(round(pf))
    else:
        # 5.5 with sharp → treat as 5 sharp
        deg = int(pf)
        if accidental is None:
            accidental = "sharp" if (pf - deg) > 0 else "flat"

    if deg < 1 or deg > 7:
        # out of range → skip as rest for GT pitch stream
        if deg == 0:
            return None, None, 0, True
        deg = max(1, min(7, deg))

    octave = int(note.get("Octave") or 0)
    return str(deg), accidental, octave, False


def jianpu_to_score(data: dict[str, Any], eval_id: str) -> dict[str, Any]:
    key = parse_key(data.get("KeySignature"))
    time_sig, tempo_bpm = parse_time_and_bpm(data.get("Tempo"), data.get("Bpm"))
    title = str(data.get("Title") or eval_id)

    measures_out: list[dict[str, Any]] = []
    pitch_seq: list[str] = []

    for mi, meas in enumerate(data.get("Measures") or [], start=1):
        notes_out: list[dict[str, Any]] = []
        # lyrics: LyricText string or LyricSyllables list
        syllables: list[str] = []
        lt = meas.get("LyricText")
        if isinstance(lt, str) and lt.strip():
            syllables = [s for s in re.split(r"\s+", lt.strip()) if s]
        ls = meas.get("LyricSyllables")
        if isinstance(ls, list) and ls:
            syllables = [str(s) for s in ls if s is not None and str(s).strip()]

        si = 0
        for note in meas.get("MelodyNotes") or []:
            pitch, accidental, octave, is_rest = map_pitch(note)
            dur, dots = map_duration(note)
            lyric = None
            if not is_rest and si < len(syllables):
                lyric = syllables[si]
                si += 1
            ev: dict[str, Any] = {
                "pitch": pitch,
                "octave": octave,
                "duration": dur,
                "dots": dots,
                "is_rest": is_rest,
                "lyric": lyric,
            }
            if accidental:
                ev["accidental"] = accidental
            if is_rest:
                ev["pitch"] = None
            notes_out.append(ev)
            if not is_rest and pitch:
                tag = pitch + ("#" if accidental == "sharp" else "b" if accidental == "flat" else "")
                pitch_seq.append(tag)

        measures_out.append({"number": mi, "notes": notes_out})

    return {
        "schema_version": "0.1",
        "title": title,
        "key": key,
        "time_signature": time_sig,
        "tempo_bpm": tempo_bpm,
        "parts": [{"id": "P1", "name": "melody", "measures": measures_out}],
        "meta": {
            "created_by": "enpu-import-manual-scores",
            "comments": "GT from user .jianpu digital score; image from matching PDF page render.",
            "source_image": f"manual/{eval_id}.png",
            "engine": None,
            "extra": {
                "eval": {
                    "id": eval_id,
                    "subset": "manual_real",
                    "synthetic": False,
                    "license": "user-local-not-for-redistribution",
                    "pitch_sequence": pitch_seq,
                    "measure_count": len(measures_out),
                    "source_jianpu": True,
                }
            },
        },
        "extra": {
            "eval": {
                "id": eval_id,
                "subset": "manual_real",
                "synthetic": False,
                "license": "user-local-not-for-redistribution",
                "pitch_sequence": pitch_seq,
                "measure_count": len(measures_out),
            }
        },
    }


def pdf_to_pngs(pdf_path: Path, out_stem: Path, dpi: int = 200) -> list[Path]:
    import fitz  # pymupdf

    doc = fitz.open(pdf_path)
    outs: list[Path] = []
    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)
    for i in range(len(doc)):
        page = doc.load_page(i)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        if len(doc) == 1:
            out = out_stem.with_suffix(".png")
        else:
            out = out_stem.parent / f"{out_stem.name}_p{i + 1}.png"
        pix.save(str(out))
        outs.append(out)
    doc.close()
    return outs


def update_manifest(results: list[dict[str, Any]]) -> None:
    man = json.loads(MANIFEST.read_text(encoding="utf-8"))
    by_id = {r["id"]: r for r in results}
    for e in man.get("entries") or []:
        rid = e.get("id")
        if rid in by_id:
            r = by_id[rid]
            e["status"] = "ready"
            e["key"] = r["key"]
            e["time_signature"] = r["time_signature"]
            e["measure_count"] = r["measure_count"]
            e["pitch_sequence"] = r["pitch_sequence"]
            e["image"] = r["image"]
            e["gt"] = r["gt"]
            e["title"] = r.get("title")
            e["pages"] = r.get("pages", 1)
            e["source_jianpu"] = r.get("source_jianpu")
            e["source_pdf"] = r.get("source_pdf")
    # recount
    ready = sum(1 for e in man["entries"] if e.get("status") == "ready")
    pending = sum(1 for e in man["entries"] if e.get("status") != "ready")
    man["counts"]["ready_total"] = ready
    man["counts"]["pending"] = pending
    man["counts"]["manual_ready"] = sum(
        1
        for e in man["entries"]
        if e.get("subset") == "manual_real" and e.get("status") == "ready"
    )
    MANIFEST.write_text(json.dumps(man, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--docs-dir",
        type=Path,
        default=Path.home() / "Documents",
        help="Folder containing .jianpu and .pdf pairs",
    )
    ap.add_argument("--dpi", type=int, default=200)
    args = ap.parse_args()
    docs: Path = args.docs_dir
    if not docs.is_dir():
        raise SystemExit(f"docs dir not found: {docs}")

    MANUAL.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []

    for mid, stem, title_hint in DEFAULT_PAIRS:
        if stem.endswith(".jianpu"):
            jpath = find_file(docs, stem, "")
            if jpath is None:
                jpath = docs / stem
        else:
            jpath = find_file(docs, stem, ".jianpu")
        # PDF: strip .jianpu if present
        pdf_stem = stem.replace(".jianpu", "")
        ppath = find_file(docs, pdf_stem, ".pdf")

        print(f"\n=== {mid} ===")
        print("  jianpu:", jpath)
        print("  pdf:   ", ppath)

        if not jpath or not jpath.is_file():
            print("  SKIP: missing .jianpu")
            continue
        if not ppath or not ppath.is_file():
            print("  SKIP: missing .pdf")
            continue

        data = json.loads(jpath.read_text(encoding="utf-8-sig"))
        score = jianpu_to_score(data, mid)
        # prefer display title
        if title_hint:
            score["title"] = title_hint

        gt_path = MANUAL / f"{mid}.gt.json"
        gt_path.write_text(
            json.dumps(score, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

        out_stem = MANUAL / mid
        pages = pdf_to_pngs(ppath, out_stem, dpi=args.dpi)
        # primary image for manifest: first page (also copied as mid.png if multipage)
        primary = MANUAL / f"{mid}.png"
        if pages[0] != primary:
            shutil.copy2(pages[0], primary)
        print(f"  wrote GT measures={score['extra']['eval']['measure_count']} "
              f"pitches={len(score['extra']['eval']['pitch_sequence'])}")
        print(f"  wrote {len(pages)} page image(s):", [p.name for p in pages])

        # also keep a copy of digital source for local reference (not required by git)
        shutil.copy2(jpath, MANUAL / f"{mid}.source.jianpu")

        results.append(
            {
                "id": mid,
                "key": score["key"],
                "time_signature": score["time_signature"],
                "measure_count": score["extra"]["eval"]["measure_count"],
                "pitch_sequence": score["extra"]["eval"]["pitch_sequence"],
                "image": f"manual/{mid}.png",
                "gt": f"manual/{mid}.gt.json",
                "title": score["title"],
                "pages": len(pages),
                "source_jianpu": jpath.name,
                "source_pdf": ppath.name,
            }
        )

    if not results:
        raise SystemExit("no pairs imported")

    if MANIFEST.is_file():
        update_manifest(results)
        print("\nupdated", MANIFEST)
    else:
        print("warn: manifest missing, skip update")

    print(f"\nimported {len(results)}/5 manual scores into {MANUAL}")


if __name__ == "__main__":
    main()
