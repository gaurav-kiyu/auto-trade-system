"""Tests for core.system_parity — backtest/live consistency checks."""

from __future__ import annotations

import pytest

from core.system_parity import (
    assert_backtest_live_parity,
    check_execution_policy_consistency,
    generate_runtime_fingerprint,
    log_startup_parity,
)


# ── assert_backtest_live_parity ──────────────────────────────────────────

def test_assert_backtest_live_parity_passes() -> None:
    """Constants in simulation_engine and tier_engine should match."""
    # Should not raise AssertionError
    assert_backtest_live_parity()


# ── check_execution_policy_consistency ───────────────────────────────────

def test_check_consistency_all_match() -> None:
    config = {
        "TIER_WEAK_MIN": 60,
        "TIER_MODERATE_MIN": 70,
        "TIER_STRONG_MIN": 80,
        "AI_THRESHOLD": 60,
    }
    issues = check_execution_policy_consistency(config)
    assert issues == []


def test_check_consistency_weak_mismatch() -> None:
    config = {
        "TIER_WEAK_MIN": 55,
        "TIER_MODERATE_MIN": 70,
        "TIER_STRONG_MIN": 80,
        "AI_THRESHOLD": 55,
    }
    issues = check_execution_policy_consistency(config)
    assert len(issues) >= 1
    assert any("TIER_WEAK_MIN" in i for i in issues)


def test_check_consistency_moderate_mismatch() -> None:
    config = {
        "TIER_WEAK_MIN": 60,
        "TIER_MODERATE_MIN": 75,
        "TIER_STRONG_MIN": 80,
        "AI_THRESHOLD": 60,
    }
    issues = check_execution_policy_consistency(config)
    assert len(issues) >= 1
    assert any("TIER_MODERATE_MIN" in i for i in issues)


def test_check_consistency_strong_mismatch() -> None:
    config = {
        "TIER_WEAK_MIN": 60,
        "TIER_MODERATE_MIN": 70,
        "TIER_STRONG_MIN": 85,
        "AI_THRESHOLD": 60,
    }
    issues = check_execution_policy_consistency(config)
    assert len(issues) >= 1
    assert any("TIER_STRONG_MIN" in i for i in issues)


def test_check_consistency_ai_threshold_mismatch() -> None:
    """AI_THRESHOLD != TIER_WEAK_MIN should be flagged."""
    config = {
        "TIER_WEAK_MIN": 60,
        "TIER_MODERATE_MIN": 70,
        "TIER_STRONG_MIN": 80,
        "AI_THRESHOLD": 65,
    }
    issues = check_execution_policy_consistency(config)
    assert len(issues) >= 1
    assert any("AI_THRESHOLD" in i for i in issues)


# ── generate_runtime_fingerprint ─────────────────────────────────────────

def test_fingerprint_produces_string() -> None:
    config = {
        "AI_THRESHOLD": 60,
        "BASE_CAPITAL": 5000,
        "EXECUTION_MODE": "PAPER",
    }
    fp = generate_runtime_fingerprint(config)
    assert isinstance(fp, str)
    assert len(fp) == 16  # hex digest[:16]


def test_fingerprint_deterministic() -> None:
    config = {"AI_THRESHOLD": 60, "BASE_CAPITAL": 5000}
    fp1 = generate_runtime_fingerprint(config)
    fp2 = generate_runtime_fingerprint(config)
    assert fp1 == fp2


def test_fingerprint_changes_on_config_change() -> None:
    config1 = {"AI_THRESHOLD": 60, "BASE_CAPITAL": 5000}
    config2 = {"AI_THRESHOLD": 65, "BASE_CAPITAL": 5000}
    fp1 = generate_runtime_fingerprint(config1)
    fp2 = generate_runtime_fingerprint(config2)
    assert fp1 != fp2


def test_fingerprint_missing_keys() -> None:
    config = {"AI_THRESHOLD": 60}  # Only has 1 of the critical keys
    fp = generate_runtime_fingerprint(config)
    assert isinstance(fp, str)
    assert len(fp) == 16


# ── log_startup_parity ──────────────────────────────────────────────────

def test_log_startup_parity_returns_fingerprint() -> None:
    config = {
        "TIER_WEAK_MIN": 60,
        "TIER_MODERATE_MIN": 70,
        "TIER_STRONG_MIN": 80,
        "AI_THRESHOLD": 60,
        "BASE_CAPITAL": 5000,
        "EXECUTION_MODE": "PAPER",
    }
    fp = log_startup_parity(config)
    assert isinstance(fp, str)
    assert len(fp) == 16


def test_log_startup_parity_raises_on_issues() -> None:
    config = {
        "TIER_WEAK_MIN": 55,  # Mismatch
        "TIER_MODERATE_MIN": 70,
        "TIER_STRONG_MIN": 80,
        "AI_THRESHOLD": 55,
        "BASE_CAPITAL": 5000,
        "EXECUTION_MODE": "PAPER",
    }
    with pytest.raises(AssertionError, match="alignment failure"):
        log_startup_parity(config)
