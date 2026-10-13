"""Focused Test Suite for Observation Storage DB Isolation (OPB v2.61 — G9-SQ-OA6).

Validates the complete test contract required by Section 10 of G9-SQ-OA6 prompt:
- Test A: Default behavior (canonical/default DB contract preserved when no override is set)
- Test B: Explicit DB override (--db-path / db_path parameter selects isolated DB)
- Test C: Environment override (SIGNALS_DB_PATH selects isolated DB)
- Test D: Precedence (explicit argument > SIGNALS_DB_PATH > default)
- Test E: SignalTracker propagation
- Test F: SignalOutcomeTracker propagation
- Test G: AllNSEScanner and daemon propagation
- Test H: Test record persistence in isolated DB
- Test I: Canonical DB immutability & protection verification
- Test J: Process-level daemon isolation with --db-path CLI argument
- Test K: Multi-cycle execution (at least 3 cycles against isolated DB)
- Test L: Clean termination with no orphaned resources
"""

from __future__ import annotations

import hashlib
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from core.all_nse_scanner import AllNSEScanner
from core.signals.signal_outcome_tracker import SignalOutcomeTracker
from core.signals.signal_tracker import SignalTracker

_CANONICAL_DB_PATH = Path("db/signals_history.db").resolve()


def _get_canonical_db_state() -> tuple[int, str]:
    if not _CANONICAL_DB_PATH.exists():
        return 0, ""
    data = _CANONICAL_DB_PATH.read_bytes()
    return len(data), hashlib.sha256(data).hexdigest()


@pytest.fixture(autouse=True)
def _clean_isolation_environment(monkeypatch):
    """Ensure clean singletons and clean environment before and after every test."""
    monkeypatch.delenv("SIGNALS_DB_PATH", raising=False)
    SignalTracker.reset_instance()
    SignalOutcomeTracker.reset_instance()
    yield
    monkeypatch.delenv("SIGNALS_DB_PATH", raising=False)
    SignalTracker.reset_instance()
    SignalOutcomeTracker.reset_instance()


