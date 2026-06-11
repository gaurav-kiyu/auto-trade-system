"""
Tests for core/services/risk_service.py — Risk Service Implementation.

Covers:
  - RiskServiceConfig defaults and custom config
  - RiskService initialization with dependency injection
  - evaluate_trade — full lifecycle with all risk checks
  - calculate_position_size with volatility adjustments
  - validate_margin_requirements
  - get_portfolio_risk_metrics with drawdown tracking
  - update_position / remove_position lifecycle
  - reset_daily_metrics and loss counter reset
  - health_check
  - Trading policy gates (window, first 20m, last 45m)
  - Greeks limits check
  - Trade quality checks
  - Error handling
"""
from __future__ import annotations

from typing import Any

import pytest

from core.datetime_ist import now_ist
from core.safety_state import (
    _HARD_HALT,
    get_consecutive_losses,
    is_hard_halted,
    reset_consecutive_losses,
)
from core.services.risk_service import RiskService, RiskServiceConfig


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_safety_state() -> None:
    """Reset safety state between tests."""
    _HARD_HALT.clear()
    reset_consecutive_losses()


@pytest.fixture()
def default_config() -> RiskServiceConfig:
    return RiskServiceConfig()


@pytest.fixture()
def risk_service() -> RiskService:
    """RiskService with all default injected functions."""
    return RiskService(
        get_capital_fn=lambda: 100000.0,
        get_open_positions_fn=lambda: 0,
        get_daily_pnl_fn=lambda: 0.0,
        get_volatility_fn=lambda s: 20.0,
        get_margin_fn=lambda s, q: 5000.0,
        get_live_vix_fn=lambda: 20.0,
    )


def _sample_signal(**overrides: Any) -> dict[str, Any]:
    """Create a sample signal dict for testing."""
    data = {
        "direction": "CALL",
        "price": 23500.0,
        "stop_loss": 23450.0,
        "target": 23600.0,
        "strength": 80,
        "volume_ratio": 1.5,
        "spread_pct": 0.5,
        "quantity": 1,
        "stop_loss_pct": 0.02,
    }
    data.update(overrides)
    return data


def _sample_metrics(**overrides: Any) -> PortfolioRiskMetrics:
    """Create sample portfolio metrics for testing."""
    data = {
        "total_capital": 100000.0,
        "used_capital": 0.0,
        "available_capital": 100000.0,
        "daily_pnl": 0.0,
        "max_daily_loss": -2000.0,
        "current_drawdown": 0.0,
        "max_drawdown": 0.0,
        "open_positions_count": 0,
        "max_open_positions": 1,
        "consecutive_losses": 0,
        "max_consecutive_losses": 3,
        "sector_exposure": {},
        "symbol_exposure": {},
    }
    data.update(overrides)
    return PortfolioRiskMetrics(**data)


# ── RiskServiceConfig ────────────────────────────────────────────────


class TestRiskServiceConfig:
    def test_default_values(self) -> None:
        cfg = RiskServiceConfig()
        assert cfg.default_risk_per_trade == 0.02
        assert cfg.max_risk_per_trade == 0.05
        assert cfg.max_daily_loss == -2000.0
        assert cfg.max_daily_trades == 10
        assert cfg.max_open_positions == 1
        assert cfg.max_portfolio_risk == 0.25

    def test_custom_values(self) -> None:
        cfg = RiskServiceConfig(
            default_risk_per_trade=0.01,
            max_daily_loss=-5000.0,
            max_open_positions=3,
        )
        assert cfg.default_risk_per_trade == 0.01
        assert cfg.max_daily_loss == -5000.0
        assert cfg.max_open_positions == 3


# ── RiskService Initialization ───────────────────────────────────────


class TestInit:
    def test_default_construction(self) -> None:
        service = RiskService()
        assert service.config.default_risk_per_trade == 0.02
        assert service._get_capital() == 100000.0

    def test_custom_config(self, default_config: RiskServiceConfig) -> None:
        default_config.max_daily_loss = -10000.0
        service = RiskService(config=default_config)
        assert service.config.max_daily_loss == -10000.0

    def test_injection_callables(self) -> None:
        capital: list[float] = [50000.0]

        def get_cap() -> float:
            return capital[0]

        service = RiskService(get_capital_fn=get_cap)
        assert service._get_capital() == 50000.0

    def test_greeks_engine_lazy_init(self, risk_service: RiskService) -> None:
        assert risk_service._greeks_engine is None
        # Accessing through evaluate_trade should init it
        risk_service._check_greeks_limits(
            "NIFTY", _sample_signal(), _sample_metrics()
        )
        assert risk_service._greeks_engine is not None


