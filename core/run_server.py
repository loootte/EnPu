"""
Console entrypoint for EnPu core (dev + PyInstaller sidecar).

Usage:
  python run_server.py
  python run_server.py --host 127.0.0.1 --port 8765

Environment:
  ENPU_RECOGNIZE_ENGINE=mock|paddleocr
  ENPU_HOST / ENPU_PORT (also accepted via CLI flags)

Note: PyInstaller windowed (console=False) builds leave sys.stdout/stderr as
None. uvicorn's default ColorFormatter calls isatty() and crashes — we patch
streams and use a plain logging config when frozen.
"""

from __future__ import annotations

import argparse
import logging
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


def _fix_stdio_for_frozen() -> Path | None:
    """Ensure stdout/stderr are real streams (not None) under windowed sidecar.

    Returns optional log file path when redirected to a file next to the exe.
    """
    frozen = bool(getattr(sys, "frozen", False))
    if not frozen and sys.stdout is not None and sys.stderr is not None:
        return None

    log_path: Path | None = None
    if frozen:
        # Prefer a log file beside the executable for debugging.
        try:
            log_path = Path(sys.executable).resolve().parent / "enpu-core.log"
            log_f = open(log_path, "a", encoding="utf-8", buffering=1)  # noqa: SIM115
            if sys.stdout is None:
                sys.stdout = log_f  # type: ignore[assignment]
            if sys.stderr is None:
                sys.stderr = log_f  # type: ignore[assignment]
            return log_path
        except OSError:
            log_path = None

    # Fallback: discard to NUL /dev/null
    try:
        devnull = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115
    except OSError:
        # Last resort: StringIO-like dummy with isatty
        class _Dummy:
            def write(self, *_a: object, **_k: object) -> int:
                return 0

            def flush(self) -> None:
                return None

            def isatty(self) -> bool:
                return False

        dummy = _Dummy()
        if sys.stdout is None:
            sys.stdout = dummy  # type: ignore[assignment]
        if sys.stderr is None:
            sys.stderr = dummy  # type: ignore[assignment]
        return log_path

    if sys.stdout is None:
        sys.stdout = devnull  # type: ignore[assignment]
    if sys.stderr is None:
        sys.stderr = devnull  # type: ignore[assignment]
    return log_path


def _plain_log_config() -> dict:
    """Uvicorn log config without ColorFormatter (no isatty dependency)."""
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "()": "logging.Formatter",
                "fmt": "%(asctime)s %(levelname)s [%(name)s] %(message)s",
                "datefmt": "%Y-%m-%d %H:%M:%S",
            },
            "access": {
                "()": "logging.Formatter",
                "fmt": '%(asctime)s %(levelname)s [access] %(client_addr)s - "%(request_line)s" %(status_code)s',
                "datefmt": "%Y-%m-%d %H:%M:%S",
            },
        },
        "handlers": {
            "default": {
                "formatter": "default",
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stderr",
            },
            "access": {
                "formatter": "access",
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout",
            },
        },
        "loggers": {
            "uvicorn": {"handlers": ["default"], "level": "INFO", "propagate": False},
            "uvicorn.error": {"handlers": ["default"], "level": "INFO", "propagate": False},
            "uvicorn.access": {"handlers": ["access"], "level": "INFO", "propagate": False},
        },
    }


def main() -> None:
    # Must run before any logging / uvicorn import side effects when frozen.
    log_path = _fix_stdio_for_frozen()
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
    if log_path is not None:
        logging.getLogger("enpu").info("logging to %s", log_path)

    # Always use plain log config when frozen, or when streams were patched.
    use_plain = frozen or sys.stdout is None or sys.stderr is None or not hasattr(
        sys.stderr, "isatty"
    )

    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        reload=(args.reload and not frozen),
        log_level="info",
        log_config=_plain_log_config() if use_plain else None,
    )


if __name__ == "__main__":
    main()
