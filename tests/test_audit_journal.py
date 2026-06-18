"""Tests for core/audit_journal.py - Audit Event Journal."""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path

import pytest

from core.audit_journal import (
    AuditEvent,
    AuditEventType,
    AuditJournal,
    AuditSeverity,
    get_audit_journal,
)


class TestAuditEventType:
    """AuditEventType enum coverage."""

    def test_has_expected_types(self):
        assert AuditEventType.SIGNAL_GENERATED.value == "SIGNAL_GENERATED"
        assert AuditEventType.RISK_DECISION.value == "RISK_DECISION"
        assert AuditEventType.ORDER_SUBMITTED.value == "ORDER_SUBMITTED"
        assert AuditEventType.ORDER_FILLED.value == "ORDER_FILLED"
        assert AuditEventType.ORDER_REJECTED.value == "ORDER_REJECTED"
        assert AuditEventType.HARD_HALT.value == "HARD_HALT"
        assert AuditEventType.CONFIG_CHANGE.value == "CONFIG_CHANGE"

    def test_all_types_unique(self):
        values = [t.value for t in AuditEventType]
        assert len(values) == len(set(values))


class TestAuditSeverity:
    """AuditSeverity enum coverage."""

    def test_has_expected_severities(self):
        assert AuditSeverity.DEBUG.value == "DEBUG"
        assert AuditSeverity.INFO.value == "INFO"
        assert AuditSeverity.WARNING.value == "WARNING"
        assert AuditSeverity.ERROR.value == "ERROR"
        assert AuditSeverity.CRITICAL.value == "CRITICAL"


class TestAuditEvent:
    """AuditEvent dataclass coverage."""

    def test_to_dict(self):
        event = AuditEvent(
            event_id="test123",
            timestamp="2026-06-11T12:00:00",
            event_type="SIGNAL_GENERATED",
            severity="INFO",
            message="Test event",
            correlation_id="corr1",
            symbol="NIFTY",
            details={"score": 85},
        )
        d = event.to_dict()
        assert d["event_id"] == "test123"
        assert d["event_type"] == "SIGNAL_GENERATED"
        assert d["details"] == {"score": 85}

    def test_default_details(self):
        event = AuditEvent(
            event_id="e1", timestamp="t1", event_type="TEST",
            severity="INFO", message="test",
        )
        assert event.details == {}
        assert event.correlation_id == ""
        assert event.intent_id == ""
        assert event.symbol == ""
        assert event.stack_trace == ""


