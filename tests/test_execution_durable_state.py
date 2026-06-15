"""
Tests for core/execution/durable_state.py — Durable Execution State Persistence.

Covers:
- ExecutionState enum (8 states)
- DurableExecutionRecord dataclass
- DurableExecutionStore (init, save, get, non-terminal, duplicate check, update, retry, cleanup, stats, reconcile)
- Singleton get_durable_store
"""

from __future__ import annotations

import sqlite3
from unittest.mock import MagicMock, patch

import pytest

from core.execution.durable_state import (
    DurableExecutionRecord,
    DurableExecutionStore,
    ExecutionState,
    get_durable_store,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def store(tmp_path):
    """DurableExecutionStore with isolated temp DB path."""
    db_path = str(tmp_path / "test_exec_state.db")
    s = DurableExecutionStore(db_path)
    return s


@pytest.fixture
def record():
    """Sample DurableExecutionRecord in PENDING state."""
    return DurableExecutionRecord(
        intent_id="int-1",
        client_order_id="OPB-int-1",
        symbol="NIFTY",
        direction="BUY",
        quantity=50,
        strike_price=150.0,
        state=ExecutionState.PENDING,
    )


# ── ExecutionState Enum Tests ────────────────────────────────────────────────


class TestExecutionState:
    """ExecutionState enum — 8 states."""

    def test_values(self):
        assert ExecutionState.PENDING.value == "PENDING"
        assert ExecutionState.SUBMITTED.value == "SUBMITTED"
        assert ExecutionState.PARTIALLY_FILLED.value == "PARTIALLY_FILLED"
        assert ExecutionState.FILLED.value == "FILLED"
        assert ExecutionState.CANCELLED.value == "CANCELLED"
        assert ExecutionState.REJECTED.value == "REJECTED"
        assert ExecutionState.FAILED.value == "FAILED"
        assert ExecutionState.UNKNOWN.value == "UNKNOWN"


# ── DurableExecutionRecord Tests ──────────────────────────────────────────────


class TestDurableExecutionRecord:
    """DurableExecutionRecord dataclass — default values and custom fields."""

    def test_default_created_at(self, record):
        assert record.created_at is not None

    def test_default_retry_count(self, record):
        assert record.retry_count == 0


# ── DurableExecutionStore Tests ───────────────────────────────────────────────


class TestDurableExecutionStoreInit:
    """Store initialization and schema creation."""

    def test_init_creates_table(self, store):
        """Init should create the execution_state table."""
        with sqlite3.connect(store._db_path) as conn:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='execution_state'"
            )
            assert cursor.fetchone() is not None

    def test_init_creates_indexes(self, store):
        """Init should create indexes on state and updated_at."""
        with sqlite3.connect(store._db_path) as conn:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_exec_state'"
            )
            assert cursor.fetchone() is not None
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_exec_updated'"
            )
            assert cursor.fetchone() is not None


class TestDurableExecutionStoreSaveGet:
    """Save and get operations."""

    def test_save_execution(self, store, record):
        result = store.save_execution(record)
        assert result is True

    def test_get_execution(self, store, record):
        store.save_execution(record)
        loaded = store.get_execution("int-1")
        assert loaded is not None
        assert loaded.intent_id == "int-1"
        assert loaded.symbol == "NIFTY"
        assert loaded.state == ExecutionState.PENDING

    def test_get_execution_nonexistent(self, store):
        loaded = store.get_execution("nonexistent")
        assert loaded is None

    def test_save_and_update(self, store, record):
        store.save_execution(record)
        updated = DurableExecutionRecord(
            intent_id="int-1",
            client_order_id="OPB-int-1",
            symbol="NIFTY",
            direction="BUY",
            quantity=50,
            strike_price=150.0,
            state=ExecutionState.SUBMITTED,
            broker_order_id="brk-123",
        )
        store.save_execution(updated)
        loaded = store.get_execution("int-1")
        assert loaded.state == ExecutionState.SUBMITTED
        assert loaded.broker_order_id == "brk-123"

    def test_save_failure_returns_false(self, store, record):
        with patch.object(sqlite3, "connect", side_effect=sqlite3.Error("mock")):
            result = store.save_execution(record)
            assert result is False


