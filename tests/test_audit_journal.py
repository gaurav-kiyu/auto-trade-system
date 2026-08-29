"""
Tests for AuditJournal — immutable, thread-safe event journaling in JSONL format.

Covers:
- AuditEvent/AuditEventType/AuditSeverity dataclasses and enums
- AuditJournal file creation, rotation, and appending
- Convenience methods (log_signal, log_risk_decision, log_order_submitted, etc.)
- Thread safety with concurrent events
- Edge cases (file errors, large payloads)
- Singleton factory (get_audit_journal, audit_log)
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from core.audit_journal import (
    AuditEvent,
    AuditEventType,
    AuditJournal,
    AuditSeverity,
    audit_log,
    get_audit_journal,
)

# ── Enums ──────────────────────────────────────────────────────────────────


class TestAuditEventType:
    def test_values(self):
        assert AuditEventType.SIGNAL_GENERATED.value == "SIGNAL_GENERATED"
        assert AuditEventType.HARD_HALT.value == "HARD_HALT"
        assert AuditEventType.CONFIG_CHANGE.value == "CONFIG_CHANGE"

    def test_all_types_present(self):
        expected = {
            "SIGNAL_GENERATED", "RISK_DECISION", "ORDER_SUBMITTED",
            "ORDER_ACKNOWLEDGED", "ORDER_FILLED", "ORDER_CANCELLED",
            "ORDER_REJECTED", "ORDER_RECONCILED", "POSITION_OPENED",
            "POSITION_CLOSED", "POSITION_RECONCILED", "SYSTEM_MODE_CHANGE",
            "HARD_HALT", "RECONCILIATION_MISMATCH", "BROKER_DISCONNECT",
            "BROKER_RECONNECT", "RISK_BREACH", "CIRCUIT_BREAKER",
            "STALE_QUOTE", "INVALID_PRICE", "DB_WRITE_FAIL", "CONFIG_CHANGE",
        }
        actual = {e.value for e in AuditEventType}
        assert actual == expected


class TestAuditSeverity:
    def test_values(self):
        assert AuditSeverity.DEBUG.value == "DEBUG"
        assert AuditSeverity.CRITICAL.value == "CRITICAL"

    def test_severity_levels_defined(self):
        """All expected severity levels exist."""
        expected = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        actual = {e.value for e in AuditSeverity}
        assert actual == expected


# ── AuditEvent Dataclass ──────────────────────────────────────────────────


class TestAuditEvent:
    def test_creation(self):
        event = AuditEvent(
            event_id="evt_001",
            timestamp="2024-01-01T00:00:00",
            event_type="ORDER_FILLED",
            severity="INFO",
            message="Order filled",
            correlation_id="corr_001",
        )
        assert event.event_id == "evt_001"
        assert event.message == "Order filled"
        assert event.details == {}

    def test_to_dict(self):
        event = AuditEvent(
            event_id="evt_001",
            timestamp="2024-01-01T00:00:00",
            event_type="ORDER_FILLED",
            severity="INFO",
            message="Test",
            details={"price": 150.0},
        )
        d = event.to_dict()
        assert d["event_id"] == "evt_001"
        assert d["details"] == {"price": 150.0}
        assert d["stack_trace"] == ""


# ── AuditJournal ───────────────────────────────────────────────────────────


class TestAuditJournal:
    @pytest.fixture
    def journal(self, tmp_path: Path) -> AuditJournal:
        return AuditJournal(log_dir=str(tmp_path), retain_days=1)

    def test_creates_log_dir(self, tmp_path: Path):
        path = tmp_path / "audit_logs"
        assert not path.exists()
        AuditJournal(log_dir=str(path))
        assert path.exists()

    def test_log_event_returns_event_id(self, journal: AuditJournal):
        event_id = journal.log_event(
            event_type=AuditEventType.ORDER_SUBMITTED,
            severity=AuditSeverity.INFO,
            message="Order submitted",
        )
        assert isinstance(event_id, str)
        assert len(event_id) > 0

    def test_log_event_writes_to_file(self, journal: AuditJournal):
        journal.log_event(
            event_type=AuditEventType.ORDER_FILLED,
            severity=AuditSeverity.INFO,
            message="Fill at 150.0",
            symbol="NIFTY",
        )
        files = list(journal._log_dir.glob("audit_*.jsonl"))
        assert len(files) == 1
        content = files[0].read_text(encoding="utf-8")
        data = json.loads(content)
        assert data["event_type"] == "ORDER_FILLED"
        assert data["symbol"] == "NIFTY"
        assert data["message"] == "Fill at 150.0"

    def test_log_event_with_details(self, journal: AuditJournal):
        journal.log_event(
            event_type=AuditEventType.RISK_BREACH,
            severity=AuditSeverity.CRITICAL,
            message="Risk breach",
            details={"breach_type": "max_daily_loss", "amount": -5000},
        )
        data = json.loads(journal._current_file.read_text(encoding="utf-8"))
        assert data["details"]["breach_type"] == "max_daily_loss"

    def test_log_event_with_trace_ids(self, journal: AuditJournal):
        journal.log_event(
            event_type=AuditEventType.ORDER_FILLED,
            severity=AuditSeverity.INFO,
            message="Fill",
            correlation_id="corr_abc",
            intent_id="intent_xyz",
        )
        data = json.loads(journal._current_file.read_text(encoding="utf-8"))
        assert data.get("correlation_id") == "corr_abc"
        assert data.get("intent_id") == "intent_xyz"

    def test_append_multiple_events(self, journal: AuditJournal):
        for i in range(5):
            journal.log_event(
                event_type=AuditEventType.SIGNAL_GENERATED,
                severity=AuditSeverity.INFO,
                message=f"Signal {i}",
            )
        lines = journal._current_file.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 5


# ── Convenience Methods ────────────────────────────────────────────────────


class TestConvenienceMethods:
    @pytest.fixture
    def journal(self, tmp_path: Path) -> AuditJournal:
        return AuditJournal(log_dir=str(tmp_path), retain_days=1)

    def test_log_signal(self, journal: AuditJournal):
        event_id = journal.log_signal(
            {"symbol": "NIFTY", "direction": "BUY", "strength": "STRONG"},
            correlation_id="corr_001",
        )
        assert event_id
        data = json.loads(journal._current_file.read_text(encoding="utf-8"))
        assert data["event_type"] == "SIGNAL_GENERATED"
        assert data["severity"] == "INFO"

    def test_log_risk_decision_allowed(self, journal: AuditJournal):
        journal.log_risk_decision(
            decision="ENTRY",
            allowed=True,
            reason="Within limits",
            symbol="NIFTY",
        )
        data = json.loads(journal._current_file.read_text(encoding="utf-8"))
        assert data["severity"] == "INFO"
        assert "ALLOWED" in data["message"]

    def test_log_risk_decision_denied(self, journal: AuditJournal):
        journal.log_risk_decision(
            decision="ENTRY",
            allowed=False,
            reason="Max positions reached",
            symbol="BANKNIFTY",
        )
        data = json.loads(journal._current_file.read_text(encoding="utf-8"))
        assert data["severity"] == "WARNING"
        assert "DENIED" in data["message"]

    def test_log_order_submitted(self, journal: AuditJournal):
        journal.log_order_submitted(
            order_data={"symbol": "NIFTY", "direction": "BUY", "qty": 75},
            intent_id="intent_001",
            correlation_id="corr_001",
        )
        data = json.loads(journal._current_file.read_text(encoding="utf-8"))
        assert data["event_type"] == "ORDER_SUBMITTED"

    def test_log_order_filled(self, journal: AuditJournal):
        journal.log_order_filled(
            order_id="ORD123",
            fill_price=150.50,
            filled_qty=75,
            intent_id="intent_001",
            symbol="NIFTY",
        )
        data = json.loads(journal._current_file.read_text(encoding="utf-8"))
        assert data["event_type"] == "ORDER_FILLED"
        assert data["details"]["order_id"] == "ORD123"

    def test_log_reconciliation_mismatch(self, journal: AuditJournal):
        journal.log_reconciliation_mismatch(
            mismatch_type="QUANTITY_MISMATCH",
            details={"expected": 75, "actual": 50},
        )
        data = json.loads(journal._current_file.read_text(encoding="utf-8"))
        assert data["event_type"] == "RECONCILIATION_MISMATCH"
        assert data["severity"] == "ERROR"

    def test_log_hard_halt(self, journal: AuditJournal):
        journal.log_hard_halt(reason="Max drawdown breached", source="RiskService")
        data = json.loads(journal._current_file.read_text(encoding="utf-8"))
        assert data["event_type"] == "HARD_HALT"
        assert data["severity"] == "CRITICAL"
        assert "HARD HALT" in data["message"]

    def test_log_system_mode_change(self, journal: AuditJournal):
        journal.log_system_mode_change(
            old_mode="MANUAL",
            new_mode="AUTO",
            reason="Scheduled start",
        )
        data = json.loads(journal._current_file.read_text(encoding="utf-8"))
        assert data["event_type"] == "SYSTEM_MODE_CHANGE"
        assert data["severity"] == "WARNING"

    def test_log_stale_quote(self, journal: AuditJournal):
        journal.log_stale_quote(symbol="NIFTY", quote_age=5.5)
        data = json.loads(journal._current_file.read_text(encoding="utf-8"))
        assert data["event_type"] == "STALE_QUOTE"
        assert data["details"]["quote_age_seconds"] == 5.5

    def test_log_invalid_price(self, journal: AuditJournal):
        journal.log_invalid_price(symbol="NIFTY", price=999999.0, reason="Outlier")
        data = json.loads(journal._current_file.read_text(encoding="utf-8"))
        assert data["event_type"] == "INVALID_PRICE"
        assert data["details"]["price"] == 999999.0


# ── File Rotation ──────────────────────────────────────────────────────────


class TestFileRotation:
    @pytest.fixture
    def journal(self, tmp_path: Path) -> AuditJournal:
        return AuditJournal(log_dir=str(tmp_path), max_file_size_mb=1, retain_days=1)

    def test_rotates_on_new_day(self, tmp_path: Path, monkeypatch):
        """When date changes, a new file is created."""

        fixed_date = "20240101"
        with patch("core.audit_journal.now_ist") as mock_now:
            mock_now.return_value.strftime.return_value = fixed_date
            journal = AuditJournal(log_dir=str(tmp_path))
            assert fixed_date in str(journal._current_file)

    def test_cleanup_old_files(self, tmp_path: Path):
        """cleanup_old_files removes files older than retain_days."""
        import time
        journal = AuditJournal(log_dir=str(tmp_path), retain_days=1)

        # Create an old file
        old_file = tmp_path / "audit_20200101.jsonl"
        old_file.write_text("{}\n", encoding="utf-8")
        # Set mtime to 10 days ago
        old_mtime = time.time() - (10 * 86400)
        os.utime(old_file, (old_mtime, old_mtime))

        # Create a recent file via journal
        journal.log_event(AuditEventType.CIRCUIT_BREAKER, AuditSeverity.INFO, "test")

        removed = journal.cleanup_old_files()
        assert removed == 1
        assert not old_file.exists()


# ── Thread Safety ──────────────────────────────────────────────────────────


class TestThreadSafety:
    def test_concurrent_log_events(self, tmp_path: Path):
        journal = AuditJournal(log_dir=str(tmp_path))
        n = 50
        errors = []

        def write_events():
            for i in range(n):
                try:
                    journal.log_event(
                        event_type=AuditEventType.SIGNAL_GENERATED,
                        severity=AuditSeverity.INFO,
                        message=f"Event {i}",
                    )
                except Exception as e:
                    errors.append(e)

        t1 = threading.Thread(target=write_events)
        t2 = threading.Thread(target=write_events)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert not errors, f"Thread safety errors: {errors}"
        lines = journal._current_file.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2 * n

    def test_concurrent_different_event_types(self, tmp_path: Path):
        journal = AuditJournal(log_dir=str(tmp_path))
        n = 30
        errors = []

        def write_signals():
            for i in range(n):
                try:
                    journal.log_signal(
                        {"symbol": "NIFTY", "direction": "BUY"},
                        f"corr_{i}",
                    )
                except Exception as e:
                    errors.append(e)

        def write_halts():
            for i in range(n):
                try:
                    journal.log_hard_halt(f"Test halt {i}")
                except Exception as e:
                    errors.append(e)

        t1 = threading.Thread(target=write_signals)
        t2 = threading.Thread(target=write_halts)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert not errors
        lines = journal._current_file.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2 * n


# ── Singleton Factory ──────────────────────────────────────────────────────


class TestSingleton:
    def test_get_audit_journal_returns_instance(self, tmp_path: Path):
        with patch("core.audit_journal._audit_journal", None):
            journal = get_audit_journal({"audit_log_dir": str(tmp_path)})
            assert isinstance(journal, AuditJournal)

    def test_get_audit_journal_singleton(self, tmp_path: Path):
        with patch("core.audit_journal._audit_journal", None):
            j1 = get_audit_journal({"audit_log_dir": str(tmp_path)})
            j2 = get_audit_journal({"audit_log_dir": str(tmp_path)})
            assert j1 is j2

    def test_audit_log_function(self, tmp_path: Path):
        with patch("core.audit_journal._audit_journal", None):
            with patch("core.audit_journal.get_audit_journal") as mock_get:
                mock_journal = MagicMock()
                mock_journal.log_event.return_value = "evt_id"
                mock_get.return_value = mock_journal
                result = audit_log(
                    AuditEventType.CIRCUIT_BREAKER,
                    AuditSeverity.INFO,
                    "Test message",
                )
                assert result == "evt_id"
                mock_journal.log_event.assert_called_once()


# ── Edge Cases ─────────────────────────────────────────────────────────────


class TestEdgeCases:
    @pytest.fixture
    def journal(self, tmp_path: Path) -> AuditJournal:
        return AuditJournal(log_dir=str(tmp_path), retain_days=1)

    def test_file_write_error_fallback(self, tmp_path: Path, monkeypatch):
        """When file write fails, event_id is still returned."""
        journal = AuditJournal(log_dir=str(tmp_path))

        def failing_write(*args, **kwargs):
            raise PermissionError("Permission denied")

        monkeypatch.setattr("builtins.open", failing_write)

        # Should not raise - caught by except block
        event_id = journal.log_event(
            AuditEventType.CIRCUIT_BREAKER,
            AuditSeverity.INFO,
            "Should fail gracefully",
        )
        assert isinstance(event_id, str)

    def test_empty_details_dict(self, journal: AuditJournal):
        """Details defaults to empty dict when None is passed."""
        event_id = journal.log_event(
            AuditEventType.CIRCUIT_BREAKER,
            AuditSeverity.INFO,
            "No details",
            details=None,
        )
        assert event_id

    def test_large_details_dict(self, tmp_path: Path):
        """Large detail payloads still write correctly."""
        journal = AuditJournal(log_dir=str(tmp_path))
        large_details = {"data": "x" * 50_000}
        journal.log_event(
            AuditEventType.CIRCUIT_BREAKER,
            AuditSeverity.INFO,
            "Large payload",
            details=large_details,
        )
        assert journal._current_file.stat().st_size > 50_000
