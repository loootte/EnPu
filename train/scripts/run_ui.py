#!/usr/bin/env python3
"""Launch Streamlit training UI (#101)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

TRAIN_ROOT = Path(__file__).resolve().parents[1]
APP = TRAIN_ROOT / "ui" / "streamlit_app.py"
CORE = TRAIN_ROOT.parent / "core"


def main() -> int:
    import os

    env = os.environ.copy()
    # Ensure core package ``app`` is importable when Streamlit spawns the runner
    pp = [str(CORE), str(TRAIN_ROOT)]
    if env.get("PYTHONPATH"):
        pp.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(pp)
    cmd = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(APP),
        "--server.headless",
        "true",
    ]
    return subprocess.call(cmd, cwd=str(TRAIN_ROOT), env=env)


if __name__ == "__main__":
    raise SystemExit(main())
