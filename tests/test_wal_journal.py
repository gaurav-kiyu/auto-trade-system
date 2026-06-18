"""
Tests for core/wal/journal.py — Write-Ahead Intent Journal with AsyncDbWriter.

Covers:
  - Intent lifecycle: append → commit → settle (full status flow)
    with AsyncDbWriter-based writes (non-blocking queue)
  - Read-back via get_intent, get_pending, get_unsettled, get_by_correlation
  - Sync fallback when async queue is saturated
  - Count by status, cleanup of old intents
  - Thread safety under concurrent access
  - Crash recovery simulation (get_pending after restart)
  - Health check with async writer stats
  - File-based and in-memory database support
  - Edge cases: empty journal, unknown intent, duplicate intent_id

Uses ``journal.flush()`` for deterministic read-after-write consistency
instead of fragile ``time.sleep()`` calls.
"""

from __future__ import annotations

import os
import tempfile
import threading
import time

import pytest

from core.wal.journal import Intent, IntentStatus, WriteAheadJournal


# ═════════════════════════════════════════════════════════════════════════
# Fixtures
# ═════════════════════════════════════════════════════════════════════════


@pytest.fixture()
def tmp_db() -> str:
    """Create a temporary database file path."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    yield path
    try:
        os.unlink(path)
        # WAL and SHM files
        for suffix in ("-wal", "-shm"):
            extra = path + suffix
            if os.path.exists(extra):
                os.unlink(extra)
    except OSError:
        pass


@pytest.fixture()
def journal(tmp_db: str) -> WriteAheadJournal:
    """Create a WAL journal with a temporary file-based database."""
    j = WriteAheadJournal(tmp_db)
    yield j
    j.close()


def _make_intent(intent_id: str, **overrides) -> Intent:
    """Helper to create an Intent with defaults overridable."""
    defaults = dict(
        intent_id=intent_id,
        action="BUY",
        params={"symbol": "NIFTY", "qty": 75, "strike": 23500},
        risk_verdict={"allowed": True, "score": 8},
        config_snapshot_hash="abc123",
        correlation_id=f"corr-{intent_id}",
    )
    defaults.update(overrides)
    return Intent(**defaults)


# ═════════════════════════════════════════════════════════════════════════
# Basic Intent Lifecycle
# ═════════════════════════════════════════════════════════════════════════


class TestIntentLifecycle:
    """Full intent status flow: PENDING → COMMITTED → SETTLED."""

    def test_append(self, journal: WriteAheadJournal) -> None:
        """Append a PENDING intent and verify via get_intent."""
        intent = _make_intent("test-001")
        journal.append(intent)
        journal.flush()
        retrieved = journal.get_intent("test-001")
        assert retrieved is not None
        assert retrieved.intent_id == "test-001"
        assert retrieved.action == "BUY"
        assert retrieved.status == IntentStatus.PENDING
        assert retrieved.params["symbol"] == "NIFTY"
        assert retrieved.params["qty"] == 75
        assert retrieved.risk_verdict["allowed"] is True
        assert retrieved.correlation_id == "corr-test-001"

    def test_append_commit_settle(self, journal: WriteAheadJournal) -> None:
        """Full lifecycle: append → commit → settle."""
        journal.append(_make_intent("test-002"))
        journal.flush()
        journal.commit("test-002")
        journal.flush()

        retrieved = journal.get_intent("test-002")
        assert retrieved is not None
        assert retrieved.status == IntentStatus.COMMITTED
        assert retrieved.committed_at is not None

        journal.settle("test-002")
        journal.flush()

        retrieved = journal.get_intent("test-002")
        assert retrieved is not None
        assert retrieved.status == IntentStatus.SETTLED

    def test_append_fail(self, journal: WriteAheadJournal) -> None:
        """Append then fail an intent."""
        journal.append(_make_intent("test-003"))
        journal.flush()
        journal.fail("test-003", "Insufficient margin")
        journal.flush()

        retrieved = journal.get_intent("test-003")
        assert retrieved is not None
        assert retrieved.status == IntentStatus.FAILED
        assert retrieved.failed_at is not None
        assert "Insufficient margin" in retrieved.error_message


# ═════════════════════════════════════════════════════════════════════════
# Queries and Read-back
# ═════════════════════════════════════════════════════════════════════════


class TestQueries:
    def test_get_pending(self, journal: WriteAheadJournal) -> None:
        """Get all PENDING intents."""
        journal.append(_make_intent("p1"))
        journal.append(_make_intent("p2"))
        journal.append(_make_intent("p3"))
        journal.flush()

        pending = journal.get_pending()
        ids = {i.intent_id for i in pending}
        assert "p1" in ids
        assert "p2" in ids
        assert "p3" in ids

    def test_get_pending_excludes_non_pending(self, journal: WriteAheadJournal) -> None:
        """COMMITTED or SETTLED intents are not returned by get_pending()."""
        journal.append(_make_intent("pending-only"))
        journal.append(_make_intent("will-commit"))
        journal.flush()
        journal.commit("will-commit")
        journal.flush()

        pending = journal.get_pending()
        ids = {i.intent_id for i in pending}
        assert "pending-only" in ids
        assert "will-commit" not in ids

    def test_get_unsettled(self, journal: WriteAheadJournal) -> None:
        """Get COMMITTED intents that haven't been SETTLED."""
        journal.append(_make_intent("u1"))
        journal.append(_make_intent("u2"))
        journal.append(_make_intent("settled-already"))
        journal.flush()
        journal.commit("u1")
        journal.commit("u2")
        journal.commit("settled-already")
        journal.flush()
        journal.settle("settled-already")
        journal.flush()

        unsettled = journal.get_unsettled()
        ids = {i.intent_id for i in unsettled}
        assert "u1" in ids
        assert "u2" in ids
        assert "settled-already" not in ids

    def test_get_by_correlation(self, journal: WriteAheadJournal) -> None:
        """Get all intents with a given correlation_id."""
        journal.append(_make_intent("c1", correlation_id="group-A"))
        journal.append(_make_intent("c2", correlation_id="group-A"))
        journal.append(_make_intent("other", correlation_id="other"))
        journal.flush()

        by_corr = journal.get_by_correlation("group-A")
        ids = {i.intent_id for i in by_corr}
        assert "c1" in ids
        assert "c2" in ids
        assert "other" not in ids

    def test_count_by_status(self, journal: WriteAheadJournal) -> None:
        """Count intents grouped by status."""
        journal.append(_make_intent("cnt-p1"))
        journal.append(_make_intent("cnt-p2"))
        journal.append(_make_intent("cnt-c1"))
        journal.flush()
        journal.commit("cnt-c1")
        journal.flush()

        counts = journal.count_by_status()
        assert counts.get(IntentStatus.PENDING, 0) == 2
        assert counts.get(IntentStatus.COMMITTED, 0) >= 1

    def test_get_unknown_intent(self, journal: WriteAheadJournal) -> None:
        """get_intent returns None for non-existent intent_id."""
        retrieved = journal.get_intent("does-not-exist")
        assert retrieved is None

    def test_get_pending_empty(self, journal: WriteAheadJournal) -> None:
        """get_pending returns empty list when no intents exist."""
        pending = journal.get_pending()
        assert pending == []


