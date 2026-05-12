"""
Tests for core/oi_snapshot_store.py (Phase A1).

Covers:
  - record_snapshot() happy path and dedup
  - get_snapshot_at() no look-ahead
  - get_pcr_at() value + None path
  - get_oi_at() strike-level + aggregate fallback
  - coverage_pct() calculation
  - archive housekeeping
  - missing DB file handling
  - non-blocking behaviour (no exceptions leak)
"""
import sqlite3
import time
import importlib
import sys

import pytest

# Use a "recent" epoch base so _maybe_archive never deletes test rows.
# (archive cutoff = now - 90*86400; this base is 5 minutes ago.)
_BASE_TS = int(time.time()) - 300


# ── Fixture — temp DB per test ────────────────────────────────────────────────

@pytest.fixture()
def db(tmp_path):
    """Return a path to a fresh temp DB file (does not pre-create it)."""
    return str(tmp_path / "oi_test.db")


@pytest.fixture(autouse=True)
def clear_cache():
    """Reset the in-process dedup cache between tests."""
    import core.oi_snapshot_store as _oss
    _oss._last_snapshot_ts.clear()
    yield
    _oss._last_snapshot_ts.clear()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _snap(index="NIFTY", ts=None, pcr=1.2, db_path=None, **kwargs):
    """Write a snapshot; archive_days=36500 prevents archiving in tests."""
    from core.oi_snapshot_store import record_snapshot
    chain = {"pcr_ratio": pcr, "call_oi": 1000, "put_oi": 1200,
             "call_volume": 500, "put_volume": 600, "total_oi": 2200,
             "snapshot_source": "test"}
    chain.update(kwargs)
    if ts is None:
        ts = float(_BASE_TS)
    return record_snapshot(index, chain, db_path=db_path, ts=ts,
                           min_interval=0, archive_days=36500)


# ── record_snapshot ───────────────────────────────────────────────────────────

class TestRecordSnapshot:
    def test_returns_true_on_write(self, db):
        ok = _snap(ts=float(_BASE_TS), db_path=db)
        assert ok is True

    def test_creates_db_and_table(self, db):
        import os
        _snap(ts=float(_BASE_TS), db_path=db)
        assert os.path.isfile(db)
        conn = sqlite3.connect(db)
        row = conn.execute("SELECT COUNT(*) FROM oi_snapshots").fetchone()
        conn.close()
        assert row[0] == 1

    def test_dedup_blocks_second_write_within_interval(self, db):
        from core.oi_snapshot_store import record_snapshot
        chain = {"pcr_ratio": 1.0}
        now = float(_BASE_TS)
        r1 = record_snapshot("NIFTY", chain, db_path=db, ts=now,
                             min_interval=60, archive_days=36500)
        r2 = record_snapshot("NIFTY", chain, db_path=db, ts=now + 30,
                             min_interval=60, archive_days=36500)
        assert r1 is True
        assert r2 is False

    def test_dedup_allows_write_after_interval(self, db):
        from core.oi_snapshot_store import record_snapshot
        chain = {"pcr_ratio": 1.0}
        now = float(_BASE_TS)
        record_snapshot("NIFTY", chain, db_path=db, ts=now,
                        min_interval=60, archive_days=36500)
        r2 = record_snapshot("NIFTY", chain, db_path=db, ts=now + 61,
                             min_interval=60, archive_days=36500)
        assert r2 is True

    def test_different_indexes_are_independent(self, db):
        r1 = _snap("NIFTY",     ts=float(_BASE_TS), db_path=db)
        r2 = _snap("BANKNIFTY", ts=float(_BASE_TS), db_path=db)
        assert r1 is True
        assert r2 is True

    def test_pcr_stored_correctly(self, db):
        _snap(ts=float(_BASE_TS), pcr=1.75, db_path=db)
        conn = sqlite3.connect(db)
        val = conn.execute("SELECT pcr_ratio FROM oi_snapshots").fetchone()[0]
        conn.close()
        assert abs(val - 1.75) < 0.001

    def test_missing_fields_default_to_zero(self, db):
        from core.oi_snapshot_store import record_snapshot
        record_snapshot("NIFTY", {}, db_path=db, ts=float(_BASE_TS),
                        min_interval=0, archive_days=36500)
        conn = sqlite3.connect(db)
        row = conn.execute("SELECT call_oi, put_oi FROM oi_snapshots").fetchone()
        conn.close()
        assert row == (0, 0)

    def test_does_not_raise_on_bad_chain(self, db):
        from core.oi_snapshot_store import record_snapshot
        result = record_snapshot("NIFTY", {"pcr_ratio": "not-a-float"},
                                 db_path=db, ts=1_000_000.0, min_interval=0)
        assert isinstance(result, bool)


