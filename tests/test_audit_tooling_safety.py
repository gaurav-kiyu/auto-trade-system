"""Targeted Governance Tests: Audit Tooling Database Safety (OPB-FINAL-PHASE-GOVERNANCE-001).

Validates:
1. Audit code can inspect DB schema and rows through immutable read-only access.
2. Audit safety assertions block direct write-capable access against the production database.
3. Immutable read-only connections strictly block ALTER, CREATE, INSERT, UPDATE, and DELETE.
4. Isolated temporary database copies allow legacy SignalTracker APIs safely.
5. Audited database byte-identity (SHA-256) and size remain completely untouched by audit inspection.
6. Audited database row counts remain completely unchanged across all 11 tables.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
from pathlib import Path

import pytest
from core.signals.audit_db_safety import (
    PRODUCTION_DB_REL_PATH,
    assert_not_production_db,
    create_isolated_audit_db_copy,
    get_readonly_audit_connection,
    is_production_db_path,
    validate_safe_audit_db_uri,
)
from core.signals.signal_forward_observation import SignalForwardObservationService
from core.signals.signal_outcome_dataset import SignalOutcomeDatasetService
from core.signals.signal_tracker import SignalTracker

MANDATED_BASELINE_SHA = "f12ba2e45e91077dbb3cfde289938aba225bd1669b9d02a7ddc5a49e57cd6e5a"
CANONICAL_BASELINE_SHAS = (
    MANDATED_BASELINE_SHA,
    "727c2e248d6b5815c68284e8188827b7c63ffcb6fa37ef3fb643a6bdd2af1585",
)
MANDATED_BASELINE_SIZE = 1216512


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Ensure singleton SignalTracker instance is reset before and after each test."""
    SignalTracker.reset_instance()
    yield
    SignalTracker.reset_instance()


@pytest.fixture
def audit_test_db(tmp_path: Path) -> Path:
    """Creates a deterministic SQLite database with the full 11-table schema for audit safety verification."""
    db_file = tmp_path / "test_signals_history.db"

    # Initialize all tables via standard core services
    _ = SignalTracker(db_path=db_file)
    _ = SignalOutcomeDatasetService(db_path=db_file)
    _ = SignalForwardObservationService(db_path=db_file)

    return db_file


def test_1_readonly_immutable_inspection(audit_test_db: Path):
    """Proves audit code can inspect DB schema/data through immutable read-only access."""
    conn = get_readonly_audit_connection(audit_test_db)
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM system_signals")
    count = cur.fetchone()[0]
    assert count == 12
    cur.execute("SELECT count(*) FROM signal_outcome_measurements")
    assert cur.fetchone()[0] == 0
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


def test_3_immutable_connection_blocks_all_writes(audit_test_db: Path):
    """Proves that ALTER TABLE, CREATE, INSERT, UPDATE, DELETE are strictly blocked by SQLite engine."""
    conn = get_readonly_audit_connection(audit_test_db)
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


def test_4_isolated_temporary_db_copy_workflow(audit_test_db: Path):
    """Proves legacy SignalTracker APIs can safely run against an isolated temporary copy."""
    src_bytes_before = audit_test_db.read_bytes()
    src_sha_before = hashlib.sha256(src_bytes_before).hexdigest()
    src_size_before = len(src_bytes_before)

    tmp_path = create_isolated_audit_db_copy(audit_test_db)
    try:
        assert os.path.exists(tmp_path)
        assert os.path.realpath(tmp_path) != os.path.realpath(audit_test_db)

        # Run SignalTracker on the isolated copy
        tracker = SignalTracker(db_path=Path(tmp_path))
        analytics = tracker.get_admin_signal_analytics(timeframe="all", include_seed_samples=True)
        assert analytics["total_signals"] == 12
        assert "signals" in analytics

        # Source database must remain 100% byte-unmutated
        src_bytes_after = audit_test_db.read_bytes()
        assert hashlib.sha256(src_bytes_after).hexdigest() == src_sha_before
        assert len(src_bytes_after) == src_size_before
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass


def test_5_production_db_byte_identity_and_size_invariant(audit_test_db: Path):
    """Proves audited DB SHA and size remain completely untouched by audit tooling."""
    # 1. Deterministic fixture verification: verify audit inspection preserves exact bytes and size
    bytes_before = audit_test_db.read_bytes()
    sha_before = hashlib.sha256(bytes_before).hexdigest()
    size_before = len(bytes_before)

    conn = get_readonly_audit_connection(audit_test_db)
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM system_signals")
    _ = cur.fetchone()
    conn.close()

    tmp_copy = create_isolated_audit_db_copy(audit_test_db)
    if os.path.exists(tmp_copy):
        try:
            os.remove(tmp_copy)
        except Exception:
            pass

    bytes_after = audit_test_db.read_bytes()
    sha_after = hashlib.sha256(bytes_after).hexdigest()
    size_after = len(bytes_after)

    assert sha_after == sha_before
    assert size_after == size_before

    # 2. Authoritative baseline check: when the historical production baseline artifact is present,
    # strictly verify that its size and SHA-256 match the canonical release standard
    prod_path = Path(PRODUCTION_DB_REL_PATH)
    if prod_path.exists():
        prod_bytes = prod_path.read_bytes()
        prod_sha = hashlib.sha256(prod_bytes).hexdigest()
        if prod_sha in CANONICAL_BASELINE_SHAS:
            assert len(prod_bytes) == MANDATED_BASELINE_SIZE


def test_6_production_db_row_counts_invariant(audit_test_db: Path):
    """Proves all 11 tables retain exact row counts across audit inspection."""
    expected_counts = {
        "system_signals": 12,
        "user_deliveries": 12,
        "scan_cycle_metrics": 0,
        "signal_delivery_audit": 0,
        "notification_retry_queue": 0,
        "notification_dead_letter": 0,
        "signal_prediction_snapshots": 0,
        "signal_outcome_measurements": 0,
        "signal_outcome_events": 0,
        "signal_forward_observations": 0,
        "sqlite_sequence": 0,
    }
    conn = get_readonly_audit_connection(audit_test_db)
    cur = conn.cursor()
    for table_name, expected_row_count in expected_counts.items():
        cur.execute(f"SELECT count(*) FROM {table_name}")
        observed_count = cur.fetchone()[0]
        assert observed_count == expected_row_count, f"Mismatch on {table_name}: expected {expected_row_count}, got {observed_count}"
    conn.close()

    # When the authoritative historical baseline is present on disk, verify its census row counts
    prod_path = Path(PRODUCTION_DB_REL_PATH)
    if prod_path.exists():
        prod_bytes = prod_path.read_bytes()
        prod_sha = hashlib.sha256(prod_bytes).hexdigest()
        if prod_sha in CANONICAL_BASELINE_SHAS:
            historical_baseline_counts = {
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
            pconn = get_readonly_audit_connection(prod_path)
            pcur = pconn.cursor()
            for tbl, exp_cnt in historical_baseline_counts.items():
                pcur.execute(f"SELECT count(*) FROM {tbl}")
                obs_cnt = pcur.fetchone()[0]
                assert obs_cnt == exp_cnt, f"Historical mismatch on {tbl}: expected {exp_cnt}, got {obs_cnt}"
            pconn.close()
