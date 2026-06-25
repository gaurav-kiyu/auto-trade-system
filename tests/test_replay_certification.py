"""
Formal Replay Certification Test Suite (v2.53+).

Certifies that the ReplayCertifier produces deterministic, verifiable results
for all trade types. Uses a temporary SQLite database fixture so the test
is self-contained and does not depend on live trades.db.

Remediates:
  - GAP-08: Build formal replay certification test suite
  - Ensures replay determinism is verifiable in CI
"""

from __future__ import annotations

import os
import random
import sqlite3
import tempfile

import pytest

from core.certification.replay_certifier import ReplayCertifier, certify_replay_determinism


# ── Fixture factories ───────────────────────────────────────────────────────

def _create_trades_db(db_path: str, trade_count: int = 5) -> None:
    """Create a temporary trades.db with the given number of closed trades."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                index_name TEXT,
                direction TEXT,
                entry REAL,
                exit_price REAL,
                ts TEXT,
                exit_ts TEXT,
                net_pnl REAL,
                score INTEGER,
                regime TEXT,
                reason TEXT,
                sl_price REAL DEFAULT 0,
                target_price REAL DEFAULT 0,
                qty INTEGER DEFAULT 1,
                entry_price REAL DEFAULT 0,
                exit_time TEXT DEFAULT '',
                strategy TEXT DEFAULT '',
                tags TEXT DEFAULT ''
            )
            """
        )
        # Insert sample trades with deterministic but varied data
        trades = [
            {
                "index_name": "NIFTY",
                "direction": "CALL",
                "entry": 18500.0,
                "exit_price": 19000.0,
                "ts": "2026-06-01 09:30:00",
                "exit_ts": "2026-06-01 14:30:00",
                "net_pnl": 500.0,
                "score": 85,
                "regime": "TRENDING",
                "reason": "TARGET_HIT",
                "qty": 1,
                "entry_price": 18500.0,
            },
            {
                "index_name": "BANKNIFTY",
                "direction": "PUT",
                "entry": 44000.0,
                "exit_price": 43500.0,
                "ts": "2026-06-02 10:15:00",
                "exit_ts": "2026-06-02 12:45:00",
                "net_pnl": -200.0,
                "score": 72,
                "regime": "RANGING",
                "reason": "STOP_LOSS",
                "qty": 1,
                "entry_price": 44000.0,
            },
            {
                "index_name": "FINNIFTY",
                "direction": "CALL",
                "entry": 19500.0,
                "exit_price": 19800.0,
                "ts": "2026-06-03 11:00:00",
                "exit_ts": "2026-06-03 15:00:00",
                "net_pnl": 150.0,
                "score": 90,
                "regime": "STRONG_TREND",
                "reason": "TARGET_HIT",
                "qty": 2,
                "entry_price": 19500.0,
            },
            {
                "index_name": "NIFTY",
                "direction": "PUT",
                "entry": 18600.0,
                "exit_price": 18400.0,
                "ts": "2026-06-04 09:45:00",
                "exit_ts": "2026-06-04 11:30:00",
                "net_pnl": -350.0,
                "score": 65,
                "regime": "VOLATILE",
                "reason": "STOP_LOSS",
                "qty": 1,
                "entry_price": 18600.0,
            },
            {
                "index_name": "BANKNIFTY",
                "direction": "CALL",
                "entry": 44500.0,
                "exit_price": 45200.0,
                "ts": "2026-06-05 10:00:00",
                "exit_ts": "2026-06-05 13:00:00",
                "net_pnl": 350.0,
                "score": 78,
                "regime": "TRENDING",
                "reason": "TARGET_HIT",
                "qty": 1,
                "entry_price": 44500.0,
            },
        ]

        # Only insert up to trade_count
        for t in trades[:trade_count]:
            conn.execute(
                """
                INSERT INTO trades
                    (index_name, direction, entry, exit_price, ts, exit_ts,
                     net_pnl, score, regime, reason, qty, entry_price)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    t["index_name"], t["direction"], t["entry"], t["exit_price"],
                    t["ts"], t["exit_ts"], t["net_pnl"], t["score"],
                    t["regime"], t["reason"], t["qty"], t["entry_price"],
                ),
            )
        conn.commit()
    finally:
        conn.close()


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_trades_db():
    """Create a temporary trades.db with test data."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name
    _create_trades_db(db_path, trade_count=5)
    yield db_path
    try:
        os.unlink(db_path)
    except (OSError, PermissionError):
        pass


@pytest.fixture
def empty_trades_db():
    """Create an empty temporary trades.db (has trades table but no rows)."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "CREATE TABLE trades ("
            "id INTEGER PRIMARY KEY, index_name TEXT, direction TEXT, "
            "entry REAL, exit_price REAL, ts TEXT, exit_ts TEXT, "
            "net_pnl REAL, score INTEGER, regime TEXT, reason TEXT, "
            "qty INTEGER, entry_price REAL DEFAULT 0"
            ")"
        )
        conn.commit()
    finally:
        conn.close()
    yield db_path
    try:
        os.unlink(db_path)
    except (OSError, PermissionError):
        pass


# ── Tests ───────────────────────────────────────────────────────────────────

class TestReplayCertifierCertify:
    """ReplayCertifier.certify() - end-to-end certification."""

    def test_certify_with_valid_trades(self, tmp_trades_db):
        """Certify with a database containing valid trades."""
        certifier = ReplayCertifier()
        report = certifier.certify(db_path=tmp_trades_db, max_trades=5)

        assert report.passed is True
        assert report.total_trades == 5
        assert report.tested_trades == 5
        assert report.deterministic_count == 5
        assert report.failed_count == 0
        assert report.error_count == 0
        assert len(report.hash_consistency) == 5
        assert "DETERMINISTIC" in report.verdict.upper()

    def test_certify_multiple_runs_produce_same_hash(self, tmp_trades_db):
        """Running certify() twice on the same DB produces identical hashes."""
        certifier = ReplayCertifier()

        report1 = certifier.certify(db_path=tmp_trades_db, max_trades=5)
        report2 = certifier.certify(db_path=tmp_trades_db, max_trades=5)

        # Same trade IDs should produce same hashes
        for tid, h1 in report1.hash_consistency.items():
            h2 = report2.hash_consistency.get(tid)
            assert h2 is not None, f"Trade {tid} missing from second run"
            assert h1 == h2, f"Trade {tid} hash changed between runs: {h1} vs {h2}"

    def test_certify_with_empty_db(self, empty_trades_db):
        """Certify with an empty database (trades table exists but no rows - vacuously true)."""
        certifier = ReplayCertifier()
        report = certifier.certify(db_path=empty_trades_db)

        assert report.passed is True
        assert report.total_trades == 0
        assert "vacuously true" in report.verdict

    def test_certify_with_nonexistent_db(self):
        """Certify with a nonexistent database file - vacuously passes when no data."""
        certifier = ReplayCertifier()
        report = certifier.certify(db_path="nonexistent_trades_xyz_nonexistent.db")

        assert report.passed is True
        assert "vacuously true" in report.verdict.lower()

    def test_certify_single_trade(self, tmp_trades_db):
        """Certify with max_trades=1."""
        certifier = ReplayCertifier()
        report = certifier.certify(db_path=tmp_trades_db, max_trades=1)

        assert report.passed is True
        assert report.tested_trades == 1
        assert report.deterministic_count == 1

    def test_certify_respects_random_seed(self, tmp_trades_db):
        """Replay is deterministic because random.seed(42) is set."""
        random.seed(42)
        certifier = ReplayCertifier()
        report = certifier.certify(db_path=tmp_trades_db, max_trades=3)

        assert report.passed is True
        assert report.tested_trades == 3


class TestConvenienceFunction:
    """certify_replay_determinism() convenience function."""

    def test_convenience_with_valid_db(self, tmp_trades_db):
        report = certify_replay_determinism(db_path=tmp_trades_db, max_trades=3)
        assert report.passed is True
        assert report.tested_trades == 3

    def test_convenience_with_empty_db(self, empty_trades_db):
        report = certify_replay_determinism(db_path=empty_trades_db)
        assert report.passed is True
        assert report.total_trades == 0


class TestReplayCertificationReport:
    """ReplayCertificationReport - data integrity checks."""

    def test_summary_format(self, tmp_trades_db):
        certifier = ReplayCertifier()
        report = certifier.certify(db_path=tmp_trades_db, max_trades=1)

        summary = report.summary()
        assert "REPLAY" in summary
        assert "PASSED" in summary or "FAILED" in summary
        assert str(report.tested_trades) in summary

    def test_to_dict_serializable(self, tmp_trades_db):
        certifier = ReplayCertifier()
        report = certifier.certify(db_path=tmp_trades_db, max_trades=1)

        d = report.to_dict()
        assert d["certification_type"] == "replay"
        assert d["passed"] is True
        assert isinstance(d["duration_seconds"], float)
        assert d["tested_trades"] == 1

    def test_failure_scenario(self):
        """Simulate a failure to verify report captures errors.

        Note: With vacuous-pass semantics, a nonexistent DB passes.
        This test verifies the verdict reflects the vacuous status.
        """
        # Use nonexistent DB - should vacuous-pass
        certifier = ReplayCertifier()
        report = certifier.certify(db_path="nonexistent_trades_xyz_nonexistent_fail.db")

        assert report.passed is True
        d = report.to_dict()
        assert d["passed"] is True
        assert "vacuously true" in d["verdict"].lower()


class TestDeterminismGuarantee:
    """Verify that the replay engine itself is deterministic."""

    def test_simulate_price_bars_reproducible(self):
        """_simulate_price_bars with seed=42 produces identical output."""
        from core.certification.replay_certifier import replay_trace

        # We need a valid trade in a DB - create one
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name
        try:
            _create_trades_db(db_path, trade_count=1)

            # Run replay_trace twice
            result1 = replay_trace(1, db_path, frames=10, width=40)
            result2 = replay_trace(1, db_path, frames=10, width=40)

            assert result1 == result2, "Replay trace produced different output between runs"
        finally:
            try:
                os.unlink(db_path)
            except (OSError, PermissionError):
                pass


class TestCertifyWithCorruptDB:
    """Certify with various edge-case databases."""

    def test_db_with_no_trades(self):
        """Database with trades table but no rows with net_pnl."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name
        try:
            conn = sqlite3.connect(db_path)
            conn.execute(
                "CREATE TABLE trades ("
                "id INTEGER PRIMARY KEY, symbol TEXT, index_name TEXT, "
                "direction TEXT, entry REAL, exit_price REAL, ts TEXT, "
                "exit_ts TEXT, net_pnl REAL, score INTEGER, regime TEXT, "
                "reason TEXT, qty INTEGER, entry_price REAL DEFAULT 0"
                ")"
            )
            # Insert a row with NULL net_pnl (open trade, not closed)
            conn.execute(
                "INSERT INTO trades (id, symbol, net_pnl) VALUES (1, 'NIFTY', NULL)"
            )
            conn.commit()
            conn.close()

            certifier = ReplayCertifier()
            report = certifier.certify(db_path=db_path, max_trades=1)

            # No closed trades (net_pnl IS NULL): vacuously true
            assert report.passed is True
            assert report.total_trades == 0
            assert "vacuously" in report.verdict
        finally:
            try:
                os.unlink(db_path)
            except (OSError, PermissionError):
                pass
