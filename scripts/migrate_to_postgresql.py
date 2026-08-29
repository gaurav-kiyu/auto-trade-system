#!/usr/bin/env python3
"""PostgreSQL Migration — Convert SQLite databases to PostgreSQL.

Migrates all core databases from SQLite to PostgreSQL (19 databases total):
  - trades.db, trade_journal.db, ml_tracker.db, oi_snapshots.db
  - manual_signals.db, data_lineage.db, sme_business.db
  - fundamental_cache.db, event_store.db, execution_state.db
  - feature_store.db, shadow_mode.db, strategy_performance.db
  - strategy_versioning.db, formal_order_state.db, order_state.db
  - regime_detector.db, fundamentals.db, replay_sessions.db

This script:
  1. Reads the SQLite database and extracts all data
  2. Creates equivalent PostgreSQL schema (DDL)
  3. Transfers data row-by-row (with type conversion)
  4. Creates indexes and applies constraints
  5. Generates a migration report

Usage:
    python scripts/migrate_to_postgresql.py --dry-run              # Preview only
    python scripts/migrate_to_postgresql.py --all                  # Full migration
    python scripts/migrate_to_postgresql.py --db trades.db         # Single database
    python scripts/migrate_to_postgresql.py --connection "postgresql://user:pass@localhost:5432/opb"

Requirements:
    psycopg2-binary or asyncpg (PostgreSQL driver)
    Only runs if a PostgreSQL connection URL is provided or OPB_PG_URL is set.
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import sqlite3
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.datetime_ist import now_ist

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _safe_ident(name: str) -> str:
    """Return a quoted SQL identifier, rejecting anything not allow-listed.

    Table/column names originate from the SQLite schema (sqlite_master /
    cursor.description) and cannot be parameter-bound, so each must pass a
    strict identifier pattern before interpolation into a query.
    """
    if not _IDENTIFIER_RE.match(name):
        raise ValueError(f"Unsafe SQL identifier: {name!r}")
    return f'"{name}"'

_log = logging.getLogger("pg_migration")

# ── PostgreSQL DDL Schemas ─────────────────────────────────────────────────

# DDL for trade_journal.db
DDL_JOURNAL = """
CREATE TABLE IF NOT EXISTS journal (
    id               SERIAL PRIMARY KEY,

    -- Identity
    trade_id         VARCHAR(64),
    symbol           VARCHAR(32),
    direction        VARCHAR(8),
    entry_ts         TIMESTAMP,
    fill_ts          TIMESTAMP,

    -- Signal quality at entry
    score            INTEGER,
    tier             VARCHAR(16),
    confidence       DOUBLE PRECISION,
    regime           VARCHAR(32),
    quality_score    DOUBLE PRECISION,
    soft_blocks      TEXT,

    -- Expected (model)
    expected_entry   DOUBLE PRECISION,
    expected_sl      DOUBLE PRECISION,
    expected_tp      DOUBLE PRECISION,
    expected_pnl     DOUBLE PRECISION,
    expected_rr      DOUBLE PRECISION,

    -- Actual (fill)
    actual_entry     DOUBLE PRECISION,
    actual_exit      DOUBLE PRECISION,
    actual_pnl       DOUBLE PRECISION,
    exit_reason      VARCHAR(32),

    -- Slippage & timing
    entry_slippage   DOUBLE PRECISION,
    exit_slippage    DOUBLE PRECISION,
    total_slippage   DOUBLE PRECISION,
    execution_delay_ms INTEGER,
    slippage_drift   DOUBLE PRECISION DEFAULT 0.0,

    -- Position
    lots             INTEGER,
    position_pct     DOUBLE PRECISION,
    lot_size         INTEGER,
    mode             VARCHAR(8),

    -- Outcome
    is_winner        SMALLINT DEFAULT 0,
    gross_pnl        DOUBLE PRECISION,
    net_pnl          DOUBLE PRECISION,
    pct_pnl          DOUBLE PRECISION,
    bars_held        INTEGER,
    rr_achieved      DOUBLE PRECISION,

    -- Feedback
    score_vs_outcome DOUBLE PRECISION,
    pnl_vs_expected  DOUBLE PRECISION,
    quality_accurate SMALLINT DEFAULT 0,

    created_at       TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS shadow_trades (
    id               SERIAL PRIMARY KEY,
    trade_id         VARCHAR(64) UNIQUE,
    symbol           VARCHAR(32),
    direction        VARCHAR(8),
    entry_ts         TIMESTAMP,
    entry_price      DOUBLE PRECISION,
    sl_price         DOUBLE PRECISION,
    tp_price         DOUBLE PRECISION,
    score            INTEGER,
    tier             VARCHAR(16),
    regime           VARCHAR(32),
    sentiment        VARCHAR(32),
    reasoning        TEXT,
    lots             INTEGER,
    lot_size         INTEGER,
    actual_exit      DOUBLE PRECISION DEFAULT 0.0,
    exit_ts          TIMESTAMP,
    exit_reason      VARCHAR(32),
    net_pnl          DOUBLE PRECISION DEFAULT 0.0,
    is_winner        SMALLINT DEFAULT 0,
    created_at       TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_journal_symbol     ON journal(symbol);
CREATE INDEX IF NOT EXISTS ix_journal_tier       ON journal(tier);
CREATE INDEX IF NOT EXISTS ix_journal_entry_ts   ON journal(entry_ts);
CREATE INDEX IF NOT EXISTS ix_journal_mode       ON journal(mode);
CREATE INDEX IF NOT EXISTS ix_journal_created_at ON journal(created_at);
CREATE INDEX IF NOT EXISTS ix_shadow_trade_id     ON shadow_trades(trade_id);
"""

# DDL for ml_tracker.db
DDL_ML_TRACKER = """
CREATE TABLE IF NOT EXISTS ml_predictions (
    id              SERIAL PRIMARY KEY,
    ts              DOUBLE PRECISION NOT NULL,
    trade_id        VARCHAR(64) NOT NULL,
    predicted_prob  DOUBLE PRECISION NOT NULL,
    actual_outcome  SMALLINT,
    shap_json       TEXT DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS ix_mlpred_ts       ON ml_predictions (ts);
CREATE INDEX IF NOT EXISTS ix_mlpred_trade_id ON ml_predictions (trade_id);
"""

# DDL for oi_snapshots.db
DDL_OI_SNAPSHOTS = """
CREATE TABLE IF NOT EXISTS oi_snapshots (
    id              SERIAL PRIMARY KEY,
    ts              DOUBLE PRECISION NOT NULL,
    index_name      VARCHAR(16) NOT NULL,
    strike          INTEGER,
    expiry_date     VARCHAR(16),
    call_oi         BIGINT,
    put_oi          BIGINT,
    call_volume     BIGINT,
    put_volume      BIGINT,
    pcr_ratio       DOUBLE PRECISION,
    total_oi        BIGINT,
    snapshot_source VARCHAR(32)
);

CREATE INDEX IF NOT EXISTS ix_oi_snap_name_ts ON oi_snapshots (index_name, ts);

CREATE TABLE IF NOT EXISTS oi_snapshots_archive (
    id              INTEGER,
    ts              DOUBLE PRECISION,
    index_name      VARCHAR(16),
    strike          INTEGER,
    expiry_date     VARCHAR(16),
    call_oi         BIGINT,
    put_oi          BIGINT,
    call_volume     BIGINT,
    put_volume      BIGINT,
    pcr_ratio       DOUBLE PRECISION,
    total_oi        BIGINT,
    snapshot_source VARCHAR(32)
);
"""

# DDL for manual_signals.db
DDL_MANUAL_SIGNALS = """
CREATE TABLE IF NOT EXISTS manual_signals (
    signal_id     VARCHAR(32) PRIMARY KEY,
    source        VARCHAR(16),
    analyst_name  VARCHAR(64),
    index_name    VARCHAR(16),
    direction     VARCHAR(8),
    score         INTEGER,
    reason        TEXT,
    submitted_at  TIMESTAMP,
    expiry        VARCHAR(16),
    lots_override INTEGER,
    sl_override   DOUBLE PRECISION,
    target_override DOUBLE PRECISION,
    status        VARCHAR(16) DEFAULT 'PENDING',
    reviewed_by   VARCHAR(64),
    reviewed_at   TIMESTAMP,
    reject_reason TEXT,
    execution_trade_id VARCHAR(64),
    auto_approve_after_secs INTEGER DEFAULT 0,
    created_at    TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_ms_status    ON manual_signals(status);
CREATE INDEX IF NOT EXISTS ix_ms_submitted ON manual_signals(submitted_at);
CREATE INDEX IF NOT EXISTS ix_ms_analyst   ON manual_signals(analyst_name);
"""

# DDL for data_lineage.db
DDL_DATA_LINEAGE = """
CREATE TABLE IF NOT EXISTS data_lineage (
    id              SERIAL PRIMARY KEY,
    artifact_type   VARCHAR(32),
    artifact_name   VARCHAR(128),
    source_type     VARCHAR(32),
    source_name     VARCHAR(128),
    feature_name    VARCHAR(64),
    computed_at     TIMESTAMP,
    lineage_metadata TEXT,
    created_at      TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_dl_artifact  ON data_lineage(artifact_name);
CREATE INDEX IF NOT EXISTS idx_dl_source    ON data_lineage(source_name);
CREATE INDEX IF NOT EXISTS idx_dl_feature   ON data_lineage(feature_name);
CREATE INDEX IF NOT EXISTS idx_dl_computed_at ON data_lineage(computed_at);
"""

# DDL for SME stocks (from db_migration.py)
DDL_SME = """
CREATE TABLE IF NOT EXISTS sme_stocks (
    id              SERIAL PRIMARY KEY,
    symbol          VARCHAR(32) UNIQUE NOT NULL,
    company_name    VARCHAR(255),
    platform        VARCHAR(32),
    isin            VARCHAR(16),
    lot_size        INTEGER DEFAULT 1,
    active          SMALLINT DEFAULT 1,
    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sme_stocks_platform ON sme_stocks(platform);
CREATE INDEX IF NOT EXISTS idx_sme_stocks_active   ON sme_stocks(active);

CREATE TABLE IF NOT EXISTS sme_positions (
    id              SERIAL PRIMARY KEY,
    symbol          VARCHAR(32) NOT NULL,
    direction       VARCHAR(8),
    quantity        INTEGER,
    entry_price     DOUBLE PRECISION,
    current_price   DOUBLE PRECISION,
    pnl             DOUBLE PRECISION,
    open_ts         TIMESTAMP,
    close_ts        TIMESTAMP,
    is_open         SMALLINT DEFAULT 1,
    strategy        VARCHAR(64),
    created_at      TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sme_positions_symbol ON sme_positions(symbol);
CREATE INDEX IF NOT EXISTS idx_sme_positions_open   ON sme_positions(is_open);
"""

# DDL for fundamental_cache (from db_migration.py)
DDL_FUNDAMENTAL_CACHE = """
CREATE TABLE IF NOT EXISTS fundamental_cache (
    id              SERIAL PRIMARY KEY,
    symbol          VARCHAR(32) NOT NULL,
    metric_name     VARCHAR(64) NOT NULL,
    metric_value    DOUBLE PRECISION,
    fiscal_period   VARCHAR(16),
    snapshot_date   DATE,
    created_at      TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_fundamental_cache_composite
    ON fundamental_cache(symbol, metric_name, fiscal_period);
"""

# DDL for event_store.db (Event Store with hash-chained integrity)
DDL_EVENT_STORE = """
CREATE TABLE IF NOT EXISTS events (
    event_id        VARCHAR(64) PRIMARY KEY,
    event_type      VARCHAR(32) NOT NULL,
    priority        INTEGER,
    timestamp       VARCHAR(32) NOT NULL,
    source          VARCHAR(64),
    aggregate_id    VARCHAR(64),
    correlation_id  VARCHAR(64),
    causation_id    VARCHAR(64),
    version         INTEGER DEFAULT 1,
    intent_id       VARCHAR(64),
    client_order_id VARCHAR(64),
    broker_order_id VARCHAR(64),
    symbol          VARCHAR(32),
    direction       VARCHAR(8),
    quantity        INTEGER,
    price           DOUBLE PRECISION,
    metadata_json   TEXT,
    sequence_number INTEGER,
    previous_hash   VARCHAR(64),
    sha256          VARCHAR(64),
    created_at      TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_events_timestamp   ON events(timestamp);
CREATE INDEX IF NOT EXISTS idx_events_type        ON events(event_type);
CREATE INDEX IF NOT EXISTS idx_events_intent      ON events(intent_id);
CREATE INDEX IF NOT EXISTS idx_events_client_ord  ON events(client_order_id);
CREATE INDEX IF NOT EXISTS idx_events_sha256      ON events(sha256);
"""

# DDL for execution_state.db (Durable Execution Store)
DDL_EXECUTION_STATE = """
CREATE TABLE IF NOT EXISTS execution_state (
    intent_id       VARCHAR(64) PRIMARY KEY,
    client_order_id VARCHAR(64) NOT NULL,
    symbol          VARCHAR(32) NOT NULL,
    direction       VARCHAR(8) NOT NULL,
    quantity        INTEGER NOT NULL,
    strike_price    DOUBLE PRECISION NOT NULL,
    state           VARCHAR(16) NOT NULL,
    broker_order_id VARCHAR(64),
    filled_quantity INTEGER DEFAULT 0,
    average_price   DOUBLE PRECISION DEFAULT 0.0,
    reject_reason   TEXT,
    created_at      VARCHAR(32) NOT NULL,
    updated_at      VARCHAR(32) NOT NULL,
    retry_count     INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_exec_state  ON execution_state(state);
CREATE INDEX IF NOT EXISTS idx_exec_updated ON execution_state(updated_at);
"""

# DDL for feature_store.db (ML Feature Store)
DDL_FEATURE_STORE = """
CREATE TABLE IF NOT EXISTS feature_definitions (
    name             VARCHAR(128) PRIMARY KEY,
    feature_type     VARCHAR(32),
    description      TEXT,
    computation_func VARCHAR(256),
    version          VARCHAR(16)
);

CREATE TABLE IF NOT EXISTS feature_lineage (
    vector_id        VARCHAR(64),
    feature_name     VARCHAR(64),
    source           VARCHAR(128),
    source_version   VARCHAR(16),
    computation_step VARCHAR(64),
    quality_score    DOUBLE PRECISION,
    computed_at      VARCHAR(32),
    PRIMARY KEY (vector_id, feature_name)
);

CREATE TABLE IF NOT EXISTS feature_statistics (
    feature_name     VARCHAR(64),
    symbol           VARCHAR(32),
    min_val          DOUBLE PRECISION,
    max_val          DOUBLE PRECISION,
    mean_val         DOUBLE PRECISION,
    std_val          DOUBLE PRECISION,
    count            INTEGER,
    null_count       INTEGER,
    updated_at       VARCHAR(32),
    PRIMARY KEY (feature_name, symbol)
);

CREATE TABLE IF NOT EXISTS feature_vectors (
    vector_id    VARCHAR(64) PRIMARY KEY,
    timestamp    VARCHAR(32),
    symbol       VARCHAR(32),
    features_json TEXT,
    label        TEXT,
    metadata_json TEXT
);
"""

# DDL for shadow_mode.db (Shadow Trading)
DDL_SHADOW_MODE = """
CREATE TABLE IF NOT EXISTS shadow_comparisons (
    comparison_id      VARCHAR(64) PRIMARY KEY,
    timestamp          VARCHAR(32),
    shadow_signal_json TEXT,
    real_signal_json   TEXT,
    match              INTEGER,
    divergence_reason  TEXT
);

CREATE TABLE IF NOT EXISTS shadow_signals (
    signal_id     VARCHAR(64) PRIMARY KEY,
    timestamp     VARCHAR(32),
    strategy_name VARCHAR(64),
    symbol        VARCHAR(32),
    direction     VARCHAR(8),
    quantity      INTEGER,
    price         DOUBLE PRECISION,
    score         DOUBLE PRECISION,
    reason        TEXT,
    metadata_json TEXT
);
"""

# DDL for strategy_performance.db
DDL_STRATEGY_PERF = """
CREATE TABLE IF NOT EXISTS strategy_trades (
    trade_id         VARCHAR(64) PRIMARY KEY,
    strategy_name    VARCHAR(64) NOT NULL,
    strategy_version VARCHAR(16) DEFAULT '1.0.0',
    direction        VARCHAR(8) DEFAULT '',
    symbol           VARCHAR(32) DEFAULT '',
    entry_price      DOUBLE PRECISION DEFAULT 0.0,
    exit_price       DOUBLE PRECISION,
    pnl              DOUBLE PRECISION,
    entry_time       VARCHAR(32) NOT NULL,
    exit_time        VARCHAR(32),
    outcome          VARCHAR(16) DEFAULT 'OPEN',
    signal_score     DOUBLE PRECISION DEFAULT 0.0,
    metadata_json    TEXT DEFAULT '{}'
);
"""

# DDL for strategy_versioning.db
DDL_STRATEGY_VERSION = """
CREATE TABLE IF NOT EXISTS strategy_versions (
    id             SERIAL PRIMARY KEY,
    strategy_name  VARCHAR(64),
    version        VARCHAR(16),
    config_hash    VARCHAR(64),
    created_at     VARCHAR(32),
    is_active      INTEGER DEFAULT 0,
    metadata_json  TEXT
);

CREATE TABLE IF NOT EXISTS trade_records (
    trade_id         VARCHAR(64) PRIMARY KEY,
    intent_id        VARCHAR(64),
    strategy_name    VARCHAR(64),
    strategy_version VARCHAR(16),
    config_hash      VARCHAR(64),
    signal_score     DOUBLE PRECISION,
    direction        VARCHAR(8),
    symbol           VARCHAR(32),
    quantity         INTEGER,
    entry_price      DOUBLE PRECISION,
    exit_price       DOUBLE PRECISION,
    pnl              DOUBLE PRECISION,
    entry_time       VARCHAR(32),
    exit_time        VARCHAR(32),
    outcome          VARCHAR(16)
);

CREATE INDEX IF NOT EXISTS idx_strategy_version ON trade_records(strategy_name, strategy_version);
CREATE INDEX IF NOT EXISTS idx_trade_time ON trade_records(entry_time);
"""

# DDL for formal_order_state.db (Formal Order Tracking)
DDL_FORMAL_ORDERS = """
CREATE TABLE IF NOT EXISTS formal_orders (
    client_order_id             VARCHAR(64) PRIMARY KEY,
    intent_id                   VARCHAR(64),
    symbol                      VARCHAR(32),
    quantity                    INTEGER,
    price                       DOUBLE PRECISION,
    direction                   VARCHAR(8),
    state                       VARCHAR(16),
    broker_order_id             VARCHAR(64),
    filled_quantity             INTEGER,
    remaining_quantity          INTEGER,
    average_price               DOUBLE PRECISION,
    error_message               TEXT,
    created_at                  VARCHAR(32),
    updated_at                  VARCHAR(32),
    submitted_at                VARCHAR(32),
    acknowledged_at             VARCHAR(32),
    filled_at                   VARCHAR(32),
    cancelled_at                VARCHAR(32),
    transition_history_json     TEXT
);
"""

# DDL for order_state.db (Order State Tracking)
DDL_ORDER_STATE = """
CREATE TABLE IF NOT EXISTS orders (
    intent_id      VARCHAR(64) PRIMARY KEY,
    broker_order_id VARCHAR(64) UNIQUE,
    request_json   TEXT,
    status         VARCHAR(16),
    filled_qty     INTEGER,
    avg_price      DOUBLE PRECISION,
    created_at     VARCHAR(32),
    updated_at     VARCHAR(32),
    error_text     TEXT
);
"""

# DDL for regime_detector.db
DDL_REGIME = """
CREATE TABLE IF NOT EXISTS regime_history (
    id              SERIAL PRIMARY KEY,
    regime          VARCHAR(32),
    confidence      DOUBLE PRECISION,
    volatility      DOUBLE PRECISION,
    trend_strength  DOUBLE PRECISION,
    timestamp       VARCHAR(32),
    metadata_json   TEXT
);
"""

# DDL for fundamentals.db (Fundamental Cache with pre-computed metrics)
DDL_FUNDAMENTALS = """
CREATE TABLE IF NOT EXISTS fundamental_cache (
    symbol          VARCHAR(32) PRIMARY KEY,
    data_json       TEXT NOT NULL,
    fetched_at      VARCHAR(32) NOT NULL DEFAULT NOW(),
    pe_ratio        DOUBLE PRECISION DEFAULT 0.0,
    pb_ratio        DOUBLE PRECISION DEFAULT 0.0,
    market_cap      DOUBLE PRECISION DEFAULT 0.0,
    eps_ttm         DOUBLE PRECISION DEFAULT 0.0,
    dividend_yield  DOUBLE PRECISION DEFAULT 0.0,
    debt_to_equity  DOUBLE PRECISION DEFAULT 0.0,
    roe_pct         DOUBLE PRECISION DEFAULT 0.0,
    composite_score DOUBLE PRECISION DEFAULT 0.0
);
"""

# DDL for replay_sessions.db
DDL_REPLAY = """
CREATE TABLE IF NOT EXISTS replay_sessions (
    session_id       VARCHAR(64) PRIMARY KEY,
    start_time       VARCHAR(32),
    end_time         VARCHAR(32),
    market_data_path VARCHAR(256),
    events_path      VARCHAR(256),
    status           VARCHAR(16),
    created_at       VARCHAR(32)
);
"""

# Map of database name -> (DDL, source_files)
DDL_TRADES = """
CREATE TABLE IF NOT EXISTS trades (
    id              SERIAL PRIMARY KEY,
    trade_id        VARCHAR(64) UNIQUE,
    symbol          VARCHAR(32),
    direction       VARCHAR(8),
    entry_ts        TIMESTAMP,
    entry_price     DOUBLE PRECISION,
    sl_price        DOUBLE PRECISION,
    tp_price        DOUBLE PRECISION,
    score           INTEGER,
    tier            VARCHAR(16),
    regime          VARCHAR(32),
    lots            INTEGER,
    lot_size        INTEGER,
    status          VARCHAR(16),
    exit_price      DOUBLE PRECISION DEFAULT 0.0,
    exit_ts         TIMESTAMP,
    exit_reason     VARCHAR(32),
    net_pnl         DOUBLE PRECISION DEFAULT 0.0,
    is_winner       SMALLINT DEFAULT 0,
    created_at      TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS execution_orders (
    id              SERIAL PRIMARY KEY,
    order_id        VARCHAR(64) UNIQUE,
    trade_id        VARCHAR(64),
    symbol          VARCHAR(32),
    direction       VARCHAR(8),
    order_type      VARCHAR(16),
    quantity        INTEGER,
    price           DOUBLE PRECISION,
    status          VARCHAR(16),
    filled_quantity INTEGER DEFAULT 0,
    filled_price    DOUBLE PRECISION,
    submitted_at    TIMESTAMP,
    filled_at       TIMESTAMP,
    created_at      TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_trades_symbol   ON trades(symbol);
CREATE INDEX IF NOT EXISTS ix_trades_status   ON trades(status);
CREATE INDEX IF NOT EXISTS ix_orders_trade    ON execution_orders(trade_id);
CREATE INDEX IF NOT EXISTS ix_orders_status   ON execution_orders(status);
"""

PG_SCHEMAS: dict[str, tuple[str, list[str]]] = {
    "trades.db": (
        DDL_TRADES + DDL_SME,  # trades.db also contains sme_stocks/sme_positions
        ["core/persistence/trades/manager.py"],
    ),
    "trade_journal.db": (
        DDL_JOURNAL,
        ["core/trade_journal.py"],
    ),
    "ml_tracker.db": (
        DDL_ML_TRACKER,
        ["core/ml_performance_tracker.py"],
    ),
    "oi_snapshots.db": (
        DDL_OI_SNAPSHOTS,
        ["core/oi_snapshot_store.py"],
    ),
    "manual_signals.db": (
        DDL_MANUAL_SIGNALS,
        ["core/manual_signal.py"],
    ),
    "data_lineage.db": (
        DDL_DATA_LINEAGE,
        ["core/data_lineage.py"],
    ),
    "sme_business.db": (
        DDL_SME,
        ["core/db_migration.py"],
    ),
    "fundamental_cache.db": (
        DDL_FUNDAMENTAL_CACHE,
        ["core/fundamental_analyzer.py", "core/db_migration.py"],
    ),
    "event_store.db": (
        DDL_EVENT_STORE,
        ["core/execution/event_system.py"],
    ),
    "execution_state.db": (
        DDL_EXECUTION_STATE,
        ["core/execution/durable_state.py"],
    ),
    "feature_store.db": (
        DDL_FEATURE_STORE,
        ["core/feature_store.py"],
    ),
    "shadow_mode.db": (
        DDL_SHADOW_MODE,
        ["core/shadow_mode.py"],
    ),
    "strategy_performance.db": (
        DDL_STRATEGY_PERF,
        ["core/strategy/perf.py"],
    ),
    "strategy_versioning.db": (
        DDL_STRATEGY_VERSION,
        ["core/strategy/strategy_versioning.py"],
    ),
    "formal_order_state.db": (
        DDL_FORMAL_ORDERS,
        ["core/execution/order_manager.py"],
    ),
    "order_state.db": (
        DDL_ORDER_STATE,
        ["core/state/order_store.py"],
    ),
    "regime_detector.db": (
        DDL_REGIME,
        ["core/regime_transition_detector.py"],
    ),
    "fundamentals.db": (
        DDL_FUNDAMENTALS,
        ["core/fundamental_analyzer.py"],
    ),
    "replay_sessions.db": (
        DDL_REPLAY,
        ["core/trade_replayer.py"],
    ),
}

# ── Data Models ────────────────────────────────────────────────────────────


@dataclass
class MigrationResult:
    """Result of a single database migration."""

    db_name: str = ""
    status: str = ""  # SUCCESS, SKIPPED, FAILED
    source_rows: int = 0
    migrated_rows: int = 0
    tables: list[str] = field(default_factory=list)
    error: str = ""
    elapsed_seconds: float = 0.0
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "db_name": self.db_name,
            "status": self.status,
            "source_rows": self.source_rows,
            "migrated_rows": self.migrated_rows,
            "tables": self.tables,
            "error": self.error,
            "elapsed_seconds": round(self.elapsed_seconds, 2),
            "warnings": self.warnings,
        }


@dataclass
class MigrationReport:
    """Complete migration report."""

    started_at: str = ""
    completed_at: str = ""
    results: list[MigrationResult] = field(default_factory=list)
    total_source_rows: int = 0
    total_migrated_rows: int = 0
    success_count: int = 0
    failed_count: int = 0
    skipped_count: int = 0
    dry_run: bool = False

    def summary_text(self) -> str:
        lines = [
            "=" * 60,
            "  POSTGRESQL MIGRATION REPORT",
            "=" * 60,
            f"  Mode: {'DRY RUN' if self.dry_run else 'LIVE'}",
            f"  Started: {self.started_at}",
            f"  Completed: {self.completed_at}",
            "",
            f"  Databases: {len(self.results)} total",
            f"    [OK] {self.success_count} succeeded",
            f"    [!!] {self.failed_count} failed",
            f"    [--] {self.skipped_count} skipped",
            "",
            f"  Rows: {self.total_source_rows} SQLite -> {self.total_migrated_rows} PostgreSQL",
            "",
        ]
        for r in self.results:
            icon = {"SUCCESS": "[OK]", "FAILED": "[!!]", "SKIPPED": "[--]"}.get(r.status, "[??]")
            lines.append(f"  {icon} {r.db_name:<25s} {r.status:<10s} "
                         f"{r.source_rows} -> {r.migrated_rows} rows, "
                         f"{r.elapsed_seconds:.1f}s")
            if r.error:
                lines.append(f"     Error: {r.error[:120]}")
            if r.warnings:
                for w in r.warnings[:3]:
                    lines.append(f"     [!] {w}")
        lines.append("=" * 60)
        return "\n".join(lines)


# ── Migration Engine ───────────────────────────────────────────────────────


class PostgreSQLMigrator:
    """Migrates SQLite databases to PostgreSQL.

    Handles schema conversion, data transfer, and type mapping.
    Supports dry-run mode for preview without making changes.
    """

    def __init__(self, pg_url: str | None = None, dry_run: bool = False) -> None:
        self._pg_url = pg_url or os.environ.get("OPB_PG_URL", "")
        self._dry_run = dry_run
        self._project_root = Path(__file__).resolve().parent.parent
        self._pg_conn: Any = None

    def _connect_pg(self) -> Any:
        """Connect to PostgreSQL (lazy import for optional dependency)."""
        if not self._pg_url:
            raise ValueError(
                "No PostgreSQL connection URL provided. "
                "Set OPB_PG_URL environment variable or pass --connection."
            )
        try:
            import psycopg2
            conn = psycopg2.connect(self._pg_url)
            conn.autocommit = False
            return conn
        except ImportError:
            raise ImportError(
                "psycopg2 is required for PostgreSQL migration. "
                "Install: pip install psycopg2-binary"
            )

    def migrate_all(self) -> MigrationReport:
        """Migrate all known databases."""
        report = MigrationReport(
            started_at=now_ist().isoformat(),
            dry_run=self._dry_run,
        )

        for db_name, (ddl, sources) in PG_SCHEMAS.items():
            result = self.migrate_db(db_name, ddl)
            report.results.append(result)

            if result.status == "SUCCESS":
                report.success_count += 1
            elif result.status == "FAILED":
                report.failed_count += 1
            else:
                report.skipped_count += 1

            report.total_source_rows += result.source_rows
            report.total_migrated_rows += result.migrated_rows

        report.completed_at = now_ist().isoformat()
        return report

    def migrate_db(self, db_name: str, ddl: str) -> MigrationResult:
        """Migrate a single SQLite database to PostgreSQL.

        Args:
            db_name: SQLite database logical name (e.g., "trades.db").
            ddl: PostgreSQL DDL string.

        Returns:
            MigrationResult with status and row counts.
        """
        result = MigrationResult(db_name=db_name)
        t0 = time.time()

        # DBs live under the db/ folder (fall back to a bare path for
        # test fixtures / legacy layouts)
        sqlite_path = self._project_root / "db" / db_name
        if not sqlite_path.is_file():
            sqlite_path = self._project_root / db_name
        if not sqlite_path.is_file():
            result.status = "SKIPPED"
            result.warnings.append(f"SQLite database not found: {db_name}")
            return result

        sqlite_conn: Any = None
        try:
            # Read SQLite data
            sqlite_conn = sqlite3.connect(str(sqlite_path))
            sqlite_conn.row_factory = sqlite3.Row
            tables = self._get_tables(sqlite_conn, sqlite_path)
            result.tables = tables

            if not tables:
                result.status = "SKIPPED"
                result.warnings.append("No tables found in source database")
                sqlite_conn.close()
                return result

            # Count source rows
            total_rows = 0
            for table in tables:
                # Identifier is allow-list validated by _safe_ident(); no user input.
                sql = "SELECT COUNT(*) FROM "
                sql += _safe_ident(table)
                count = sqlite_conn.execute(sql).fetchone()[0]
                total_rows += count
            result.source_rows = total_rows

            # Dry run - don't actually migrate
            if self._dry_run:
                result.status = "SUCCESS"
                result.migrated_rows = total_rows
                result.warnings.append("DRY RUN - no data written to PostgreSQL")
                for table in tables:
                    # Identifiers are allow-list validated by _safe_ident(); no user input.
                    sql = "SELECT COUNT(*) FROM "
                    sql += _safe_ident(table)
                    row_count = sqlite_conn.execute(sql).fetchone()[0]
                    cols_sql = "SELECT * FROM "
                    cols_sql += _safe_ident(table)
                    cols_sql += " LIMIT 0"
                    cols = [desc[0] for desc in
                            sqlite_conn.execute(cols_sql).description]
                    result.warnings.append(
                        f"  Table: {table} ({row_count} rows, {len(cols)} columns)"
                    )
                result.elapsed_seconds = time.time() - t0
                return result

            # Connect to PostgreSQL and execute migration
            if not self._pg_conn:
                self._pg_conn = self._connect_pg()

            pg_conn = self._pg_conn

            # Execute DDL
            try:
                statements = [s.strip() for s in ddl.split(";") if s.strip()]
                for stmt in statements:
                    if stmt:
                        pg_conn.execute(stmt + ";")
                pg_conn.commit()
            except Exception as exc:
                pg_conn.rollback()
                result.status = "FAILED"
                result.error = f"DDL execution failed: {exc}"
                result.elapsed_seconds = time.time() - t0
                if sqlite_conn:
                    sqlite_conn.close()
                return result

            # Transfer data for each table
            migrated = 0
            for table in tables:
                try:
                    # Identifier is allow-list validated by _safe_ident(); no user input.
                    sql = "SELECT * FROM "
                    sql += _safe_ident(table)
                    rows = sqlite_conn.execute(sql).fetchall()
                    if not rows:
                        continue

                    # Identifier is allow-list validated by _safe_ident(); no user input.
                    cols_sql = "SELECT * FROM "
                    cols_sql += _safe_ident(table)
                    cols_sql += " LIMIT 0"
                    cols = [desc[0] for desc in
                            sqlite_conn.execute(cols_sql).description]
                    placeholders = ",".join(["%s"] * len(cols))
                    col_names = ",".join(_safe_ident(c) for c in cols)

                    for row in rows:
                        values = self._convert_row(row, cols)
                        try:
                            # Table/column identifiers are allow-list validated by
                            # _safe_ident(); values are always bound parameters.
                            insert_sql = "INSERT INTO "
                            insert_sql += _safe_ident(table)
                            insert_sql += " (" + col_names + ") "
                            insert_sql += "VALUES (" + placeholders + ") "
                            insert_sql += "ON CONFLICT DO NOTHING"
                            pg_conn.execute(insert_sql, values)
                            migrated += 1
                        except Exception as exc:
                            _log.warning("[MIGRATE] Row insert failed: %s", exc)

                    pg_conn.commit()

                except Exception as exc:
                    pg_conn.rollback()
                    _log.warning("[MIGRATE] Table %s failed: %s", table, exc)
                    result.warnings.append(f"Table '{table}' partial: {exc}")

            result.status = "SUCCESS"
            result.migrated_rows = migrated

        except Exception as exc:
            result.status = "FAILED"
            result.error = str(exc)
        finally:
            if sqlite_conn:
                try:
                    sqlite_conn.close()
                except Exception:
                    pass

        result.elapsed_seconds = time.time() - t0
        return result

    def _get_tables(self, conn: sqlite3.Connection, db_path: Path) -> list[str]:
        """Get list of user tables from SQLite database."""
        try:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
            return [r[0] for r in rows]
        except Exception:
            return []

    def _convert_row(self, row: sqlite3.Row, cols: list[str]) -> list[Any]:
        """Convert a SQLite row to PostgreSQL-compatible values."""
        import math
        values = []
        for col in cols:
            val = row[col]
            # Convert NaN/Inf which PostgreSQL rejects
            if val is not None and isinstance(val, float):
                if math.isnan(val) or math.isinf(val):
                    val = None
            values.append(val)
        return values

    def generate_schema_report(self) -> str:
        """Generate a report of all PostgreSQL schemas for review."""
        lines = [
            "=" * 60,
            "  POSTGRESQL SCHEMA GENERATION REPORT",
            "=" * 60,
            f"  Generated: {now_ist().isoformat()}",
            f"  Databases: {len(PG_SCHEMAS)}",
            "",
        ]
        for db_name, (ddl, sources) in PG_SCHEMAS.items():
            stmt_count = len([s for s in ddl.split(";") if s.strip()])
            lines.append(f"  Database: {db_name}")
            lines.append(f"    Source files: {', '.join(sources)}")
            lines.append(f"    Statements: {stmt_count}")
            lines.append("")

        lines.append("=" * 60)
        return "\n".join(lines)


# ── CLI ─────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="Preview migration without writing to PostgreSQL")
    ap.add_argument("--all", action="store_true",
                    help="Migrate all databases")
    ap.add_argument("--db", type=str, default="",
                    help="Migrate a single database by filename")
    ap.add_argument("--connection", type=str, default="",
                    help="PostgreSQL connection URL")
    ap.add_argument("--schema-only", action="store_true",
                    help="Generate schema report only (no migration)")
    ap.add_argument("--verbose", action="store_true",
                    help="Verbose output")

    args = ap.parse_args(argv)

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG, format="%(message)s")
    else:
        logging.basicConfig(level=logging.INFO, format="%(message)s")

    pg_url = args.connection or os.environ.get("OPB_PG_URL", "")

    migrator = PostgreSQLMigrator(pg_url=pg_url, dry_run=args.dry_run)

    if args.schema_only:
        print(migrator.generate_schema_report())
        return 0

    if args.db:
        # Single database migration
        if args.db not in PG_SCHEMAS:
            print(f"Unknown database: {args.db}")
            print(f"Available: {', '.join(sorted(PG_SCHEMAS.keys()))}")
            return 1

        ddl, sources = PG_SCHEMAS[args.db]
        print(f"\nMigrating {args.db} (from {', '.join(sources)})...")
        result = migrator.migrate_db(args.db, ddl)

        if args.dry_run:
            print(f"\n[DRY RUN] {args.db}: {result.source_rows} rows ready")
            for w in result.warnings:
                print(f"  {w}")
        else:
            icon = "[OK]" if result.status == "SUCCESS" else "[!!]"
            print(f"\n{icon} {args.db}: {result.source_rows} -> {result.migrated_rows} rows ({result.elapsed_seconds:.1f}s)")
            if result.error:
                print(f"  Error: {result.error}")
            if result.warnings:
                for w in result.warnings:
                    print(f"  [!] {w}")

        return 0 if (result.status == "SUCCESS" or (args.dry_run and result.status == "SKIPPED")) else 1

    if args.all:
        print("\nRunning full PostgreSQL migration...")
        report = migrator.migrate_all()
        print(report.summary_text())
        return 1 if report.failed_count > 0 else 0

    # Default: show help
    ap.print_help()
    print("\n\nAvailable databases:")
    for db_name in sorted(PG_SCHEMAS.keys()):
        _, sources = PG_SCHEMAS[db_name]
        print(f"  {db_name:<25s} ({', '.join(sources)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
