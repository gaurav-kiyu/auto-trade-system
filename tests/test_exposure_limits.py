"""Tests for core.exposure_limits - exposure concentration limits."""

from __future__ import annotations

from core.exposure_limits import (
    ExposureCheckResult,
    ExposureConcentrationLimiter,
    ExposureSnapshot,
    get_exposure_limiter,
)


# ── ExposureSnapshot ─────────────────────────────────────────────────────

def test_exposure_snapshot_defaults() -> None:
    snap = ExposureSnapshot()
    assert snap.total_value == 0.0
    assert snap.by_symbol == {}
    assert snap.by_expiry == {}
    assert snap.by_direction == {}
    assert snap.by_strategy == {}
    assert snap.timestamp is not None


# ── ExposureCheckResult ─────────────────────────────────────────────────

def test_exposure_check_result_defaults() -> None:
    result = ExposureCheckResult(allowed=True)
    assert result.allowed is True
    assert result.reason == ""
    assert result.current_exposure_pct == 0.0
    assert result.limit_pct == 0.0
    assert result.suggested_reduction == 0.0


def test_exposure_check_result_blocked() -> None:
    result = ExposureCheckResult(
        allowed=False,
        reason="Symbol exposure 35% > 30% limit",
        current_exposure_pct=35.0,
        limit_pct=30.0,
        suggested_reduction=500.0,
    )
    assert result.allowed is False
    assert result.current_exposure_pct == 35.0
    assert result.suggested_reduction == 500.0


# ── ExposureConcentrationLimiter ─────────────────────────────────────────

def test_limiter_default_config() -> None:
    limiter = ExposureConcentrationLimiter()
    assert limiter._max_per_symbol_pct == 30.0
    assert limiter._max_per_expiry_pct == 50.0
    assert limiter._max_per_direction_pct == 80.0
    assert limiter._max_per_strategy_pct == 40.0


def test_limiter_custom_config() -> None:
    limiter = ExposureConcentrationLimiter({
        "max_exposure_per_symbol_pct": 20.0,
        "max_exposure_per_direction_pct": 50.0,
    })
    assert limiter._max_per_symbol_pct == 20.0
    assert limiter._max_per_direction_pct == 50.0


# ── update_position / remove_position ───────────────────────────────────

def test_update_position_adds_tracking() -> None:
    limiter = ExposureConcentrationLimiter()
    limiter.update_position(symbol="NIFTY", expiry="2026-06-18",
                            direction="CALL", strategy="DIRECTIONAL", value=10000)
    assert "NIFTY" in limiter._positions
    assert limiter._positions["NIFTY"]["value"] == 10000


def test_update_position_zero_value_removes() -> None:
    limiter = ExposureConcentrationLimiter()
    limiter.update_position(symbol="NIFTY", expiry="2026-06-18",
                            direction="CALL", strategy="DIRECTIONAL", value=10000)
    limiter.update_position(symbol="NIFTY", expiry="",
                            direction="", strategy="", value=0)
    assert "NIFTY" not in limiter._positions


def test_remove_position() -> None:
    limiter = ExposureConcentrationLimiter()
    limiter.update_position("NIFTY", "exp1", "CALL", "DIR", 5000)
    limiter.remove_position("NIFTY")
    assert "NIFTY" not in limiter._positions


# ── get_exposure_snapshot ────────────────────────────────────────────────

def test_get_exposure_snapshot_empty() -> None:
    limiter = ExposureConcentrationLimiter()
    snap = limiter.get_exposure_snapshot(total_capital=100000)
    assert snap.total_value == 0.0
    assert snap.by_symbol == {}


def test_get_exposure_snapshot_with_positions() -> None:
    limiter = ExposureConcentrationLimiter()
    limiter.update_position("NIFTY", "2026-06-18", "CALL", "DIR", 15000)
    limiter.update_position("BANKNIFTY", "2026-06-18", "PUT", "DIR", 10000)

    snap = limiter.get_exposure_snapshot(total_capital=100000)
    assert snap.total_value == 25000
    assert snap.by_symbol["NIFTY"] == 15000
    assert snap.by_symbol["BANKNIFTY"] == 10000
    assert snap.by_expiry["2026-06-18"] == 25000
    assert snap.by_direction["CALL"] == 15000
    assert snap.by_direction["PUT"] == 10000


