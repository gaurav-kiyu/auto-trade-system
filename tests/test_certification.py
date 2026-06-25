"""Tests for the Certification Framework (core/certification/)."""

from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path

import pytest

from core.certification import (
    PaperCertificationReport,
    PaperCertifier,
    ReplayCertificationReport,
    ReplayCertifier,
    certify_paper_trading,
    certify_replay_determinism,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def empty_trades_db() -> str:
    """Create an empty trades.db for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE trades ("
        "  id INTEGER PRIMARY KEY,"
        "  ts TEXT,"
        "  index_name TEXT,"
        "  direction TEXT,"
        "  entry REAL,"
        "  exit_price REAL,"
        "  net_pnl REAL,"
        "  score INTEGER,"
        "  regime TEXT,"
        "  reason TEXT"
        ")"
    )
    conn.commit()
    conn.close()
    yield db_path
    Path(db_path).unlink(missing_ok=True)


@pytest.fixture
def seeded_trades_db() -> str:
    """Create a trades.db with sample closed trades."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE trades ("
        "  id INTEGER PRIMARY KEY,"
        "  ts TEXT,"
        "  index_name TEXT,"
        "  direction TEXT,"
        "  entry REAL,"
        "  exit_price REAL,"
        "  net_pnl REAL,"
        "  score INTEGER,"
        "  regime TEXT,"
        "  reason TEXT"
        ")"
    )
    sample_trades = [
        (1, "2026-05-01 09:30:00", "NIFTY", "CALL", 18500.0, 18600.0, 500.0, 85, "TRENDING", "TARGET"),
        (2, "2026-05-01 10:00:00", "BANKNIFTY", "PUT", 44000.0, 43800.0, 2000.0, 72, "SIDEWAYS", "TARGET"),
        (3, "2026-05-01 11:00:00", "NIFTY", "CALL", 18600.0, 18500.0, -500.0, 65, "CHOPPY", "STOP_LOSS"),
        (4, "2026-05-02 09:45:00", "FINNIFTY", "CALL", 17500.0, 17600.0, 400.0, 80, "TRENDING", "TARGET"),
        (5, "2026-05-02 10:30:00", "NIFTY", "PUT", 18400.0, 18300.0, 500.0, 78, "TRENDING", "TARGET"),
    ]
    conn.executemany(
        "INSERT INTO trades VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        sample_trades,
    )
    conn.commit()
    conn.close()
    yield db_path
    Path(db_path).unlink(missing_ok=True)


# ── Replay Certifier Tests ────────────────────────────────────────────────────


class TestReplayCertifier:
    def test_init(self):
        certifier = ReplayCertifier()
        assert certifier is not None

    def test_empty_db(self, empty_trades_db):
        """Empty DB = vacuously true."""
        certifier = ReplayCertifier()
        report = certifier.certify(db_path=empty_trades_db)
        assert report.passed is True
        assert report.total_trades == 0
        assert "vacuously true" in report.verdict

    def test_missing_db(self):
        """Missing DB = vacuously passes (no trade data to certify)."""
        certifier = ReplayCertifier()
        report = certifier.certify(db_path="/nonexistent/trades.db")
        assert report.passed is True
        assert "vacuously true" in report.verdict

    def test_seeded_db_determinism(self, seeded_trades_db):
        """Seeded trades should be deterministic."""
        certifier = ReplayCertifier(frames_to_show=5, bar_width=30)
        report = certifier.certify(db_path=seeded_trades_db, max_trades=3)
        # Trades should be deterministic since _simulate_price_bars uses random.seed(42)
        assert report.passed is True
        assert report.deterministic_count > 0

    def test_report_to_dict(self, seeded_trades_db):
        """to_dict produces serializable output."""
        certifier = ReplayCertifier()
        report = certifier.certify(db_path=seeded_trades_db, max_trades=2)
        d = report.to_dict()
        assert d["certification_type"] == "replay"
        assert isinstance(d["passed"], bool)
        assert isinstance(d["duration_seconds"], float)
        assert isinstance(d["tested_trades"], int)
        # Verify JSON-serializable
        json.dumps(d)

    def test_consistency_hash_format(self, seeded_trades_db):
        """Hash consistency dict has expected format."""
        certifier = ReplayCertifier()
        report = certifier.certify(db_path=seeded_trades_db, max_trades=2)
        for tid, hash_val in report.hash_consistency.items():
            assert isinstance(tid, int)
            assert isinstance(hash_val, str)
            assert len(hash_val) == 16  # hexdigest[:16]

    def test_convenience_function(self, seeded_trades_db):
        """Convenience function works."""
        report = certify_replay_determinism(
            db_path=seeded_trades_db, max_trades=2, frames=5, width=30
        )
        assert report is not None
        assert isinstance(report, ReplayCertificationReport)

    def test_report_summary_format(self, seeded_trades_db):
        """Summary string has expected content."""
        certifier = ReplayCertifier()
        report = certifier.certify(db_path=seeded_trades_db, max_trades=2)
        summary = report.summary()
        assert "REPLAY CERTIFICATION" in summary
        assert "PASSED" in summary or "FAILED" in summary


# ── Paper Certifier Tests ─────────────────────────────────────────────────────


