"""
System Parity Checker — fail-fast assertion that backtest and live share identical constants.

Call assert_backtest_live_parity() at application startup before any signal evaluation.
A mismatch means the simulation used different thresholds than the live engine, making
all backtest statistics unreliable. This is treated as a hard boot error.

Also provides a lightweight runtime checksum to detect config drift between restarts.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

log = logging.getLogger("system_parity")


def assert_backtest_live_parity() -> None:
    """
    Hard assertion: simulation_engine tier constants must mirror tier_engine constants.

    Raises AssertionError with a clear diagnostic if any constant diverges.
    Called at startup — failing here means the backtest results are unreliable.
    """
    from core.simulation_engine import SIGNAL_CONFIRMED, SIGNAL_EARLY, SIGNAL_STRONG
    from core.tier_engine import TIER_MODERATE_MIN, TIER_STRONG_MIN, TIER_WEAK_MIN

    mismatches = []

    if SIGNAL_EARLY != TIER_WEAK_MIN:
        mismatches.append(
            f"SIGNAL_EARLY={SIGNAL_EARLY} != TIER_WEAK_MIN={TIER_WEAK_MIN} "
            f"(simulation_engine vs tier_engine)"
        )
    if SIGNAL_CONFIRMED != TIER_MODERATE_MIN:
        mismatches.append(
            f"SIGNAL_CONFIRMED={SIGNAL_CONFIRMED} != TIER_MODERATE_MIN={TIER_MODERATE_MIN} "
            f"(simulation_engine vs tier_engine)"
        )
    if SIGNAL_STRONG != TIER_STRONG_MIN:
        mismatches.append(
            f"SIGNAL_STRONG={SIGNAL_STRONG} != TIER_STRONG_MIN={TIER_STRONG_MIN} "
            f"(simulation_engine vs tier_engine)"
        )

    if mismatches:
        msg = (
            "BACKTEST ↔ LIVE PARITY FAILURE — constants diverged:\n"
            + "\n".join(f"  • {m}" for m in mismatches)
            + "\nBacktest statistics are unreliable. Fix the constants and restart."
        )
        log.critical(msg)
        raise AssertionError(msg)

    log.info(
        "Parity OK: WEAK=%d MODERATE=%d STRONG=%d (backtest=live)",
        TIER_WEAK_MIN, TIER_MODERATE_MIN, TIER_STRONG_MIN,
    )


def check_execution_policy_consistency(config: dict[str, Any]) -> list[str]:
    """
    Verify that ExecutionPolicy constants align with config at runtime.

    Returns a list of inconsistency strings (empty = all good).
    """
    from core.tier_engine import TIER_MODERATE_MIN, TIER_STRONG_MIN, TIER_WEAK_MIN

    issues = []

    cfg_weak     = int(config.get("TIER_WEAK_MIN",     60))
    cfg_moderate = int(config.get("TIER_MODERATE_MIN", 70))
    cfg_strong   = int(config.get("TIER_STRONG_MIN",   80))

    if cfg_weak != TIER_WEAK_MIN:
        issues.append(
            f"config.TIER_WEAK_MIN={cfg_weak} != tier_engine.TIER_WEAK_MIN={TIER_WEAK_MIN}"
        )
    if cfg_moderate != TIER_MODERATE_MIN:
        issues.append(
            f"config.TIER_MODERATE_MIN={cfg_moderate} != "
            f"tier_engine.TIER_MODERATE_MIN={TIER_MODERATE_MIN}"
        )
    if cfg_strong != TIER_STRONG_MIN:
        issues.append(
            f"config.TIER_STRONG_MIN={cfg_strong} != "
            f"tier_engine.TIER_STRONG_MIN={TIER_STRONG_MIN}"
        )

    ai_thr = int(config.get("AI_THRESHOLD", 60))
    if ai_thr != cfg_weak:
        issues.append(
            f"config.AI_THRESHOLD={ai_thr} != config.TIER_WEAK_MIN={cfg_weak}: "
            f"signals {min(ai_thr, cfg_weak)}-{max(ai_thr, cfg_weak)-1} are in a dead zone"
        )

    return issues


def generate_runtime_fingerprint(config: dict[str, Any]) -> str:
    """
    SHA-256 fingerprint of execution-critical config values.

    Use at startup to detect silent config drift between restarts.
    Store the fingerprint in logs; alert if it changes.
    """
    critical_keys = [
        "AI_THRESHOLD", "TIER_WEAK_MIN", "TIER_MODERATE_MIN", "TIER_STRONG_MIN",
        "QUALITY_MIN_SCORE", "EXECUTION_MODE",
        "BASE_CAPITAL", "MAX_DAILY_LOSS", "MAX_DRAWDOWN",
        "RISK_MODE", "RISK_PER_TRADE", "RISK_FIXED_AMOUNT",
        "SL_PCT", "TARGET_PCT", "TRAIL_PCT", "MIN_NET_RR",
        "VIX_HALT_THRESHOLD", "VIX_BLOCK_THRESHOLD",
        "MAX_OPEN", "MAX_TRADES_DAY",
    ]
    snapshot = {k: config.get(k) for k in critical_keys}
    canonical = json.dumps(snapshot, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def log_startup_parity(config: dict[str, Any], logger: logging.Logger = None) -> str:
    """
    Run all parity checks at startup, log results, return fingerprint.

    Raises AssertionError if backtest/live constants diverge (hard failure).
    Returns fingerprint string for logging.
    """
    L = logger or log

    # 1. Hard assertion — must pass before any signal evaluation
    assert_backtest_live_parity()

    # 2. Config-vs-code alignment
    issues = check_execution_policy_consistency(config)
    for issue in issues:
        L.error("PARITY ISSUE: %s", issue)
    if issues:
        raise AssertionError(
            f"Config/code alignment failure ({len(issues)} issue(s)). Fix config.json."
        )

    # 3. Fingerprint
    fp = generate_runtime_fingerprint(config)
    L.info("Config fingerprint: %s (log this; alert on change between restarts)", fp)
    return fp