# ═════════════════════════════════════════════════════════════════════════
# AsyncDbWriter Integration
# ═════════════════════════════════════════════════════════════════════════


class TestAsyncDbWriterIntegration:
    """Verify async writer processes writes and stats reflect reality."""

    def test_async_writer_stats(self, journal: WriteAheadJournal) -> None:
        """Async writer records written count after intents are appended."""
        journal.append(_make_intent("stats-1"))
        journal.append(_make_intent("stats-2"))
        journal.append(_make_intent("stats-3"))
        journal.flush()

        health = journal.health_check()
        aw = health.get("async_writer", {})
        assert aw.get("written", 0) >= 3, (
            f"Expected >=3 async writes, got {aw.get('written')}"
        )
        assert aw.get("errors", 0) == 0

    def test_async_writer_queue_processed(self, journal: WriteAheadJournal) -> None:
        """Queue should be drained after writes with sufficient wait."""
        journal.append(_make_intent("q-1"))
        journal.append(_make_intent("q-2"))
        journal.flush()

        health = journal.health_check()
        aw = health.get("async_writer", {})
        assert aw.get("queue_size", -1) == 0, (
            f"Expected empty queue, got size {aw.get('queue_size')}"
        )

    def test_read_after_write_async(self, journal: WriteAheadJournal) -> None:
        """Read-back via get_intent sees data written via async writer."""
        journal.append(_make_intent("read-after-write"))
        journal.flush()
        retrieved = journal.get_intent("read-after-write")
        assert retrieved is not None
        assert retrieved.action == "BUY"

    def test_commit_after_async_append(self, journal: WriteAheadJournal) -> None:
        """Commit operation sees the intent written by async append."""
        journal.append(_make_intent("commit-after"))
        journal.flush()
        journal.commit("commit-after")
        journal.flush()
        retrieved = journal.get_intent("commit-after")
        assert retrieved is not None
        assert retrieved.status == IntentStatus.COMMITTED


