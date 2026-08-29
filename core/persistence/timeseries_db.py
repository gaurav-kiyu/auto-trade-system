"""Tick-level Time-Series Data Lake (DuckDB-backed).

Wired in as an opt-in tick recorder (config key ``timeseries_lake_enabled``,
default False -- see ``index_app/domains/trading/service.py::
TradingLoopService._record_tick_to_lake()``, called once per index per scan
cycle when enabled). This stores raw per-tick price/volume history for
fast on-the-fly OHLCV rollups via DuckDB's ``time_bucket`` -- genuinely
distinct data from anything else already live: ``core/oi_snapshot_store.py``
only records point-in-time OI, and ``db/trades.db``/the journal DBs store
completed trade/journal records, not tick history.

Public API: ``TimeSeriesDataLake(db_path=...)``, ``insert_tick(symbol,
price, volume, source)``, ``get_historical_candles(symbol, minutes)``,
``close()``, plus the process-wide singleton accessors
``get_timeseries_lake()``/``reset_timeseries_lake()`` (mirroring
``core.loop_watchdog.get_loop_watchdog()``/``reset_loop_watchdog()``).

The singleton is intentionally lazy (constructed on first
``get_timeseries_lake()`` call, not at import time) so importing this
module never has the side effect of creating a DuckDB file on disk --
that only happens once the feature is actually enabled and used.
"""
import logging
import threading
from typing import Any

import duckdb

_log = logging.getLogger(__name__)

__all__ = [
    "TimeSeriesDataLake",
    "get_timeseries_lake",
    "reset_timeseries_lake",
]


class TimeSeriesDataLake:
    """
    High-performance analytical DB for storing historical OHLCV and ticks.
    Replaces SQLite for heavy ML backtesting workloads.
    """
    def __init__(self, db_path: str = "timeseries.duckdb"):
        self.db_path = db_path
        self._conn = None
        self._init_db()

    def _init_db(self):
        try:
            self._conn = duckdb.connect(self.db_path)
            # Create a hyper-fast columnar table for market ticks
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS market_ticks (
                    timestamp TIMESTAMP,
                    symbol VARCHAR,
                    price DOUBLE,
                    volume INTEGER,
                    source VARCHAR
                )
            """)
            # Create a table for ML strategy walkforward performance
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS ml_model_performance (
                    timestamp TIMESTAMP,
                    model_version VARCHAR,
                    symbol VARCHAR,
                    predicted_class INTEGER,
                    confidence DOUBLE,
                    actual_outcome INTEGER
                )
            """)
            _log.info(f"Time-Series DataLake initialized at {self.db_path}")
        except Exception as e:
            _log.error(f"Failed to initialize DuckDB DataLake: {e}")

    def insert_tick(self, symbol: str, price: float, volume: int, source: str = "redis"):
        if not self._conn:
            return
        try:
            self._conn.execute(
                "INSERT INTO market_ticks VALUES (CURRENT_TIMESTAMP, ?, ?, ?, ?)",
                (symbol, price, volume, source)
            )
        except Exception as e:
            _log.error(f"Insert tick failed: {e}")

    def get_historical_candles(self, symbol: str, minutes: int = 5) -> list[dict[str, Any]]:
        """Aggregates raw ticks into OHLCV candles on the fly."""
        if not self._conn:
            return []
        try:
            query = f"""
                SELECT
                    time_bucket(INTERVAL '{minutes} minutes', timestamp) AS candle_time,
                    symbol,
                    first(price) AS open,
                    max(price) AS high,
                    min(price) AS low,
                    last(price) AS close,
                    sum(volume) AS volume
                FROM market_ticks
                WHERE symbol = ?
                GROUP BY candle_time, symbol
                ORDER BY candle_time ASC
            """
            result = self._conn.execute(query, (symbol,)).df()
            return result.to_dict('records')
        except Exception as e:
            _log.error(f"Failed to aggregate candles: {e}")
            return []

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None


_ts_lake: TimeSeriesDataLake | None = None
_ts_lake_lock = threading.Lock()


def get_timeseries_lake(db_path: str = "timeseries.duckdb") -> TimeSeriesDataLake:
    """Process-wide singleton (mirrors core.loop_watchdog's
    get_loop_watchdog() pattern). Constructed lazily on first call so that
    merely importing this module never creates a DuckDB file as a side
    effect -- only actually using the lake does."""
    global _ts_lake
    with _ts_lake_lock:
        if _ts_lake is None:
            _ts_lake = TimeSeriesDataLake(db_path)
        return _ts_lake


def reset_timeseries_lake() -> None:
    """Test-only reset of the singleton. Closes the existing connection (if
    any) before dropping the reference so tests don't leak open DuckDB
    file handles across test cases."""
    global _ts_lake
    with _ts_lake_lock:
        if _ts_lake is not None:
            try:
                _ts_lake.close()
            except Exception:
                pass
        _ts_lake = None
