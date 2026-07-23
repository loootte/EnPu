"""Pytest fixtures — default to mock OCR so unit tests stay offline-fast."""

from __future__ import annotations

import os

import pytest

# Must set before app.config is first imported in workers; also clear cache below.
os.environ.setdefault("ENPU_RECOGNIZE_ENGINE", "mock")


@pytest.fixture(autouse=True)
def _mock_engine_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force mock engine unless a test explicitly opts into real OCR."""
    if os.environ.get("ENPU_TEST_REAL_OCR") == "1":
        return
    monkeypatch.setenv("ENPU_RECOGNIZE_ENGINE", "mock")
    from app.config import clear_settings_cache

    clear_settings_cache()
    yield
    clear_settings_cache()
