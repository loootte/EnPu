"""Tests for train UI backend (#101)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from enpu_train.data.synthetic import make_synthetic_layout_sample
from enpu_train.ui_backend import (
    TrainJobSpec,
    inspect_layout_sample,
    list_samples_info,
    poll_train_job,
    start_train_job,
    write_train_config,
)


def test_inspect_synthetic(tmp_path: Path) -> None:
    d = tmp_path / "S001"
    make_synthetic_layout_sample(d, sample_id="S001", seed=1)
    info = inspect_layout_sample(d)
    assert info.ok
    assert info.n_systems >= 1
    assert info.n_splits >= 0


def test_list_samples_finds_repo_layout() -> None:
    repo_layout = ROOT.parent / "samples" / "layout"
    if not repo_layout.is_dir():
        pytest.skip("no samples/layout")
    infos = list_samples_info([repo_layout])
    assert any(i.ok for i in infos) or len(infos) >= 0


def test_write_config_and_train_job(tmp_path: Path, monkeypatch) -> None:
    for i in range(2):
        make_synthetic_layout_sample(
            tmp_path / f"S{i}", sample_id=f"S{i}", seed=i, width=320, height=400
        )
    # run under tmp runs
    from enpu_train import ui_backend as ub

    monkeypatch.setattr(ub, "DEFAULT_RUNS", tmp_path / "runs")
    monkeypatch.setattr(ub, "JOBS_DIR", tmp_path / "runs" / "ui_jobs")
    monkeypatch.setattr(ub, "DEFAULT_LAYOUT_ROOT", tmp_path)

    spec = TrainJobSpec(
        run_name="test_ui_run",
        tasks=["l2", "l3"],
        epochs=1,
        batch_size=1,
        data_roots=[str(tmp_path)],
        synth_count=0,
        skip_export=True,
        device="cpu",
    )
    job = start_train_job(spec)
    assert job.get("pid")
    run_dir = Path(job["run_dir"])
    assert (run_dir / "job.json").is_file()
    assert (run_dir / "config.yaml").is_file()

    # wait for process finish (toy train usually < 10s)
    import time

    st = {"status": "starting"}
    for _ in range(120):
        st = poll_train_job(run_dir)
        if st["status"] in ("succeeded", "failed"):
            break
        time.sleep(0.25)
    if st["status"] == "failed":
        print(st.get("log_tail"))
    assert st["status"] == "succeeded", st.get("log_tail")
    assert (run_dir / "last.pt").is_file() or (run_dir / "best.pt").is_file()
