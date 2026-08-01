"""Backend helpers for the training UI (#101).

Thin wrappers around layout_gt export + train/eval scripts.
UI must not embed training algorithms — only call these entry points.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TRAIN_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = TRAIN_ROOT.parent
CORE_ROOT = REPO_ROOT / "core"
DEFAULT_LAYOUT_ROOT = REPO_ROOT / "samples" / "layout"
DEFAULT_RUNS = TRAIN_ROOT / "runs"
JOBS_DIR = DEFAULT_RUNS / "ui_jobs"


def _ensure_sys_path() -> None:
    for p in (str(TRAIN_ROOT), str(CORE_ROOT)):
        if p not in sys.path:
            sys.path.insert(0, p)


def discover_layout_samples(roots: list[str | Path] | None = None) -> list[Path]:
    roots = roots or [DEFAULT_LAYOUT_ROOT, TRAIN_ROOT / "data_cache" / "synth"]
    found: list[Path] = []
    for r in roots:
        p = Path(r)
        if not p.is_dir():
            continue
        for layout in p.rglob("layout.json"):
            found.append(layout.parent)
    # unique, stable order
    uniq = sorted({f.resolve() for f in found}, key=lambda x: str(x).lower())
    return uniq


@dataclass
class SampleInfo:
    path: str
    sample_id: str
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    n_systems: int = 0
    n_splits: int = 0
    n_measures: int = 0
    image_path: str | None = None
    width: int | None = None
    height: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def inspect_layout_sample(sample_dir: str | Path) -> SampleInfo:
    _ensure_sys_path()
    from app.layout_gt.validate import validate_layout_sample

    sample_dir = Path(sample_dir)
    layout_path = sample_dir / "layout.json"
    info = SampleInfo(
        path=str(sample_dir),
        sample_id=sample_dir.name,
        ok=False,
    )
    if not layout_path.is_file():
        info.errors = ["missing layout.json"]
        return info
    try:
        data = json.loads(layout_path.read_text(encoding="utf-8"))
    except Exception as e:
        info.errors = [f"invalid JSON: {e}"]
        return info

    info.sample_id = str(data.get("id") or sample_dir.name)
    img = data.get("image") or {}
    info.width = img.get("width")
    info.height = img.get("height")
    rel = img.get("path") or "image.png"
    ip = sample_dir / rel
    if ip.is_file():
        info.image_path = str(ip)
    else:
        for cand in sample_dir.glob("image.*"):
            info.image_path = str(cand)
            break

    systems = (data.get("l2") or {}).get("systems") or []
    rows = (data.get("l3") or {}).get("rows") or []
    info.n_systems = len(systems)
    info.n_splits = sum(len(r.get("splits") or []) for r in rows)
    info.n_measures = sum(len(r.get("measures") or []) for r in rows)

    result = validate_layout_sample(data)
    info.ok = result.ok
    info.errors = list(result.errors)
    info.warnings = list(result.warnings)
    return info


def list_samples_info(roots: list[str | Path] | None = None) -> list[SampleInfo]:
    return [inspect_layout_sample(p) for p in discover_layout_samples(roots)]


def import_enpu_project(
    project_path: str | Path,
    *,
    out_dir: str | Path | None = None,
    sample_id: str | None = None,
) -> dict[str, Any]:
    """Export .enpu.json → layout sample dir. Returns sample info + paths."""
    _ensure_sys_path()
    from app.layout_gt.export import export_project_to_sample_dir

    project_path = Path(project_path)
    if not project_path.is_file():
        raise FileNotFoundError(f"project not found: {project_path}")

    sid = sample_id or project_path.stem.replace(".enpu", "")
    # sanitize dir name
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in sid)[:80]
    if not safe:
        safe = f"import_{int(time.time())}"
    out = Path(out_dir) if out_dir else (DEFAULT_LAYOUT_ROOT / safe)
    out.mkdir(parents=True, exist_ok=True)

    try:
        sample = export_project_to_sample_dir(
            project_path,
            out,
            sample_id=sid,
            copy_image=True,
            validate=True,
        )
        err = None
    except ValueError as e:
        # still write partial if possible — re-raise with message
        raise ValueError(str(e)) from e

    info = inspect_layout_sample(out)
    return {
        "ok": info.ok,
        "out_dir": str(out),
        "sample_id": sample.get("id") if isinstance(sample, dict) else sid,
        "info": info.to_dict(),
        "error": err,
    }


def list_runs(runs_root: str | Path | None = None) -> list[dict[str, Any]]:
    root = Path(runs_root or DEFAULT_RUNS)
    if not root.is_dir():
        return []
    runs: list[dict[str, Any]] = []
    for d in sorted(root.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if not d.is_dir() or d.name == "ui_jobs":
            continue
        meta = {
            "name": d.name,
            "path": str(d),
            "mtime": datetime.fromtimestamp(d.stat().st_mtime, tz=timezone.utc).isoformat(),
            "has_best": (d / "best.pt").is_file(),
            "has_last": (d / "last.pt").is_file(),
            "has_history": (d / "history.json").is_file(),
        }
        hist = d / "history.json"
        if hist.is_file():
            try:
                h = json.loads(hist.read_text(encoding="utf-8"))
                meta["epochs"] = len(h) if isinstance(h, list) else None
                if isinstance(h, list) and h:
                    last = h[-1]
                    meta["last_train_loss"] = last.get("train_loss")
                    val = last.get("val") or {}
                    meta["last_val"] = val
            except Exception:
                pass
        job = d / "job.json"
        if job.is_file():
            try:
                meta["job"] = json.loads(job.read_text(encoding="utf-8"))
            except Exception:
                pass
        runs.append(meta)
    return runs


def load_history(run_dir: str | Path) -> list[dict[str, Any]]:
    p = Path(run_dir) / "history.json"
    if not p.is_file():
        return []
    data = json.loads(p.read_text(encoding="utf-8"))
    return data if isinstance(data, list) else []


def load_eval_metrics(path: str | Path) -> dict[str, Any] | None:
    p = Path(path)
    if not p.is_file():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


@dataclass
class TrainJobSpec:
    run_name: str
    tasks: list[str] = field(default_factory=lambda: ["l2", "l3"])
    epochs: int = 2
    batch_size: int = 2
    lr: float = 1e-3
    device: str = "cpu"
    data_roots: list[str] = field(default_factory=list)
    synth_count: int = 4
    val_ratio: float = 0.25
    skip_export: bool = False


def write_train_config(spec: TrainJobSpec, out_dir: Path) -> Path:
    """Write a yaml config for scripts/train.py."""
    out_dir.mkdir(parents=True, exist_ok=True)
    roots = list(spec.data_roots) if spec.data_roots else [str(DEFAULT_LAYOUT_ROOT)]
    # use forward-friendly paths as strings
    cfg = {
        "tasks": list(spec.tasks),
        "data": {
            "roots": roots,
            "synth_count": int(spec.synth_count),
            "synth_dir": str(TRAIN_ROOT / "data_cache" / "synth"),
            "page_size": [384, 512],
            "row_size": [64, 256],
            "l2_heat_len": 128,
            "l3_heat_len": 128,
            "augment": True,
            "val_ratio": float(spec.val_ratio),
        },
        "train": {
            "epochs": int(spec.epochs),
            "batch_size": int(spec.batch_size),
            "lr": float(spec.lr),
            "weight_decay": 0.0001,
            "l2_loss_weight": 1.0,
            "l3_loss_weight": 1.5,
            "device": spec.device,
            "num_workers": 0,
            "out_dir": str(out_dir),
            "log_every": 1,
        },
        "export": {
            "state_dict": str(out_dir / "export" / "layout_net.pt"),
            "onnx_dir": str(out_dir / "export" / "onnx"),
        },
    }
    try:
        import yaml

        text = yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False)
    except Exception:
        text = json.dumps(cfg, ensure_ascii=False, indent=2)
        cfg_path = out_dir / "config.json"
        cfg_path.write_text(text, encoding="utf-8")
        return cfg_path

    cfg_path = out_dir / "config.yaml"
    cfg_path.write_text(text, encoding="utf-8")
    return cfg_path


def start_train_job(spec: TrainJobSpec) -> dict[str, Any]:
    """Launch train.py as a subprocess; returns job metadata (Windows-safe logging)."""
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    run_dir = DEFAULT_RUNS / spec.run_name
    run_dir.mkdir(parents=True, exist_ok=True)
    cfg_path = write_train_config(spec, run_dir)
    log_path = run_dir / "train.log"
    job_path = run_dir / "job.json"

    cmd = [
        sys.executable,
        "-u",
        str(TRAIN_ROOT / "scripts" / "train.py"),
        "--config",
        str(cfg_path),
        "--device",
        spec.device,
        "--epochs",
        str(spec.epochs),
    ]
    if spec.skip_export:
        cmd.append("--skip-export")

    env = os.environ.copy()
    pp = [str(TRAIN_ROOT), str(CORE_ROOT)]
    if env.get("PYTHONPATH"):
        pp.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(pp)
    env["PYTHONUNBUFFERED"] = "1"

    # Keep log file handle open for the child process lifetime (do not close here).
    log_f = open(log_path, "w", encoding="utf-8", errors="replace")
    kwargs: dict[str, Any] = {
        "cwd": str(TRAIN_ROOT),
        "stdout": log_f,
        "stderr": subprocess.STDOUT,
        "env": env,
    }
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    proc = subprocess.Popen(cmd, **kwargs)

    job = {
        "kind": "train",
        "pid": proc.pid,
        "cmd": cmd,
        "run_dir": str(run_dir),
        "log_path": str(log_path),
        "cfg_path": str(cfg_path),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "status": "running",
        "spec": asdict(spec),
    }
    job_path.write_text(json.dumps(job, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return job


def _pid_running(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = kernel32.OpenProcess(
                PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid)
            )
            if handle:
                kernel32.CloseHandle(handle)
                return True
            return False
        except Exception:
            try:
                out = subprocess.run(
                    ["tasklist", "/FI", f"PID eq {pid}"],
                    capture_output=True,
                    timeout=10,
                )
                text = out.stdout.decode("gbk", errors="replace")
                return str(pid) in text
            except Exception:
                return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def poll_train_job(run_dir: str | Path) -> dict[str, Any]:
    run_dir = Path(run_dir)
    job_path = run_dir / "job.json"
    status: dict[str, Any] = {
        "run_dir": str(run_dir),
        "status": "unknown",
        "history": [],
        "log_tail": "",
        "pid": None,
    }
    if job_path.is_file():
        try:
            job = json.loads(job_path.read_text(encoding="utf-8"))
            status["pid"] = job.get("pid")
            status["job"] = job
        except Exception as e:
            status["error"] = f"job.json: {e}"
            return status
    else:
        status["status"] = "no_job"
        return status

    pid = status.get("pid")
    running = _pid_running(int(pid)) if pid else False
    history = load_history(run_dir)
    status["history"] = history
    log_path = run_dir / "train.log"
    if log_path.is_file():
        try:
            text = log_path.read_text(encoding="utf-8", errors="replace")
            status["log_tail"] = "\n".join(text.splitlines()[-80:])
            status["log_path"] = str(log_path)
        except Exception:
            pass

    if running:
        status["status"] = "running"
    else:
        # finished — success if history and best/last exist
        if (run_dir / "best.pt").is_file() or (run_dir / "last.pt").is_file():
            status["status"] = "succeeded"
        elif history:
            status["status"] = "succeeded"
        else:
            # Distinguish "still starting" (empty log, just spawned) vs failed
            log_path = run_dir / "train.log"
            age = time.time() - run_dir.stat().st_mtime
            log_size = log_path.stat().st_size if log_path.is_file() else 0
            started = (status.get("job") or {}).get("started_at")
            if log_size == 0 and age < 15:
                status["status"] = "starting"
            else:
                status["status"] = "failed"
        # update job.json only on terminal states
        if status["status"] in ("succeeded", "failed", "cancelled"):
            try:
                job = status.get("job") or {}
                job["status"] = status["status"]
                job["finished_at"] = datetime.now(timezone.utc).isoformat()
                job_path.write_text(
                    json.dumps(job, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
            except Exception:
                pass
    return status


def cancel_train_job(run_dir: str | Path) -> dict[str, Any]:
    run_dir = Path(run_dir)
    job_path = run_dir / "job.json"
    if not job_path.is_file():
        return {"ok": False, "error": "no job.json"}
    job = json.loads(job_path.read_text(encoding="utf-8"))
    pid = int(job.get("pid") or 0)
    if not pid:
        return {"ok": False, "error": "no pid"}
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                text=True,
                timeout=30,
            )
        else:
            os.killpg(pid, signal.SIGTERM)
    except Exception as e:
        return {"ok": False, "error": str(e), "pid": pid}
    job["status"] = "cancelled"
    job["finished_at"] = datetime.now(timezone.utc).isoformat()
    job_path.write_text(json.dumps(job, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"ok": True, "pid": pid}


def run_eval(
    ckpt: str | Path,
    data_root: str | Path,
    *,
    out_json: str | Path | None = None,
    device: str = "cpu",
) -> dict[str, Any]:
    """Synchronous eval via scripts/eval.py (usually fast on toy data)."""
    ckpt = Path(ckpt)
    data_root = Path(data_root)
    if not ckpt.is_file():
        raise FileNotFoundError(f"ckpt not found: {ckpt}")
    if out_json is None:
        out_json = ckpt.parent / "eval_ui.json"
    out_json = Path(out_json)

    cmd = [
        sys.executable,
        "-u",
        str(TRAIN_ROOT / "scripts" / "eval.py"),
        "--ckpt",
        str(ckpt),
        "--data",
        str(data_root),
        "--device",
        device,
        "--out",
        str(out_json),
    ]
    env = os.environ.copy()
    pp = [str(TRAIN_ROOT), str(CORE_ROOT)]
    if env.get("PYTHONPATH"):
        pp.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(pp)

    proc = subprocess.run(
        cmd,
        cwd=str(TRAIN_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=600,
    )
    result: dict[str, Any] = {
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "out_json": str(out_json),
    }
    if out_json.is_file():
        result["metrics"] = json.loads(out_json.read_text(encoding="utf-8"))
    if proc.returncode != 0:
        result["ok"] = False
        result["error"] = (proc.stderr or proc.stdout or f"exit {proc.returncode}")[-2000:]
    else:
        result["ok"] = True
    return result


def default_ckpt_for_run(run_dir: str | Path) -> Path | None:
    run_dir = Path(run_dir)
    for name in ("best.pt", "last.pt"):
        p = run_dir / name
        if p.is_file():
            return p
    return None


def cuda_available() -> bool:
    try:
        import torch

        return bool(torch.cuda.is_available())
    except Exception:
        return False