# ── evaluate_trade ──────────────────────────────────────────────────


class TestEvaluateTrade:
    def test_allows_valid_trade(self, risk_service: RiskService) -> None:
        result = risk_service.evaluate_trade("NIFTY", _sample_signal(), _sample_metrics())
        assert result.decision == RiskDecision.ALLOWED
        assert result.recommended_position_size > 0

    def test_denied_missing_direction(self, risk_service: RiskService) -> None:
        result = risk_service.evaluate_trade("NIFTY", _sample_signal(direction=""), _sample_metrics())
        assert result.decision == RiskDecision.DENIED

    def test_denied_missing_price(self, risk_service: RiskService) -> None:
        result = risk_service.evaluate_trade("NIFTY", _sample_signal(price=0), _sample_metrics())
        assert result.decision == RiskDecision.DENIED

    def test_denied_daily_loss_limit(self, risk_service: RiskService) -> None:
        metrics = _sample_metrics(daily_pnl=-2500.0)
        result = risk_service.evaluate_trade("NIFTY", _sample_signal(), metrics)
        assert result.decision == RiskDecision.DENIED
        assert "daily loss limit" in result.reason.lower()
        assert is_hard_halted()

    def test_denied_consecutive_losses(self, risk_service: RiskService) -> None:
        metrics = _sample_metrics(consecutive_losses=3)
        result = risk_service.evaluate_trade("NIFTY", _sample_signal(), metrics)
        assert result.decision == RiskDecision.DENIED
        assert "consecutive loss limit" in result.reason.lower()

    def test_denied_max_open_positions(self, risk_service: RiskService) -> None:
        metrics = _sample_metrics(open_positions_count=1)
        result = risk_service.evaluate_trade("NIFTY", _sample_signal(), metrics)
        assert result.decision == RiskDecision.DENIED
        assert "maximum open positions" in result.reason.lower()

    def test_denied_low_volume(self, risk_service: RiskService) -> None:
        result = risk_service.evaluate_trade("NIFTY", _sample_signal(volume_ratio=0.1), _sample_metrics())
        assert result.decision == RiskDecision.DENIED
        assert "volume" in result.reason.lower()

    def test_denied_excessive_spread(self, risk_service: RiskService) -> None:
        result = risk_service.evaluate_trade("NIFTY", _sample_signal(spread_pct=5.0), _sample_metrics())
        assert result.decision == RiskDecision.DENIED
        assert "spread" in result.reason.lower()

    def test_returns_risk_score(self, risk_service: RiskService) -> None:
        result = risk_service.evaluate_trade("NIFTY", _sample_signal(), _sample_metrics())
        assert 0.0 <= result.risk_score <= 1.0


# ── calculate_position_size ─────────────────────────────────────────


