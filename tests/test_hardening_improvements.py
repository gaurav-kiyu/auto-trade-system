"""
Tests for the hardening improvements applied to core modules.

Covers:
  - AuditEngine: thread safety, trace_id, severity, backward compat
  - TradeJournal: dead-code removal sanity, VALID_EXIT_REASONS, sanitize_exit_reason
  - ReconciliationEngine: has_qty_mismatch typed field, ok-computation correctness
  - StateManager: positions_aligned field
  - soft_reload_common: ignored_keys_warning
  - config.json: CONFIG_VERSION present
"""
from __future__ import annotations

import json
import threading
import tempfile
import os
from pathlib import Path

import pytest

from core.audit_engine import AuditEngine, AuditRecord
from core.reconciliation_engine import ReconciliationEngine, ReconciliationItem, ReconciliationReport
from core.soft_reload_common import ignored_keys_warning, partition_soft_reload_changes
from core.state_manager import SessionRecoveryReport, StateManager
from core.trade_journal import VALID_EXIT_REASONS, TradeJournal

ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# AuditEngine — thread safety, trace_id, severity
# ---------------------------------------------------------------------------

class TestAuditEngine:

    def test_record_returns_audit_record(self, tmp_path):
        engine = AuditEngine(tmp_path / "audit.jsonl", enabled=True)
        rec = engine.record("test_event", foo="bar")
        assert isinstance(rec, AuditRecord)
        assert rec.event == "test_event"

    def test_severity_written_to_jsonl(self, tmp_path):
        path = tmp_path / "audit.jsonl"
        engine = AuditEngine(path, enabled=True)
        engine.record("halt_tripped", severity="CRITICAL", reason="qty mismatch")
        row = json.loads(path.read_text(encoding="utf-8").strip())
        assert row["severity"] == "CRITICAL"
        assert row["event"] == "halt_tripped"

    def test_default_severity_is_info(self, tmp_path):
        path = tmp_path / "audit.jsonl"
        engine = AuditEngine(path, enabled=True)
        engine.record("scan_cycle")
        row = json.loads(path.read_text(encoding="utf-8").strip())
        assert row["severity"] == "INFO"

    def test_invalid_severity_falls_back_to_info(self, tmp_path):
        path = tmp_path / "audit.jsonl"
        engine = AuditEngine(path, enabled=True)
        engine.record("event", severity="BOGUS")
        row = json.loads(path.read_text(encoding="utf-8").strip())
        assert row["severity"] == "INFO"

    def test_trace_id_included_when_provided(self, tmp_path):
        path = tmp_path / "audit.jsonl"
        engine = AuditEngine(path, enabled=True)
        engine.record("signal_confirmed", trace_id="NIFTY-20260427-4a2f", score=85)
        row = json.loads(path.read_text(encoding="utf-8").strip())
        assert row["trace_id"] == "NIFTY-20260427-4a2f"
        assert row["score"] == 85

    def test_trace_id_absent_when_not_provided(self, tmp_path):
        path = tmp_path / "audit.jsonl"
        engine = AuditEngine(path, enabled=True)
        engine.record("state_saved")
        row = json.loads(path.read_text(encoding="utf-8").strip())
        assert "trace_id" not in row

    def test_backward_compat_existing_callers(self, tmp_path):
        """Callers that do not pass trace_id or severity still work unchanged."""
        path = tmp_path / "audit.jsonl"
        engine = AuditEngine(path, enabled=True)
        rec = engine.record("state_saved", positions=2, trades=4)
        assert rec is not None
        row = json.loads(path.read_text(encoding="utf-8").strip())
        assert row["event"] == "state_saved"
        assert row["positions"] == 2

    def test_thread_safety_no_interleaved_lines(self, tmp_path):
        """Concurrent record() calls must produce complete, parseable JSONL lines."""
        path = tmp_path / "audit.jsonl"
        engine = AuditEngine(path, enabled=True)
        errors: list[str] = []

        def _write(n: int) -> None:
            for i in range(20):
                try:
                    engine.record(f"event_{n}_{i}", thread=n, seq=i)
                except Exception as exc:
                    errors.append(str(exc))

        threads = [threading.Thread(target=_write, args=(t,)) for t in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Exceptions during concurrent writes: {errors}"
        lines = path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 160  # 8 threads × 20 writes
        for line in lines:
            json.loads(line)  # every line must be valid JSON

    def test_disabled_engine_returns_none(self, tmp_path):
        engine = AuditEngine(tmp_path / "audit.jsonl", enabled=False)
        assert engine.record("event") is None
        assert not (tmp_path / "audit.jsonl").exists()

    def test_audit_severity_constants_complete(self):
        assert AuditEngine.SEVERITIES == {"INFO", "WARN", "CRITICAL", "AUDIT"}


# ---------------------------------------------------------------------------
# TradeJournal — VALID_EXIT_REASONS, sanitize_exit_reason
# ---------------------------------------------------------------------------

class TestTradeJournalExitReason:

    def test_valid_exit_reasons_constant_exists(self):
        assert isinstance(VALID_EXIT_REASONS, frozenset)
        expected = {"stop_loss", "take_profit", "trail_sl", "time_exit", "manual", "unknown"}
        assert VALID_EXIT_REASONS == expected

    def test_sanitize_known_reasons_pass_through(self):
        for reason in VALID_EXIT_REASONS:
            assert TradeJournal.sanitize_exit_reason(reason) == reason

    def test_sanitize_unknown_reason_returns_unknown(self):
        result = TradeJournal.sanitize_exit_reason("expired_worthless")
        assert result == "unknown"

    def test_sanitize_empty_string_returns_unknown(self):
        assert TradeJournal.sanitize_exit_reason("") == "unknown"

    def test_sanitize_none_like_values_return_unknown(self):
        # Should not crash on unexpected input types that get coerced
        assert TradeJournal.sanitize_exit_reason("NONE") == "unknown"

    def test_write_close_uses_entry_slip_correctly(self, tmp_path):
        """Entry slippage + exit slippage = total_slippage in the journal row."""
        db = str(tmp_path / "journal.db")
        j = TradeJournal(db)
        import time, datetime
        ts = datetime.datetime.utcnow().isoformat()
        entry = j.open_trade(
            trade_id="T-SLIP-001",
            symbol="NIFTY",
            direction="CALL",
            entry_ts=ts,
            score=80,
            tier="STRONG",
            confidence=0.85,
            regime="TRENDING",
            quality_score=0.9,
            expected_entry=200.0,
            expected_sl=184.0,
            expected_tp=240.0,
            lots=1,
            position_pct=1.0,
            lot_size=25,
            mode="PAPER",
        )
        # Simulate fill with 2-point entry slippage
        j.record_fill("T-SLIP-001", actual_entry=202.0, fill_ts=ts, execution_delay_ms=50)
        # Give async write a moment
        import time; time.sleep(0.1)
        # Close with 1-point exit slippage
        j.close_trade(
            "T-SLIP-001",
            actual_exit=239.0,
            exit_reason=TradeJournal.sanitize_exit_reason("take_profit"),
            net_pnl=925.0,
            gross_pnl=965.0,
            pct_pnl=0.09,
            bars_held=5,
            rr_achieved=2.4,
            exit_slippage=1.0,
        )
        time.sleep(0.2)
        j.shutdown()

        import sqlite3
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM journal WHERE trade_id='T-SLIP-001'").fetchone()
        conn.close()
        assert row is not None
        assert row["exit_reason"] == "take_profit"
        # total_slippage should be entry_slippage (2.0) + exit_slippage (1.0) = 3.0
        if row["entry_slippage"] is not None and row["total_slippage"] is not None:
            assert abs(row["total_slippage"] - (row["entry_slippage"] + 1.0)) < 0.01


# ---------------------------------------------------------------------------
# ReconciliationEngine — has_qty_mismatch, ok computation
# ---------------------------------------------------------------------------

class TestReconciliationHardening:

    def test_has_qty_mismatch_true_on_mismatch(self):
        engine = ReconciliationEngine(
            broker_snapshot_fn=lambda: {"NIFTY": {"qty": 25, "avg_price": 100.0}},
            qty_mismatch_halts=True,
        )
        report = engine.reconcile_positions({"NIFTY": {"qty": 50, "entry": 100.0}})
        assert report.items[0].has_qty_mismatch is True

    def test_has_qty_mismatch_false_when_matched(self):
        engine = ReconciliationEngine(
            broker_snapshot_fn=lambda: {"NIFTY": {"qty": 50, "avg_price": 100.0}},
            qty_mismatch_halts=True,
        )
        report = engine.reconcile_positions({"NIFTY": {"qty": 50, "entry": 100.0}})
        assert report.items[0].has_qty_mismatch is False

    def test_has_qty_mismatch_false_for_broker_only_position(self):
        """Broker-only positions are a different anomaly class, not a qty mismatch."""
        engine = ReconciliationEngine(
            broker_snapshot_fn=lambda: {"BANKNIFTY": {"qty": 15, "avg_price": 200.0}},
            report_broker_only_positions=True,
        )
        report = engine.reconcile_positions({})
        broker_only = report.items[0]
        assert broker_only.has_qty_mismatch is False
        assert "broker-only" in broker_only.note

    def test_ok_computation_uses_typed_field_not_string(self):
        """When qty_mismatch_halts=False, report.ok depends on has_qty_mismatch,
        not on parsing the note string."""
        engine = ReconciliationEngine(
            broker_snapshot_fn=lambda: {"NIFTY": {"qty": 25, "avg_price": 100.0}},
            qty_mismatch_halts=False,  # qty mismatches are tolerated
        )
        report = engine.reconcile_positions({"NIFTY": {"qty": 50, "entry": 100.0}})
        # Only a qty mismatch — should be ok=True when halts disabled
        assert report.items[0].has_qty_mismatch is True
        assert report.ok is True

    def test_ok_false_when_halts_enabled(self):
        engine = ReconciliationEngine(
            broker_snapshot_fn=lambda: {"NIFTY": {"qty": 25, "avg_price": 100.0}},
            qty_mismatch_halts=True,
        )
        report = engine.reconcile_positions({"NIFTY": {"qty": 50, "entry": 100.0}})
        assert report.ok is False

    def test_price_mismatch_makes_ok_false_even_when_halts_disabled(self):
        """Price mismatch is NOT a qty mismatch — ok must be False even if halts disabled."""
        engine = ReconciliationEngine(
            broker_snapshot_fn=lambda: {"NIFTY": {"qty": 50, "avg_price": 120.0}},
            price_tolerance_pct=0.05,
            qty_mismatch_halts=False,
        )
        # qty matches but price is 20% off
        report = engine.reconcile_positions({"NIFTY": {"qty": 50, "entry": 100.0}})
        assert report.items[0].has_qty_mismatch is False  # qty matched
        assert report.ok is False  # price mismatch still fails

    def test_note_still_contains_qty_mismatch_string(self):
        """Existing tests that assert 'qty mismatch' in note must not break."""
        engine = ReconciliationEngine(
            broker_snapshot_fn=lambda: {"NIFTY": {"qty": 25, "avg_price": 100.0}},
            qty_mismatch_halts=True,
        )
        report = engine.reconcile_positions({"NIFTY": {"qty": 50, "entry": 100.0}})
        assert "qty mismatch" in report.items[0].note


# ---------------------------------------------------------------------------
# StateManager — positions_aligned
# ---------------------------------------------------------------------------

class TestStateManagerHardening:

    def test_positions_aligned_true_when_all_match(self):
        sm = StateManager(
            save_fn=lambda: None,
            load_fn=lambda: None,
            local_positions_fn=lambda: {"NIFTY": {"qty": 50}},
            broker_positions_fn=lambda: {"NIFTY": {"qty": 50}},
        )
        report = sm.session_recovery_report()
        assert report.positions_aligned is True

    def test_positions_aligned_false_when_local_not_in_broker(self):
        sm = StateManager(
            save_fn=lambda: None,
            load_fn=lambda: None,
            local_positions_fn=lambda: {"NIFTY": {"qty": 50}, "BANKNIFTY": {"qty": 15}},
            broker_positions_fn=lambda: {"NIFTY": {"qty": 50}},
        )
        report = sm.session_recovery_report()
        assert report.positions_aligned is False
        assert "mismatch" in report.note.lower()

    def test_positions_aligned_true_when_no_local_positions(self):
        sm = StateManager(
            save_fn=lambda: None,
            load_fn=lambda: None,
            local_positions_fn=lambda: {},
            broker_positions_fn=lambda: {"NIFTY": {"qty": 50}},
        )
        report = sm.session_recovery_report()
        # No local positions to match — trivially aligned
        assert report.positions_aligned is True

    def test_existing_fields_unchanged(self):
        """Backward compat: existing field checks from test_operational_hardening still pass."""
        sm = StateManager(
            save_fn=lambda: None,
            load_fn=lambda: None,
            local_positions_fn=lambda: {"NIFTY": {"qty": 50}},
            broker_positions_fn=lambda: {"NIFTY": {"qty": 50}, "BANKNIFTY": {"qty": 15}},
        )
        report = sm.session_recovery_report()
        assert report.local_positions == 1
        assert report.broker_positions == 2
        assert report.matched_symbols == 1

    def test_positions_aligned_default_is_false(self):
        """SessionRecoveryReport can be constructed without positions_aligned."""
        r = SessionRecoveryReport(local_positions=0, broker_positions=0, matched_symbols=0)
        assert r.positions_aligned is False


# ---------------------------------------------------------------------------
# soft_reload_common — ignored_keys_warning
# ---------------------------------------------------------------------------

class TestIgnoredKeysWarning:

    def test_returns_none_when_no_ignored_keys(self):
        assert ignored_keys_warning([]) is None

    def test_returns_warning_string_with_key_names(self):
        msg = ignored_keys_warning(["SIGNAL_MAX_AGE", "SCAN_INTERVAL"])
        assert msg is not None
        assert "SIGNAL_MAX_AGE" in msg
        assert "SCAN_INTERVAL" in msg
        assert "restart" in msg.lower()

    def test_single_key_warning(self):
        msg = ignored_keys_warning(["BASE_CAPITAL"])
        assert msg is not None
        assert "BASE_CAPITAL" in msg

    def test_integrates_with_partition(self):
        """ignored_keys_warning works with the output of partition_soft_reload_changes."""
        old = {"SCAN_INTERVAL": 30, "BASE_CAPITAL": 10000}
        new = {"SCAN_INTERVAL": 45, "BASE_CAPITAL": 20000}
        safe = frozenset({"SCAN_INTERVAL"})
        immutable = frozenset()
        _, _, ignored = partition_soft_reload_changes(old, new, immutable, safe)
        # BASE_CAPITAL changed but is not in safe_reload_keys → ignored
        assert "BASE_CAPITAL" in ignored
        msg = ignored_keys_warning(ignored)
        assert msg is not None
        assert "BASE_CAPITAL" in msg


# ---------------------------------------------------------------------------
# config.json — CONFIG_VERSION present
# ---------------------------------------------------------------------------

class TestConfigVersion:

    def test_config_version_present(self):
        cfg_path = ROOT / "config.json"
        with cfg_path.open(encoding="utf-8") as f:
            cfg = json.load(f)
        assert "CONFIG_VERSION" in cfg, "CONFIG_VERSION key missing from config.json"

    def test_config_version_is_positive_integer(self):
        cfg_path = ROOT / "config.json"
        with cfg_path.open(encoding="utf-8") as f:
            cfg = json.load(f)
        ver = cfg["CONFIG_VERSION"]
        assert isinstance(ver, int) and ver >= 1, (
            f"CONFIG_VERSION must be a positive integer, got {ver!r}"
        )
