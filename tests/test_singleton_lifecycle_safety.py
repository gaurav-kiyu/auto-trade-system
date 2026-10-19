import hashlib
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest
from core.signals.signal_forward_monitor import SignalForwardMonitorService
from core.signals.signal_forward_observation import SignalForwardObservationService
from core.signals.signal_outcome_resolver import HistoricalOutcomeResolverService, SignalBar
from core.signals.signal_outcome_tracker import SignalOutcomeTracker


@pytest.fixture(autouse=True)
def reset_all_singletons():
    SignalOutcomeTracker.reset_instance()
    SignalForwardObservationService.reset_instance()
    SignalForwardMonitorService.reset_instance()
    HistoricalOutcomeResolverService.reset_instance()
    yield
    SignalOutcomeTracker.reset_instance()
    SignalForwardObservationService.reset_instance()
    SignalForwardMonitorService.reset_instance()
    HistoricalOutcomeResolverService.reset_instance()


def _init_test_db(p: Path) -> None:
    conn = sqlite3.connect(str(p))
    conn.execute("""
        CREATE TABLE system_signals (
            signal_id TEXT PRIMARY KEY,
            symbol TEXT NOT NULL,
            category TEXT NOT NULL,
            entry_price REAL NOT NULL,
            stop_loss REAL NOT NULL,
            target_1 REAL NOT NULL,
            target_2 REAL NOT NULL,
            created_date TEXT NOT NULL,
            status TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            current_price REAL DEFAULT 0,
            pnl_pct REAL DEFAULT 0,
            first_touch TEXT DEFAULT '',
            first_touch_at TEXT DEFAULT '',
            first_touch_price REAL DEFAULT 0,
            outcome_confidence TEXT DEFAULT ''
        )
    """)
    conn.execute("""
        CREATE TABLE user_deliveries (
            delivery_id INTEGER PRIMARY KEY AUTOINCREMENT,
            signal_id TEXT NOT NULL,
            status TEXT NOT NULL,
            current_price REAL DEFAULT 0,
            pnl_pct REAL DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE signal_outcome_events (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            signal_id TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            observed_price REAL NOT NULL,
            hit_sl INTEGER NOT NULL,
            hit_t1 INTEGER NOT NULL,
            hit_t2 INTEGER NOT NULL,
            transition_note TEXT DEFAULT ''
        )
    """)
    conn.execute("""
        CREATE TABLE signal_forward_observations (
            forward_id TEXT PRIMARY KEY,
            signal_id TEXT UNIQUE NOT NULL,
            cohort_id TEXT NOT NULL,
            observation_source TEXT NOT NULL,
            forward_cutoff_version TEXT NOT NULL,
            registered_at TEXT NOT NULL,
            market_date TEXT NOT NULL,
            session_name TEXT DEFAULT '',
            score INTEGER NOT NULL,
            score_bucket TEXT NOT NULL,
            direction TEXT NOT NULL,
            symbol TEXT NOT NULL,
            category TEXT NOT NULL,
            entry_price REAL NOT NULL,
            stop_loss REAL NOT NULL,
            target_1 REAL NOT NULL,
            target_2 REAL NOT NULL,
            holding_horizon_days INTEGER NOT NULL,
            max_calendar_days INTEGER NOT NULL,
            observation_status TEXT NOT NULL,
            terminal_outcome TEXT NOT NULL,
            barrier_hit TEXT NOT NULL,
            is_resolved INTEGER NOT NULL,
            resolved_at TEXT,
            terminal_price REAL,
            terminal_return_pct REAL,
            pnl_r REAL,
            mfe_pct REAL,
            mfe_r REAL,
            mae_pct REAL,
            mae_r REAL,
            bars_held INTEGER,
            touch_timestamp TEXT,
            last_evaluated_at TEXT,
            evaluation_notes TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()


def test_01_writable_tracker_then_dry_run_resolver(tmp_path: Path):
    """Scenario A: Writable tracker must not contaminate a subsequent dry-run resolver."""
    db = tmp_path / "test.db"
    _init_test_db(db)

    # 1. Obtain writable tracker
    tracker_w = SignalOutcomeTracker.get_instance(db_path=db, read_only=False)
    assert tracker_w._read_only is False

    # 2. Obtain dry-run resolver
    res_dry = HistoricalOutcomeResolverService.get_instance(db_path=db, dry_run=True)
    assert res_dry._dry_run is True
    # The resolver's tracker must be read-only!
    assert res_dry._tracker._read_only is True, "Dry-run resolver received a writable tracker!"


def test_02_writable_forward_service_then_dry_run_resolver(tmp_path: Path):
    """Scenario A: Writable forward observation service must not contaminate dry-run resolver."""
    db = tmp_path / "test.db"
    _init_test_db(db)

    fwd_w = SignalForwardObservationService.get_instance(db_path=db, read_only=False)
    assert fwd_w._read_only is False

    res_dry = HistoricalOutcomeResolverService.get_instance(db_path=db, dry_run=True)
    assert res_dry._fwd_service._read_only is True, "Dry-run resolver received a writable forward service!"


def test_03_read_only_tracker_then_writable_request(tmp_path: Path):
    """Scenario B: Read-only tracker must not break a subsequent writable request."""
    db = tmp_path / "test.db"
    _init_test_db(db)

    # 1. Obtain read-only tracker
    tracker_ro = SignalOutcomeTracker.get_instance(db_path=db, read_only=True)
    assert tracker_ro._read_only is True

    # 2. Obtain normal writable tracker
    tracker_w = SignalOutcomeTracker.get_instance(db_path=db, read_only=False)
    assert tracker_w._read_only is False, "Normal writable request received a read-only tracker!"

    # 3. Verify write capability on tracker_w
    conn = tracker_w._get_conn()
    conn.execute("INSERT INTO system_signals (signal_id, symbol, category, entry_price, stop_loss, target_1, target_2, created_date, status, timestamp) VALUES ('S1', 'TEST', 'EQUITY', 100, 95, 105, 110, '2026-10-18', 'ACTIVE', '2026-10-18T10:00:00')")
    conn.commit()
    conn.close()


def test_04_read_only_forward_service_then_writable_request(tmp_path: Path):
    """Scenario B: Read-only forward service must not break a subsequent writable request."""
    db = tmp_path / "test.db"
    _init_test_db(db)

    fwd_ro = SignalForwardObservationService.get_instance(db_path=db, read_only=True)
    assert fwd_ro._read_only is True

    fwd_w = SignalForwardObservationService.get_instance(db_path=db, read_only=False)
    assert fwd_w._read_only is False, "Normal writable request received a read-only forward service!"


def test_05_different_database_paths(tmp_path: Path):
    """Scenario D: Instances for database A and database B remain completely isolated."""
    db_a = tmp_path / "db_a.db"
    db_b = tmp_path / "db_b.db"
    _init_test_db(db_a)
    _init_test_db(db_b)

    tracker_a = SignalOutcomeTracker.get_instance(db_path=db_a, read_only=False)
    tracker_b = SignalOutcomeTracker.get_instance(db_path=db_b, read_only=True)

    assert tracker_a._db_path.resolve() == db_a.resolve()
    assert tracker_b._db_path.resolve() == db_b.resolve()
    assert tracker_a._read_only is False
    assert tracker_b._read_only is True


def test_06_resolver_transitions_between_modes(tmp_path: Path):
    """Scenario E: Resolver transitions cleanly between writable and dry-run."""
    db = tmp_path / "test.db"
    _init_test_db(db)

    # 1. Writable resolver
    res_w = HistoricalOutcomeResolverService.get_instance(db_path=db, dry_run=False)
    assert res_w._dry_run is False
    assert res_w._tracker._read_only is False

    # 2. Switch to dry-run
    res_dry = HistoricalOutcomeResolverService.get_instance(db_path=db, dry_run=True)
    assert res_dry._dry_run is True
    assert res_dry._tracker._read_only is True
    assert res_dry._fwd_service._read_only is True

    # 3. Switch back to writable
    res_w2 = HistoricalOutcomeResolverService.get_instance(db_path=db, dry_run=False)
    assert res_w2._dry_run is False
    assert res_w2._tracker._read_only is False
    assert res_w2._fwd_service._read_only is False

def test_07_dry_run_construction_does_not_create_missing_db(tmp_path: Path):
    """Test 5 & 8: Dry-run construction does not create missing DB and fails closed on connect."""
    missing = tmp_path / "absent.db"
    assert not missing.exists()

    svc = HistoricalOutcomeResolverService.get_instance(db_path=missing, dry_run=True)
    assert not missing.exists(), "Dry-run construction created a missing DB file!"

    with pytest.raises(FileNotFoundError):
        svc._get_conn()


def test_08_dry_run_construction_does_not_initialize_schema(tmp_path: Path):
    """Test 6: Dry-run construction on empty file does not execute schema DDL."""
    empty_db = tmp_path / "empty.db"
    empty_db.touch()

    HistoricalOutcomeResolverService.get_instance(db_path=empty_db, dry_run=True)
    conn = sqlite3.connect(f"file:{empty_db.resolve().as_posix()}?mode=ro", uri=True)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = cur.fetchall()
    conn.close()
    assert len(tables) == 0, f"Dry-run created tables in empty DB: {tables}"


def test_09_dry_run_resolution_leaves_database_unchanged(tmp_path: Path):
    """Test 7: Dry-run resolution leaves logical and physical content unchanged."""
    db = tmp_path / "test.db"
    _init_test_db(db)

    # Insert a test signal
    conn = sqlite3.connect(str(db))
    conn.execute("""
        INSERT INTO system_signals (signal_id, symbol, category, entry_price, stop_loss, target_1, target_2, created_date, status, timestamp)
        VALUES ('S-DRY', 'ALPHA', 'EQUITY', 100, 95, 105, 110, '2026-10-18', 'ACTIVE', '2026-10-18T10:00:00')
    """)
    conn.commit()
    conn.close()

    def get_dump(p: Path) -> str:
        c = sqlite3.connect(f"file:{p.resolve().as_posix()}?mode=ro", uri=True)
        try:
            return "\n".join(c.iterdump())
        finally:
            c.close()

    dump_before = get_dump(db)

    svc = HistoricalOutcomeResolverService.get_instance(db_path=db, dry_run=True)

    def mock_fetch(symbol: str, category: str = "", start_date: str | None = None):
        return [
            SignalBar(open=100, high=101, low=94, close=94.5, timestamp="2026-10-18"),  # SL hit
        ]

    with patch.object(svc, "fetch_daily_bars", side_effect=mock_fetch):
        res = svc.resolve_all_pending(dry_run=True)

    assert res["status"] == "success"
    assert res["dry_run"] is True
    assert res["resolved_barriers"] == 1

    dump_after = get_dump(db)
    assert dump_before == dump_after, "Database dump changed during dry-run resolution!"


def test_10_no_wal_mode_change_through_dry_run(tmp_path: Path):
    """Test 9: Dry-run connections do not execute PRAGMA journal_mode = WAL."""
    db = tmp_path / "test_delete.db"
    conn = sqlite3.connect(str(db))
    conn.execute("PRAGMA journal_mode = DELETE;")
    mode_before = conn.execute("PRAGMA journal_mode;").fetchone()[0]
    conn.close()
    assert mode_before.upper() == "DELETE"

    svc = HistoricalOutcomeResolverService.get_instance(db_path=db, dry_run=True)
    c_ro = svc._get_conn()
    mode_after = c_ro.execute("PRAGMA journal_mode;").fetchone()[0]
    c_ro.close()
    # In mode=ro, journal_mode cannot and must not be altered to WAL
    assert mode_after.upper() == "DELETE", f"Journal mode was modified to {mode_after} in dry-run!"


def test_11_existing_normal_writable_behavior_compatible(tmp_path: Path):
    """Test 10: Existing normal writable operations work with 100% backward compatibility."""
    db = tmp_path / "test.db"
    _init_test_db(db)

    tracker = SignalOutcomeTracker.get_instance(db_path=db)
    assert tracker._read_only is False

    # Perform normal write
    conn = tracker._get_conn()
    conn.execute("INSERT INTO system_signals (signal_id, symbol, category, entry_price, stop_loss, target_1, target_2, created_date, status, timestamp) VALUES ('S-NORM', 'BETA', 'EQUITY', 200, 190, 210, 220, '2026-10-18', 'ACTIVE', '2026-10-18T10:00:00')")
    conn.commit()
    conn.close()

    res = tracker.expire_stale_signals()
    assert isinstance(res, dict)


def test_12_repeated_alternating_calls_no_config_leak(tmp_path: Path):
    """Test 12: Repeated alternating requests never leak configuration across singletons."""
    db = tmp_path / "test.db"
    _init_test_db(db)

    for i in range(10):
        want_ro = (i % 2 == 0)
        t = SignalOutcomeTracker.get_instance(db_path=db, read_only=want_ro)
        assert t._read_only is want_ro, f"Iteration {i}: expected read_only={want_ro}, got {t._read_only}"

        f = SignalForwardObservationService.get_instance(db_path=db, read_only=want_ro)
        assert f._read_only is want_ro, f"Iteration {i}: expected fwd read_only={want_ro}, got {f._read_only}"

        r = HistoricalOutcomeResolverService.get_instance(db_path=db, dry_run=want_ro)
        assert r._dry_run is want_ro, f"Iteration {i}: expected resolver dry_run={want_ro}, got {r._dry_run}"
        assert r._tracker._read_only is want_ro
        assert r._fwd_service._read_only is want_ro


def test_13_cli_dry_run_invokes_safe_path(tmp_path: Path):
    """Test 13: CLI execution with --dry-run uses the safe path end-to-end."""
    from core.signals.signal_outcome_resolver import main

    db = tmp_path / "test.db"
    _init_test_db(db)

    test_args = ["signal_outcome_resolver", "--db-path", str(db), "--dry-run"]
    with patch("sys.argv", test_args):
        # Must execute cleanly without writing to DB
        with patch.object(HistoricalOutcomeResolverService, "fetch_daily_bars", return_value=[]):
            main()


def test_14_timeout_is_quarantined_from_predictive_success(tmp_path: Path):
    """Test 14: TIMEOUT outcome updates resolved count but is excluded from predictive usable."""
    db = tmp_path / "test.db"
    _init_test_db(db)

    conn = sqlite3.connect(str(db))
    conn.execute("""
        INSERT INTO signal_forward_observations (
            forward_id, signal_id, cohort_id, observation_source, forward_cutoff_version,
            registered_at, market_date, session_name, score, score_bucket, direction,
            symbol, category, entry_price, stop_loss, target_1, target_2, holding_horizon_days,
            max_calendar_days, observation_status, terminal_outcome, barrier_hit, is_resolved,
            mfe_r, mae_r, created_at, updated_at
        ) VALUES (
            'FWD-1', 'SIG-1', 'COHORT-A', 'LIVE_SCAN', 'V1',
            '2026-10-18T10:00:00', '2026-10-18', 'REGULAR', 85, 'HIGH', 'DOWN',
            'FUT_TEST', 'FUTURES', 1000, 1050, 950, 900, 5, 7,
            'TIMEOUT', 'TIMEOUT', 'TIMEOUT', 1,
            0.0, 0.0, '2026-10-18T10:00:00', '2026-10-18T10:00:00'
        )
    """)
    conn.commit()
    conn.close()

    mon = SignalForwardMonitorService.get_instance(db_path=db)
    summary = mon.get_forward_summary()
    assert summary["total_registered"] == 1
    assert summary["total_resolved"] == 1
    assert summary["stale_unresolved_count"] == 0
    assert summary["predictive_usable_count"] == 0
    assert summary["data_quality_affected_count"] == 1


def test_15_canonical_db_not_used_as_fixture(tmp_path: Path):
    """Test 15: Canonical db path is not inadvertently selected as a test fixture.

    Verifies that:
    1. Singletons instantiated across the test lifecycle bind strictly to their
       provided fixture paths and never inadvertently resolve or default to the
       canonical production database path (db/signals_history.db).
    2. If the canonical database file exists on disk (e.g. on developer workstations),
       its size and SHA-256 remain completely unmodified by test execution.
    3. If the canonical database file is absent (e.g. in clean CI checkouts),
       it is never created as a side effect of running the safety test suite.
    """
    canonical_path = Path("db/signals_history.db").resolve()
    fixture_db = (tmp_path / "fixture_isolation_check.db").resolve()
    _init_test_db(fixture_db)

    # Record pre-test canonical state if file is present on disk
    canonical_existed_before = canonical_path.exists()
    canonical_hash_before = hashlib.sha256(canonical_path.read_bytes()).hexdigest() if canonical_existed_before else None

    # Instantiate all 4 core outcome services with explicit test fixture
    tracker = SignalOutcomeTracker.get_instance(db_path=fixture_db)
    fwd = SignalForwardObservationService.get_instance(db_path=fixture_db)
    mon = SignalForwardMonitorService.get_instance(db_path=fixture_db)
    resolver = HistoricalOutcomeResolverService.get_instance(db_path=fixture_db)

    # Invariant A: Services must bind strictly to the fixture and NEVER to canonical DB
    for service, name in [
        (tracker, "SignalOutcomeTracker"),
        (fwd, "SignalForwardObservationService"),
        (mon, "SignalForwardMonitorService"),
        (resolver, "HistoricalOutcomeResolverService"),
    ]:
        bound_path = getattr(service, "_db_path", None)
        assert bound_path is not None, f"{name} must have a bound _db_path"
        assert bound_path == fixture_db, f"{name} bound to {bound_path}, expected fixture {fixture_db}"
        assert bound_path != canonical_path, f"{name} must NOT bind to canonical path {canonical_path}"

    # Invariant B: Canonical database file must not be created if absent, or altered if present
    if not canonical_existed_before:
        assert not canonical_path.exists(), "Test execution must never create canonical db/signals_history.db"
    else:
        assert canonical_path.exists(), "Canonical database file must still exist"
        canonical_hash_after = hashlib.sha256(canonical_path.read_bytes()).hexdigest()
        assert canonical_hash_after == canonical_hash_before, "Canonical database was mutated during test execution"