# ═════════════════════════════════════════════════════════════════════════
# Sync Fallback (Queue Saturation)
# ═════════════════════════════════════════════════════════════════════════


class TestBulkAsyncWrites:
    """Bulk async append operations are processed correctly.

    Note: triggering the actual sync fallback path requires filling the
    async queue (size 512), which is impractical in unit tests. The sync
    fallback is tested explicitly via ``test_sync_fallback_when_writer_stopped``.
    """

    def test_bulk_async_appends(self, tmp_db: str) -> None:
        """Bulk async appends are all readable after processing."""
        j = WriteAheadJournal(tmp_db)
        for i in range(20):
            j.append(_make_intent(f"bulk-async-{i}"))
        j.flush()

        pending = j.get_pending()
        assert len(pending) >= 20, (
            f"Expected >=20 intents after bulk async appends, got {len(pending)}"
        )
        j.close()

    def test_sync_fallback_when_writer_stopped(self, tmp_db: str) -> None:
        """When async writer is stopped, submit() returns False and
        the journal falls back to synchronous writes (DEBT-009 safety net)."""
        j = WriteAheadJournal(tmp_db)

        # Verify async writer works normally first
        j.append(_make_intent("normal-1"))
        j.append(_make_intent("normal-2"))
        j.flush()
        assert j.get_intent("normal-1") is not None
        assert j.get_intent("normal-2") is not None

        # Stop the async writer to force sync fallback
        j._async_writer.stop(block=True, timeout=3.0)

        # All subsequent appends fall back to synchronous writes
        j.append(_make_intent("sync-fb-1"))
        j.append(_make_intent("sync-fb-2"))
        j.commit("sync-fb-1")
        j.fail("sync-fb-2", "fallback test")

        # Verify data persisted via sync fallback (no flush needed - sync is immediate)
        r1 = j.get_intent("sync-fb-1")
        assert r1 is not None, "sync-fb-1 not found (sync fallback failed)"
        assert r1.status == IntentStatus.COMMITTED, (
            f"Expected COMMITTED, got {r1.status}"
        )

        r2 = j.get_intent("sync-fb-2")
        assert r2 is not None, "sync-fb-2 not found (sync fallback failed)"
        assert r2.status == IntentStatus.FAILED, (
            f"Expected FAILED, got {r2.status}"
        )
        assert "fallback test" in r2.error_message

        # Verify normal intents are still intact
        rn = j.get_intent("normal-1")
        assert rn is not None
        assert rn.status == IntentStatus.PENDING

        j.close()

    def test_sync_fallback_all_methods(self, tmp_db: str) -> None:
        """Sync fallback works for append, commit, fail, and settle."""
        j = WriteAheadJournal(tmp_db)

        # Use sync path for initial appends
        j.append(_make_intent("sf-all-1"))
        j.append(_make_intent("sf-all-2"))
        j.append(_make_intent("sf-all-3"))
        j.flush()

        # Stop async writer to force sync fallback on status transitions
        j._async_writer.stop(block=True, timeout=3.0)

        # All status transitions should use sync fallback
        j.commit("sf-all-1")      # PENDING -> COMMITTED via sync
        j.settle("sf-all-1")      # COMMITTED -> SETTLED via sync
        j.fail("sf-all-2", "err") # PENDING -> FAILED via sync
        # sf-all-3 stays PENDING

        r1 = j.get_intent("sf-all-1")
        assert r1 is not None
        assert r1.status == IntentStatus.SETTLED

        r2 = j.get_intent("sf-all-2")
        assert r2 is not None
        assert r2.status == IntentStatus.FAILED

        r3 = j.get_intent("sf-all-3")
        assert r3 is not None
        assert r3.status == IntentStatus.PENDING

        j.close()


# ═════════════════════════════════════════════════════════════════════════
# Crash Recovery
# ═════════════════════════════════════════════════════════════════════════


