"""
Tests for core/audit_engine.py - Structured JSONL Audit Trail.

Tests cover:
- AuditEngine initialization and configuration
- record() method with various severities
- Thread safety under concurrent access
- File output format (JSONL validation)
- Disabled/enabled states
- Custom now_fn and trace_id propagation
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

import pytest
from core.audit_engine import AuditEngine, AuditRecord

# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def tmp_log(tmp_path: Path) -> Path:
    """Temporary audit log path."""
    return tmp_path / "audit.jsonl"


@pytest.fixture
def engine(tmp_log: Path) -> AuditEngine:
    """Default audit engine instance."""
    return AuditEngine(tmp_log)


# ── Initialisation ───────────────────────────────────────────────────────────


class TestAuditEngineInit:
    """AuditEngine construction and configuration."""

    def test_default_construction(self, tmp_log: Path) -> None:
        """Default construction should set expected attributes."""
        eng = AuditEngine(tmp_log)
        assert eng._path == tmp_log
        assert eng._enabled is True
        assert eng._lock is not None

    def test_disabled_on_request(self, tmp_log: Path) -> None:
        """enabled=False should suppress all output."""
        eng = AuditEngine(tmp_log, enabled=False)
        assert eng._enabled is False

    def test_custom_now_fn(self, tmp_log: Path) -> None:
        """Custom now_fn should be used for timestamps."""
        fixed = datetime(2026, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        eng = AuditEngine(tmp_log, now_fn=lambda: fixed)
        result = eng.record("test_event", key="value")
        assert result is not None
        line = tmp_log.read_text(encoding="utf-8").strip()
        parsed = json.loads(line)
        assert parsed["ts"] == fixed.isoformat()

    def test_custom_now_fn_defaults_to_utc(self, tmp_log: Path) -> None:
        """Default now_fn produces timezone-aware UTC."""
        eng = AuditEngine(tmp_log)
        before = datetime.now(timezone.utc)
        result = eng.record("test_event")
        after = datetime.now(timezone.utc)
        assert result is not None
        parsed = json.loads(tmp_log.read_text(encoding="utf-8").strip())
        parsed_ts = datetime.fromisoformat(parsed["ts"])
        assert before <= parsed_ts <= after

    def test_path_created_on_record(self, tmp_path: Path) -> None:
        """Parent directory should be created on first record()."""
        nested = tmp_path / "sub" / "dir" / "audit.jsonl"
        eng = AuditEngine(nested)
        eng.record("test")
        assert nested.exists()


# ── record() ─────────────────────────────────────────────────────────────────


class TestAuditEngineRecord:
    """AuditEngine.record() method behaviour."""

    def test_record_returns_audit_record(self, engine: AuditEngine) -> None:
        """record() should return an AuditRecord."""
        result = engine.record("order_placed", symbol="NIFTY", qty=50)
        assert isinstance(result, AuditRecord)
        assert result.event == "order_placed"
        assert result.payload["symbol"] == "NIFTY"

    def test_record_writes_jsonl(self, engine: AuditEngine, tmp_log: Path) -> None:
        """record() should write one JSONL line."""
        engine.record("state_saved", key="value")
        lines = tmp_log.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 1
        parsed = json.loads(lines[0])
        assert parsed["event"] == "state_saved"
        assert parsed["key"] == "value"

    def test_record_multiple_events(self, engine: AuditEngine, tmp_log: Path) -> None:
        """Multiple calls should append separate lines."""
        for i in range(5):
            engine.record("event", index=i)
        lines = tmp_log.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 5
        for i, line in enumerate(lines):
            parsed = json.loads(line)
            assert parsed["index"] == i

    def test_record_disabled_returns_none(self, tmp_log: Path) -> None:
        """Disabled engine should return None and write nothing."""
        eng = AuditEngine(tmp_log, enabled=False)
        result = eng.record("should_not_appear")
        assert result is None
        assert not tmp_log.exists()

    def test_record_default_severity(self, engine: AuditEngine, tmp_log: Path) -> None:
        """Default severity should be INFO."""
        engine.record("test")
        parsed = json.loads(tmp_log.read_text(encoding="utf-8").strip())
        assert parsed["severity"] == "INFO"

    @pytest.mark.parametrize("severity", ["INFO", "WARN", "CRITICAL", "AUDIT"])
    def test_record_valid_severities(self, engine: AuditEngine, tmp_log: Path, severity: str) -> None:
        """Valid severities should be accepted."""
        engine.record("test", severity=severity)
        parsed = json.loads(tmp_log.read_text(encoding="utf-8").strip())
        assert parsed["severity"] == severity

    def test_record_invalid_severity_defaults_to_info(self, engine: AuditEngine, tmp_log: Path) -> None:
        """Invalid severity should default to INFO."""
        engine.record("test", severity="INVALID")
        parsed = json.loads(tmp_log.read_text(encoding="utf-8").strip())
        assert parsed["severity"] == "INFO"

    def test_record_trace_id_propagation(self, engine: AuditEngine, tmp_log: Path) -> None:
        """trace_id should be included in the JSONL row."""
        engine.record("test", trace_id="trace_123")
        parsed = json.loads(tmp_log.read_text(encoding="utf-8").strip())
        assert parsed["trace_id"] == "trace_123"

    def test_record_trace_id_omitted_when_none(self, engine: AuditEngine, tmp_log: Path) -> None:
        """trace_id should not appear in output when None."""
        engine.record("test")
        parsed = json.loads(tmp_log.read_text(encoding="utf-8").strip())
        assert "trace_id" not in parsed

    def test_record_payload_arbitrary_keys(self, engine: AuditEngine, tmp_log: Path) -> None:
        """Any kwargs should be merged into the JSONL row."""
        engine.record("test", symbol="NIFTY", score=85, regime="TRENDING")
        parsed = json.loads(tmp_log.read_text(encoding="utf-8").strip())
        assert parsed["symbol"] == "NIFTY"
        assert parsed["score"] == 85
        assert parsed["regime"] == "TRENDING"

    def test_record_ts_isoformat(self, engine: AuditEngine, tmp_log: Path) -> None:
        """Timestamp should be ISO 8601 formatted."""
        engine.record("test")
        parsed = json.loads(tmp_log.read_text(encoding="utf-8").strip())
        # Should parse as ISO datetime
        dt = datetime.fromisoformat(parsed["ts"])
        assert dt.tzinfo is not None  # timezone-aware


# ── Thread Safety ────────────────────────────────────────────────────────────


class TestAuditEngineThreadSafety:
    """Verify thread safety under concurrent access."""

    def test_concurrent_records(self, tmp_log: Path) -> None:
        """Multiple threads writing concurrently should not corrupt the file."""
        eng = AuditEngine(tmp_log)
        n_threads = 10
        n_records_per = 50
        errors: list[Exception] = []
        barrier = threading.Barrier(n_threads)

        def _worker(worker_id: int) -> None:
            barrier.wait()  # Ensure all threads start at the same time
            for i in range(n_records_per):
                try:
                    eng.record(f"event_{worker_id}", worker=worker_id, index=i)
                except Exception as exc:
                    errors.append(exc)

        threads = [threading.Thread(target=_worker, args=(i,)) for i in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert len(errors) == 0, f"Concurrent writes produced errors: {errors}"
        lines = tmp_log.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == n_threads * n_records_per

        # Validate every line is valid JSON
        for line in lines:
            parsed = json.loads(line)
            assert "event" in parsed
            assert "ts" in parsed
            assert "severity" in parsed
            assert "worker" in parsed
            assert "index" in parsed

    def test_concurrent_same_event(self, tmp_log: Path) -> None:
        """Concurrent calls with the same event should not interleave JSON."""
        eng = AuditEngine(tmp_log)
        n_threads = 20
        barrier = threading.Barrier(n_threads)

        def _worker() -> None:
            barrier.wait()
            eng.record("same_event", data="x" * 100)

        threads = [threading.Thread(target=_worker) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        lines = tmp_log.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == n_threads
        for line in lines:
            # Each line should be a complete JSON object
            parsed = json.loads(line)
            assert parsed["event"] == "same_event"
            assert parsed["data"] == "x" * 100


# ── Edge Cases ───────────────────────────────────────────────────────────────


class TestAuditEngineEdgeCases:
    """Edge cases and error handling."""

    def test_record_empty_event(self, engine: AuditEngine, tmp_log: Path) -> None:
        """Empty event string should still write."""
        engine.record("")
        parsed = json.loads(tmp_log.read_text(encoding="utf-8").strip())
        assert parsed["event"] == ""

    def test_record_special_chars_in_payload(self, engine: AuditEngine, tmp_log: Path) -> None:
        """Special characters should be properly JSON-encoded."""
        engine.record("test", message="line1\nline2\twith\"quotes\"")
        parsed = json.loads(tmp_log.read_text(encoding="utf-8").strip())
        assert parsed["message"] == "line1\nline2\twith\"quotes\""

    def test_record_non_string_values(self, engine: AuditEngine, tmp_log: Path) -> None:
        """Non-string payload values should be serialised."""
        engine.record("test", int_val=42, float_val=3.14, bool_val=True, none_val=None)
        parsed = json.loads(tmp_log.read_text(encoding="utf-8").strip())
        assert parsed["int_val"] == 42
        assert parsed["float_val"] == 3.14
        assert parsed["bool_val"] is True
        assert parsed["none_val"] is None

    def test_audit_record_dataclass(self, engine: AuditEngine) -> None:
        """AuditRecord should be a frozen dataclass with correct fields."""
        result = engine.record("test", key="value")
        assert isinstance(result, AuditRecord)
        assert result.event == "test"
        assert result.payload["key"] == "value"

    def test_reinit_with_same_path_appends(self, tmp_log: Path) -> None:
        """A new engine with the same path should append, not overwrite."""
        eng1 = AuditEngine(tmp_log)
        eng1.record("first")
        eng2 = AuditEngine(tmp_log)
        eng2.record("second")
        lines = tmp_log.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2
        assert json.loads(lines[0])["event"] == "first"
        assert json.loads(lines[1])["event"] == "second"