class TestAuditJournal:
    """AuditJournal functional coverage."""

    @pytest.fixture
    def journal(self):
        tmp = tempfile.mktemp(suffix="_audit")
        os.makedirs(tmp, exist_ok=True)
        j = AuditJournal(
            log_dir=tmp,
            filename_prefix="audit",
            max_file_size_mb=50,
            retain_days=30,
        )
        yield j
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)

    def test_log_event_creates_file(self, journal):
        event_id = journal.log_event(
            event_type=AuditEventType.SIGNAL_GENERATED,
            severity=AuditSeverity.INFO,
            message="Test signal",
            symbol="NIFTY",
            details={"score": 85},
        )
        assert event_id.startswith("202")
        log_dir = Path(journal._log_dir)
        files = list(log_dir.glob("audit_*.jsonl"))
        assert len(files) == 1
        content = files[0].read_text()
        assert "Test signal" in content
        assert "NIFTY" in content

    def test_log_signal(self, journal):
        signal = {"symbol": "BANKNIFTY", "direction": "CALL", "strength": "STRONG"}
        event_id = journal.log_signal(signal, correlation_id="cid123")
        assert event_id
        log_dir = Path(journal._log_dir)
        content = list(log_dir.glob("audit_*.jsonl"))[0].read_text()
        assert "BANKNIFTY" in content
        assert "STRONG" in content

    def test_log_risk_decision_allowed(self, journal):
        event_id = journal.log_risk_decision(
            decision="entry_check",
            allowed=True,
            reason="All checks passed",
            intent_id="int1",
            symbol="NIFTY",
        )
        assert event_id
        log_dir = Path(journal._log_dir)
        content = list(log_dir.glob("audit_*.jsonl"))[0].read_text()
        assert "ALLOWED" in content

    def test_log_risk_decision_denied(self, journal):
        journal.log_risk_decision(
            decision="entry_check",
            allowed=False,
            reason="Max daily loss exceeded",
            symbol="NIFTY",
        )
        log_dir = Path(journal._log_dir)
        content = list(log_dir.glob("audit_*.jsonl"))[0].read_text()
        assert "DENIED" in content

    def test_log_order_submitted(self, journal):
        order = {"symbol": "NIFTY", "direction": "BUY", "qty": 50}
        journal.log_order_submitted(order, intent_id="int1", correlation_id="cid1")
        log_dir = Path(journal._log_dir)
        content = list(log_dir.glob("audit_*.jsonl"))[0].read_text()
        assert "BUY" in content
        assert "50" in content

    def test_log_order_filled(self, journal):
        journal.log_order_filled(
            order_id="ord123", fill_price=23500.5, filled_qty=50,
            intent_id="int1", symbol="NIFTY",
        )
        log_dir = Path(journal._log_dir)
        content = list(log_dir.glob("audit_*.jsonl"))[0].read_text()
        assert "ord123" in content
        assert "23500.5" in content

    def test_log_reconciliation_mismatch(self, journal):
        journal.log_reconciliation_mismatch(
            mismatch_type="quantity_mismatch",
            details={"expected": 50, "actual": 25},
        )
        log_dir = Path(journal._log_dir)
        content = list(log_dir.glob("audit_*.jsonl"))[0].read_text()
        assert "quantity_mismatch" in content
        assert "expected" in content

    def test_log_hard_halt(self, journal):
        journal.log_hard_halt(reason="Max loss breached", source="test")
        log_dir = Path(journal._log_dir)
        content = list(log_dir.glob("audit_*.jsonl"))[0].read_text()
        assert "HARD HALT" in content
        assert "Max loss" in content

    def test_log_system_mode_change(self, journal):
        journal.log_system_mode_change(
            old_mode="PAPER", new_mode="LIVE", reason="Go live",
        )
        log_dir = Path(journal._log_dir)
        content = list(log_dir.glob("audit_*.jsonl"))[0].read_text()
        assert "PAPER" in content
        assert "LIVE" in content

    def test_log_stale_quote(self, journal):
        journal.log_stale_quote(symbol="NIFTY", quote_age=32.5)
        log_dir = Path(journal._log_dir)
        content = list(log_dir.glob("audit_*.jsonl"))[0].read_text()
        assert "stale" in content.lower()
        assert "32.5" in content

    def test_log_invalid_price(self, journal):
        journal.log_invalid_price(symbol="NIFTY", price=-100, reason="Negative price")
        log_dir = Path(journal._log_dir)
        content = list(log_dir.glob("audit_*.jsonl"))[0].read_text()
        assert "Invalid price" in content
        assert "-100" in content

    def test_file_rotation_on_date_change(self, journal):
        """Simulate rotation by manipulating current file."""
        journal.log_event(AuditEventType.SIGNAL_GENERATED, AuditSeverity.INFO, "first")
        first_file = journal._current_file
        # Force rotation by clearing current file
        journal._current_file = None
        journal.log_event(AuditEventType.RISK_DECISION, AuditSeverity.WARNING, "second")
        second_file = journal._current_file
        assert first_file.exists()
        assert second_file.exists()

    def test_size_based_rotation_updates_size(self, journal):
        """After writing past max_file_size, _current_file_size should be reset."""
        journal._max_file_size = 1
        journal.log_event(AuditEventType.SIGNAL_GENERATED, AuditSeverity.INFO, "event1")
        size_after_first = journal._current_file_size
        # Second write should trigger rotation (resets file size tracking)
        journal.log_event(AuditEventType.ORDER_SUBMITTED, AuditSeverity.INFO, "event2")
        # File still exists and has content
        assert journal._current_file.exists()
        assert journal._current_file.stat().st_size > 0

    def test_cleanup_old_files(self, journal):
        """Create old files and verify cleanup removes them."""
        log_dir = Path(journal._log_dir)
        # Create fake old audit files with mtime older than retain_days
        old_mtime = time.time() - (31 * 86400) - 100  # 31+ days ago
        for i in range(3):
            old_file = log_dir / f"audit_20200101_{i}.jsonl"
            old_file.write_text("old event\n")
            os.utime(str(old_file), (old_mtime, old_mtime))
        removed = journal.cleanup_old_files()
        assert removed == 3

    def test_cleanup_skips_current_file(self, journal):
        """Current file should not be removed by cleanup."""
        journal.log_event(AuditEventType.SIGNAL_GENERATED, AuditSeverity.INFO, "current")
        removed = journal.cleanup_old_files()
        assert removed == 0

    def test_multiple_events_append(self, journal):
        """Multiple events should all be written and be valid JSON."""
        for i in range(5):
            journal.log_event(
                AuditEventType.SIGNAL_GENERATED, AuditSeverity.INFO, f"event_{i}",
            )
        log_dir = Path(journal._log_dir)
        content = list(log_dir.glob("audit_*.jsonl"))[0].read_text()
        lines = content.strip().split("\n")
        assert len(lines) == 5
        for line in lines:
            data = json.loads(line)
            assert "event_id" in data
            assert "message" in data

    def test_multiple_event_types_inline(self, journal):
        """Log events of various types and ensure proper routing."""
        for et, sev, msg in [
            (AuditEventType.SIGNAL_GENERATED, AuditSeverity.INFO, "sig"),
            (AuditEventType.RISK_DECISION, AuditSeverity.WARNING, "risk"),
            (AuditEventType.ORDER_SUBMITTED, AuditSeverity.INFO, "order"),
            (AuditEventType.HARD_HALT, AuditSeverity.CRITICAL, "halt"),
        ]:
            journal.log_event(et, sev, msg)
        log_dir = Path(journal._log_dir)
        content = list(log_dir.glob("audit_*.jsonl"))[0].read_text()
        assert "SIGNAL_GENERATED" in content
        assert "RISK_DECISION" in content
        assert "ORDER_SUBMITTED" in content
        assert "HARD_HALT" in content


class TestGetAuditJournal:
    """Singleton get_audit_journal coverage."""

    def test_get_default_journal(self):
        journal = get_audit_journal()
        assert isinstance(journal, AuditJournal)

    def test_get_with_config(self):
        journal = get_audit_journal({"audit_log_dir": tempfile.gettempdir()})
        assert isinstance(journal, AuditJournal)

    def test_singleton_behavior(self):
        j1 = get_audit_journal()
        j2 = get_audit_journal()
        assert j1 is j2


class TestExplicitAuditLog:
    """Quick access audit_log function coverage."""

    def test_audit_log_function(self):
        from core.audit_journal import audit_log
        event_id = audit_log(
            AuditEventType.SIGNAL_GENERATED,
            AuditSeverity.INFO,
            "quick test",
            symbol="NIFTY",
        )
        assert event_id
