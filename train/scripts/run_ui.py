#!/usr/bin/env python3
"""Launch Streamlit training UI (#101)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

TRAIN_ROOT = Path(__file__).resolve().parents[1]
APP = TRAIN_ROOT / "ui" / "app.py"


def main() -> int:
    cmd = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(APP),
        "--server.headless",
        "true",
    ]
    return subprocess.call(cmd, cwd=str(TRAIN_ROOT))


if __name__ == "__main__":
    raise SystemExit(main())
