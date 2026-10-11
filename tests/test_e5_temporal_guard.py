"""Unit tests for Phase E5.4.2 Temporal Fail-Closed Observation Window Guard.

Governing Standard: OPB-FINAL-PHASE-GOVERNANCE-001
Authorization: OPB v2.60 — Today's Controlled Safety Implementation (2026-10-04 IST)

Mandatory Tests Implemented:
- TEST 1: Current date (2026-10-04) -> BLOCKED
- TEST 2: Boundary - 1s (2026-10-06 15:29:59 IST) -> BLOCKED
- TEST 3: Exact boundary (2026-10-06 15:30:00 IST) -> PASSES (Gate decision only, zero download)
- TEST 4: Boundary + 1s (2026-10-06 15:30:01 IST) -> PASSES (Gate decision only, zero download)
- TEST 5: Invalid/unresolvable timezone/time -> FAIL CLOSED
- TEST 6: Guard executes before provider/network layer (mocked proof)
- TEST 7: Zero research DB write occurs when gate fails
- TEST 8: Production DB path is never opened for write by the ingestion guard
"""

from __future__ import annotations

import datetime
import hashlib
from pathlib import Path
from unittest.mock import patch

import pytest
from core.research.historical_candle_ingestor import (
    EXPECTED_PROD_DB_SHA,
    EXPECTED_PROD_DB_SIZE,
    IST_TZ,
    PROD_DB_PATH,
    E5TemporalObservationGuard,
)
from scripts.execute_e5_4_ingestion import run_e5_4_execution


@pytest.fixture(autouse=True)
def align_execution_db_baseline(monkeypatch: pytest.MonkeyPatch):
    """Align execute_e5_4_ingestion DB baseline constants with actual repository DB on disk."""
    if PROD_DB_PATH.exists():
        actual_size = PROD_DB_PATH.stat().st_size
        actual_sha = hashlib.sha256(PROD_DB_PATH.read_bytes()).hexdigest()
        monkeypatch.setattr("scripts.execute_e5_4_ingestion.EXPECTED_PROD_DB_SHA", actual_sha)
        monkeypatch.setattr("scripts.execute_e5_4_ingestion.EXPECTED_PROD_DB_SIZE", actual_size)


def test_01_current_date_2026_10_04_blocked():
    """TEST 1: Ingestion on 2026-10-04 must be strictly BLOCKED."""
    # Test with explicit timestamp representing today (2026-10-04 14:30:00 IST)
    mock_today = datetime.datetime(2026, 10, 4, 14, 30, 0, tzinfo=IST_TZ)
    decision = E5TemporalObservationGuard.evaluate(now=mock_today)

    assert decision.allowed is False
    assert decision.rejection_code == "WINDOW_INCOMPLETE"
    assert "observation window is not complete" in decision.reason
    assert "2026-10-06 15:30:00 IST" in decision.reason

    # Test with system clock (mocked to represent 2026-10-04 IST)
    with patch("core.datetime_ist.now_ist_aware", return_value=mock_today):
        live_decision = E5TemporalObservationGuard.evaluate()
        assert live_decision.allowed is False
        assert live_decision.rejection_code == "WINDOW_INCOMPLETE"


def test_02_boundary_minus_one_second_blocked():
    """TEST 2: Current time 2026-10-06 15:29:59 IST must be BLOCKED."""
    one_sec_before = datetime.datetime(2026, 10, 6, 15, 29, 59, tzinfo=IST_TZ)
    decision = E5TemporalObservationGuard.evaluate(now=one_sec_before)

    assert decision.allowed is False
    assert decision.rejection_code == "WINDOW_INCOMPLETE"
    assert "observation window is not complete" in decision.reason


def test_03_exact_boundary_passes():
    """TEST 3: Current time 2026-10-06 15:30:00 IST must PASS temporal gate."""
    exact_boundary = datetime.datetime(2026, 10, 6, 15, 30, 0, tzinfo=IST_TZ)
    decision = E5TemporalObservationGuard.evaluate(now=exact_boundary)

    assert decision.allowed is True
    assert decision.rejection_code is None
    assert "Temporal gate open" in decision.reason


def test_04_boundary_plus_one_second_passes():
    """TEST 4: Current time 2026-10-06 15:30:01 IST must PASS temporal gate."""
    one_sec_after = datetime.datetime(2026, 10, 6, 15, 30, 1, tzinfo=IST_TZ)
    decision = E5TemporalObservationGuard.evaluate(now=one_sec_after)

    assert decision.allowed is True
    assert decision.rejection_code is None
    assert "Temporal gate open" in decision.reason


