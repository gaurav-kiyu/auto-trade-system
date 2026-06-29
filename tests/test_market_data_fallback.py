"""Tests for core.market_data_fallback - dual-source market data with fallback."""

from __future__ import annotations

from core.market_data_fallback import (
    DualSourceMarketData,
    PriceQuote,
    PriceValidationResult,
    get_market_data,
)

# ── PriceQuote ───────────────────────────────────────────────────────────

def test_price_quote() -> None:
    from datetime import datetime
    pq = PriceQuote(symbol="NIFTY", price=23000.0, timestamp=datetime(2026, 6, 1, 9, 15), source="primary")
    assert pq.symbol == "NIFTY"
    assert pq.price == 23000.0
    assert pq.source == "primary"


# ── PriceValidationResult ────────────────────────────────────────────────

def test_price_validation_result_valid() -> None:
    result = PriceValidationResult(is_valid=True, primary_price=23000.0, fallback_price=23005.0, mismatch_pct=0.02)
    assert result.is_valid is True
    assert result.should_pause is False


def test_price_validation_result_invalid() -> None:
    result = PriceValidationResult(
        is_valid=False, primary_price=23000.0, fallback_price=25000.0,
        mismatch_pct=8.7, reason="Mismatch 8.70% > 1.00%", should_pause=True,
    )
    assert result.is_valid is False
    assert result.should_pause is True


# ── DualSourceMarketData construction ───────────────────────────────────

def test_dual_source_default_config() -> None:
    dsm = DualSourceMarketData(primary_getter=lambda s: 23000.0)
    assert dsm._enabled is False
    assert dsm._mismatch_threshold_pct == 1.0
    assert dsm._paused is False


def test_dual_source_custom_config() -> None:
    dsm = DualSourceMarketData(
        primary_getter=lambda s: 23000.0,
        config={"market_data_secondary_enabled": True, "market_data_mismatch_threshold_pct": 2.0},
    )
    assert dsm._enabled is True
    assert dsm._mismatch_threshold_pct == 2.0


# ── get_price ────────────────────────────────────────────────────────────

def test_get_price_primary() -> None:
    dsm = DualSourceMarketData(primary_getter=lambda s: 23000.0)
    price, source = dsm.get_price("NIFTY")
    assert price == 23000.0
    assert source == "primary"


def test_get_price_primary_none_fallback_disabled() -> None:
    dsm = DualSourceMarketData(primary_getter=lambda s: None, config={"market_data_secondary_enabled": False})
    price, source = dsm.get_price("NIFTY")
    assert price is None
    assert source == "none"


def test_get_price_fallback() -> None:
    dsm = DualSourceMarketData(
        primary_getter=lambda s: None,
        fallback_getter=lambda s: 23100.0,
        config={"market_data_secondary_enabled": True},
    )
    price, source = dsm.get_price("NIFTY")
    assert price == 23100.0
    assert source == "fallback"


def test_get_price_all_sources_fail() -> None:
    dsm = DualSourceMarketData(
        primary_getter=lambda s: None,
        fallback_getter=lambda s: None,
        config={"market_data_secondary_enabled": True},
    )
    price, source = dsm.get_price("NIFTY")
    assert price is None
    assert source == "none"


def test_get_price_primary_exception() -> None:
    def failing(symbol: str) -> float:
        raise ValueError("connection error")
    dsm = DualSourceMarketData(primary_getter=failing)
    price, source = dsm.get_price("NIFTY")
    assert price is None
    assert source == "error"


# ── validate_price ──────────────────────────────────────────────────────

def test_validate_price_disabled() -> None:
    dsm = DualSourceMarketData(
        primary_getter=lambda s: 23000.0,
        config={"market_data_secondary_enabled": False},
    )
    result = dsm.validate_price("NIFTY", 23000.0)
    assert result.is_valid is True
    assert result.reason == "Fallback disabled"


def test_validate_price_fallback_unavailable() -> None:
    dsm = DualSourceMarketData(
        primary_getter=lambda s: 23000.0,
        fallback_getter=lambda s: None,
        config={"market_data_secondary_enabled": True},
    )
    result = dsm.validate_price("NIFTY", 23000.0)
    assert result.is_valid is True
    assert result.reason == "Fallback unavailable"


def test_validate_price_mismatch_exceeds_threshold() -> None:
    dsm = DualSourceMarketData(
        primary_getter=lambda s: 23000.0,
        fallback_getter=lambda s: 24000.0,
        config={"market_data_secondary_enabled": True, "market_data_mismatch_threshold_pct": 1.0},
    )
    result = dsm.validate_price("NIFTY", 23000.0)
    assert result.is_valid is False
    assert result.should_pause is True
    assert result.mismatch_pct > 1.0


def test_validate_price_within_threshold() -> None:
    dsm = DualSourceMarketData(
        primary_getter=lambda s: 23000.0,
        fallback_getter=lambda s: 23050.0,
        config={"market_data_secondary_enabled": True, "market_data_mismatch_threshold_pct": 1.0},
    )
    result = dsm.validate_price("NIFTY", 23000.0)
    assert result.is_valid is True
    # (50/23000)*100 = 0.217% which is < 1% threshold
    assert result.mismatch_pct < 1.0


def test_validate_price_zero_primary() -> None:
    dsm = DualSourceMarketData(
        primary_getter=lambda s: 0.0,
        fallback_getter=lambda s: 23000.0,
        config={"market_data_secondary_enabled": True},
    )
    result = dsm.validate_price("NIFTY", 0.0)
    assert result.is_valid is False
    assert result.should_pause is True


def test_validate_price_store_last_prices() -> None:
    dsm = DualSourceMarketData(
        primary_getter=lambda s: 23000.0,
        fallback_getter=lambda s: 23050.0,
        config={"market_data_secondary_enabled": True},
    )
    dsm.validate_price("NIFTY", 23000.0)
    last = dsm.get_last_prices()
    assert "NIFTY" in last
    assert last["NIFTY"]["primary"] == 23000.0
    assert last["NIFTY"]["fallback"] == 23050.0


# ── pause / resume / is_paused ──────────────────────────────────────────

def test_pause_and_resume() -> None:
    dsm = DualSourceMarketData(primary_getter=lambda s: 23000.0)
    paused, reason = dsm.is_paused()
    assert paused is False

    dsm.pause("Data mismatch detected")
    paused, reason = dsm.is_paused()
    assert paused is True
    assert "Data mismatch" in reason

    dsm.resume()
    paused, reason = dsm.is_paused()
    assert paused is False
    assert reason == ""


# ── health_check ─────────────────────────────────────────────────────────

def test_health_check() -> None:
    dsm = DualSourceMarketData(
        primary_getter=lambda s: 23000.0,
        config={"market_data_secondary_enabled": True},
    )
    health = dsm.health_check()
    assert health["enabled"] is True
    assert health["paused"] is False
    assert health["tracked_symbols"] == 0


# ── get_market_data singleton ───────────────────────────────────────────

def test_get_market_data_singleton() -> None:
    from core.market_data_fallback import _market_data
    original = _market_data
    try:
        import core.market_data_fallback
        core.market_data_fallback._market_data = None
        md1 = get_market_data(primary_getter=lambda s: 23000.0)
        md2 = get_market_data()
        assert md1 is md2
    finally:
        core.market_data_fallback._market_data = original
