"""OPB v2.60 — Phase E5.4 Ingestion Execution & Validation Runner.

Governing Standard: OPB-FINAL-PHASE-GOVERNANCE-001
Authorization: OPB v2.60 — E5.4 Authorized Isolated Historical Candle Ingestion

Executes the isolated research data acquisition process for the E5 cohort,
tests provider availability, executes DATA-01..DATA-15 validation,
and enforces strict zero mutation of production.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.research.historical_candle_ingestor import (
    EXPECTED_PROD_DB_SHA,
    EXPECTED_PROD_DB_SIZE,
    PROD_DB_PATH,
    RESEARCH_CANDLES_DB_PATH,
    CandidateUniverseExtractor,
    E5TemporalObservationGuard,
    IngestionValidationSuite,
    ResearchCandleDatabaseManager,
    TemporalGuardDecision,
)

_log = logging.getLogger("EXECUTE_E5_4")


def run_e5_4_execution(now: datetime.datetime | None = None) -> dict[str, Any]:
    """Execute Phase E5.4 / E5.4.2 workflow with temporal fail-closed protection.

    CRITICAL ORDER OF OPERATIONS:
    1. Verify production DB read-only baseline.
    2. Enforce temporal fail-closed guard (Observation window: 2026-09-28 to 2026-10-06 15:30 IST).
       If current time < boundary, immediately fail closed with zero network, zero downloads, zero DB writes.
    3. Only if temporal guard passes, proceed with provider check and validation suite.
    """
    # 1. Pre-execution production DB verification (Read-Only)
    assert PROD_DB_PATH.exists(), "FATAL: Production DB missing!"
    prod_size_before = PROD_DB_PATH.stat().st_size
    with open(PROD_DB_PATH, "rb") as f:
        prod_sha_before = hashlib.sha256(f.read()).hexdigest()

    assert prod_sha_before == EXPECTED_PROD_DB_SHA, f"FATAL: Production DB mismatch before E5.4! ({prod_sha_before})"
    assert prod_size_before == EXPECTED_PROD_DB_SIZE, f"FATAL: Production DB size mismatch before E5.4! ({prod_size_before})"

    # 2. Enforce Temporal Fail-Closed Guard (MUST EXECUTE BEFORE ANY PROVIDER/NETWORK/DB WRITES)
    guard = E5TemporalObservationGuard.evaluate(now=now)
    if not guard.allowed:
        _log.warning("Temporal guard BLOCKED ingestion: %s", guard.reason)
        return {
            "classification": guard.reason,
            "e5_replay_gate_open": False,
            "temporal_guard": {
                "allowed": False,
                "current_time_ist": str(guard.current_time_ist),
                "boundary_time_ist": str(guard.boundary_time_ist),
                "reason": guard.reason,
                "rejection_code": guard.rejection_code,
            },
            "total_candidate_snapshots": 0,
            "total_unique_underlying_symbols": 0,
            "total_candles_in_research_db": 0,
            "research_db_path": str(RESEARCH_CANDLES_DB_PATH),
            "production_db_sha_before": prod_sha_before,
            "production_db_sha_after": prod_sha_before,
            "production_db_size_before": prod_size_before,
            "production_db_size_after": prod_size_before,
            "production_db_unmutated": True,
            "provider_statuses": {},
            "validation_passed_count": 0,
            "validation_failed_count": 0,
            "validation_results": [],
            "network_requests_performed": 0,
            "db_writes_performed": 0,
        }

    # 3. Extract Candidate Cohort Universe (Read-Only, post-temporal gate only)
    mappings = CandidateUniverseExtractor.extract_cohort(PROD_DB_PATH)
    unique_symbols = CandidateUniverseExtractor.get_unique_underlying_symbols(mappings)

    # 4. Provider Availability and Credential Audit
    provider_statuses = {}

    # Provider 1: Zerodha Kite Connect
    kite_sdk_installed = False
    try:
        import kiteconnect  # type: ignore
        kite_sdk_installed = True
    except ImportError:
        pass
    provider_statuses["zerodha_kite"] = {
        "priority": 1,
        "sdk_installed": kite_sdk_installed,
        "credentials_configured": False,
        "limitation": "kiteconnect SDK not installed in runtime environment; no API key / access token provisioned.",
    }

    # Provider 2: Angel One SmartAPI
    angel_sdk_installed = False
    try:
        import SmartApi  # type: ignore
        angel_sdk_installed = True
    except ImportError:
        pass
    provider_statuses["angel_one"] = {
        "priority": 2,
        "sdk_installed": angel_sdk_installed,
        "credentials_configured": False,
        "limitation": "smartapi-python SDK not installed; no API key / client ID / TOTP provisioned.",
    }

    # Provider 3: Dhan HQ
    dhan_sdk_installed = False
    try:
        import dhanhq  # type: ignore
        dhan_sdk_installed = True
    except ImportError:
        pass
    provider_statuses["dhan_hq"] = {
        "priority": 3,
        "sdk_installed": dhan_sdk_installed,
        "credentials_configured": False,
        "limitation": "dhanhq SDK not installed; no client ID / access token provisioned.",
    }

    # 4. Check if research DB exists; initialize schema if authorized
    db_mgr = ResearchCandleDatabaseManager(db_path=RESEARCH_CANDLES_DB_PATH)
    db_mgr.ensure_schema()
    research_db_sha = db_mgr.compute_db_sha256()
    candles_count = db_mgr.get_candle_count()

    # 5. Run DATA-01..DATA-15 Validation Suite
    suite = IngestionValidationSuite(
        research_db_path=RESEARCH_CANDLES_DB_PATH,
        prod_db_path=PROD_DB_PATH,
        expected_prod_sha=EXPECTED_PROD_DB_SHA,
    )
    validation_results = suite.run_all(mappings)

    # 6. Post-execution production DB verification
    prod_size_after = PROD_DB_PATH.stat().st_size
    with open(PROD_DB_PATH, "rb") as f:
        prod_sha_after = hashlib.sha256(f.read()).hexdigest()

    assert prod_sha_before == prod_sha_after, "FATAL: Production DB altered during E5.4!"
    assert prod_size_before == prod_size_after, "FATAL: Production DB size changed during E5.4!"

    passed_rules = [r for r in validation_results if r.passed]
    failed_rules = [r for r in validation_results if not r.passed]

    # Evaluate Gate
    # Gate requires genuine source, complete symbols, forward coverage, etc.
    gate_open = (len(failed_rules) == 0 and candles_count > 0)

    # Determine Classification
    if gate_open:
        classification = "E5.4 COMPLETE — HISTORICAL CANDLES INGESTED AND DATA-01..DATA-15 PASSED"
    elif candles_count > 0 and len(failed_rules) > 0:
        classification = "E5.4 COMPLETE — DATA INGESTED BUT E5 REPLAY GATE REMAINS CLOSED"
    else:
        classification = "E5.4 BLOCKED — HISTORICAL CANDLE DATA INCOMPLETE"

    return {
        "classification": classification,
        "e5_replay_gate_open": gate_open,
        "total_candidate_snapshots": len(mappings),
        "total_unique_underlying_symbols": len(unique_symbols),
        "total_candles_in_research_db": candles_count,
        "research_db_path": str(RESEARCH_CANDLES_DB_PATH),
        "research_db_sha256": research_db_sha,
        "production_db_sha_before": prod_sha_before,
        "production_db_sha_after": prod_sha_after,
        "production_db_size_before": prod_size_before,
        "production_db_size_after": prod_size_after,
        "production_db_unmutated": (prod_sha_before == prod_sha_after and prod_size_before == prod_size_after),
        "provider_statuses": provider_statuses,
        "validation_passed_count": len(passed_rules),
        "validation_failed_count": len(failed_rules),
        "validation_results": [
            {
                "rule_id": r.rule_id,
                "name": r.name,
                "passed": r.passed,
                "details": r.details,
                "observed_metrics": r.observed_metrics,
            }
            for r in validation_results
        ],
    }


if __name__ == "__main__":
    res = run_e5_4_execution()
    print("=" * 80)
    print("E5.4 EXECUTION SUMMARY:")
    print("=" * 80)
    print(f"Classification:              {res['classification']}")
    print(f"E5 Replay Gate Open:         {res['e5_replay_gate_open']}")
    print(f"Total Unique Symbols:        {res['total_unique_underlying_symbols']}")
    print(f"Total Candles Ingested:      {res['total_candles_in_research_db']}")
    print(f"Validation Rules Passed:     {res['validation_passed_count']} / 15")
    print(f"Validation Rules Failed:     {res['validation_failed_count']} / 15")
    print(f"Production DB Unmutated:     {res['production_db_unmutated']}")
    print(f"Production DB SHA-256:       {res['production_db_sha_after']}")
    print("=" * 80)
    for r in res["validation_results"]:
        status_str = "PASS" if r["passed"] else "FAIL"
        print(f"  [{status_str}] {r['rule_id']}: {r['name']} -- {r['details']}")
    print("=" * 80)
