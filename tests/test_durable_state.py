"""
Tests for core/execution/durable_state.py - Durable Execution State Persistence.

Covers:
  - ExecutionState enum values
  - DurableExecutionRecord dataclass (defaults, custom)
  - DurableExecutionStore initialization (table/index creation, error handling)
  - save_execution (create, update)
  - get_execution (found, not found, error)
  - get_non_terminal_executions (filters terminal states, empty)
  - is_duplicate (non-terminal, terminal, not found)
  - update_state (state only, all fields, error)
  - increment_retry (success, not found)
  - clear_in_flight
  - cleanup_old_records
  - get_stats
  - reconcile_with_broker (filled, still_pending, error)
  - get_durable_store singleton
"""

from __future__ import annotations

import os
import time as _time
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest
from core.execution.durable_state import (
    DurableExecutionRecord,
    DurableExecutionStore,
    ExecutionState,
    get_durable_store,
)


def _cleanup_db(db_path: str) -> None:
    """Safely remove a SQLite DB file on Windows (retry with backoff)."""
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
            _time.sleep(0.1 * (attempt + 1))


def _make_record(
    intent_id: str = "INT-001",
    state: ExecutionState = ExecutionState.PENDING,
    **overrides,
) -> DurableExecutionRecord:
    """Helper to create DurableExecutionRecord with defaults."""
    params = {
        "intent_id": intent_id,
        "client_order_id": f"OPB-{intent_id}",
        "symbol": "NIFTY",
        "direction": "BUY",
        "quantity": 50,
        "strike_price": 23500.0,
        "state": state,
    }
    params.update(overrides)
    return DurableExecutionRecord(**params)


# ═══════════════════════════════════════════════════════════════════════
#  ExecutionState
# ═══════════════════════════════════════════════════════════════════════


class TestExecutionState:
    def test_values(self):
        assert ExecutionState.PENDING.value == "PENDING"
        assert ExecutionState.SUBMITTED.value == "SUBMITTED"
        assert ExecutionState.PARTIALLY_FILLED.value == "PARTIALLY_FILLED"
        assert ExecutionState.FILLED.value == "FILLED"
        assert ExecutionState.CANCELLED.value == "CANCELLED"
        assert ExecutionState.REJECTED.value == "REJECTED"
        assert ExecutionState.FAILED.value == "FAILED"
        assert ExecutionState.UNKNOWN.value == "UNKNOWN"


# ═══════════════════════════════════════════════════════════════════════
#  DurableExecutionRecord
# ═══════════════════════════════════════════════════════════════════════


class TestDurableExecutionRecord:
    def test_minimal(self):
        rec = DurableExecutionRecord(
            intent_id="INT-001",
            client_order_id="OPB-INT-001",
            symbol="NIFTY",
            direction="BUY",
            quantity=50,
            strike_price=23500.0,
            state=ExecutionState.PENDING,
        )
        assert rec.intent_id == "INT-001"
        assert rec.retry_count == 0
        assert rec.filled_quantity == 0
        assert rec.average_price == 0.0
        assert rec.broker_order_id is None

    def test_full(self):
        now = datetime(2026, 6, 19, 12, 0, 0)
        rec = DurableExecutionRecord(
            intent_id="INT-002",
            client_order_id="OPB-INT-002",
            symbol="BANKNIFTY",
            direction="SELL",
            quantity=25,
            strike_price=50000.0,
            state=ExecutionState.FILLED,
            broker_order_id="BROKER-001",
            filled_quantity=25,
            average_price=49950.0,
            reject_reason=None,
            created_at=now,
            updated_at=now,
            retry_count=2,
        )
        assert rec.broker_order_id == "BROKER-001"
        assert rec.retry_count == 2


# ═══════════════════════════════════════════════════════════════════════
#  DurableExecutionStore
# ═══════════════════════════════════════════════════════════════════════


