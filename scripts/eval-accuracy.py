#!/usr/bin/env python3
"""Eval harness for issue #29 — validate GT and compute OCR accuracy.

Modes:
  --manifest-only   Validate manifest + GT JSON (no OCR)
  --gt-stats        Print pitch-sequence / measure stats for ready entries
  --run             Run recognition vs GT and print accuracy table
  --engine mock|paddleocr   (default paddleocr for --run)
  --subset NAME     Only entries with this subset
  --limit N         Max entries (debug)
  --out PATH        Write JSON report

Examples:
  python scripts/eval-accuracy.py --run --engine paddleocr
  python scripts/eval-accuracy.py --run --subset print_clear
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
EVAL = ROOT / "samples" / "eval"
MANIFEST = EVAL / "manifest.json"
MANIFEST_LOCAL = EVAL / "manifest.local.json"
CORE = ROOT / "core"


def load_manifest() -> dict:
    path = MANIFEST_LOCAL if MANIFEST_LOCAL.is_file() else MANIFEST
    if not path.is_file():
        raise SystemExit(f"manifest missing: {MANIFEST} (run generate-eval-samples.py)")
    print(f"using {path.name}")
    return json.loads(path.read_text(encoding="utf-8"))


def validate_score_dict(data: dict, path: Path) -> list[str]:
    errs: list[str] = []
    if data.get("schema_version") != "0.1":
        errs.append(f"{path}: schema_version must be '0.1'")
    for k in ("key", "time_signature", "parts"):
        if k not in data:
            errs.append(f"{path}: missing {k}")
    parts = data.get("parts") or []
    if not parts:
        errs.append(f"{path}: parts empty")
    else:
        measures = parts[0].get("measures") or []
        if not measures:
            errs.append(f"{path}: no measures")
    return errs


def pitch_sequence_from_score(data: dict[str, Any]) -> list[str]:
    extra = (data.get("extra") or {}).get("eval") or {}
    if extra.get("pitch_sequence"):
        return [str(p) for p in extra["pitch_sequence"]]
    out: list[str] = []
    parts = data.get("parts") or []
    if not parts:
        return out
    for meas in parts[0].get("measures") or []:
        for n in meas.get("notes") or []:
            if n.get("is_rest"):
                continue
            p = n.get("pitch")
            if not p:
                continue
            acc = n.get("accidental")
            tag = str(p)
            if acc == "sharp":
                tag += "#"
            elif acc == "flat":
                tag += "b"
            out.append(tag)
    return out


def measure_count_from_score(data: dict[str, Any]) -> int:
    extra = (data.get("extra") or {}).get("eval") or {}
    if extra.get("measure_count") is not None:
        return int(extra["measure_count"])
    parts = data.get("parts") or []
    if not parts:
        return 0
    return len(parts[0].get("measures") or [])


def lcs_len(a: list[str], b: list[str]) -> int:
    """Longest common subsequence length (token-level)."""
    n, m = len(a), len(b)
    if n == 0 or m == 0:
        return 0
    # rolling DP for memory
    prev = [0] * (m + 1)
    for i in range(1, n + 1):
        cur = [0] * (m + 1)
        ai = a[i - 1]
        for j in range(1, m + 1):
            if ai == b[j - 1]:
                cur[j] = prev[j - 1] + 1
            else:
                cur[j] = max(prev[j], cur[j - 1])
        prev = cur
    return prev[m]


def pitch_accuracy(gt: list[str], pred: list[str]) -> dict[str, float]:
    """LCS-based recall/precision/F1 over pitch tokens."""
    if not gt and not pred:
        return {"recall": 1.0, "precision": 1.0, "f1": 1.0, "lcs": 0.0}
    if not gt:
        return {"recall": 0.0, "precision": 0.0, "f1": 0.0, "lcs": 0.0}
    if not pred:
        return {"recall": 0.0, "precision": 0.0, "f1": 0.0, "lcs": 0.0}
    L = lcs_len(gt, pred)
    recall = L / len(gt)
    precision = L / len(pred)
    f1 = (2 * recall * precision / (recall + precision)) if (recall + precision) else 0.0
    return {
        "recall": recall,
        "precision": precision,
        "f1": f1,
        "lcs": float(L),
    }


def normalize_key(k: str | None) -> str:
    if not k:
        return ""
    k = k.strip().replace("♭", "b").replace("♯", "#")
    if k.startswith("1="):
        k = k[2:]
    return k[0].upper() + k[1:] if k else ""


def normalize_time(t: str | None) -> str:
    if not t:
        return ""
    m = __import__("re").search(r"(\d+)\s*/\s*(\d+)", str(t))
    if m:
        return f"{m.group(1)}/{m.group(2)}"
    return str(t).strip()


def cmd_manifest_only() -> int:
    man = load_manifest()
    entries = man.get("entries") or []
    ready = [e for e in entries if e.get("status") == "ready"]
    pending = [e for e in entries if e.get("status") != "ready"]
    print(f"entries: {len(entries)}  ready={len(ready)}  pending={len(pending)}")

    errors: list[str] = []
    for e in ready:
        img = EVAL / e["image"]
        gt = EVAL / e["gt"]
        if not img.is_file():
            errors.append(f"missing image: {img}")
        if not gt.is_file():
            errors.append(f"missing gt: {gt}")
            continue
        try:
            data = json.loads(gt.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append(f"bad json {gt}: {exc}")
            continue
        errors.extend(validate_score_dict(data, gt))
        try:
            sys.path.insert(0, str(CORE))
            from app.schemas.score import Score  # type: ignore

            Score.model_validate(data)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"Score validate fail {gt.name}: {exc}")

    if errors:
        print("FAIL:")
        for err in errors:
            print(" -", err)
        return 1
    print("OK: all ready entries have valid image + Score GT")
    return 0


def cmd_gt_stats() -> int:
    man = load_manifest()
    print(f"{'id':<36} {'subset':<12} {'bars':>4} {'pitches':>7} key  time")
    for e in man.get("entries") or []:
        if e.get("status") != "ready":
            print(f"{e['id']:<36} {e.get('subset','?'):<12}  — pending")
            continue
        gt_path = EVAL / e["gt"]
        data = json.loads(gt_path.read_text(encoding="utf-8"))
        seq = pitch_sequence_from_score(data)
        bars = measure_count_from_score(data)
        print(
            f"{e['id']:<36} {e.get('subset','?'):<12} {bars!s:>4} {len(seq):>7} "
            f"{data.get('key','?'):<3} {data.get('time_signature','?')}"
        )
    return 0


def recognize_image(img_path: Path, engine: str) -> dict[str, Any]:
    """Run local pipeline; returns dict with score / notes / meta / error."""
    sys.path.insert(0, str(CORE))
    os.environ["ENPU_RECOGNIZE_ENGINE"] = engine
    from app.config import Settings, clear_settings_cache
    from app.pipeline.runner import PipelineError, run_recognize

    clear_settings_cache()
    settings = Settings(recognize_engine=engine)
    data = img_path.read_bytes()
    try:
        resp = run_recognize(
            data,
            settings=settings,
            filename=img_path.name,
            content_type="image/png",
        )
    except PipelineError as exc:
        return {"error": str(exc), "score": None, "notes": [], "engine": engine}
    score = None
    if resp.score is not None:
        score = resp.score.model_dump(mode="json")
    return {
        "error": None,
        "score": score,
        "notes": [n.model_dump(mode="json") for n in resp.notes],
        "engine": resp.engine,
        "parse_mode": resp.meta.parse_mode,
        "texts": list(resp.texts),
        "elapsed_ms": resp.meta.elapsed_ms,
    }


def pred_pitch_from_result(result: dict[str, Any]) -> list[str]:
    if result.get("score"):
        return pitch_sequence_from_score(result["score"])
    # fallback: digit hints in order
    out: list[str] = []
    for n in result.get("notes") or []:
        p = n.get("pitch")
        if p and str(p) in "1234567":
            out.append(str(p))
    return out


def cmd_run(
    engine: str,
    subset: str | None,
    limit: int | None,
    out_path: Path | None,
    min_f1: float | None = None,
    min_f1_subset: str = "print_clear",
) -> int:
    man = load_manifest()
    entries = [e for e in man.get("entries") or [] if e.get("status") == "ready"]
    if subset:
        entries = [e for e in entries if e.get("subset") == subset]
    if limit is not None:
        entries = entries[:limit]

    if not entries:
        print("no ready entries to evaluate")
        return 1

    print(f"engine={engine}  n={len(entries)}  subset={subset or 'ALL'}")
    print(
        f"{'id':<36} {'sub':<11} {'gtN':>4} {'prN':>4} {'f1':>6} {'rec':>6} "
        f"{'barsΔ':>5} {'key':>4} {'time':>4} ms"
    )

    rows: list[dict[str, Any]] = []
    t0 = time.perf_counter()

    for e in entries:
        img = EVAL / e["image"]
        gt_path = EVAL / e["gt"]
        gt = json.loads(gt_path.read_text(encoding="utf-8"))
        gt_seq = pitch_sequence_from_score(gt)
        gt_bars = measure_count_from_score(gt)
        gt_key = normalize_key(gt.get("key"))
        gt_time = normalize_time(gt.get("time_signature"))

        started = time.perf_counter()
        try:
            result = recognize_image(img, engine)
        except Exception as exc:  # noqa: BLE001
            result = {"error": str(exc), "score": None, "notes": [], "engine": engine}
        elapsed = int((time.perf_counter() - started) * 1000)

        if result.get("error"):
            row = {
                "id": e["id"],
                "subset": e.get("subset"),
                "error": result["error"],
                "gt_n": len(gt_seq),
                "pred_n": 0,
                "pitch_f1": 0.0,
                "pitch_recall": 0.0,
                "pitch_precision": 0.0,
                "bars_err": None,
                "key_ok": False,
                "time_ok": False,
                "elapsed_ms": elapsed,
            }
            rows.append(row)
            print(
                f"{e['id']:<36} {str(e.get('subset'))[:11]:<11} {len(gt_seq):>4} "
                f"{'ERR':>4} {'0':>6} {'0':>6} {'—':>5} {'—':>4} {'—':>4} {elapsed}"
            )
            print(f"  error: {result['error'][:120]}")
            continue

        pred_seq = pred_pitch_from_result(result)
        score = result.get("score") or {}
        pred_bars = measure_count_from_score(score) if score else 0
        pred_key = normalize_key(score.get("key") if score else None)
        pred_time = normalize_time(score.get("time_signature") if score else None)
        # if no score key, leave empty → mismatch
        if not score:
            pred_key, pred_time = "", ""

        acc = pitch_accuracy(gt_seq, pred_seq)
        bars_err = abs(pred_bars - gt_bars) if score else None
        key_ok = bool(pred_key) and pred_key == gt_key
        time_ok = bool(pred_time) and pred_time == gt_time

        row = {
            "id": e["id"],
            "subset": e.get("subset"),
            "error": None,
            "gt_n": len(gt_seq),
            "pred_n": len(pred_seq),
            "pitch_f1": acc["f1"],
            "pitch_recall": acc["recall"],
            "pitch_precision": acc["precision"],
            "lcs": acc["lcs"],
            "gt_bars": gt_bars,
            "pred_bars": pred_bars,
            "bars_err": bars_err,
            "gt_key": gt_key,
            "pred_key": pred_key,
            "key_ok": key_ok,
            "gt_time": gt_time,
            "pred_time": pred_time,
            "time_ok": time_ok,
            "parse_mode": result.get("parse_mode"),
            "elapsed_ms": elapsed,
            "engine": result.get("engine"),
        }
        rows.append(row)
        print(
            f"{e['id']:<36} {str(e.get('subset'))[:11]:<11} {len(gt_seq):>4} {len(pred_seq):>4} "
            f"{acc['f1']:>6.2%} {acc['recall']:>6.2%} "
            f"{(bars_err if bars_err is not None else -1):>5} "
            f"{('Y' if key_ok else 'N'):>4} {('Y' if time_ok else 'N'):>4} {elapsed}"
        )

    # Aggregate
    ok_rows = [r for r in rows if not r.get("error")]
    def mean(xs: list[float]) -> float:
        return sum(xs) / len(xs) if xs else 0.0

    by_subset: dict[str, list[dict]] = {}
    for r in rows:
        by_subset.setdefault(str(r.get("subset") or "?"), []).append(r)

    print("\n=== Summary ===")
    print(f"engine={engine}  total={len(rows)}  ok={len(ok_rows)}  "
          f"errors={len(rows) - len(ok_rows)}  wall_s={time.perf_counter() - t0:.1f}")

    def print_group(name: str, group: list[dict]) -> dict[str, Any]:
        good = [r for r in group if not r.get("error")]
        f1s = [r["pitch_f1"] for r in good]
        recs = [r["pitch_recall"] for r in good]
        precs = [r["pitch_precision"] for r in good]
        key_rate = mean([1.0 if r["key_ok"] else 0.0 for r in good]) if good else 0.0
        time_rate = mean([1.0 if r["time_ok"] else 0.0 for r in good]) if good else 0.0
        bars = [r["bars_err"] for r in good if r.get("bars_err") is not None]
        mean_bars = mean([float(x) for x in bars]) if bars else None
        # weighted pitch by gt length
        w_rec_num = sum(r["lcs"] for r in good if "lcs" in r)
        w_rec_den = sum(r["gt_n"] for r in good) or 1
        w_prec_num = sum(r["lcs"] for r in good if "lcs" in r)
        w_prec_den = sum(r["pred_n"] for r in good) or 1
        w_rec = w_rec_num / w_rec_den
        w_prec = w_prec_num / w_prec_den if w_prec_den else 0.0
        w_f1 = (2 * w_rec * w_prec / (w_rec + w_prec)) if (w_rec + w_prec) else 0.0
        print(
            f"[{name}] n={len(group)} ok={len(good)}  "
            f"pitch_f1_avg={mean(f1s):.2%}  pitch_recall_avg={mean(recs):.2%}  "
            f"pitch_f1_weighted={w_f1:.2%}  "
            f"key_acc={key_rate:.2%}  time_acc={time_rate:.2%}  "
            f"mean_|Δbars|={mean_bars if mean_bars is not None else 'n/a'}"
        )
        return {
            "n": len(group),
            "ok": len(good),
            "pitch_f1_avg": mean(f1s),
            "pitch_recall_avg": mean(recs),
            "pitch_precision_avg": mean(precs),
            "pitch_f1_weighted": w_f1,
            "pitch_recall_weighted": w_rec,
            "key_accuracy": key_rate,
            "time_accuracy": time_rate,
            "mean_abs_bar_error": mean_bars,
        }

    target = min_f1 if min_f1 is not None else 0.60
    summary = {
        "engine": engine,
        "overall": print_group("ALL", rows),
        "by_subset": {s: print_group(s, g) for s, g in sorted(by_subset.items())},
        "rows": rows,
        "baseline_target": {
            "subset": min_f1_subset,
            "min_pitch_f1_weighted": target,
            "note": "ROADMAP / CI gate: print_clear weighted Pitch F1 ≥ threshold",
        },
    }

    gate_group = summary["by_subset"].get(min_f1_subset) or (
        summary["overall"] if min_f1_subset in {"ALL", "all", "*"} else {}
    )
    if min_f1_subset in {"ALL", "all", "*"}:
        gate_group = summary["overall"]

    f1 = 0.0
    if gate_group:
        f1 = float(
            gate_group.get("pitch_f1_weighted")
            or gate_group.get("pitch_f1_avg")
            or 0.0
        )
        mark = "PASS" if f1 + 1e-9 >= target else "BELOW TARGET"
        print(
            f"\n[{min_f1_subset}] weighted pitch F1 = {f1:.2%}  → {mark} "
            f"(target ≥{target:.0%})"
        )
    else:
        print(f"\nWARN: subset {min_f1_subset!r} missing from results; gate fails")
        mark = "BELOW TARGET"

    n_err = len(rows) - len(ok_rows)
    summary["gate"] = {
        "subset": min_f1_subset,
        "min_f1": target,
        "actual_f1": f1,
        "passed": mark == "PASS" and n_err == 0,
        "errors": n_err,
    }

    if out_path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"wrote report: {out_path}")

    if n_err > 0:
        print(f"FAIL: {n_err} recognition error(s)")
        return 1
    if min_f1 is not None and mark != "PASS":
        print(
            f"FAIL: CI gate — {min_f1_subset} weighted F1 {f1:.2%} "
            f"< min {target:.2%}"
        )
        return 1
    return 0


def main() -> None:
    p = argparse.ArgumentParser(description="EnPu eval harness (#29)")
    p.add_argument("--manifest-only", action="store_true")
    p.add_argument("--gt-stats", action="store_true")
    p.add_argument("--run", action="store_true", help="Run OCR vs GT accuracy")
    p.add_argument(
        "--engine",
        default="paddleocr",
        choices=["paddleocr", "mock"],
    )
    p.add_argument("--subset", default=None)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument(
        "--out",
        type=Path,
        default=None,
        help="JSON report path (default samples/eval/reports/latest.json for --run)",
    )
    p.add_argument(
        "--min-f1",
        type=float,
        default=None,
        help=(
            "If set, exit 1 when gate subset weighted pitch F1 is below this "
            "(e.g. 0.60 for CI). Also fails on any recognition errors."
        ),
    )
    p.add_argument(
        "--min-f1-subset",
        default="print_clear",
        help="Subset used for --min-f1 gate (default: print_clear; use ALL for overall)",
    )
    args = p.parse_args()
    if args.gt_stats:
        raise SystemExit(cmd_gt_stats())
    if args.run:
        out = args.out
        if out is None:
            out = EVAL / "reports" / f"baseline-{args.engine}.json"
        raise SystemExit(
            cmd_run(
                args.engine,
                args.subset,
                args.limit,
                out,
                min_f1=args.min_f1,
                min_f1_subset=args.min_f1_subset,
            )
        )
    raise SystemExit(cmd_manifest_only())


if __name__ == "__main__":
    main()