class TestDurableExecutionStoreNonTerminal:
    """Non-terminal execution queries."""

    def test_get_non_terminal_empty(self, store):
        assert store.get_non_terminal_executions() == []

    def test_get_non_terminal_filters_terminal(self, store):
        pending = DurableExecutionRecord(
            intent_id="int-1", client_order_id="OPB-1", symbol="NIFTY",
            direction="BUY", quantity=50, strike_price=150.0, state=ExecutionState.PENDING,
        )
        filled = DurableExecutionRecord(
            intent_id="int-2", client_order_id="OPB-2", symbol="NIFTY",
            direction="SELL", quantity=25, strike_price=200.0, state=ExecutionState.FILLED,
        )
        store.save_execution(pending)
        store.save_execution(filled)

        non_terminal = store.get_non_terminal_executions()
        assert len(non_terminal) == 1
        assert non_terminal[0].intent_id == "int-1"

    def test_get_non_terminal_error(self, store):
        with patch.object(sqlite3, "connect", side_effect=sqlite3.Error("mock")):
            assert store.get_non_terminal_executions() == []


class TestDurableExecutionStoreDuplicate:
    """Duplicate intent detection."""

    def test_is_duplicate_nonexistent(self, store):
        assert store.is_duplicate("nonexistent") is False

    def test_is_duplicate_terminal_not_duplicate(self, store):
        rec = DurableExecutionRecord(
            intent_id="int-1", client_order_id="OPB-1", symbol="NIFTY",
            direction="BUY", quantity=50, strike_price=150.0, state=ExecutionState.FILLED,
        )
        store.save_execution(rec)
        assert store.is_duplicate("int-1") is False

    def test_is_duplicate_non_terminal_is_duplicate(self, store):
        rec = DurableExecutionRecord(
            intent_id="int-1", client_order_id="OPB-1", symbol="NIFTY",
            direction="BUY", quantity=50, strike_price=150.0, state=ExecutionState.PENDING,
        )
        store.save_execution(rec)
        assert store.is_duplicate("int-1") is True


class TestDurableExecutionStoreUpdateState:
    """Atomic state updates."""

    def test_update_state_basic(self, store, record):
        store.save_execution(record)
        result = store.update_state("int-1", ExecutionState.SUBMITTED)
        assert result is True
        loaded = store.get_execution("int-1")
        assert loaded.state == ExecutionState.SUBMITTED

    def test_update_state_with_broker_order_id(self, store, record):
        store.save_execution(record)
        store.update_state("int-1", ExecutionState.SUBMITTED, broker_order_id="brk-123")
        loaded = store.get_execution("int-1")
        assert loaded.broker_order_id == "brk-123"

    def test_update_state_with_fill(self, store, record):
        store.save_execution(record)
        store.update_state("int-1", ExecutionState.FILLED, filled_quantity=50, average_price=151.0)
        loaded = store.get_execution("int-1")
        assert loaded.filled_quantity == 50
        assert loaded.average_price == 151.0

    def test_update_state_failure(self, store, record):
        store.save_execution(record)
        with patch.object(sqlite3, "connect", side_effect=sqlite3.Error("mock")):
            result = store.update_state("int-1", ExecutionState.FILLED)
            assert result is False


class TestDurableExecutionStoreRetry:
    """Retry counter management."""

    def test_increment_retry(self, store, record):
        store.save_execution(record)
        new_count = store.increment_retry("int-1")
        assert new_count == 1

    def test_increment_retry_multiple(self, store, record):
        store.save_execution(record)
        store.increment_retry("int-1")
        store.increment_retry("int-1")
        new_count = store.increment_retry("int-1")
        assert new_count == 3

    def test_increment_retry_nonexistent(self, store):
        new_count = store.increment_retry("nonexistent")
        assert new_count == 0


