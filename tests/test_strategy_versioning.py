"""
Tests for core/strategy/strategy_versioning.py - Strategy Versioning.

Covers:
  - StrategyVersion dataclass (fields, defaults)
  - TradeRecord dataclass (fields, defaults)
  - StrategyVersionManager init (in-memory + SQLite)
  - register_version (new, duplicate, config hash)
  - get_version (found, not found)
  - get_latest_version (multiple versions, empty)
  - compute_config_hash (deterministic, different configs)
  - get_strategy_version_manager singleton
"""

from __future__ import annotations

import os
import tempfile

import pytest

from core.strategy.strategy_versioning import (
    StrategyVersion,
    StrategyVersionManager,
    TradeRecord,
    get_strategy_version_manager,
)


def _cleanup_db(db_path: str) -> None:
    """Safely remove a SQLite DB file on Windows."""
    import time as _t
    for suffix in ("-wal", "-shm"):
        companion = db_path + suffix
        if os.path.exists(companion):
            try:
                os.unlink(companion)
            except PermissionError:
                pass
    for attempt in range(5):
        try:
            if os.path.exists(db_path):
                os.unlink(db_path)
            return
        except PermissionError:
            _t.sleep(0.1 * (attempt + 1))


# ═══════════════════════════════════════════════════════════════════════
#  Dataclasses
# ═══════════════════════════════════════════════════════════════════════


class TestStrategyVersion:
    def test_defaults(self):
        sv = StrategyVersion(
            strategy_name="spread", version="1.0.0",
            config_hash="abc123", created_at="2026-01-01T00:00:00",
        )
        assert sv.is_active is True
        assert sv.metadata == {}

    def test_fields(self):
        sv = StrategyVersion(
            strategy_name="straddle", version="2.1.0",
            config_hash="def456", created_at="2026-06-01T12:00:00",
            is_active=False, metadata={"author": "quant"},
        )
        assert sv.is_active is False
        assert sv.metadata["author"] == "quant"


class TestTradeRecord:
    def test_fields(self):
        tr = TradeRecord(
            trade_id="T-001", intent_id="INT-001", strategy_name="spread",
            strategy_version="1.0", config_hash="abc", signal_score=80.0,
            direction="BUY", symbol="NIFTY", quantity=50, entry_price=23500.0,
            exit_price=None, pnl=None, entry_time="09:15:00", exit_time=None,
            outcome="OPEN",
        )
        assert tr.exit_price is None
        assert tr.pnl is None
        assert tr.exit_time is None


# ═══════════════════════════════════════════════════════════════════════
#  StrategyVersionManager
# ═══════════════════════════════════════════════════════════════════════


class TestStrategyVersionManager:
    @pytest.fixture(autouse=True)
    def _use_memory_db(self, monkeypatch):
        """Use in-memory DB for each test to avoid conflicts."""
        fd, self._db_path = tempfile.mkstemp(suffix="_strategy_versioning.db")
        os.close(fd)
        monkeypatch.setattr("core.strategy.strategy_versioning.StrategyVersionManager.PERSISTENCE_PATH", self._db_path)
        self.mgr = StrategyVersionManager()
        yield
        _cleanup_db(self._db_path)

    def test_init_creates_tables(self):
        """Verify tables exist after init."""
        import sqlite3
        conn = sqlite3.connect(self._db_path)
        try:
            tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
            assert "strategy_versions" in tables
            assert "trade_records" in tables
        finally:
            conn.close()

    def test_register_version(self):
        sv = self.mgr.register_version("spread", "1.0.0", {"param": 42})
        assert sv.strategy_name == "spread"
        assert sv.version == "1.0.0"
        assert len(sv.config_hash) == 16
        assert sv.is_active is True

    def test_register_multiple_versions(self):
        self.mgr.register_version("spread", "1.0.0", {"param": 42})
        self.mgr.register_version("spread", "2.0.0", {"param": 99})
        assert self.mgr.get_latest_version("spread").version == "2.0.0"

    def test_register_two_strategies(self):
        self.mgr.register_version("spread", "1.0.0", {})
        self.mgr.register_version("straddle", "2.0.0", {})
        assert len(self.mgr._versions) == 2

    def test_get_version_found(self):
        self.mgr.register_version("spread", "1.0.0", {"a": 1})
        sv = self.mgr.get_version("spread", "1.0.0")
        assert sv is not None
        assert sv.config_hash is not None

    def test_get_version_not_found(self):
        sv = self.mgr.get_version("nonexistent", "1.0")
        assert sv is None

    def test_get_latest_version_empty(self):
        sv = self.mgr.get_latest_version("empty")
        assert sv is None

    def test_compute_config_hash(self):
        h1 = self.mgr.compute_config_hash({"a": 1, "b": 2})
        h2 = self.mgr.compute_config_hash({"a": 1, "b": 2})
        h3 = self.mgr.compute_config_hash({"a": 1, "b": 3})
        assert h1 == h2
        assert h1 != h3
        assert len(h1) == 16

    def test_persist_to_db(self):
        self.mgr.register_version("spread", "1.0.0", {"param": 42})
        import sqlite3
        conn = sqlite3.connect(self._db_path)
        try:
            rows = conn.execute(
                "SELECT strategy_name, version FROM strategy_versions"
            ).fetchall()
            assert ("spread", "1.0.0") in rows
        finally:
            conn.close()

    def test_register_memory_and_db_sync(self):
        sv = self.mgr.register_version("straddle", "3.0.0", {"k": "v"})
        # In-memory
        assert self.mgr.get_version("straddle", "3.0.0") is sv
        # DB
        import sqlite3
        conn = sqlite3.connect(self._db_path)
        try:
            rows = conn.execute(
                "SELECT config_hash FROM strategy_versions WHERE strategy_name=? AND version=?",
                ("straddle", "3.0.0"),
            ).fetchall()
            assert len(rows) == 1
            assert rows[0][0] == sv.config_hash
        finally:
            conn.close()


# ═══════════════════════════════════════════════════════════════════════
#  Singleton
# ═══════════════════════════════════════════════════════════════════════


class TestGetStrategyVersionManager:
    @pytest.fixture(autouse=True)
    def _reset(self):
        """Reset the singleton before and after each test."""
        from core.strategy import strategy_versioning as sv
        old = sv._version_manager
        sv._version_manager = None
        yield
        sv._version_manager = old

    def test_singleton(self):
        m1 = get_strategy_version_manager()
        m2 = get_strategy_version_manager()
        assert m1 is m2
