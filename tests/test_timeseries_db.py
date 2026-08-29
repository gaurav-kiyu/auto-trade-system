"""Tests for core.persistence.timeseries_db — TimeSeriesDataLake.

Covers:
- insert_tick()/get_historical_candles() basic round-trip (real DuckDB, tmp
  path — no real network/broker calls)
- close() is safe to call multiple times and after close() the lake no
  longer accepts inserts
- get_historical_candles() on an empty/missing symbol returns [] rather
  than raising
- singleton accessor get_timeseries_lake()/reset_timeseries_lake(), mirroring
  core.loop_watchdog's get_loop_watchdog()/reset_loop_watchdog() pattern
- importing the module alone never creates a DuckDB file (lazy singleton)
"""
from __future__ import annotations

import threading

import pytest
from core.persistence.timeseries_db import (
    TimeSeriesDataLake,
    get_timeseries_lake,
    reset_timeseries_lake,
)


@pytest.fixture(autouse=True)
def _reset_singleton():
    reset_timeseries_lake()
    yield
    reset_timeseries_lake()


class TestInsertAndAggregate:
    def test_insert_and_get_historical_candles_round_trip(self, tmp_path):
        lake = TimeSeriesDataLake(db_path=str(tmp_path / "ts.duckdb"))
        try:
            lake.insert_tick("NIFTY", 23000.0, 1000, source="test")
            lake.insert_tick("NIFTY", 23050.0, 1500, source="test")
            lake.insert_tick("NIFTY", 22950.0, 1200, source="test")
            candles = lake.get_historical_candles("NIFTY", minutes=5)
            assert len(candles) >= 1
            row = candles[0]
            assert row["symbol"] == "NIFTY"
            assert row["open"] == 23000.0
            assert row["high"] == 23050.0
            assert row["low"] == 22950.0
            assert row["close"] == 22950.0
            assert row["volume"] == 1000 + 1500 + 1200
        finally:
            lake.close()

    def test_get_historical_candles_unknown_symbol_returns_empty(self, tmp_path):
        lake = TimeSeriesDataLake(db_path=str(tmp_path / "ts.duckdb"))
        try:
            lake.insert_tick("NIFTY", 23000.0, 1000)
            assert lake.get_historical_candles("BANKNIFTY", minutes=5) == []
        finally:
            lake.close()

    def test_get_historical_candles_empty_db_returns_empty(self, tmp_path):
        lake = TimeSeriesDataLake(db_path=str(tmp_path / "ts.duckdb"))
        try:
            assert lake.get_historical_candles("NIFTY", minutes=5) == []
        finally:
            lake.close()


class TestCloseSafety:
    def test_close_is_idempotent(self, tmp_path):
        lake = TimeSeriesDataLake(db_path=str(tmp_path / "ts.duckdb"))
        lake.close()
        lake.close()  # must not raise

    def test_insert_after_close_does_not_raise(self, tmp_path):
        lake = TimeSeriesDataLake(db_path=str(tmp_path / "ts.duckdb"))
        lake.close()
        # _conn is None after close(); insert_tick()/get_historical_candles()
        # must fail open (no-op / empty list), never raise.
        lake.insert_tick("NIFTY", 23000.0, 1000)
        assert lake.get_historical_candles("NIFTY") == []

    def test_bad_db_path_fails_open_not_raise(self, tmp_path):
        # A path under a non-existent nested directory should fail to open;
        # _init_db()'s try/except must swallow it, leaving _conn None.
        bad_path = str(tmp_path / "does" / "not" / "exist" / "ts.duckdb")
        lake = TimeSeriesDataLake(db_path=bad_path)
        lake.insert_tick("NIFTY", 23000.0, 1000)  # must not raise
        assert lake.get_historical_candles("NIFTY") == []  # must not raise


class TestSingleton:
    def test_returns_same_instance(self, tmp_path):
        db_path = str(tmp_path / "singleton.duckdb")
        l1 = get_timeseries_lake(db_path)
        l2 = get_timeseries_lake(db_path)
        assert l1 is l2

    def test_reset_drops_singleton(self, tmp_path):
        db_path = str(tmp_path / "singleton.duckdb")
        l1 = get_timeseries_lake(db_path)
        reset_timeseries_lake()
        l2 = get_timeseries_lake(db_path)
        assert l1 is not l2

    def test_reset_closes_underlying_connection(self, tmp_path):
        db_path = str(tmp_path / "singleton.duckdb")
        lake = get_timeseries_lake(db_path)
        assert lake._conn is not None
        reset_timeseries_lake()
        # The old instance's connection must have been closed by reset.
        assert lake._conn is None

    def test_reset_with_no_instance_is_safe(self):
        reset_timeseries_lake()
        reset_timeseries_lake()  # must not raise even with nothing to reset


class TestImportHasNoSideEffect:
    def test_module_import_alone_creates_no_default_db_file(self, tmp_path, monkeypatch):
        """Regression guard: importing core.persistence.timeseries_db must
        never create timeseries.duckdb in the current working directory as
        an import-time side effect -- the singleton is lazy and only built
        on the first get_timeseries_lake() call."""
        monkeypatch.chdir(tmp_path)
        import importlib

        import core.persistence.timeseries_db as mod
        importlib.reload(mod)
        try:
            assert not (tmp_path / "timeseries.duckdb").exists()
        finally:
            mod.reset_timeseries_lake()


class TestThreadSafety:
    def test_concurrent_get_timeseries_lake_returns_one_instance(self, tmp_path):
        db_path = str(tmp_path / "concurrent.duckdb")
        results: list[TimeSeriesDataLake] = []

        def _get():
            results.append(get_timeseries_lake(db_path))

        threads = [threading.Thread(target=_get) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 8
        assert all(r is results[0] for r in results)
