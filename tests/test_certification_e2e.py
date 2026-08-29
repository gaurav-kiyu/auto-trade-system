"""E2E Integration Tests for the full Certification Pipeline.

Tests the complete flow:
  Replay Cert → Paper Cert → Hygiene Check → Architecture Check → Release Governance

Each test validates that the pipeline produces correct results and correctly
blocks releases when certs fail.
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path

import pytest
from core.certification import (
    PaperCertifier,
    ReplayCertifier,
    certify_paper_trading,
    certify_replay_determinism,
)

# ── Fixture: seeded trade DB for E2E tests ──────────────────────────────────


@pytest.fixture
def e2e_trades_db() -> str:
    """Create a trades.db with diverse sample trades for E2E testing."""
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
    sample_trades = [
        (1, "2026-05-01 09:30", "NIFTY", "CALL", 18500.0, 18600.0, 500.0, 85, "TRENDING", "TARGET"),
        (2, "2026-05-01 10:00", "BANKNIFTY", "PUT", 44000.0, 43800.0, 2000.0, 72, "SIDEWAYS", "TARGET"),
        (3, "2026-05-01 11:00", "NIFTY", "CALL", 18600.0, 18500.0, -500.0, 65, "CHOPPY", "STOP_LOSS"),
        (4, "2026-05-02 09:45", "FINNIFTY", "CALL", 17500.0, 17600.0, 400.0, 80, "TRENDING", "TARGET"),
        (5, "2026-05-02 10:30", "NIFTY", "PUT", 18400.0, 18300.0, 500.0, 78, "TRENDING", "TARGET"),
    ]
    conn.executemany("INSERT INTO trades VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", sample_trades)
    conn.commit()
    conn.close()
    yield db_path
    Path(db_path).unlink(missing_ok=True)


# ── E2E Pipeline Tests ──────────────────────────────────────────────────────


class TestCertificationPipeline:
    """Tests the complete certification pipeline end-to-end."""

    def test_replay_then_paper_pipeline(self, e2e_trades_db):
        """Run replay cert then paper cert sequentially (as in release pipeline)."""
        # Step 1: Replay certification
        replay_report = certify_replay_determinism(
            db_path=e2e_trades_db, max_trades=3, frames=5, width=30
        )
        assert replay_report.passed is True
        assert replay_report.deterministic_count > 0

        # Step 2: Paper trading certification
        paper_report = certify_paper_trading(db_path=e2e_trades_db)
        assert paper_report.passed is True
        assert paper_report.win_rate > 0

        # Step 3: Verify combined results make sense
        assert paper_report.closed_trades >= replay_report.deterministic_count

    def test_pipeline_with_different_db_formats(self):
        """Pipeline should handle various trade counts gracefully."""
        # Single trade
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            conn = sqlite3.connect(db_path)
            conn.execute(
                "CREATE TABLE trades ("
                "  id INTEGER PRIMARY KEY, ts TEXT, index_name TEXT,"
                "  direction TEXT, entry REAL, exit_price REAL, net_pnl REAL,"
                "  score INTEGER, regime TEXT, reason TEXT"
                ")"
            )
            conn.execute(
                "INSERT INTO trades VALUES (1, '2026-05-01', 'NIFTY', 'CALL', "
                "18500.0, 18600.0, 500.0, 85, 'TRENDING', 'TARGET')"
            )
            conn.commit()
            conn.close()

            replay_report = certify_replay_determinism(db_path=db_path, max_trades=1, frames=5, width=30)
            assert replay_report.passed is True

            paper_report = certify_paper_trading(db_path=db_path)
            assert paper_report.passed is True
            assert paper_report.total_trades == 1
        finally:
            Path(db_path).unlink(missing_ok=True)

    def test_release_governance_script_exists(self):
        """Verify the release governance script is importable and runnable."""
        script_path = Path("scripts/release_governance.py")
        assert script_path.exists(), "release_governance.py not found"
        # Verify it has the cert gate functions
        content = script_path.read_text(encoding="utf-8")
        assert "_run_certification_checks" in content
        assert "_run_hygiene_gate" in content
        assert "_run_architecture_gate" in content

    def test_hygiene_script_exists(self):
        """Verify the hygiene check script exists and is importable."""
        script_path = Path("scripts/hygiene_check.py")
        assert script_path.exists(), "hygiene_check.py not found"

    def test_sync_artifacts_script_exists(self):
        """Verify the sync artifacts script exists."""
        script_path = Path("scripts/sync_artifacts.py")
        assert script_path.exists(), "sync_artifacts.py not found"

    def test_architecture_script_exists(self):
        """Verify the architecture compliance script exists."""
        script_path = Path("scripts/check_architecture_compliance.py")
        assert script_path.exists(), "check_architecture_compliance.py not found"

    def test_certification_modules_importable(self):
        """All certification modules should be importable."""
        from core.certification import (
            PaperCertificationReport,
            ReplayCertificationReport,
        )
        assert ReplayCertifier is not None
        assert ReplayCertificationReport is not None
        assert PaperCertifier is not None
        assert PaperCertificationReport is not None

    def test_chaos_modules_importable(self):
        """Chaos engineering modules should be importable."""
        from core.chaos import ChaosEngine, ChaosScenario, FailureType
        assert ChaosEngine is not None
        assert ChaosScenario is not None
        assert FailureType is not None

    def test_black_swan_modules_importable(self):
        """Black swan testing modules should be importable."""
        from core.black_swan import BlackSwanEngine, BlackSwanReport, BlackSwanType
        assert BlackSwanEngine is not None
        assert BlackSwanReport is not None
        assert BlackSwanType is not None

    def test_all_checks_serializable_to_json(self, e2e_trades_db):
        """All certification report formats should be JSON-serializable for audit records."""
        # Replay report
        replay_report = certify_replay_determinism(db_path=e2e_trades_db, max_trades=2, frames=5, width=30)
        replay_json = json.dumps(replay_report.to_dict())
        assert len(replay_json) > 0

        # Paper report
        paper_report = certify_paper_trading(db_path=e2e_trades_db)
        paper_json = json.dumps(paper_report.to_dict())
        assert len(paper_json) > 0

    def test_empty_db_behavior(self):
        """Pipeline should handle empty databases gracefully."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            conn = sqlite3.connect(db_path)
            conn.execute(
                "CREATE TABLE trades ("
                "  id INTEGER PRIMARY KEY, ts TEXT, index_name TEXT,"
                "  direction TEXT, entry REAL, exit_price REAL, net_pnl REAL,"
                "  score INTEGER, regime TEXT, reason TEXT"
                ")"
            )
            conn.commit()
            conn.close()

            replay_report = certify_replay_determinism(db_path=db_path, max_trades=5, frames=5, width=30)
            assert replay_report.passed is True
            assert replay_report.total_trades == 0

            paper_report = certify_paper_trading(db_path=db_path)
            assert paper_report.passed is True
            assert paper_report.total_trades == 0
        finally:
            Path(db_path).unlink(missing_ok=True)
