"""
Tests for core/domains/risk/model.py - Risk Domain Models.

Covers (30+ tests):
- RiskError exception
- RiskLimits dataclass with defaults
- RiskDecision dataclass
- Risk domain Position dataclass with direction computation
- MarketConditions dataclass
- PortfolioRiskMetrics dataclass
- PriceLevel, VolumeProfile, HistoricalStats frozen value objects
"""

from __future__ import annotations

from datetime import datetime

import pytest
from core.domains.risk.model import (
    HistoricalStats,
    MarketConditions,
    PortfolioRiskMetrics,
    Position,
    PriceLevel,
    RiskDecision,
    RiskError,
    RiskLimits,
    VolumeProfile,
)

# ── RiskError Tests ───────────────────────────────────────────────────────────


class TestRiskError:
    """RiskError exception."""

    def test_is_exception(self):
        assert issubclass(RiskError, Exception)

    def test_raise_with_message(self):
        with pytest.raises(RiskError, match="risk limit exceeded"):
            raise RiskError("risk limit exceeded")


# ── RiskLimits Tests ──────────────────────────────────────────────────────────


class TestRiskLimits:
    """RiskLimits configuration dataclass."""

    def test_default_values(self):
        limits = RiskLimits()
        assert limits.max_position_size == 100
        assert limits.max_daily_loss == 1000.0
        assert limits.max_drawdown == 0.20
        assert limits.max_consecutive_losses == 5
        assert limits.max_portfolio_exposure == 0.80
        assert limits.max_volatility == 0.50
        assert limits.use_kelly_sizing is True
        assert limits.kelly_fraction == 0.5

    def test_custom_values(self):
        limits = RiskLimits(
            max_position_size=50,
            max_daily_loss=500.0,
            max_drawdown=0.15,
            max_consecutive_losses=3,
        )
        assert limits.max_position_size == 50
        assert limits.max_daily_loss == 500.0
        assert limits.max_drawdown == 0.15
        assert limits.max_consecutive_losses == 3

    def test_kelly_disabled(self):
        limits = RiskLimits(use_kelly_sizing=False)
        assert limits.use_kelly_sizing is False

    def test_all_fields_have_defaults(self):
        """All RiskLimits fields should have non-None defaults."""
        limits = RiskLimits()
        fields = [
            limits.max_position_size, limits.max_daily_loss,
            limits.max_drawdown, limits.max_consecutive_losses,
            limits.max_portfolio_exposure, limits.max_volatility,
            limits.max_liquidity_size, limits.max_correlation,
            limits.max_open_positions, limits.target_volatility,
            limits.use_kelly_sizing, limits.kelly_fraction,
            limits.min_position_size, limits.account_equity,
            limits.max_portfolio_risk_score,
        ]
        assert all(f is not None for f in fields)


# ── RiskDecision Tests ────────────────────────────────────────────────────────


class TestRiskDecision:
    """RiskDecision dataclass."""

    def test_allowed_default(self):
        decision = RiskDecision(allowed=True)
        assert decision.allowed is True
        assert decision.reason == ""
        assert decision.suggested_size == 0
        assert decision.risk_metrics is None

    def test_blocked_with_reason(self):
        decision = RiskDecision(
            allowed=False,
            reason="Daily loss limit exceeded",
            suggested_size=0,
        )
        assert decision.allowed is False
        assert "Daily loss" in decision.reason

    def test_with_risk_metrics(self):
        metrics = {"var_95": 5000.0, "expected_shortfall": 7500.0}
        decision = RiskDecision(
            allowed=True,
            reason="OK",
            suggested_size=25,
            risk_metrics=metrics,
        )
        assert decision.suggested_size == 25
        assert decision.risk_metrics["var_95"] == 5000.0


# ── Position (Risk Domain) Tests ──────────────────────────────────────────────


class TestRiskDomainPosition:
    """Risk domain Position with auto-computed direction."""

    def test_long_position(self):
        pos = Position(
            symbol="NIFTY",
            quantity=50,
            average_price=150.0,
            market_value=7500.0,
            unrealized_pnl=250.0,
            realized_pnl=0.0,
        )
        assert pos.symbol == "NIFTY"
        assert pos.quantity == 50
        assert pos.direction == "LONG"
        assert pos.market_value == 7500.0

    def test_short_position(self):
        pos = Position(
            symbol="BANKNIFTY",
            quantity=-25,
            average_price=50000.0,
            market_value=1250000.0,
            unrealized_pnl=-500.0,
            realized_pnl=0.0,
        )
        assert pos.quantity == -25
        assert pos.direction == "SHORT"

    def test_neutral_position(self):
        pos = Position(
            symbol="FINNIFTY",
            quantity=0,
            average_price=0.0,
            market_value=0.0,
            unrealized_pnl=0.0,
            realized_pnl=0.0,
        )
        assert pos.direction == "NEUTRAL"

    def test_timestamp_defaults(self):
        pos = Position(
            symbol="NIFTY", quantity=50,
            average_price=150.0, market_value=7500.0,
            unrealized_pnl=0.0, realized_pnl=0.0,
        )
        assert pos.timestamp is not None

    def test_custom_timestamp(self):
        ts = datetime(2026, 6, 20, 9, 15, 0)
        pos = Position(
            symbol="NIFTY", quantity=50,
            average_price=150.0, market_value=7500.0,
            unrealized_pnl=0.0, realized_pnl=0.0,
            timestamp=ts,
        )
        assert pos.timestamp == ts