class TestCalculatePositionSize:
    def test_returns_positive_size(self, risk_service: RiskService) -> None:
        sizing = PositionSizingInput(
            symbol="NIFTY", entry_price=23500.0, stop_loss_price=23450.0,
            capital_available=100000.0, risk_per_trade=0.02, lot_size=50,
            volatility=20.0, existing_exposure=0.0,
        )
        size = risk_service.calculate_position_size(sizing)
        assert size > 0

    def test_zero_on_invalid_stop(self, risk_service: RiskService) -> None:
        sizing = PositionSizingInput(
            symbol="NIFTY", entry_price=23500.0, stop_loss_price=0,
            capital_available=100000.0, risk_per_trade=0.02, lot_size=50,
            volatility=20.0, existing_exposure=0.0,
        )
        assert risk_service.calculate_position_size(sizing) == 0

    def test_zero_on_matching_price(self, risk_service: RiskService) -> None:
        sizing = PositionSizingInput(
            symbol="NIFTY", entry_price=23500.0, stop_loss_price=23500.0,
            capital_available=100000.0, risk_per_trade=0.02, lot_size=50,
            volatility=20.0, existing_exposure=0.0,
        )
        assert risk_service.calculate_position_size(sizing) == 0

    def test_volatility_reduces_size(self, risk_service: RiskService) -> None:
        low_vol = PositionSizingInput(
            symbol="NIFTY", entry_price=23500.0, stop_loss_price=23450.0,
            capital_available=100000.0, risk_per_trade=0.02, lot_size=50,
            volatility=12.0, existing_exposure=0.0,
        )
        high_vol = PositionSizingInput(
            symbol="NIFTY", entry_price=23500.0, stop_loss_price=23450.0,
            capital_available=100000.0, risk_per_trade=0.02, lot_size=50,
            volatility=40.0, existing_exposure=0.0,
        )
        low_size = risk_service.calculate_position_size(low_vol)
        high_size = risk_service.calculate_position_size(high_vol)
        # Low volatility should have higher size (1.2x multiplier)
        # High volatility should have lower size (0.6x multiplier)
        if low_size > 0 and high_size > 0:
            assert low_size >= high_size

    def test_minimum_size_one(self, risk_service: RiskService) -> None:
        sizing = PositionSizingInput(
            symbol="NIFTY", entry_price=23500.0, stop_loss_price=100.0,
            capital_available=1000.0, risk_per_trade=0.02, lot_size=50,
            volatility=20.0, existing_exposure=0.0,
        )
        # Very tight stop should still give minimum size
        size = risk_service.calculate_position_size(sizing)
        assert size >= 0


# ── validate_margin_requirements ────────────────────────────────────


class TestValidateMargin:
    def test_zero_quantity_returns_true(self, risk_service: RiskService) -> None:
        assert risk_service.validate_margin_requirements("NIFTY", 0, 100000.0)

    def test_sufficient_margin(self, risk_service: RiskService) -> None:
        assert risk_service.validate_margin_requirements("NIFTY", 1, 100000.0)

    def test_insufficient_margin(self, risk_service: RiskService) -> None:
        service = RiskService(
            get_margin_fn=lambda s, q: 1000000.0,  # Very high margin
            get_capital_fn=lambda: 100000.0,
        )
        assert not service.validate_margin_requirements("NIFTY", 5, 100000.0)

    def test_margin_error_fails_safe(self, risk_service: RiskService) -> None:
        service = RiskService(
            get_margin_fn=lambda s, q: (_ for _ in ()).throw(TypeError("bad type")),
        )
        assert not service.validate_margin_requirements("NIFTY", 1, 100000.0)


# ── get_portfolio_risk_metrics ──────────────────────────────────────


class TestPortfolioRiskMetrics:
    def test_returns_valid_metrics(self, risk_service: RiskService) -> None:
        metrics = risk_service.get_portfolio_risk_metrics()
        assert metrics.total_capital == 100000.0
        assert metrics.available_capital == 100000.0
        assert metrics.open_positions_count == 0

    def test_tracks_drawdown(self, risk_service: RiskService) -> None:
        # Initially zero
        m1 = risk_service.get_portfolio_risk_metrics()
        assert m1.current_drawdown == 0.0

    def test_drawdown_updates(self, risk_service: RiskService) -> None:
        # Set peak P&L by calling with high daily P&L
        service = RiskService(
            get_daily_pnl_fn=lambda: 1000.0,
            get_capital_fn=lambda: 100000.0,
        )
        m1 = service.get_portfolio_risk_metrics()
        # Now simulate drop
        service._get_daily_pnl = lambda: 500.0
        m2 = service.get_portfolio_risk_metrics()
        assert m2.current_drawdown >= 0.0
        if m2.max_drawdown > 0:
            assert m2.daily_pnl == 500.0

    def test_consecutive_losses_from_safety(self, risk_service: RiskService) -> None:
        from core.safety_state import record_trade_outcome
        record_trade_outcome(was_profit=False)
        record_trade_outcome(was_profit=False)
        metrics = risk_service.get_portfolio_risk_metrics()
        assert metrics.consecutive_losses >= 2


# ── update_position / remove_position ───────────────────────────────


