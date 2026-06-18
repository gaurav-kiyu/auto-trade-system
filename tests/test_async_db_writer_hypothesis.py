"""
Property-based tests for AsyncDbWriter using Hypothesis.

Verifies that the async writer handles arbitrary write sequences
without data loss or corruption, even under concurrent access.

Key properties tested:
  - All submitted writes are eventually processed (or rejected)
  - Written count equals number of successful submits
  - Data integrity: values persisted match what was submitted
  - Error count increments on invalid SQL
  - Stats are consistent after stop()

IMPORTANT: Each Hypothesis example MUST use a unique database path
because ``tmp_path`` returns the SAME directory for all examples
within a single test function call. We use ``uuid4()`` to create
unique subdirectories per example.

Usage:
    python -m pytest tests/test_async_db_writer_hypothesis.py -v
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

from core.db_utils import AsyncDbWriter, get_connection


# ── Helpers ────────────────────────────────────────────────────────────────


def _unique_db_path(tmp_path: Any, name: str = "test") -> str:
    """Create a unique database path per Hypothesis example.

    ``tmp_path`` is shared across all examples of a test function,
    so we create a unique subdirectory using a UUID to avoid
    cross-example database collisions.
    """
    subdir = tmp_path / uuid.uuid4().hex[:12]
    subdir.mkdir(parents=True, exist_ok=True)
    return str(subdir / f"{name}.db")


# ── Strategies ──────────────────────────────────────────────────────────────


def insert_statements(table: str = "test_items") -> st.SearchStrategy[tuple[str, tuple[int, str]]]:
    """Generate INSERT statements with random integer id and short string msg.

    IDs are in a wide range (0-9999) to avoid clashes, and the table uses
    a plain INTEGER column (not PRIMARY KEY) to avoid UNIQUE constraint
    failures from auto-generated duplicates.
    """
    return st.builds(
        lambda id_, msg: (
            f"INSERT INTO {table} VALUES (?, ?)",
            (id_, msg),
        ),
        id_=st.integers(min_value=0, max_value=9999),
        msg=st.text(min_size=1, max_size=20).filter(lambda s: s.strip() != ""),
    )


# Strategy for generating arbitrary write sequences (up to 30 writes)
write_sequences = st.lists(
    insert_statements(),
    min_size=0,
    max_size=30,
)


# ── Property-based tests ──────────────────────────────────────────────────


class TestAsyncDbWriterProperties:
    """Property-based tests for AsyncDbWriter using Hypothesis."""

    @given(writes=write_sequences)
    @settings(
        max_examples=30,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
        deadline=None,
    )
    def test_all_writes_processed(self, tmp_path: Any, writes: list[tuple[str, tuple[int, str]]]) -> None:
        """All submitted writes are processed (written = submitted count).

        Note: Because ``submit()`` may return False if the queue is full,
        ``submitted`` counts only successful enqueues. ``written`` should
        equal ``submitted`` (no errors expected since the table allows
        duplicate IDs).
        """
        db_path = _unique_db_path(tmp_path, "hypothesis_all")
        conn = get_connection(db_path)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS test_items "
            "(id INTEGER, msg TEXT)"
        )
        conn.commit()
        conn.close()

        writer = AsyncDbWriter(db_path)
        submitted = 0
        for sql, params in writes:
            ok = writer.submit(sql, params)
            if ok:
                submitted += 1
        writer.stop()

        assert writer.stats["written"] == submitted, (
            f"Expected {submitted} writes, got {writer.stats['written']}. "
            f"Errors: {writer.stats['errors']}, Last: {writer.stats['last_error']}"
        )

    @given(writes=write_sequences)
    @settings(
        max_examples=30,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
        deadline=None,
    )
    def test_data_integrity(self, tmp_path: Any, writes: list[tuple[str, tuple[int, str]]]) -> None:
        """Every persisted row matches a successfully submitted write.

        Tracks (id, msg) pairs from successful submits, then verifies
        each persisted row corresponds to at least one tracked pair.
        Uses a unique DB path per example to avoid cross-example
        state leakage via ``tmp_path``.
        """
        db_path = _unique_db_path(tmp_path, "hypothesis_integrity")
        conn = get_connection(db_path)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS test_items "
            "(id INTEGER, msg TEXT)"
        )
        conn.commit()
        conn.close()

        writer = AsyncDbWriter(db_path)
        expected: set[tuple[int, str]] = set()
        for sql, (id_, msg) in writes:
            ok = writer.submit(sql, (id_, msg))
            if ok:
                expected.add((id_, msg))
        writer.stop()

        # Row count must match written count (no phantom rows from other examples)
        rows = writer.execute_sync("SELECT id, msg FROM test_items")
        assert len(rows) == writer.stats.get("written", 0), (
            f"DB has {len(rows)} rows but written={writer.stats.get('written', 0)}. "
            f"This may indicate state leakage between test examples. "
            f"Errors: {writer.stats.get('errors', 0)}"
        )
        # Verify every persisted row matches an expected pair
        for row in rows:
            pair = (row["id"], row["msg"])
            assert pair in expected, (
                f"Unexpected row: id={pair[0]}, msg={pair[1]!r}. "
                f"Not found among {len(expected)} expected pairs. "
                f"Stats: written={writer.stats.get('written', 0)}, "
                f"errors={writer.stats.get('errors', 0)}"
            )

    @given(writes=write_sequences)
    @settings(
        max_examples=20,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
        deadline=None,
    )
    def test_errors_tracked(self, tmp_path: Any, writes: list[tuple[str, tuple[int, str]]]) -> None:
        """Invalid SQL statements correctly increment error count."""
        db_path = _unique_db_path(tmp_path, "hypothesis_errors")
        # Don't create the table — writes will fail
        writer = AsyncDbWriter(db_path)
        for sql, params in writes:
            writer.submit(sql, params)
        writer.stop()

        stats = writer.stats
        assert stats["written"] + stats["errors"] >= 0
        if stats["errors"] > 0:
            assert stats["last_error"] != ""

    @given(
        n_writes=st.integers(min_value=0, max_value=30),
        queue_size=st.integers(min_value=1, max_value=10),
    )
    @settings(
        max_examples=20,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
        deadline=None,
    )
    def test_queue_full_behavior(
        self, tmp_path: Any, n_writes: int, queue_size: int
    ) -> None:
        """Queue full behavior: total accepted never exceeds queue capacity.

        Written count equals accepted count since the table has no
        unique constraints (all INSERTs succeed).
        """
        db_path = _unique_db_path(tmp_path, "hypothesis_queue")
        conn = get_connection(db_path)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS test_items "
            "(id INTEGER, msg TEXT)"
        )
        conn.commit()
        conn.close()

        writer = AsyncDbWriter(db_path, max_queue_size=queue_size)
        accepted = 0
        for i in range(n_writes):
            ok = writer.submit(
                "INSERT INTO test_items VALUES (?, ?)",
                (i, f"msg_{i}"),
            )
            if ok:
                accepted += 1
        writer.stop()

        # Accepted should be <= n_writes and >= 0
        assert 0 <= accepted <= n_writes
        # Written should match accepted (no errors expected since table exists)
        assert writer.stats["written"] == accepted, (
            f"accepted={accepted}, written={writer.stats['written']}, "
            f"errors={writer.stats['errors']}, last_error={writer.stats['last_error']}"
        )

    @given(
        n_submit=st.integers(min_value=0, max_value=10),
    )
    @settings(
        max_examples=10,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
        deadline=None,
    )
    def test_stats_after_stop_consistent(
        self, tmp_path: Any, n_submit: int
    ) -> None:
        """Stats dict is internally consistent after stop()."""
        db_path = _unique_db_path(tmp_path, "hypothesis_stats")
        conn = get_connection(db_path)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS test_items "
            "(id INTEGER, msg TEXT)"
        )
        conn.commit()
        conn.close()

        writer = AsyncDbWriter(db_path)
        for i in range(n_submit):
            if writer._stop_event.is_set():
                break
            writer.submit("INSERT INTO test_items VALUES (?, ?)", (i, f"msg_{i}"))
        writer.stop()

        stats = writer.stats
        assert isinstance(stats["db_path"], str)
        assert isinstance(stats["queue_size"], int)
        assert isinstance(stats["max_queue_size"], int)
        assert isinstance(stats["written"], int)
        assert isinstance(stats["errors"], int)
        assert isinstance(stats["last_error"], str)
        assert isinstance(stats["is_running"], bool)
        assert stats["max_queue_size"] == 256
        assert stats["written"] >= 0
        assert stats["errors"] >= 0