class TestDurableExecutionStore:
    @pytest.fixture(autouse=True)
    def _db(self, tmp_path):
        """Each test gets an isolated temp DB file."""
        self._db_path = str(tmp_path / "test_exec_state.db")
        self.store = DurableExecutionStore(self._db_path)
        yield
        # Cleanup after test
        _cleanup_db(self._db_path)

    # ── init ────────────────────────────────────────────────────────

    def test_init_creates_tables(self):
        """Verify table and indexes exist."""
        import sqlite3

        conn = sqlite3.connect(self._db_path)
        try:
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            assert ("execution_state",) in tables
            indexes = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()
            names = [r[0] for r in indexes]
            assert "idx_exec_state" in names
            assert "idx_exec_updated" in names
        finally:
            conn.close()

    # ── save_execution ──────────────────────────────────────────────

    def test_save_new_record(self):
        rec = _make_record()
        result = self.store.save_execution(rec)
        assert result is True

    def test_save_update_existing(self):
        rec = _make_record(state=ExecutionState.PENDING)
        self.store.save_execution(rec)
        rec.state = ExecutionState.SUBMITTED
        result = self.store.save_execution(rec)
        assert result is True

    # ── get_execution ───────────────────────────────────────────────

    def test_get_execution_found(self):
        rec = _make_record(intent_id="INT-FOUND")
        self.store.save_execution(rec)
        loaded = self.store.get_execution("INT-FOUND")
        assert loaded is not None
        assert loaded.intent_id == "INT-FOUND"
        assert loaded.state == ExecutionState.PENDING

    def test_get_execution_not_found(self):
        loaded = self.store.get_execution("DOES-NOT-EXIST")
        assert loaded is None

    # ── get_non_terminal_executions ─────────────────────────────────

    def test_get_non_terminal_filters_filled(self):
        self.store.save_execution(_make_record("INT-PENDING", ExecutionState.PENDING))
        self.store.save_execution(_make_record("INT-FILLED", ExecutionState.FILLED))
        self.store.save_execution(_make_record("INT-SUBMITTED", ExecutionState.SUBMITTED))

        results = self.store.get_non_terminal_executions()
        ids = [r.intent_id for r in results]
        assert "INT-FILLED" not in ids
        assert "INT-PENDING" in ids
        assert "INT-SUBMITTED" in ids

    def test_get_non_terminal_empty(self):
        results = self.store.get_non_terminal_executions()
        assert results == []

    # ── is_duplicate ─────────────────────────────────────────────────

    def test_is_duplicate_non_terminal(self):
        self.store.save_execution(_make_record("INT-DUP", ExecutionState.PENDING))
        assert self.store.is_duplicate("INT-DUP") is True

    def test_is_duplicate_terminal(self):
        self.store.save_execution(_make_record("INT-DUP", ExecutionState.FILLED))
        assert self.store.is_duplicate("INT-DUP") is False

    def test_is_duplicate_not_found(self):
        assert self.store.is_duplicate("UNKNOWN") is False

    # ── update_state ─────────────────────────────────────────────────

    def test_update_state_only(self):
        self.store.save_execution(_make_record("INT-UPD"))
        result = self.store.update_state("INT-UPD", ExecutionState.SUBMITTED)
        assert result is True
        loaded = self.store.get_execution("INT-UPD")
        assert loaded.state == ExecutionState.SUBMITTED

    def test_update_state_with_all_fields(self):
        self.store.save_execution(_make_record("INT-UPD"))
        result = self.store.update_state(
            "INT-UPD",
            ExecutionState.FILLED,
            broker_order_id="BROKER-999",
            filled_quantity=50,
            average_price=23400.0,
            reject_reason=None,
        )
        assert result is True
        loaded = self.store.get_execution("INT-UPD")
        assert loaded.state == ExecutionState.FILLED
        assert loaded.broker_order_id == "BROKER-999"
        assert loaded.filled_quantity == 50

    def test_update_state_nonexistent(self):
        result = self.store.update_state("NONEXIST", ExecutionState.FAILED)
        assert result is True  # SQLite UPDATE on missing row succeeds (0 rows affected)

    # ── increment_retry ──────────────────────────────────────────────

    def test_increment_retry(self):
        self.store.save_execution(_make_record("INT-RETRY", retry_count=0))
        new_count = self.store.increment_retry("INT-RETRY")
        assert new_count == 1

    def test_increment_retry_not_found(self):
        new_count = self.store.increment_retry("NONEXIST")
        assert new_count == 0

    # ── clear_in_flight ──────────────────────────────────────────────

    def test_clear_in_flight(self):
        self.store.save_execution(_make_record("INT-FLIGHT"))
        result = self.store.clear_in_flight("INT-FLIGHT")
        assert result is True
        loaded = self.store.get_execution("INT-FLIGHT")
        assert loaded.state == ExecutionState.FAILED
        assert "Cleared for retry" in (loaded.reject_reason or "")

    # ── cleanup_old_records ──────────────────────────────────────────

    def test_cleanup_removes_old_terminal(self):
        # Create a record with an old timestamp
        old_time = (datetime.now() - timedelta(hours=48)).isoformat()
        self.store.save_execution(_make_record("INT-OLD", ExecutionState.FILLED))
        # Manually set updated_at to old timestamp
        import sqlite3
        conn = sqlite3.connect(self._db_path)
        conn.execute(
            "UPDATE execution_state SET updated_at = ? WHERE intent_id = ?",
            (old_time, "INT-OLD"),
        )
        conn.commit()
        conn.close()

        deleted = self.store.cleanup_old_records(hours=24)
        assert deleted >= 1
        assert self.store.get_execution("INT-OLD") is None

    def test_cleanup_keeps_recent(self):
        self.store.save_execution(_make_record("INT-RECENT", ExecutionState.FILLED))
        self.store.cleanup_old_records(hours=24)
        assert self.store.get_execution("INT-RECENT") is not None

    # ── get_stats ────────────────────────────────────────────────────

    def test_get_stats(self):
        self.store.save_execution(_make_record("INT-1", ExecutionState.PENDING))
        self.store.save_execution(_make_record("INT-2", ExecutionState.FILLED))
        self.store.save_execution(_make_record("INT-3", ExecutionState.PENDING))

        stats = self.store.get_stats()
        assert stats.get("PENDING") == 2
        assert stats.get("FILLED") == 1
        for state in ExecutionState:
            assert state.value in stats

    # ── reconcile_with_broker ────────────────────────────────────────

    def test_reconcile_filled(self):
        self.store.save_execution(_make_record("INT-REC", ExecutionState.SUBMITTED,
                                                broker_order_id="BR-001"))
        broker = MagicMock()
        broker.get_order_status.return_value = "FILLED"

        result = self.store.reconcile_with_broker(broker)

        assert result["filled"] == 1
        loaded = self.store.get_execution("INT-REC")
        assert loaded.state == ExecutionState.FILLED

    def test_reconcile_still_pending_no_broker_id(self):
        self.store.save_execution(_make_record("INT-REC", ExecutionState.SUBMITTED))
        broker = MagicMock()

        result = self.store.reconcile_with_broker(broker)

        assert result["still_pending"] == 1

    def test_reconcile_broker_error(self):
        self.store.save_execution(_make_record("INT-REC", ExecutionState.SUBMITTED,
                                                broker_order_id="BR-001"))
        broker = MagicMock()
        broker.get_order_status.side_effect = ConnectionError("Broker down")

        result = self.store.reconcile_with_broker(broker)

        assert result["unknown"] == 1


# ═══════════════════════════════════════════════════════════════════════
#  Singleton
# ═══════════════════════════════════════════════════════════════════════


class TestGetDurableStore:
    @pytest.fixture(autouse=True)
    def _reset(self):
        """Reset the singleton before and after each test."""
        from core.execution import durable_state as ds

        old = ds._durable_store_instance
        ds._durable_store_instance = None
        yield
        ds._durable_store_instance = old

    def test_singleton(self):
        store1 = get_durable_store(":memory:")
        store2 = get_durable_store(":memory:")
        assert store1 is store2