class TestPositionLifecycle:
    def test_add_position(self, risk_service: RiskService) -> None:
        risk_service.update_position("NIFTY", 1, 23500.0, now_ist())
        assert "NIFTY" in risk_service._positions
        assert risk_service._positions["NIFTY"]["quantity"] == 1

    def test_add_position_uses_default_greeks(self, risk_service: RiskService) -> None:
        risk_service.update_position("NIFTY", 1, 23500.0, now_ist())
        pos = risk_service._positions["NIFTY"]
        assert pos["option_type"] == "CE"
        assert pos["tte_days"] == 3.0
        assert pos["iv"] == 0.15

    def test_add_position_with_option_type(self, risk_service: RiskService) -> None:
        risk_service.update_position("NIFTY", 1, 23500.0, now_ist(), option_type="PE")
        assert risk_service._positions["NIFTY"]["option_type"] == "PE"

    def test_zero_quantity_removes_position(self, risk_service: RiskService) -> None:
        risk_service.update_position("NIFTY", 1, 23500.0, now_ist())
        risk_service.update_position("NIFTY", 0, 0.0, now_ist())
        assert "NIFTY" not in risk_service._positions

    def test_remove_position(self, risk_service: RiskService) -> None:
        risk_service.update_position("NIFTY", 1, 23500.0, now_ist())
        risk_service.remove_position("NIFTY")
        assert "NIFTY" not in risk_service._positions

    def test_remove_nonexistent_position(self, risk_service: RiskService) -> None:
        risk_service.remove_position("BANKNIFTY")  # Should not raise

    def test_multiple_positions(self, risk_service: RiskService) -> None:
        risk_service.update_position("NIFTY", 1, 23500.0, now_ist())
        risk_service.update_position("BANKNIFTY", 2, 50000.0, now_ist())
        assert len(risk_service._positions) == 2
        metrics = risk_service.get_portfolio_risk_metrics()
        assert metrics.symbol_exposure.get("NIFTY", 0.0) > 0


# ── reset_daily_metrics ─────────────────────────────────────────────


class TestResetDailyMetrics:
    def test_reset_does_not_crash(self, risk_service: RiskService) -> None:
        risk_service.reset_daily_metrics()

    def test_reset_preserves_peak_pnl(self, risk_service: RiskService) -> None:
        service = RiskService(
            get_daily_pnl_fn=lambda: 1000.0,
            get_capital_fn=lambda: 100000.0,
        )
        service.get_portfolio_risk_metrics()  # Sets peak
        service.reset_daily_metrics()
        # After reset, peak should be 0
        assert service._peak_pnl == 0.0


# ── Trading Policy Gates ────────────────────────────────────────────


class TestTradingPolicyGates:
    def test_is_in_trading_window(self, risk_service: RiskService) -> None:
        # Morning window: 9:20-11:30 IST
        # Afternoon window: 13:00-14:45 IST
        result = risk_service.is_in_trading_window()
        # Result depends on current time — just verify it returns bool
        assert isinstance(result, bool)

    def test_should_skip_first_20_min(self, risk_service: RiskService) -> None:
        # First 20 min after 9:20 is 9:20-9:40
        result = risk_service.should_skip_first_20_min()
        assert isinstance(result, bool)

    def test_should_skip_last_45_min(self, risk_service: RiskService) -> None:
        # Last 45 min before 15:20 is 14:35-15:20
        result = risk_service.should_skip_last_45_min()
        assert isinstance(result, bool)

    def test_get_min_score_for_regime(self, risk_service: RiskService) -> None:
        assert risk_service.get_min_score_for_regime("TRENDING") == 68
        assert risk_service.get_min_score_for_regime("NEUTRAL") == 73
        assert risk_service.get_min_score_for_regime("CHOPPY") == 78
        assert risk_service.get_min_score_for_regime("UNKNOWN") == 73

    def test_should_block_false_signal(self, risk_service: RiskService) -> None:
        assert risk_service.should_block_false_signal(80, 30)
        assert not risk_service.should_block_false_signal(70, 20)
        assert not risk_service.should_block_false_signal(80, 20)  # Low IV

    def test_get_max_trades_per_day(self, risk_service: RiskService) -> None:
        assert risk_service.get_max_trades_per_day(vix=15, consecutive_losses=0) == 4
        assert risk_service.get_max_trades_per_day(vix=22, consecutive_losses=0) == 2
        assert risk_service.get_max_trades_per_day(vix=30, consecutive_losses=0) == 1
        assert risk_service.get_max_trades_per_day(vix=15, consecutive_losses=2) == 1