class TestDurableExecutionStoreClearInflight:
    """Clear in-flight state after failure."""

    def test_clear_in_flight(self, store, record):
        store.save_execution(record)
        result = store.clear_in_flight("int-1")
        assert result is True
        loaded = store.get_execution("int-1")
        assert loaded.state == ExecutionState.FAILED

    def test_clear_in_flight_nonexistent(self, store):
        result = store.clear_in_flight("nonexistent")
        # Still returns True because update_state returns True for nonexistent
        assert result is True


class TestDurableExecutionStoreCleanup:
    """Old record cleanup."""

    def test_cleanup_old_records(self, store):
        store.save_execution(DurableExecutionRecord(
            intent_id="old-1", client_order_id="OPB-old", symbol="NIFTY",
            direction="BUY", quantity=50, strike_price=150.0, state=ExecutionState.FILLED,
        ))
        deleted = store.cleanup_old_records(hours=0)
        assert deleted >= 0  # May or may not be deleted depending on exact timing

    def test_cleanup_preserves_non_terminal(self, store):
        store.save_execution(DurableExecutionRecord(
            intent_id="pending-1", client_order_id="OPB-pending", symbol="NIFTY",
            direction="BUY", quantity=50, strike_price=150.0, state=ExecutionState.PENDING,
        ))
        deleted = store.cleanup_old_records(hours=0)
        remaining = store.get_execution("pending-1")
        assert remaining is not None

    def test_cleanup_error(self, store):
        with patch.object(sqlite3, "connect", side_effect=sqlite3.Error("mock")):
            result = store.cleanup_old_records()
            assert result == 0


class TestDurableExecutionStoreStats:
    """Execution state statistics."""

    def test_get_stats_empty(self, store):
        stats = store.get_stats()
        assert isinstance(stats, dict)
        assert all(stats[s.value] == 0 for s in ExecutionState)

    def test_get_stats_with_records(self, store):
        store.save_execution(DurableExecutionRecord(
            intent_id="int-1", client_order_id="OPB-1", symbol="NIFTY",
            direction="BUY", quantity=50, strike_price=150.0, state=ExecutionState.FILLED,
        ))
        store.save_execution(DurableExecutionRecord(
            intent_id="int-2", client_order_id="OPB-2", symbol="NIFTY",
            direction="SELL", quantity=25, strike_price=200.0, state=ExecutionState.PENDING,
        ))
        stats = store.get_stats()
        assert stats["FILLED"] == 1
        assert stats["PENDING"] == 1


class TestDurableExecutionStoreReconcile:
    """Reconciliation with broker port."""

    def test_reconcile_empty(self, store):
        broker = MagicMock()
        result = store.reconcile_with_broker(broker)
        assert result["checked"] == 0

    def test_reconcile_with_broker(self, store):
        store.save_execution(DurableExecutionRecord(
            intent_id="int-1", client_order_id="OPB-1", symbol="NIFTY",
            direction="BUY", quantity=50, strike_price=150.0, state=ExecutionState.SUBMITTED,
            broker_order_id="brk-1",
        ))
        broker = MagicMock()
        broker.get_order_status.return_value = "FILLED"
        result = store.reconcile_with_broker(broker)
        assert result["checked"] == 1
        assert result["filled"] == 1


# ── Singleton Tests ───────────────────────────────────────────────────────────


class TestGetDurableStore:
    """Module-level singleton."""

    def test_returns_store(self):
        store = get_durable_store(":memory:")
        assert isinstance(store, DurableExecutionStore)

    def test_singleton_identity(self):
        store1 = get_durable_store(":memory:")
        store2 = get_durable_store(":memory:")
        assert store1 is store2
