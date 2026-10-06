"""test_d20_b_shadow_analysis.py - Unit tests for D20-B retrospective shadow analysis.

Governing Standard: OPB-FINAL-PHASE-GOVERNANCE-001
Execution Mode: STRICTLY OFFLINE / ZERO MUTATION UNIT TESTS
"""

from __future__ import annotations

import pytest

from core.research.d20_b_shadow_analysis import (
    SignalRecord,
    apply_d20_b_shadow_simulation,
    load_signals,
    verify_prod_db_integrity,
)


def test_production_db_integrity():
    """Verify production database SHA and size match authoritative specification."""
    sha, size = verify_prod_db_integrity()
    assert sha == "f12ba2e45e91077dbb3cfde289938aba225bd1669b9d02a7ddc5a49e57cd6e5a"
    assert size == 1216512


def test_d20_b_simulation_allows_one_call_and_one_put():
    """Verify D20-B allows 1 CALL and 1 PUT in the same session, suppressing duplicates."""
    recs = [
        SignalRecord("S1", "2026-09-17 09:30:00", "2026-09-17", "NIFTY", "NIFTY", "INDEX_OPTIONS", "CALL", 90, "ACTIVE", "", "UNRESOLVED"),
        SignalRecord("S2", "2026-09-17 09:45:00", "2026-09-17", "NIFTY", "NIFTY", "INDEX_OPTIONS", "PUT", 85, "ACTIVE", "", "UNRESOLVED"),
        SignalRecord("S3", "2026-09-17 10:00:00", "2026-09-17", "NIFTY", "NIFTY", "INDEX_OPTIONS", "CALL", 92, "SL_HIT", "SL", "SL"),
        SignalRecord("S4", "2026-09-17 10:15:00", "2026-09-17", "NIFTY", "NIFTY", "INDEX_OPTIONS", "PUT", 80, "SL_HIT", "SL", "SL"),
        # Next session allows 1 CALL again
        SignalRecord("S5", "2026-09-18 09:30:00", "2026-09-18", "NIFTY", "NIFTY", "INDEX_OPTIONS", "CALL", 90, "ACTIVE", "", "UNRESOLVED"),
    ]

    evaluated = apply_d20_b_shadow_simulation(recs)
    decisions = [s.decision for s in evaluated]

    assert decisions == [
        "RETAINED",  # S1: first CALL on 2026-09-17
        "RETAINED",  # S2: first PUT on 2026-09-17
        "D20_B_SHADOW_SUPPRESSED",  # S3: second CALL on 2026-09-17
        "D20_B_SHADOW_SUPPRESSED",  # S4: second PUT on 2026-09-17
        "RETAINED",  # S5: first CALL on 2026-09-18
    ]


def test_d20_b_different_canonical_indices_independent():
    """Verify NIFTY and BANKNIFTY have independent session quotas."""
    recs = [
        SignalRecord("S1", "2026-09-17 09:30:00", "2026-09-17", "NIFTY", "NIFTY", "INDEX_OPTIONS", "CALL", 90, "ACTIVE", "", "UNRESOLVED"),
        SignalRecord("S2", "2026-09-17 09:35:00", "2026-09-17", "BANKNIFTY", "BANKNIFTY", "INDEX_OPTIONS", "CALL", 88, "ACTIVE", "", "UNRESOLVED"),
        SignalRecord("S3", "2026-09-17 10:00:00", "2026-09-17", "NIFTY", "NIFTY", "INDEX_OPTIONS", "CALL", 95, "ACTIVE", "", "UNRESOLVED"),
    ]

    evaluated = apply_d20_b_shadow_simulation(recs)
    assert evaluated[0].decision == "RETAINED"
    assert evaluated[1].decision == "RETAINED"
    assert evaluated[2].decision == "D20_B_SHADOW_SUPPRESSED"


def test_load_signals_authoritative_count():
    """Verify load_signals reads exactly 29 INDEX_OPTIONS signals from production DB."""
    sigs = load_signals(population_scope="INDEX_OPTIONS")
    assert len(sigs) == 29
    assert all(s.category == "INDEX_OPTIONS" for s in sigs)