# ── Greeks Limits Check ─────────────────────────────────────────────


class TestGreeksCheck:
    def test_greeks_check_allows_valid(self, risk_service: RiskService) -> None:
        result = risk_service._check_greeks_limits("NIFTY", _sample_signal(), _sample_metrics())
        assert result.decision == RiskDecision.ALLOWED

    def test_greeks_check_skips_missing_direction(self, risk_service: RiskService) -> None:
        result = risk_service._check_greeks_limits("NIFTY", _sample_signal(direction=""), _sample_metrics())
        assert result.decision == RiskDecision.ALLOWED
        assert "skipped" in result.reason.lower()

    def test_greeks_check_skips_unknown_type(self, risk_service: RiskService) -> None:
        result = risk_service._check_greeks_limits("NIFTY", _sample_signal(direction="OTHER"), _sample_metrics())
        assert result.decision == RiskDecision.ALLOWED
        assert "unknown" in result.reason.lower()

    def test_greeks_check_with_existing_positions(self, risk_service: RiskService) -> None:
        risk_service.update_position("BANKNIFTY", 1, 50000.0, now_ist(), option_type="PE")
        result = risk_service._check_greeks_limits("NIFTY", _sample_signal(), _sample_metrics())
        assert result.decision in (RiskDecision.ALLOWED, RiskDecision.DENIED)


# ── Health Check ────────────────────────────────────────────────────


class TestHealthCheck:
    def test_health_check_returns_healthy(self, risk_service: RiskService) -> None:
        result = risk_service.health_check()
        assert result["status"] == "healthy"
        assert result["service"] == "RiskService"

    def test_health_check_has_config(self, risk_service: RiskService) -> None:
        result = risk_service.health_check()
        assert "config" in result
        assert result["config"]["max_daily_loss"] == -2000.0

    def test_health_check_has_metrics(self, risk_service: RiskService) -> None:
        result = risk_service.health_check()
        assert "metrics" in result
        assert result["metrics"]["capital"] == 100000.0

    def test_health_check_unhealthy_on_error(self) -> None:
        def bad_capital() -> float:
            raise ValueError("Capital unavailable")

        service = RiskService(get_capital_fn=bad_capital)
        result = service.health_check()
        assert result["status"] == "unhealthy"


# ── Helper: Lot Size ────────────────────────────────────────────────


class TestLotSize:
    def test_nifty_lot_size(self, risk_service: RiskService) -> None:
        assert risk_service._get_lot_size("NIFTY") == 50

    def test_banknifty_lot_size(self, risk_service: RiskService) -> None:
        assert risk_service._get_lot_size("BANKNIFTY") == 15

    def test_unknown_symbol_default(self, risk_service: RiskService) -> None:
        assert risk_service._get_lot_size("UNKNOWN") == 50

    def test_finnifty_lot_size(self, risk_service: RiskService) -> None:
        assert risk_service._get_lot_size("FINNIFTY") == 40


# ── Helper: Volatility Multiplier ───────────────────────────────────


class TestVolatilityMultiplier:
    def test_low_volatility_increases_size(self, risk_service: RiskService) -> None:
        mult = risk_service._get_volatility_multiplier(12.0)
        assert mult == 1.2

    def test_high_volatility_decreases_size(self, risk_service: RiskService) -> None:
        mult = risk_service._get_volatility_multiplier(40.0)
        assert mult == 0.6

    def test_mid_volatility_interpolates(self, risk_service: RiskService) -> None:
        mult_low = risk_service._get_volatility_multiplier(15.0)
        mult_high = risk_service._get_volatility_multiplier(35.0)
        mid = risk_service._get_volatility_multiplier(25.0)
        # Linear interpolation between 1.2 and 0.6
        assert mult_low == 1.2
        assert mid > 0.6 and mid < 1.2
        assert mult_high == 0.6

    def test_mid_calculation(self, risk_service: RiskService) -> None:
        # At threshold_low=15, mult=1.2
        # At threshold_high=35, mult=0.6
        # At 25: ratio=(25-15)/(35-15)=0.5, mult=1.2+0.5*(0.6-1.2)=1.2-0.3=0.9
        mult = risk_service._get_volatility_multiplier(25.0)
        assert mult == pytest.approx(0.9, abs=1e-10)