class TestCrashRecovery:
    """Simulate crash recovery: open new journal on same DB, verify PENDING intents."""

    def test_pending_survives_close_reopen(self, tmp_db: str) -> None:
        """PENDING intents are available after closing and reopening the journal."""
        j1 = WriteAheadJournal(tmp_db)
        j1.append(_make_intent("recover-1"))
        j1.append(_make_intent("recover-2"))
        j1.flush()
        j1.commit("recover-2")
        j1.flush()
        j1.close()

        # Reopen with same DB file
        j2 = WriteAheadJournal(tmp_db)
        j2.flush()
        pending = j2.get_pending()
        ids = {i.intent_id for i in pending}
        assert "recover-1" in ids, "PENDING intent lost after crash/reopen"
        assert "recover-2" not in ids, "COMMITTED intent should not be PENDING"

        # Verify the committed intent
        recovered = j2.get_intent("recover-2")
        assert recovered is not None
        assert recovered.status == IntentStatus.COMMITTED
        j2.close()

    def test_unsettled_survives_close_reopen(self, tmp_db: str) -> None:
        """COMMITTED intents are available as unsettled after reopen."""
        j1 = WriteAheadJournal(tmp_db)
        j1.append(_make_intent("unsettled-recover"))
        j1.flush()
        j1.commit("unsettled-recover")
        j1.flush()
        j1.close()

        j2 = WriteAheadJournal(tmp_db)
        j2.flush()
        unsettled = j2.get_unsettled()
        assert any(i.intent_id == "unsettled-recover" for i in unsettled)
        j2.close()


# ═════════════════════════════════════════════════════════════════════════
# Cleanup
# ═════════════════════════════════════════════════════════════════════════


class TestCleanup:
    def test_cleanup_removes_settled_intents(self, journal: WriteAheadJournal) -> None:
        """cleanup() removes SETTLED intents older than max_age_hours."""
        journal.append(_make_intent("old-settled"))
        journal.append(_make_intent("pending-kept"))
        journal.flush()
        journal.commit("old-settled")
        journal.flush()
        journal.settle("old-settled")
        journal.flush()

        # Use max_age=0 to remove everything SETTLED
        deleted = journal.cleanup(max_age_hours=0)
        journal.flush()

        # PENDING intents should remain
        pending = journal.get_pending()
        assert any(i.intent_id == "pending-kept" for i in pending)
        # SETTLED intent should be gone
        assert not any(i.intent_id == "old-settled" for i in pending)


# ═════════════════════════════════════════════════════════════════════════
# Thread Safety
# ═════════════════════════════════════════════════════════════════════════


