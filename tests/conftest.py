"""
OPB Test Suite - Shared fixtures, hooks, and configuration.

All tests automatically have access to:
  - ROOT path (project root)
  - config_values fixture (session-scoped config.json)
  - temp_db fixture (temporary sqlite3 database for any test)
  - mock_yfinance fixture (patches yfinance to prevent network calls)
  - disable_notifications fixture (patches Telegram to prevent accidental sends)
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ── Register custom markers ───────────────────────────────────────────────────


def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers to suppress pytest warnings about unknown markers."""
    config.addinivalue_line("markers", "slow: marks tests as slow (subprocess, real I/O)")
    config.addinivalue_line("markers", "confidence_gate: marks tests as core safety checks")
    config.addinivalue_line("markers", "network: marks tests that require network access")
    config.addinivalue_line("markers", "ml: marks tests that require ML dependencies (lightgbm, shap)")



# ── Session-scoped fixtures ───────────────────────────────────────────────────


@pytest.fixture(scope="session")
def config_values() -> dict:
    """Load config.json once per test session.

    Use this fixture instead of hardcoding config threshold values in tests.
    If config.json changes, tests using this fixture automatically pick up the
    new values rather than silently testing against stale constants.

    Example::

        def test_signal_max_age_from_config(config_values):
            assert mod.SIGNAL_MAX_AGE == config_values["SIGNAL_MAX_AGE"]
    """
    cfg_path = ROOT / "config.json"
    with cfg_path.open(encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="session")
def defaults_config() -> dict:
    """Load index_config.defaults.json once per test session."""
    cfg_path = ROOT / "index_config.defaults.json"
    with cfg_path.open(encoding="utf-8") as f:
        return json.load(f)


# ── Function-scoped fixtures ──────────────────────────────────────────────────


@pytest.fixture
def temp_db() -> Generator[str, None, None]:
    """Create a temporary SQLite database file that is cleaned up after the test.

    The DB is created with a journal table suitable for most trading tests.
    Returns the file path as a string.
    """
    import sqlite3

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        con = sqlite3.connect(path)
        con.execute("""
            CREATE TABLE IF NOT EXISTS journal (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                score REAL,
                confidence REAL,
                direction TEXT,
                tier TEXT,
                soft_blocks TEXT,
                entry_ts TEXT,
                actual_entry REAL,
                is_winner INTEGER,
                net_pnl REAL,
                iv_rank REAL DEFAULT 50.0,
                vix_at_entry REAL DEFAULT 15.0,
                pcr_at_entry REAL DEFAULT 1.0,
                regime TEXT DEFAULT 'NEUTRAL',
                session_code INTEGER DEFAULT 1
            )
        """)
        con.commit()
        con.close()
        yield path
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


@pytest.fixture
def temp_file() -> Generator[str, None, None]:
    """Create a temporary file that is cleaned up after the test."""
    fd, path = tempfile.mkstemp()
    os.close(fd)
    try:
        yield path
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


@pytest.fixture(autouse=True)
def _patch_network_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent accidental real network calls in tests.

    Tests requiring network should use ``@pytest.mark.network`` and opt out
    by overriding this fixture locally.
    """
    monkeypatch.setattr("yfinance.download", lambda *a, **kw: None)  # type: ignore[assignment]
    monkeypatch.setattr("requests.Session.request", lambda *a, **kw: type("Resp", (), {"status_code": 200, "text": "{}", "json": lambda: {}}))  # type: ignore[assignment]


# ── Thread-safety helper for tests ────────────────────────────────────────────


def run_concurrently(
    target: Any,
    args_list: list[tuple],
    n_threads: int = 4,
    timeout: float = 10.0,
) -> list[Any]:
    """Run a function concurrently across multiple threads.

    Useful for testing thread safety of shared state.

    Args:
        target: Function to call in each thread.
        args_list: List of argument tuples, one per thread invocation.
        n_threads: Number of threads to use (default 4).
        timeout: Maximum seconds to wait for all threads.

    Returns:
        List of return values from each thread (in order).
    """
    results: list[Any] = [None] * len(args_list)
    exceptions: list[Exception | None] = [None] * len(args_list)
    barrier = threading.Barrier(len(args_list))

    def _worker(idx: int, args: tuple) -> None:
        barrier.wait()  # synchronize start
        try:
            results[idx] = target(*args)
        except Exception as e:
            exceptions[idx] = e

    threads = [
        threading.Thread(target=_worker, args=(i, args_list[i]))
        for i in range(len(args_list))
    ]
    for t in threads:
        t.daemon = True
        t.start()
    for t in threads:
        t.join(timeout=timeout)

    # Raise first exception found
    for exc in exceptions:
        if exc is not None:
            raise exc
    return results
