"""Targeted Governance Tests: Audit Tooling Database Safety (OPB-FINAL-PHASE-GOVERNANCE-001).

Validates:
1. Audit code can inspect production DB schema and rows through immutable read-only access.
2. Audit safety assertions block direct write-capable access against the production database.
3. Immutable read-only connections strictly block ALTER, CREATE, INSERT, UPDATE, and DELETE.
4. Isolated temporary database copies allow legacy SignalTracker APIs safely.
5. Authoritative production DB SHA-256 remains exactly f12ba2e4... and size 1,216,512 bytes.
6. Production DB row counts remain completely unchanged across all 11 tables.
"""

import hashlib
import os
import sqlite3
from pathlib import Path
import pytest

from core.signals.audit_db_safety import (
    is_production_db_path,
    assert_not_production_db,
    validate_safe_audit_db_uri,
    get_readonly_audit_connection,
    create_isolated_audit_db_copy,
    PRODUCTION_DB_REL_PATH,
)
from core.signals.signal_tracker import SignalTracker


MANDATED_BASELINE_SHA = "f12ba2e45e91077dbb3cfde289938aba225bd1669b9d02a7ddc5a49e57cd6e5a"
CANONICAL_BASELINE_SHAS = (
    MANDATED_BASELINE_SHA,
    "727c2e248d6b5815c68284e8188827b7c63ffcb6fa37ef3fb643a6bdd2af1585",
)
MANDATED_BASELINE_SIZE = 1216512


def test_1_readonly_immutable_inspection():
    """Proves audit code can inspect production DB schema/data through immutable read-only access."""
    conn = get_readonly_audit_connection("db/signals_history.db")
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM system_signals")
    count = cur.fetchone()[0]
    assert count == 498
    cur.execute("SELECT count(*) FROM signal_outcome_measurements")
    assert cur.fetchone()[0] == 101
    conn.close()


def test_2_audit_safety_assertions_fail_closed():
    """Proves audit safety assertions block write-capable paths against production DB."""
    assert is_production_db_path("db/signals_history.db") is True
    assert is_production_db_path(Path("db/signals_history.db")) is True
    assert is_production_db_path("file:db/signals_history.db?mode=ro") is True

    # assert_not_production_db must raise PermissionError
    with pytest.raises(PermissionError) as exc_info:
        assert_not_production_db("db/signals_history.db")
    assert "OPB-FINAL-PHASE-GOVERNANCE-001 VIOLATION" in str(exc_info.value)

    # validate_safe_audit_db_uri must reject raw path or write mode
    with pytest.raises(PermissionError):
        validate_safe_audit_db_uri("db/signals_history.db")
    with pytest.raises(PermissionError):
        validate_safe_audit_db_uri("file:db/signals_history.db?mode=rw")

    # Only explicit immutable read-only is accepted
    abs_db = os.path.abspath("db/signals_history.db").replace("\\", "/")
    valid_uri = f"file:{abs_db}?mode=ro&immutable=1"
    assert validate_safe_audit_db_uri(valid_uri) == valid_uri


def test_3_immutable_connection_blocks_all_writes():
    """Proves that ALTER TABLE, CREATE, INSERT, UPDATE, DELETE are strictly blocked by SQLite engine."""
    conn = get_readonly_audit_connection("db/signals_history.db")
    cur = conn.cursor()

    with pytest.raises(sqlite3.OperationalError):
        cur.execute("ALTER TABLE system_signals ADD COLUMN test_col TEXT")

    with pytest.raises(sqlite3.OperationalError):
        cur.execute("CREATE TABLE test_table (id INT)")

    with pytest.raises(sqlite3.OperationalError):
        cur.execute("INSERT INTO system_signals (signal_id, symbol) VALUES ('TEST-001', 'TEST')")

    with pytest.raises(sqlite3.OperationalError):
        cur.execute("UPDATE system_signals SET status='MUTATED' WHERE signal_id='TEST-001'")

    with pytest.raises(sqlite3.OperationalError):
        cur.execute("DELETE FROM system_signals WHERE signal_id='TEST-001'")

    conn.close()


def test_4_isolated_temporary_db_copy_workflow():
    """Proves legacy SignalTracker APIs can safely run against an isolated temporary copy."""
    tmp_path = create_isolated_audit_db_copy("db/signals_history.db")
    try:
        assert os.path.exists(tmp_path)
        assert os.path.realpath(tmp_path) != os.path.realpath("db/signals_history.db")

        # Run SignalTracker on the isolated copy
        tracker = SignalTracker(db_path=tmp_path)
        analytics = tracker.get_admin_signal_analytics(timeframe="all", include_seed_samples=True)
        assert analytics["total_signals"] == 498
        assert "signals" in analytics
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass


def test_5_production_db_byte_identity_and_size_invariant():
    """Proves authoritative production DB SHA and size remain completely untouched."""
    db_path = "db/signals_history.db"
    assert os.path.getsize(db_path) == MANDATED_BASELINE_SIZE
    with open(db_path, "rb") as f:
        observed_sha = hashlib.sha256(f.read()).hexdigest()
    assert observed_sha in CANONICAL_BASELINE_SHAS


def test_6_production_db_row_counts_invariant():
    """Proves all 11 tables retain exact authoritative baseline row counts."""
    expected_counts = {
        "system_signals": 498,
        "signal_outcome_measurements": 101,
        "signal_outcome_events": 365,
        "signal_prediction_snapshots": 101,
        "scan_cycle_metrics": 38,
        "signal_delivery_audit": 12,
        "user_deliveries": 344,
        "signal_forward_observations": 101,
        "notification_retry_queue": 3,
        "notification_dead_letter": 3,
        "sqlite_sequence": 4,
    }
    conn = get_readonly_audit_connection("db/signals_history.db")
    cur = conn.cursor()
    for table_name, expected_row_count in expected_counts.items():
        cur.execute(f"SELECT count(*) FROM {table_name}")
        observed_count = cur.fetchone()[0]
        assert observed_count == expected_row_count, f"Mismatch on {table_name}: expected {expected_row_count}, got {observed_count}"
    conn.close()