class TestPaperCertifier:
    def test_init(self):
        certifier = PaperCertifier()
        assert certifier is not None

    def test_empty_db(self, empty_trades_db):
        """Empty DB = vacuously true."""
        certifier = PaperCertifier()
        report = certifier.certify(db_path=empty_trades_db)
        assert report.passed is True
        assert "vacuously true" in report.verdict

    def test_missing_db(self):
        """Missing DB = vacuously true (paper mode only)."""
        certifier = PaperCertifier()
        report = certifier.certify(db_path="/nonexistent/trades.db")
        assert report.passed is True
        assert "vacuously true" in report.verdict

    def test_seeded_db_statistics(self, seeded_trades_db):
        """Seeded trades produce expected statistics."""
        certifier = PaperCertifier()
        report = certifier.certify(db_path=seeded_trades_db)
        assert report.total_trades == 5
        assert report.closed_trades == 5
        assert report.win_count == 4  # 4 positive PnL trades
        assert report.loss_count == 1  # 1 negative PnL trade
        assert report.win_rate == 0.8  # 4/5

    def test_pnl_calculation(self, seeded_trades_db):
        """Total PnL is correct."""
        certifier = PaperCertifier()
        report = certifier.certify(db_path=seeded_trades_db)
        # 500 + 2000 + (-500) + 400 + 500 = 2900
        assert report.total_pnl == 2900.0

    def test_drawdown_calculation(self, seeded_trades_db):
        """Max drawdown is computed."""
        certifier = PaperCertifier()
        report = certifier.certify(db_path=seeded_trades_db)
        assert report.max_drawdown >= 0.0

    def test_report_to_dict(self, seeded_trades_db):
        """to_dict produces serializable output."""
        certifier = PaperCertifier()
        report = certifier.certify(db_path=seeded_trades_db)
        d = report.to_dict()
        assert d["certification_type"] == "paper_trading"
        assert isinstance(d["passed"], bool)
        assert isinstance(d["overall_score"], float)
        assert isinstance(d["duration_seconds"], float)
        assert "win_rate" in d
        assert "profit_factor" in d
        assert "sharpe_ratio" in d
        # Verify JSON-serializable
        json.dumps(d)

    def test_convenience_function(self, seeded_trades_db):
        """Convenience function works."""
        report = certify_paper_trading(db_path=seeded_trades_db)
        assert report is not None
        assert isinstance(report, PaperCertificationReport)

    def test_report_summary_format(self, seeded_trades_db):
        """Summary string has expected content."""
        certifier = PaperCertifier()
        report = certifier.certify(db_path=seeded_trades_db)
        summary = report.summary()
        assert "PAPER TRADING CERTIFICATION" in summary
        assert "PASSED" in summary or "FAILED" in summary

    def test_dimension_scores(self, seeded_trades_db):
        """All dimension scores are in 0-10 range."""
        certifier = PaperCertifier()
        report = certifier.certify(db_path=seeded_trades_db)
        assert 0 <= report.signal_quality_score <= 10
        assert 0 <= report.execution_quality_score <= 10
        assert 0 <= report.risk_enforcement_score <= 10
        assert 0 <= report.overall_score <= 10

    def test_profit_factor_non_zero(self, seeded_trades_db):
        """Profit factor is computed and positive."""
        certifier = PaperCertifier()
        report = certifier.certify(db_path=seeded_trades_db)
        assert report.profit_factor > 0
        # total_wins = 500 + 2000 + 400 + 500 = 3400
        # total_losses_abs = 500
        # profit_factor = 3400 / 500 = 6.8
        assert report.profit_factor == 6.8

    def test_sharpe_ratio_calculated(self, seeded_trades_db):
        """Sharpe ratio is computed."""
        certifier = PaperCertifier()
        report = certifier.certify(db_path=seeded_trades_db)
        assert report.sharpe_ratio != 0.0

    def test_single_trade_db(self):
        """Single trade produces valid report."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        conn = sqlite3.connect(db_path)
        conn.execute(
            "CREATE TABLE trades ("
            "  id INTEGER PRIMARY KEY,"
            "  ts TEXT, index_name TEXT, direction TEXT,"
            "  entry REAL, exit_price REAL, net_pnl REAL,"
            "  score INTEGER, regime TEXT, reason TEXT"
            ")"
        )
        conn.execute(
            "INSERT INTO trades VALUES (1, '2026-05-01', 'NIFTY', 'CALL', "
            "18500.0, 18600.0, 500.0, 85, 'TRENDING', 'TARGET')"
        )
        conn.commit()
        conn.close()

        try:
            certifier = PaperCertifier()
            report = certifier.certify(db_path=db_path)
            assert report.total_trades == 1
            assert report.closed_trades == 1
            assert report.win_count == 1
            assert report.passed is True
        finally:
            Path(db_path).unlink(missing_ok=True)

    def test_all_losses_db(self):
        """All losses produces valid report."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        conn = sqlite3.connect(db_path)
        conn.execute(
            "CREATE TABLE trades ("
            "  id INTEGER PRIMARY KEY,"
            "  ts TEXT, index_name TEXT, direction TEXT,"
            "  entry REAL, exit_price REAL, net_pnl REAL,"
            "  score INTEGER, regime TEXT, reason TEXT"
            ")"
        )
        conn.execute(
            "INSERT INTO trades VALUES (1, '2026-05-01', 'NIFTY', 'CALL', "
            "18500.0, 18450.0, -250.0, 60, 'CHOPPY', 'STOP_LOSS')"
        )
        conn.commit()
        conn.close()

        try:
            certifier = PaperCertifier()
            report = certifier.certify(db_path=db_path)
            assert report.total_trades == 1
            assert report.closed_trades == 1
            assert report.win_count == 0
            assert report.loss_count == 1
            assert report.passed is True  # Even all-losses certifies (informational)
        finally:
            Path(db_path).unlink(missing_ok=True)