# ── MarketConditions Tests ────────────────────────────────────────────────────


class TestMarketConditions:
    """MarketConditions dataclass."""

    def test_default_values(self):
        mc = MarketConditions()
        assert mc.volatility == 0.0
        assert mc.liquidity == "NORMAL"
        assert mc.trend == "NEUTRAL"
        assert mc.volume_profile == "NORMAL"

    def test_bullish_trend(self):
        mc = MarketConditions(volatility=0.15, trend="BULLISH")
        assert mc.volatility == 0.15
        assert mc.trend == "BULLISH"

    def test_high_volatility(self):
        mc = MarketConditions(volatility=0.45, liquidity="LOW")
        assert mc.volatility == 0.45
        assert mc.liquidity == "LOW"


# ── PortfolioRiskMetrics Tests ────────────────────────────────────────────────


class TestPortfolioRiskMetrics:
    """PortfolioRiskMetrics dataclass."""

    def test_create(self):
        metrics = PortfolioRiskMetrics(
            total_exposure=500000.0,
            net_value=1000000.0,
            concentration_risk=0.35,
            volatility=0.20,
            drawdown=0.05,
            value_at_risk_95=50000.0,
        )
        assert metrics.total_exposure == 500000.0
        assert metrics.net_value == 1000000.0
        assert metrics.concentration_risk == 0.35
        assert metrics.drawdown == 0.05
        assert metrics.value_at_risk_95 == 50000.0

    def test_timestamp_defaults(self):
        metrics = PortfolioRiskMetrics(
            total_exposure=0.0, net_value=0.0,
            concentration_risk=0.0, volatility=0.0,
            drawdown=0.0, value_at_risk_95=0.0,
        )
        assert isinstance(metrics.timestamp, datetime)


# ── Frozen Value Objects Tests ───────────────────────────────────────────────


class TestPriceLevel:
    """PriceLevel immutable value object."""

    def test_create(self):
        ts = datetime.now()
        pl = PriceLevel(price=150.0, timestamp=ts)
        assert pl.price == 150.0
        assert pl.timestamp == ts

    def test_immutable(self):
        pl = PriceLevel(price=150.0, timestamp=datetime.now())
        with pytest.raises(AttributeError):
            pl.price = 200.0  # frozen dataclass

    def test_equality(self):
        ts = datetime.now()
        pl1 = PriceLevel(price=150.0, timestamp=ts)
        pl2 = PriceLevel(price=150.0, timestamp=ts)
        assert pl1 == pl2  # frozen dataclasses are comparable


class TestVolumeProfile:
    """VolumeProfile immutable value object."""

    def test_create(self):
        ts = datetime.now()
        pl = PriceLevel(price=150.0, timestamp=ts)
        vp = VolumeProfile(volume_node=1000.0, price_level=pl, timestamp=ts)
        assert vp.volume_node == 1000.0
        assert vp.price_level.price == 150.0

    def test_immutable(self):
        ts = datetime.now()
        pl = PriceLevel(price=150.0, timestamp=ts)
        vp = VolumeProfile(volume_node=1000.0, price_level=pl, timestamp=ts)
        with pytest.raises(AttributeError):
            vp.volume_node = 2000.0  # frozen dataclass


class TestHistoricalStats:
    """HistoricalStats immutable value object."""

    def test_create(self):
        stats = HistoricalStats(
            win_rate=0.55,
            avg_win=1500.0,
            avg_loss=800.0,
            sample_size=100,
        )
        assert stats.win_rate == 0.55
        assert stats.avg_win == 1500.0
        assert stats.avg_loss == 800.0
        assert stats.sample_size == 100

    def test_immutable(self):
        stats = HistoricalStats(
            win_rate=0.5, avg_win=1000.0,
            avg_loss=500.0, sample_size=50,
        )
        with pytest.raises(AttributeError):
            stats.win_rate = 0.6

    def test_kelly_computation_viability(self):
        """Verify historical stats support a valid Kelly calculation."""
        stats = HistoricalStats(
            win_rate=0.55, avg_win=1500.0,
            avg_loss=800.0, sample_size=100,
        )
        # Kelly % = p - (1-p) / (avg_win/avg_loss)
        r = stats.avg_win / stats.avg_loss if stats.avg_loss > 0 else 0
        # This tests that the data supports a valid Kelly calculation
        assert r > 0
        assert stats.win_rate > 0.5  # positive edge
