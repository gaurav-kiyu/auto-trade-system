# OPB HISTORICAL SIGNAL REPLAY ENGINE — ARCHITECTURAL SPECIFICATION
**Version**: 1.0.0 (Phase 2.2 / v2.59.4 Hardening)
**Status**: DESIGN APPROVED — MODULAR SHADOW EXECUTION SPECIFICATION
**Author**: Senior Production & Trading Systems Engineering Team

---

## 1. Executive Summary & Objective

The **OPB Historical Signal Replay Engine** provides an offline, deterministic backtesting and shadow-simulation environment for trade signal generation models. It enables quantitative researchers and production operators to evaluate proposed signal scoring, barrier definitions, filtering heuristics, and candidate parameters across historical market sessions without modifying live production logic or touching live databases.

### Key Tenets:
1. **Zero Production Mutation**: Live trading rules, parameter thresholds, order routing, and databases (`signals_history.db`, `opb_trading.db`) are strictly read-only or completely decoupled.
2. **Deterministic Time-Travel**: Market state is reconstructed candle-by-candle as of the historical evaluation timestamp, strictly preventing lookahead bias.
3. **Canonical Comparison**: Replay outputs are benchmarked against canonical production signals generated during the same session to measure drift, false-positive reduction, and expectancy delta.
4. **Isolated Storage**: All replay runs, simulated signals, and comparative metrics persist exclusively to an isolated shadow database (`db/signal_replay.db`).

---

## 2. High-Level System Architecture

```text
       ┌──────────────────────────────────────────────────────────┐
       │                HISTORICAL DATA SOURCES                   │
       │   - Historical 1m/5m Candles (timeseries_lake / cache)   │
       │   - Persisted Scanner Cycles (scan_cycle_metrics)        │
       │   - NSE Holiday & Session Calendar (ExchangeCalendar)    │
       └─────────────────────────────┬────────────────────────────┘
                                     │
                                     ▼
       ┌──────────────────────────────────────────────────────────┐
       │             REPLAY CONTROLLER & TIME-TRAVEL CLOCK         │
       │   - Iterates chronological slice [start_time, end_time]  │
       │   - Sets frozen simulation time (mock_now_ist)           │
       │   - Feeds historical slice up to T_eval to scanner       │
       └─────────────────────────────┬────────────────────────────┘
                                     │
                                     ▼
       ┌──────────────────────────────────────────────────────────┐
       │             SHADOW SIGNAL EVALUATOR (SANDBOX)            │
       │   - Candidate Indicator Calculations (RSI, ADX, MACD)    │
       │   - Candidate Composite Scoring & Tier Classification    │
       │   - Barrier Assignment (Entry, SL, T1, T2)               │
       └─────────────────────────────┬────────────────────────────┘
                                     │
                                     ▼
       ┌──────────────────────────────────────────────────────────┐
       │            OUTCOME COMPARATOR & METRICS ENGINE           │
       │   - Matches shadow signals with canonical production     │
       │   - Evaluates first-touch resolution on subsequent bars  │
       │   - Computes: Win Rate, Expectancy, MFE/MAE, Duration    │
       └─────────────────────────────┬────────────────────────────┘
                                     │
                                     ▼
       ┌──────────────────────────────────────────────────────────┐
       │             ISOLATED SHADOW DATABASE                     │
       │   - File: db/signal_replay.db (PRAGMA WAL enabled)       │
       │   - Tables: replay_runs, replay_signals, replay_metrics  │
       └──────────────────────────────────────────────────────────┘
```

---

## 3. Subsystem Specifications

### 3.1 Data Ingestion Pipeline
- **Candle Provider**: Ingests historical OHLCV bars from `timeseries_lake/` parquet files or local SQLite cache.
- **Calendar Alignment**: Queries `ExchangeCalendarEngine` to ensure replay honors official NSE trading hours (09:15–15:30 IST) and skips weekends/holidays.
- **Integrity Assertion**: Pre-validates candle sequences for missing bars, duplicate timestamps, and zero volumes.

### 3.2 Time-Travel Simulation Engine
- **Clock Mocking**: Replaces runtime `now_ist()` with a deterministic simulation clock stepped at the configured bar interval (e.g., 1m or 5m).
- **Point-in-Time Slicing**: At time $T_k$, the evaluator has access *only* to data with timestamp $\le T_k$. Accessing data with timestamp $> T_k$ raises a `LookaheadBiasViolationError`.

### 3.3 Shadow Signal Evaluator
- Runs in an isolated thread/process without network socket creation.
- Disables all notification dispatchers (Telegram, Email, Webhook) and broker adapters.
- Captures candidate `score_components` for full mathematical explainability.

### 3.4 Isolated Database Schema (`db/signal_replay.db`)

```sql
CREATE TABLE IF NOT EXISTS replay_runs (
    run_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    config_tag TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    universe TEXT NOT NULL,
    total_replayed_signals INTEGER NOT NULL,
    win_rate_pct REAL,
    expectancy_pct REAL,
    profit_factor REAL,
    avg_mfe_pct REAL,
    avg_mae_pct REAL,
    metadata_json TEXT
);

CREATE TABLE IF NOT EXISTS replay_signals (
    replay_signal_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    symbol TEXT NOT NULL,
    direction TEXT NOT NULL,
    entry_price REAL NOT NULL,
    stop_loss REAL NOT NULL,
    target_1 REAL NOT NULL,
    target_2 REAL NOT NULL,
    score INTEGER NOT NULL,
    tier TEXT NOT NULL,
    first_touch TEXT,
    pnl_pct REAL,
    mfe_pct REAL,
    mae_pct REAL,
    duration_mins REAL,
    canonical_match_id TEXT,
    FOREIGN KEY (run_id) REFERENCES replay_runs(run_id)
);
```

---

## 4. Safety & Governance Mandates

1. **Physical Database Decoupling**: Replay engine must never obtain write handles to `signals_history.db`, `opb_trading.db`, or `users.db`.
2. **Notification Lockout**: Dispatch pipelines are monkey-patched or bypassed; zero external HTTP requests are made.
3. **Resource Throttling**: Replay tasks execute at lower OS priority with memory limits to prevent starvation of the primary trading daemon.
4. **Audit Trail**: Every replay execution records input parameters, Git commit SHA, and data checksums in `replay_runs`.
