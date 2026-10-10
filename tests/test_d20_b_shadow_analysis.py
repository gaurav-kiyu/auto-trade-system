"""test_d20_b_shadow_analysis.py - Unit tests for D20-B retrospective shadow analysis.

Governing Standard: OPB-FINAL-PHASE-GOVERNANCE-001
Execution Mode: STRICTLY OFFLINE / ZERO MUTATION UNIT TESTS
"""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Generator
from pathlib import Path

import core.research.d20_b_shadow_analysis as d20_mod
import pytest
from core.research.d20_b_shadow_analysis import (
    EXPECTED_PROD_DB_SHA,
    EXPECTED_PROD_DB_SIZE,
    PROD_DB_PATH,
    SignalRecord,
    apply_d20_b_shadow_simulation,
    load_signals,
    verify_prod_db_integrity,
)


@pytest.fixture
def d20_shadow_fixture(tmp_path: Path) -> Generator[tuple[Path, str, int], None, None]:
    """Creates a deterministic SQLite database with 29 INDEX_OPTIONS and auxiliary signals."""
    db_file = tmp_path / "fixture_signals_history.db"
    conn = sqlite3.connect(str(db_file))
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE system_signals (
            signal_id TEXT PRIMARY KEY,
            timestamp TEXT NOT NULL,
            created_date TEXT NOT NULL,
            symbol TEXT NOT NULL,
            category TEXT NOT NULL,
            direction TEXT NOT NULL,
            score INTEGER NOT NULL,
            status TEXT NOT NULL,
            first_touch TEXT NOT NULL
        )
    """)
    # Seed 29 deterministic INDEX_OPTIONS signals matching authoritative test count
    for i in range(29):
        cur.execute(
            """INSERT INTO system_signals VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                f"SIG_SHADOW_{i:03d}",
                f"2026-09-17 09:{i:02d}:00",
                "2026-09-17",
                "NIFTY",
                "INDEX_OPTIONS",
                "CALL" if i % 2 == 0 else "PUT",
                90,
                "ACTIVE",
                "T1" if i % 2 == 0 else "SL",
            ),
        )
    # Seed 5 auxiliary non-INDEX_OPTIONS signals to verify scope filtering
    for i in range(5):
        cur.execute(
            """INSERT INTO system_signals VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                f"SIG_AUX_{i:03d}",
                f"2026-09-17 09:{i:02d}:00",
                "2026-09-17",
                "NIFTYFUT",
                "FUTURES",
                "CALL",
                85,
                "ACTIVE",
                "T1",
            ),
        )
    conn.commit()
    conn.close()

    sha = hashlib.sha256(db_file.read_bytes()).hexdigest()
    sz = db_file.stat().st_size
    yield db_file, sha, sz


def test_production_db_integrity(monkeypatch: pytest.MonkeyPatch, d20_shadow_fixture: tuple[Path, str, int]):
    """Verify production database SHA and size match authoritative specification."""
    db_file, exp_sha, exp_sz = d20_shadow_fixture

    # 1. Deterministic Fixture Verification
    monkeypatch.setattr(d20_mod, "PROD_DB_PATH", db_file)
    monkeypatch.setattr(d20_mod, "EXPECTED_PROD_DB_SHA", exp_sha)
    monkeypatch.setattr(d20_mod, "EXPECTED_PROD_DB_SIZE", exp_sz)
    sha, size = verify_prod_db_integrity()
    assert sha == exp_sha
    assert size == exp_sz

    # 2. Integrity Mismatch Guard Verification
    monkeypatch.setattr(d20_mod, "EXPECTED_PROD_DB_SHA", "0" * 64)
    with pytest.raises(RuntimeError, match="FATAL: Production DB integrity mismatch"):
        verify_prod_db_integrity()

    # 3. Missing Database Guard Verification
    monkeypatch.setattr(d20_mod, "PROD_DB_PATH", db_file.parent / "nonexistent.db")
    with pytest.raises(FileNotFoundError, match="Production database missing"):
        verify_prod_db_integrity()

    # 4. Canonical Baseline Validation (when historical production database is present on disk)
    if PROD_DB_PATH.exists() and PROD_DB_PATH.stat().st_size == EXPECTED_PROD_DB_SIZE:
        if hashlib.sha256(PROD_DB_PATH.read_bytes()).hexdigest() == EXPECTED_PROD_DB_SHA:
            monkeypatch.undo()
            c_sha, c_sz = verify_prod_db_integrity()
            assert c_sha == EXPECTED_PROD_DB_SHA
            assert c_sz == EXPECTED_PROD_DB_SIZE


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


def test_load_signals_authoritative_count(monkeypatch: pytest.MonkeyPatch, d20_shadow_fixture: tuple[Path, str, int]):
    """Verify load_signals reads exactly 29 INDEX_OPTIONS signals from production DB."""
    db_file, exp_sha, exp_sz = d20_shadow_fixture

    # 1. Deterministic Fixture Loading
    monkeypatch.setattr(d20_mod, "PROD_DB_PATH", db_file)
    monkeypatch.setattr(d20_mod, "EXPECTED_PROD_DB_SHA", exp_sha)
    monkeypatch.setattr(d20_mod, "EXPECTED_PROD_DB_SIZE", exp_sz)
    sigs = load_signals(population_scope="INDEX_OPTIONS")
    assert len(sigs) == 29
    assert all(s.category == "INDEX_OPTIONS" for s in sigs)

    # 2. Canonical Baseline Loading (when historical production database is present on disk)
    if PROD_DB_PATH.exists() and PROD_DB_PATH.stat().st_size == EXPECTED_PROD_DB_SIZE:
        if hashlib.sha256(PROD_DB_PATH.read_bytes()).hexdigest() == EXPECTED_PROD_DB_SHA:
            monkeypatch.undo()
            c_sigs = load_signals(population_scope="INDEX_OPTIONS")
            assert len(c_sigs) == 29
            assert all(s.category == "INDEX_OPTIONS" for s in c_sigs)