# ── check_limits ─────────────────────────────────────────────────────────

def test_check_limits_zero_capital() -> None:
    limiter = ExposureConcentrationLimiter()
    result = limiter.check_limits("NIFTY", "exp", "CALL", "DIR", 10000, 0)
    assert result.allowed is True
    assert result.reason == "No capital"


def test_check_limits_symbol_allowed() -> None:
    limiter = ExposureConcentrationLimiter({"max_exposure_per_symbol_pct": 30.0})
    result = limiter.check_limits("NIFTY", "exp", "CALL", "DIR", 25000, 100000)
    assert result.allowed is True
    assert "OK" in result.reason


def test_check_limits_symbol_exceeded() -> None:
    limiter = ExposureConcentrationLimiter({"max_exposure_per_symbol_pct": 20.0})
    result = limiter.check_limits("NIFTY", "exp", "CALL", "DIR", 25000, 100000)
    assert result.allowed is False
    assert "Symbol exposure" in result.reason
    assert result.current_exposure_pct == 25.0
    assert result.limit_pct == 20.0


def test_check_limits_expiry_exceeded() -> None:
    limiter = ExposureConcentrationLimiter({
        "max_exposure_per_symbol_pct": 50.0,
        "max_exposure_per_expiry_pct": 30.0,
    })
    limiter.update_position("BANKNIFTY", "2026-06-18", "PUT", "DIR", 35000)
    result = limiter.check_limits("NIFTY", "2026-06-18", "CALL", "DIR", 10000, 100000)
    assert result.allowed is False
    assert "Expiry exposure" in result.reason


def test_check_limits_direction_exceeded() -> None:
    limiter = ExposureConcentrationLimiter({
        "max_exposure_per_symbol_pct": 50.0,
        "max_exposure_per_expiry_pct": 50.0,
        "max_exposure_per_direction_pct": 50.0,
    })
    limiter.update_position("BANKNIFTY", "exp1", "CALL", "DIR", 45000)
    result = limiter.check_limits("NIFTY", "exp2", "CALL", "DIR", 10000, 100000)
    assert result.allowed is False
    assert "Direction exposure" in result.reason


def test_check_limits_strategy_exceeded() -> None:
    limiter = ExposureConcentrationLimiter({
        "max_exposure_per_symbol_pct": 50.0,
        "max_exposure_per_direction_pct": 80.0,
        "max_exposure_per_strategy_pct": 50.0,
    })
    limiter.update_position("NIFTY", "exp1", "CALL", "STRADDLE", 35000)
    # 35000 + 10000 = 45000 = 45% of 100000, strategy limit = 50% -> allowed
    result = limiter.check_limits("BANKNIFTY", "exp2", "PUT", "STRADDLE", 10000, 100000)
    assert result.allowed is True
    assert "OK" in result.reason


# ── get_limits_config ────────────────────────────────────────────────────

def test_get_limits_config() -> None:
    limiter = ExposureConcentrationLimiter({
        "max_exposure_per_symbol_pct": 25.0,
    })
    config = limiter.get_limits_config()
    assert config["max_per_symbol_pct"] == 25.0
    assert config["max_per_expiry_pct"] == 50.0


# ── reset ────────────────────────────────────────────────────────────────

def test_reset_clears_positions() -> None:
    limiter = ExposureConcentrationLimiter()
    limiter.update_position("NIFTY", "exp", "CALL", "DIR", 5000)
    limiter.reset()
    assert limiter._positions == {}


# ── get_exposure_limiter singleton ──────────────────────────────────────

def test_get_exposure_limiter_singleton() -> None:
    from core.exposure_limits import _exposure_limiter
    # Reset for test
    _exposure_limiter_orig = _exposure_limiter
    try:
        import core.exposure_limits
        core.exposure_limits._exposure_limiter = None
        limiter1 = get_exposure_limiter()
        limiter2 = get_exposure_limiter()
        assert limiter1 is limiter2
    finally:
        core.exposure_limits._exposure_limiter = _exposure_limiter_orig