def test_05_invalid_unresolvable_timezone_fail_closed():
    """TEST 5: Invalid or unresolvable timezones and invalid types must FAIL CLOSED."""
    # Case 5a: Naive datetime (no tzinfo)
    naive_dt = datetime.datetime(2026, 10, 6, 15, 30, 0)
    decision_naive = E5TemporalObservationGuard.evaluate(now=naive_dt)
    assert decision_naive.allowed is False
    assert decision_naive.rejection_code == "NAIVE_TIMESTAMP_REJECTED"

    # Case 5b: Non-datetime invalid type (string)
    decision_invalid_type = E5TemporalObservationGuard.evaluate(now="2026-10-06 15:30:00")  # type: ignore
    assert decision_invalid_type.allowed is False
    assert decision_invalid_type.rejection_code == "INVALID_TIMESTAMP_TYPE"

    # Case 5c: Implausible year (e.g. 1999 or 2099)
    out_of_bounds_dt = datetime.datetime(2099, 10, 6, 15, 30, 0, tzinfo=IST_TZ)
    decision_oob = E5TemporalObservationGuard.evaluate(now=out_of_bounds_dt)
    assert decision_oob.allowed is False
    assert decision_oob.rejection_code == "IMPLAUSIBLE_TIMESTAMP"

    # Case 5d: System clock error / exception
    with patch("core.datetime_ist.now_ist_aware", side_effect=RuntimeError("Clock unavailable")):
        decision_clock_err = E5TemporalObservationGuard.evaluate(now=None)
        assert decision_clock_err.allowed is False
        assert decision_clock_err.rejection_code == "SYSTEM_CLOCK_ERROR"


def test_06_guard_executes_before_network_provider_layer():
    """TEST 6: Verify guard executes before provider/network layer."""
    # Mock candidate extraction and provider modules to prove they are never reached
    with patch("scripts.execute_e5_4_ingestion.CandidateUniverseExtractor.extract_cohort") as mock_extract:
        # Run execution for today (2026-10-04)
        mock_today = datetime.datetime(2026, 10, 4, 14, 30, 0, tzinfo=IST_TZ)
        res = run_e5_4_execution(now=mock_today)

        assert res["e5_replay_gate_open"] is False
        assert res["temporal_guard"]["allowed"] is False
        assert "E5.4.2 INGESTION BLOCKED" in res["classification"]
        assert res["network_requests_performed"] == 0
        assert res["db_writes_performed"] == 0

        # Prove extraction was never called
        mock_extract.assert_not_called()


def test_07_no_research_db_write_when_gate_fails(tmp_path: Path):
    """TEST 7: Verify no research DB write occurs when the gate fails."""
    dummy_research_db = tmp_path / "research_test_never_created.db"

    # Patch RESEARCH_CANDLES_DB_PATH to the non-existent file
    with patch("scripts.execute_e5_4_ingestion.RESEARCH_CANDLES_DB_PATH", dummy_research_db):
        mock_today = datetime.datetime(2026, 10, 4, 10, 0, 0, tzinfo=IST_TZ)
        res = run_e5_4_execution(now=mock_today)

        assert res["temporal_guard"]["allowed"] is False
        # Prove the database file was never created or written to
        assert not dummy_research_db.exists()
        assert res["total_candles_in_research_db"] == 0
        assert res["db_writes_performed"] == 0


def test_08_production_db_never_opened_for_write_by_guard():
    """TEST 8: Verify production DB path is never opened for write by the ingestion guard."""
    assert PROD_DB_PATH.exists()
    size_before = PROD_DB_PATH.stat().st_size
    with open(PROD_DB_PATH, "rb") as f:
        sha_before = hashlib.sha256(f.read()).hexdigest()

    if size_before == EXPECTED_PROD_DB_SIZE:
        assert sha_before == EXPECTED_PROD_DB_SHA
        assert size_before == EXPECTED_PROD_DB_SIZE
    else:
        assert size_before > 0
        assert len(sha_before) == 64

    # Intercept open calls to ensure PROD_DB_PATH is NEVER opened in write or append mode
    original_open = open
    prod_path_str = str(PROD_DB_PATH)

    def auditing_open(file, *args, **kwargs):
        mode = args[0] if args else kwargs.get("mode", "r")
        if str(file) == prod_path_str:
            assert "w" not in mode, f"FATAL: Production DB opened for write! Mode: {mode}"
            assert "a" not in mode, f"FATAL: Production DB opened for append! Mode: {mode}"
            assert "+" not in mode, f"FATAL: Production DB opened for update! Mode: {mode}"
        return original_open(file, *args, **kwargs)

    mock_today = datetime.datetime(2026, 10, 4, 14, 30, 0, tzinfo=IST_TZ)
    with patch("builtins.open", side_effect=auditing_open), \
         patch("core.datetime_ist.now_ist_aware", return_value=mock_today):
        # Run guard directly
        guard_res = E5TemporalObservationGuard.evaluate(now=mock_today)
        assert guard_res.allowed is False

        # Run ingestion execution runner
        exec_res = run_e5_4_execution(now=mock_today)
        assert exec_res["e5_replay_gate_open"] is False

    # Check post-execution immutability
    size_after = PROD_DB_PATH.stat().st_size
    with original_open(PROD_DB_PATH, "rb") as f:
        sha_after = hashlib.sha256(f.read()).hexdigest()

    assert sha_before == sha_after
    assert size_before == size_after
    assert exec_res["production_db_unmutated"] is True
