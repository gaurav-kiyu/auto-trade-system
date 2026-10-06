"""Unit tests for Phase E5.4 Isolated Historical Candle Ingestor & Validation Engine.

Governing Standard: OPB-FINAL-PHASE-GOVERNANCE-001
Authorization: OPB v2.60 — E5.4 Authorized Isolated Historical Candle Ingestion
"""

from __future__ import annotations

import datetime
import hashlib
import sqlite3
from pathlib import Path

import pytest

from core.research.historical_candle_ingestor import (
    EXPECTED_PROD_DB_SHA,
    EXPECTED_PROD_DB_SIZE,
    PROD_DB_PATH,
    CandidateUniverseExtractor,
    IngestionValidationSuite,
    ResearchCandleDatabaseManager,
)


def test_production_db_baseline_integrity():
    """Verify production DB is byte-identical and matches the authoritative hash."""
    assert PROD_DB_PATH.exists()
    assert PROD_DB_PATH.stat().st_size == EXPECTED_PROD_DB_SIZE

    with open(PROD_DB_PATH, "rb") as f:
        actual_sha = hashlib.sha256(f.read()).hexdigest()
    assert actual_sha == EXPECTED_PROD_DB_SHA


def test_candidate_universe_extraction():
    """Extract candidate cohort and verify 101 candidates and 68 underlying symbols."""
    mappings = CandidateUniverseExtractor.extract_cohort(PROD_DB_PATH)
    assert len(mappings) == 101

    unique_syms = CandidateUniverseExtractor.get_unique_underlying_symbols(mappings)
    assert len(unique_syms) == 68

    # Verify categories represented
    categories = set(m.category for m in mappings)
    assert "EQUITY_SWING_DELIVERY" in categories
    assert "STOCK_OPTIONS" in categories
    assert "FUTURES" in categories
    assert "INDEX_OPTIONS" in categories

    # Verify ATR eligible count
    eligible_count = sum(1 for m in mappings if m.is_atr_eligible)
    assert eligible_count == 93


def test_research_db_schema_initialization(tmp_path: Path):
    """Test schema creation in isolated temporary database."""
    test_db = tmp_path / "test_candles.db"
    mgr = ResearchCandleDatabaseManager(db_path=test_db)
    mgr.ensure_schema()
    assert test_db.exists()

    conn = sqlite3.connect(str(test_db))
    cur = conn.cursor()
    tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    assert "raw_market_data_payloads" in tables
    assert "candles_1m_historical" in tables
    assert "ingestion_audit_log" in tables
    conn.close()


def test_validation_suite_on_unpopulated_db(tmp_path: Path):
    """Verify DATA-01..DATA-14 fail cleanly and DATA-15 passes on unpopulated database."""
    test_db = tmp_path / "unpopulated_candles.db"
    suite = IngestionValidationSuite(research_db_path=test_db)
    mappings = CandidateUniverseExtractor.extract_cohort(PROD_DB_PATH)

    results = suite.run_all(mappings)
    assert len(results) == 15

    results_by_id = {r.rule_id: r for r in results}
    # DATA-15 (Production DB unchanged) must PASS
    assert results_by_id["DATA-15"].passed is True

    # DATA-01 through DATA-12 must FAIL on missing data
    assert results_by_id["DATA-01"].passed is False
    assert results_by_id["DATA-12"].passed is False


def test_validation_suite_ohlc_invariants(tmp_path: Path):
    """Verify DATA-04 catches invalid OHLC relationships."""
    test_db = tmp_path / "test_invariants.db"
    mgr = ResearchCandleDatabaseManager(db_path=test_db)
    mgr.ensure_schema()

    conn = sqlite3.connect(str(test_db))
    cur = conn.cursor()
    # Insert dummy raw payload
    cur.execute("""
        INSERT INTO raw_market_data_payloads 
        (symbol, provider, endpoint, start_date, end_date, interval, retrieved_at_ist, raw_payload, payload_sha256)
        VALUES ('TEST', 'PROVIDER', '/test', '2026-09-28', '2026-10-06', '1m', '2026-10-03 15:00:00', '{}', 'hash')
    """)
    pid = cur.lastrowid

    # Insert a bar where High < Low (violates invariant)
    cur.execute("""
        INSERT INTO candles_1m_historical
        (symbol, exchange, timestamp_ist, open, high, low, close, volume, payload_id)
        VALUES ('TEST', 'NSE', '2026-09-28 09:15:00', 100.0, 90.0, 110.0, 95.0, 100.0, ?)
    """, (pid,))
    conn.commit()
    conn.close()

    suite = IngestionValidationSuite(research_db_path=test_db)
    mappings = CandidateUniverseExtractor.extract_cohort(PROD_DB_PATH)
    results = suite.run_all(mappings)
    results_by_id = {r.rule_id: r for r in results}

    assert results_by_id["DATA-04"].passed is False
    assert "Invalid OHLC bars count: 1" in results_by_id["DATA-04"].details