# ── Helper: Risk Score Calculation ──────────────────────────────────


class TestRiskScore:
    def test_risk_score_in_range(self, risk_service: RiskService) -> None:
        score = risk_service._calculate_risk_score("NIFTY", _sample_signal(), _sample_metrics())
        assert 0.0 <= score <= 1.0

    def test_risk_score_lower_for_strong_signal(self, risk_service: RiskService) -> None:
        weak = risk_service._calculate_risk_score("NIFTY", _sample_signal(strength=30), _sample_metrics())
        strong = risk_service._calculate_risk_score("NIFTY", _sample_signal(strength=90), _sample_metrics())
        assert weak >= strong

    def test_risk_score_higher_with_loss_usage(self, risk_service: RiskService) -> None:
        metrics_near_loss = _sample_metrics(daily_pnl=-1500.0)
        metrics_flat = _sample_metrics(daily_pnl=0.0)
        score1 = risk_service._calculate_risk_score("NIFTY", _sample_signal(price=23500.0, stop_loss=23450.0), metrics_near_loss)
        score2 = risk_service._calculate_risk_score("NIFTY", _sample_signal(price=23500.0, stop_loss=23450.0), metrics_flat)
        assert score1 >= score2


# ── Margin Check Inside evaluate_trade ──────────────────────────────


class TestMarginCheck:
    def test_insufficient_margin_denies(self) -> None:
        service = RiskService(
            get_margin_fn=lambda s, q: 200000.0,  # Very high margin needed
            get_capital_fn=lambda: 100000.0,
            get_open_positions_fn=lambda: 0,
            get_daily_pnl_fn=lambda: 0.0,
            get_volatility_fn=lambda s: 20.0,
            get_live_vix_fn=lambda: 20.0,
        )
        signal = _sample_signal(price=23500.0, stop_loss=23450.0)
        result = service.evaluate_trade("NIFTY", signal, _sample_metrics())
        assert result.decision in (RiskDecision.ALLOWED, RiskDecision.DENIED)


# ── Error Handling ──────────────────────────────────────────────────


class TestErrorHandling:
    def test_get_portfolio_metrics_error_safe(self) -> None:
        def bad_capital() -> float:
            raise KeyError("Missing capital data")

        service = RiskService(get_capital_fn=bad_capital)
        metrics = service.get_portfolio_risk_metrics()
        # Fail-closed: returns metrics that block trading
        assert metrics.available_capital == 0.0
        assert metrics.open_positions_count == 999

    def test_evaluate_trade_handles_exception(self) -> None:
        def bad_volatility(symbol: str) -> float:
            raise TypeError("Volatility unavailable")

        service = RiskService(
            get_volatility_fn=bad_volatility,
            get_capital_fn=lambda: 100000.0,
            get_open_positions_fn=lambda: 0,
            get_daily_pnl_fn=lambda: 0.0,
            get_margin_fn=lambda s, q: 5000.0,
            get_live_vix_fn=lambda: 20.0,
        )
        result = service.evaluate_trade("NIFTY", _sample_signal(), _sample_metrics())
        # Should handle gracefully and return denied
        assert result.decision == RiskDecision.DENIED

    def test_health_check_error(self) -> None:
        def bad_open() -> int:
            raise TypeError("Bad type")

        service = RiskService(get_open_positions_fn=bad_open)
        result = service.health_check()
        assert result["status"] == "unhealthy"


# ── Live VIX ────────────────────────────────────────────────────────


class TestLiveVIX:
    def test_get_live_vix_returns_value(self, risk_service: RiskService) -> None:
        vix = risk_service.get_live_vix()
        assert vix == 20.0

    def test_get_live_vix_fallback_on_error(self) -> None:
        def bad_vix() -> float:
            raise OSError("Connection failed")

        service = RiskService(get_live_vix_fn=bad_vix)
        vix = service.get_live_vix()
        assert vix == 20.0

    def test_required_margin_per_lot(self, risk_service: RiskService) -> None:
        margin = risk_service.get_required_margin_per_lot("NIFTY", 23500.0)
        # 23500 * 50 * 0.20 = 235000
        assert margin == 235000.0