class TestObservationDBIsolation:
    def test_a_default_behavior(self):
        """Test A: Without override, application preserves existing default DB contract."""
        from core.signals.signal_outcome_tracker import _DEFAULT_DB_PATH, resolve_outcome_db_path
        from core.signals.signal_tracker import _DB_PATH, resolve_signals_db_path
        assert resolve_signals_db_path() == _CANONICAL_DB_PATH
        assert resolve_outcome_db_path() == _CANONICAL_DB_PATH
        assert _DB_PATH.resolve() == _CANONICAL_DB_PATH
        assert _DEFAULT_DB_PATH.resolve() == _CANONICAL_DB_PATH

    def test_b_explicit_db_override(self, tmp_path):
        """Test B: Explicit db_path override routes directly to the isolated DB."""
        isolated_db = (tmp_path / "isolated_b.db").resolve()
        tracker = SignalTracker.get_instance(db_path=isolated_db)
        assert tracker._db_path.resolve() == isolated_db
        outcome_tracker = SignalOutcomeTracker.get_instance(db_path=isolated_db)
        assert outcome_tracker._db_path.resolve() == isolated_db
        assert isolated_db.exists()

    def test_c_environment_override(self, tmp_path, monkeypatch):
        """Test C: SIGNALS_DB_PATH environment variable selects isolated DB."""
        isolated_db = (tmp_path / "isolated_c.db").resolve()
        monkeypatch.setenv("SIGNALS_DB_PATH", str(isolated_db))
        tracker = SignalTracker.get_instance()
        assert tracker._db_path.resolve() == isolated_db
        outcome_tracker = SignalOutcomeTracker.get_instance()
        assert outcome_tracker._db_path.resolve() == isolated_db
        assert isolated_db.exists()

    def test_d_precedence_hierarchy(self, tmp_path, monkeypatch):
        """Test D: Explicit argument takes strict precedence over SIGNALS_DB_PATH."""
        env_db = (tmp_path / "env_db.db").resolve()
        arg_db = (tmp_path / "arg_db.db").resolve()
        monkeypatch.setenv("SIGNALS_DB_PATH", str(env_db))

        # Explicit arg wins over env var
        tracker = SignalTracker.get_instance(db_path=arg_db)
        assert tracker._db_path.resolve() == arg_db

        outcome_tracker = SignalOutcomeTracker.get_instance(db_path=arg_db)
        assert outcome_tracker._db_path.resolve() == arg_db

    def test_e_tracker_propagation(self, tmp_path):
        """Test E: SignalTracker singleton preserves isolated path across repeated calls."""
        isolated_db = (tmp_path / "isolated_e.db").resolve()
        tracker1 = SignalTracker.get_instance(db_path=isolated_db)
        tracker2 = SignalTracker.get_instance()
        assert tracker1 is tracker2
        assert tracker2._db_path.resolve() == isolated_db

    def test_f_outcome_tracker_propagation(self, tmp_path):
        """Test F: SignalOutcomeTracker preserves isolated path when called without args."""
        isolated_db = (tmp_path / "isolated_f.db").resolve()
        out1 = SignalOutcomeTracker.get_instance(db_path=isolated_db)
        out2 = SignalOutcomeTracker.get_instance()
        assert out1 is out2
        assert out2._db_path.resolve() == isolated_db

    def test_g_scanner_propagation(self, tmp_path):
        """Test G: AllNSEScanner passes isolated db_path to singletons."""
        isolated_db = (tmp_path / "isolated_g.db").resolve()
        scanner = AllNSEScanner(cfg={"SCANNER_FORCE_RUN": True, "ALLOW_AFTER_HOURS_SCANNING": True}, db_path=isolated_db)
        assert scanner._db_path == isolated_db
        assert SignalTracker.get_instance()._db_path.resolve() == isolated_db
        assert SignalOutcomeTracker.get_instance()._db_path.resolve() == isolated_db

    def test_h_isolated_persistence(self, tmp_path):
        """Test H: Records persist strictly to isolated DB and not to canonical DB."""
        pre_size, pre_hash = _get_canonical_db_state()
        isolated_db = (tmp_path / "isolated_h.db").resolve()

        tracker = SignalTracker.get_instance(db_path=isolated_db)
        sig_id = tracker.record_generated_signal({
            "symbol": "TEST_ISOLATION_SYM",
            "company_name": "Test Company",
            "series": "EQ",
            "direction": "BUY",
            "price": 100.0,
            "score": 90,
            "raw_score": 90,
            "normalized_score": 90,
            "score_saturated": False,
            "tier": "STRONG",
            "category": "LARGE_CAP",
            "regime": "BULLISH",
            "timeframe": "15m",
            "strategy": "MOMENTUM",
        })
        assert sig_id is not None

        # Verify record exists in isolated DB
        conn = sqlite3.connect(str(isolated_db))
        row = conn.execute("SELECT symbol, direction FROM system_signals WHERE signal_id = ?", (sig_id,)).fetchone()
        conn.close()
        assert row is not None
        assert row[0] == "TEST_ISOLATION_SYM"

        # Verify canonical DB was NOT touched
        post_size, post_hash = _get_canonical_db_state()
        assert post_size == pre_size
        assert post_hash == pre_hash

    def test_i_canonical_db_protection(self, tmp_path):
        """Test I: Canonical DB remains 100% bit-identical throughout operations."""
        pre_size, pre_hash = _get_canonical_db_state()

        isolated_db = (tmp_path / "isolated_i.db").resolve()
        scanner = AllNSEScanner(cfg={"SCANNER_FORCE_RUN": True, "ALLOW_AFTER_HOURS_SCANNING": True}, db_path=isolated_db)
        scanner._cfg["ALLOW_AFTER_HOURS_SCANNING"] = True
        scanner.scan_universe(symbols_limit=5, send_alerts=False)

        post_size, post_hash = _get_canonical_db_state()
        assert post_size == pre_size
        assert post_hash == pre_hash

    def test_j_process_cli_isolation(self, tmp_path):
        """Test J: Process-level daemon execution with --db-path routes to isolated DB."""
        pre_size, pre_hash = _get_canonical_db_state()
        isolated_db = (tmp_path / "process_cli.db").resolve()

        # Run 1 quick scan iteration via CLI
        code = f"""
import sys
sys.path.insert(0, ".")
from core.market_scanner_daemon import AllNSEScanner
scanner = AllNSEScanner(cfg={{"SCANNER_FORCE_RUN": True, "ALLOW_AFTER_HOURS_SCANNING": True}}, db_path=r"{isolated_db}")
scanner._cfg["ALLOW_AFTER_HOURS_SCANNING"] = True
signals = scanner.scan_universe(symbols_limit=10, send_alerts=False)
print(f"COMPLETE: {{len(signals)}}")
"""
        cmd = [sys.executable, "-c", code]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        assert proc.returncode == 0
        assert "COMPLETE:" in proc.stdout

        # Verify isolated DB exists and has tables
        assert isolated_db.exists()
        conn = sqlite3.connect(str(isolated_db))
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        conn.close()
        assert "system_signals" in tables
        assert "scan_cycle_metrics" in tables

        # Verify canonical DB remains untouched
        post_size, post_hash = _get_canonical_db_state()
        assert post_size == pre_size
        assert post_hash == pre_hash

    def test_k_multi_cycle_execution(self, tmp_path):
        """Test K: Execute at least 3 consecutive cycles using isolated DB."""
        pre_size, pre_hash = _get_canonical_db_state()
        isolated_db = (tmp_path / "multi_cycle.db").resolve()

        scanner = AllNSEScanner(cfg={"SCANNER_FORCE_RUN": True, "ALLOW_AFTER_HOURS_SCANNING": True}, db_path=isolated_db)
        scanner._cfg["ALLOW_AFTER_HOURS_SCANNING"] = True
        for cycle in range(1, 4):
            signals = scanner.scan_universe(symbols_limit=10, send_alerts=False)
            assert isinstance(signals, list)

        # Verify scan cycle metrics recorded in isolated DB
        conn = sqlite3.connect(str(isolated_db))
        cycles = conn.execute("SELECT count(*) FROM scan_cycle_metrics").fetchone()[0]
        conn.close()
        assert cycles == 3

        # Verify canonical DB remains untouched
        post_size, post_hash = _get_canonical_db_state()
        assert post_size == pre_size
        assert post_hash == pre_hash

    def test_l_clean_termination(self, tmp_path):
        """Test L: Clean resource deallocation and shutdown."""
        isolated_db = (tmp_path / "clean_term.db").resolve()
        scanner = AllNSEScanner(cfg={"SCANNER_FORCE_RUN": True, "ALLOW_AFTER_HOURS_SCANNING": True}, db_path=isolated_db)
        scanner._cfg["ALLOW_AFTER_HOURS_SCANNING"] = True
        scanner.scan_universe(symbols_limit=5, send_alerts=False)
        SignalTracker.reset_instance()
        SignalOutcomeTracker.reset_instance()
        assert SignalTracker._instance is None
        assert SignalOutcomeTracker._instance is None