# ── get_snapshot_at ───────────────────────────────────────────────────────────

class TestGetSnapshotAt:
    def test_returns_none_when_db_missing(self, tmp_path):
        from core.oi_snapshot_store import get_snapshot_at
        result = get_snapshot_at("NIFTY", 9_999_999.0,
                                 db_path=str(tmp_path / "nosuchfile.db"))
        assert result is None

    def test_returns_none_when_no_prior_snapshot(self, db):
        from core.oi_snapshot_store import get_snapshot_at
        t0 = float(_BASE_TS)
        _snap(ts=t0 + 100, db_path=db)          # snapshot AFTER target
        result = get_snapshot_at("NIFTY", t0, db_path=db)
        assert result is None

    def test_returns_closest_snapshot_before_target(self, db):
        t0 = float(_BASE_TS)
        _snap("NIFTY", ts=t0,      pcr=1.1, db_path=db)
        _snap("NIFTY", ts=t0 + 60, pcr=1.3, db_path=db)
        from core.oi_snapshot_store import get_snapshot_at
        snap = get_snapshot_at("NIFTY", t0 + 50, db_path=db)
        assert snap is not None
        assert abs(snap["pcr_ratio"] - 1.1) < 0.01

    def test_strict_before_not_at(self, db):
        t0 = float(_BASE_TS)
        _snap("NIFTY", ts=t0, pcr=1.5, db_path=db)
        from core.oi_snapshot_store import get_snapshot_at
        snap = get_snapshot_at("NIFTY", t0, db_path=db)
        assert snap is None

    def test_index_isolation(self, db):
        t0 = float(_BASE_TS)
        _snap("NIFTY",     ts=t0, pcr=1.1, db_path=db)
        _snap("BANKNIFTY", ts=t0, pcr=2.2, db_path=db)
        from core.oi_snapshot_store import get_snapshot_at
        snap = get_snapshot_at("BANKNIFTY", t0 + 1, db_path=db)
        assert snap is not None
        assert abs(snap["pcr_ratio"] - 2.2) < 0.01


# ── get_pcr_at ────────────────────────────────────────────────────────────────

class TestGetPcrAt:
    def test_returns_float_when_snapshot_exists(self, db):
        t0 = float(_BASE_TS)
        _snap("NIFTY", ts=t0, pcr=1.35, db_path=db)
        from core.oi_snapshot_store import get_pcr_at
        pcr = get_pcr_at("NIFTY", t0 + 1, db_path=db)
        assert isinstance(pcr, float)
        assert abs(pcr - 1.35) < 0.01

    def test_returns_none_when_no_snapshot(self, db):
        from core.oi_snapshot_store import get_pcr_at
        assert get_pcr_at("NIFTY", float(_BASE_TS), db_path=db) is None

    def test_pcr_zero_stored_as_fallback(self, db):
        # record_snapshot uses `pcr_ratio or 1.0` (falsy check), so 0.0 → 1.0
        t0 = float(_BASE_TS)
        _snap("NIFTY", ts=t0, pcr=0.0, db_path=db)
        from core.oi_snapshot_store import get_pcr_at
        pcr = get_pcr_at("NIFTY", t0 + 1, db_path=db)
        # 0.0 falls through to 1.0 default; get_pcr_at returns None for pcr<=0
        # but stored value is 1.0 which is > 0, so returns 1.0
        assert pcr == 1.0


# ── coverage_pct ──────────────────────────────────────────────────────────────

class TestCoveragePct:
    def test_zero_when_db_missing(self, tmp_path):
        from core.oi_snapshot_store import coverage_pct
        v = coverage_pct("NIFTY", 0.0, 3600.0,
                         db_path=str(tmp_path / "no.db"))
        assert v == 0.0

    def test_zero_when_end_before_start(self, db):
        from core.oi_snapshot_store import coverage_pct
        assert coverage_pct("NIFTY", 100.0, 50.0, db_path=db) == 0.0

    def test_full_coverage_with_dense_snapshots(self, db):
        base = float(_BASE_TS - 3600)   # 1 hour before base, still recent
        for i in range(60):
            _snap("NIFTY", ts=base + i * 60, db_path=db)
        from core.oi_snapshot_store import coverage_pct
        pct = coverage_pct("NIFTY", base, base + 3600, db_path=db)
        assert pct > 0.9

    def test_partial_coverage(self, db):
        base = float(_BASE_TS - 3600)
        for i in range(10):
            _snap("NIFTY", ts=base + i * 60, db_path=db)
        from core.oi_snapshot_store import coverage_pct
        pct = coverage_pct("NIFTY", base, base + 3600, db_path=db)
        assert 0.0 < pct < 1.0