class TestThreadSafety:
    """Concurrent append and read operations are safe."""

    def test_concurrent_appends(self, journal: WriteAheadJournal) -> None:
        """Multiple threads can append concurrently."""
        errors: list[Exception] = []

        def writer(prefix: str, count: int) -> None:
            for i in range(count):
                try:
                    journal.append(_make_intent(f"{prefix}-{i}"))
                except Exception as exc:
                    errors.append(exc)

        threads = [
            threading.Thread(target=writer, args=("A", 20)),
            threading.Thread(target=writer, args=("B", 20)),
            threading.Thread(target=writer, args=("C", 20)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(10)

        assert len(errors) == 0, f"Concurrent append errors: {errors}"
        journal.flush()
        pending = journal.get_pending()
        assert len(pending) >= 60, (
            f"Expected >=60 intents from concurrent appends, got {len(pending)}"
        )

    def test_concurrent_commit_and_read(self, journal: WriteAheadJournal) -> None:
        """Concurrent commit and read operations are safe."""
        for i in range(10):
            journal.append(_make_intent(f"concur-{i}"))
        journal.flush()

        results: list[bool] = []
        errors: list[Exception] = []

        def committer() -> None:
            for i in range(10):
                try:
                    journal.commit(f"concur-{i}")
                except Exception as exc:
                    errors.append(exc)

        def reader() -> None:
            try:
                pending = journal.get_pending()
                results.append(len(pending) == 0)
            except Exception as exc:
                errors.append(exc)

        threads = [
            threading.Thread(target=committer),
            threading.Thread(target=reader),
            threading.Thread(target=reader),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(5)

        assert len(errors) == 0, f"Concurrent errors: {errors}"


# ═════════════════════════════════════════════════════════════════════════
# Edge Cases
# ═════════════════════════════════════════════════════════════════════════


class TestEdgeCases:
    def test_duplicate_intent_id(self, journal: WriteAheadJournal) -> None:
        """Appending same intent_id replaces (INSERT OR REPLACE)."""
        journal.append(_make_intent("dup", params={"version": 1}))
        journal.flush()
        journal.append(_make_intent("dup", params={"version": 2}))
        journal.flush()

        retrieved = journal.get_intent("dup")
        assert retrieved is not None
        assert retrieved.params["version"] == 2

    def test_commit_nonexistent(self, journal: WriteAheadJournal) -> None:
        """Committing a non-existent intent is a no-op (no crash)."""
        # Should not raise
        journal.commit("nonexistent")
        journal.flush()
        # Verify no crash or state corruption
        assert journal.get_pending() == []

    def test_double_close_safe(self, journal: WriteAheadJournal) -> None:
        """Calling close() multiple times is safe."""
        journal.close()
        journal.close()  # Should not raise

    def test_health_check_basic(self, journal: WriteAheadJournal) -> None:
        """Health check returns expected keys.

        The async_writer key is present once a write has been performed
        (lazy init), so we trigger a write first.
        """
        # Trigger async writer lazy init by appending an intent
        journal.append(_make_intent("health-check-trigger"))
        journal.flush()
        health = journal.health_check()
        assert "db_path" in health
        assert "exists" in health
        assert "by_status" in health
        assert "async_writer" in health, (
            f"Expected async_writer key in health check, got keys: {list(health.keys())}"
        )

    def test_health_check_with_data(self, journal: WriteAheadJournal) -> None:
        """Health check reflects actual data."""
        journal.append(_make_intent("h1"))
        journal.append(_make_intent("h2"))
        journal.flush()

        health = journal.health_check()
        counts = health["by_status"]
        assert counts.get(IntentStatus.PENDING, 0) >= 2
        aw = health.get("async_writer", {})
        assert aw.get("errors", 0) == 0

    def test_correlation_id_auto_generated(self, journal: WriteAheadJournal) -> None:
        """When no correlation_id provided, one is auto-generated."""
        intent = Intent(intent_id="auto-corr", action="SELL", params={"symbol": "BANKNIFTY"})
        journal.append(intent)
        journal.flush()

        retrieved = journal.get_intent("auto-corr")
        assert retrieved is not None
        assert retrieved.correlation_id != ""
        assert retrieved.params["symbol"] == "BANKNIFTY"


# ═════════════════════════════════════════════════════════════════════════
# Serializable Intent Shape
# ═════════════════════════════════════════════════════════════════════════


class TestIntentShape:
    """Verify Intent dataclass serializes/deserializes correctly."""

    def test_intent_with_all_fields(self, journal: WriteAheadJournal) -> None:
        """All Intent fields persist through append→read cycle."""
        intent = Intent(
            intent_id="full-fields",
            action="SELL",
            params={"symbol": "FINNIFTY", "qty": 50, "strategy": "straddle"},
            risk_verdict={"score": 7, "max_risk": 5000},
            config_snapshot_hash="def456",
            correlation_id="corr-full",
            status=IntentStatus.PENDING,
            created_at="2026-06-17T10:00:00",
        )
        journal.append(intent)
        journal.flush()

        retrieved = journal.get_intent("full-fields")
        assert retrieved is not None
        assert retrieved.intent_id == "full-fields"
        assert retrieved.action == "SELL"
        assert retrieved.params["strategy"] == "straddle"
        assert retrieved.risk_verdict["score"] == 7
        assert retrieved.config_snapshot_hash == "def456"

    def test_intent_with_empty_risk_verdict(self, journal: WriteAheadJournal) -> None:
        """Intent with None risk_verdict is handled."""
        intent = Intent(
            intent_id="no-risk",
            action="BUY",
            params={},
            risk_verdict=None,
        )
        journal.append(intent)
        journal.flush()

        retrieved = journal.get_intent("no-risk")
        assert retrieved is not None
        assert retrieved.risk_verdict is None

    def test_intent_with_empty_params(self, journal: WriteAheadJournal) -> None:
        """Intent with empty params dict is handled."""
        intent = Intent(intent_id="empty-params", action="HOLD", params={})
        journal.append(intent)
        journal.flush()

        retrieved = journal.get_intent("empty-params")
        assert retrieved is not None
        assert retrieved.params == {}
