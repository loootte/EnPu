"""
Console entrypoint for EnPu core (dev + PyInstaller sidecar).

Usage:
  python run_server.py
  python run_server.py --host 127.0.0.1 --port 8765

Environment:
  ENPU_RECOGNIZE_ENGINE=mock|paddleocr
  ENPU_HOST / ENPU_PORT (also accepted via CLI flags)
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def _ensure_app_path() -> None:
    """Make `app` importable when frozen or run from core/."""
    if getattr(sys, "frozen", False):
        # PyInstaller onedir/onefile: modules live next to the executable bundle.
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        sys.path.insert(0, str(base))
    else:
        core_dir = Path(__file__).resolve().parent
        if str(core_dir) not in sys.path:
            sys.path.insert(0, str(core_dir))


def main() -> None:
    _ensure_app_path()

    parser = argparse.ArgumentParser(description="EnPu recognition core (FastAPI)")
    parser.add_argument("--host", default=os.environ.get("ENPU_HOST", "127.0.0.1"))
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("ENPU_PORT", os.environ.get("ENPU_CORE_PORT", "8765"))),
    )
    parser.add_argument(
        "--engine",
        default=os.environ.get("ENPU_RECOGNIZE_ENGINE", "mock"),
        help="mock (default for sidecar PoC) or paddleocr",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Dev only; ignored when frozen.",
    )
    args = parser.parse_args()

    os.environ["ENPU_RECOGNIZE_ENGINE"] = args.engine

    # Clear settings cache if app already imported settings in this process.
    try:
        from app.config import clear_settings_cache

        clear_settings_cache()
    except Exception:
        pass

    import uvicorn

    from app.main import app

    frozen = bool(getattr(sys, "frozen", False))
    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        reload=(args.reload and not frozen),
        log_level="info",
    )


if __name__ == "__main__":
    main()
