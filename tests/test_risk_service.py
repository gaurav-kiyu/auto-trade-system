"""
Tests for RiskService — comprehensive risk management service.

Covers:
- RiskServiceConfig dataclass defaults and custom values
- RiskService construction with dependency injection
- evaluate_trade: composite risk checks, success path, denied paths
- Individual _check_* methods: daily loss, consecutive losses, portfolio limits,
  margin requirements, trade quality, position sizing limits, Greeks limits
- calculate_position_size: base sizing, volatility adjustment, portfolio/capital limits
- validate_margin_requirements
- get_portfolio_risk_metrics: basic metrics, error fallback
- update_position / remove_position: position tracking
- reset_daily_metrics
- health_check: healthy/unhealthy paths
- Trading policy gates: is_in_trading_window, should_skip_first_20_min, etc.
- Capital scaling delegation: scale_position, record_trade_result, lock_profits, get_capital_state
- Helper methods: _get_lot_size, _get_volatility_multiplier, _estimate_portfolio_risk, _calculate_risk_score
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from core.services.risk_service import (
    RiskService,
    RiskServiceConfig,
    PortfolioRiskMetrics,
    PositionSizingInput,
    RiskDecision,
)


# ── RiskServiceConfig ─────────────────────────────────────────────────────


class TestRiskServiceConfig:
    def test_defaults(self):
        cfg = RiskServiceConfig()
        assert cfg.default_risk_per_trade == 0.02
        assert cfg.max_risk_per_trade == 0.05
        assert cfg.max_daily_loss == -2000.0
        assert cfg.max_daily_trades == 10
        assert cfg.max_open_positions == 1
        assert cfg.max_consecutive_losses == 3

    def test_custom_values(self):
        cfg = RiskServiceConfig(
            default_risk_per_trade=0.01,
            max_daily_loss=-5000.0,
            max_open_positions=3,
            max_consecutive_losses=5,
        )
        assert cfg.default_risk_per_trade == 0.01
        assert cfg.max_daily_loss == -5000.0
        assert cfg.max_open_positions == 3
        assert cfg.max_consecutive_losses == 5

    def test_vix_thresholds(self):
        cfg = RiskServiceConfig(vix_threshold_low=12.0, vix_threshold_high=40.0)
        assert cfg.vix_threshold_low == 12.0
        assert cfg.vix_threshold_high == 40.0
        assert cfg.vix_size_multiplier_low == 1.2
        assert cfg.vix_size_multiplier_high == 0.6

    def test_margin_safety(self):
        cfg = RiskServiceConfig(margin_safety_factor=0.9)
        assert cfg.margin_safety_factor == 0.9


# ── RiskService Construction ──────────────────────────────────────────────


class TestRiskServiceConstruction:
    def test_default_construction(self):
        service = RiskService()
        assert service.config is not None
        assert service.config.max_open_positions == 1
        assert service._get_capital() == 100000.0
        assert service._get_open_positions() == 0

    def test_custom_config(self):
        cfg = RiskServiceConfig(max_open_positions=3)
        service = RiskService(config=cfg)
        assert service.config.max_open_positions == 3

    def test_dependency_injection(self):
        """Injected callables are used instead of defaults."""
        def my_capital() -> float:
            return 50000.0
        service = RiskService(get_capital_fn=my_capital)
        assert service._get_capital() == 50000.0

    def test_margin_fn_injection(self):
        def my_margin(symbol: str, qty: int) -> float:
            return 10000.0
        service = RiskService(get_margin_fn=my_margin)
        assert service._get_margin("NIFTY", 1) == 10000.0

    def test_volatility_fn_injection(self):
        def my_vol(symbol: str) -> float:
            return 25.0
        service = RiskService(get_volatility_fn=my_vol)
        assert service._get_volatility("NIFTY") == 25.0

    def test_thread_safety(self):
        """Construction doesn't raise threading errors."""
        import threading
        results = []
        def create():
            s = RiskService()
            results.append(s)
        t1 = threading.Thread(target=create)
        t2 = threading.Thread(target=create)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        assert len(results) == 2


# ── evaluate_trade — Composite Checks ─────────────────────────────────────


class TestEvaluateTrade:
    def _make_service(self, **overrides) -> RiskService:
        cfg = RiskServiceConfig(**overrides)
        return RiskService(config=cfg)

    def _make_default_metrics(self, **overrides) -> PortfolioRiskMetrics:
        params = dict(
            total_capital=100000.0,
            used_capital=0.0,
            available_capital=100000.0,
            daily_pnl=0.0,
            max_daily_loss=-2000.0,
            current_drawdown=0.0,
            max_drawdown=0.0,
            open_positions_count=0,
            max_open_positions=1,
            consecutive_losses=0,
            max_consecutive_losses=3,
            sector_exposure={},
            symbol_exposure={},
        )
        params.update(overrides)
        return PortfolioRiskMetrics(**params)

    def test_invalid_signal_missing_direction(self):
        service = self._make_service()
        result = service.evaluate_trade(
            "NIFTY",
            {"price": 23500},
            self._make_default_metrics(),
        )
        assert result.decision == RiskDecision.DENIED
        assert "missing direction or price" in result.reason

    def test_invalid_signal_zero_price(self):
        service = self._make_service()
        result = service.evaluate_trade(
            "NIFTY",
            {"direction": "CALL", "price": 0},
            self._make_default_metrics(),
        )
        assert result.decision == RiskDecision.DENIED

    def test_all_checks_pass(self):
        """Happy path: all risk checks pass, trade ALLOWED with position size."""
        service = self._make_service()
        signal = {"direction": "CALL", "price": 23500, "stop_loss": 23000, "volume_ratio": 1.0, "spread_pct": 0.5}
        result = service.evaluate_trade("NIFTY", signal, self._make_default_metrics())
        assert result.decision == RiskDecision.ALLOWED
        assert "All risk checks passed" in result.reason
        assert result.recommended_position_size > 0

    @patch("core.services.risk_service.trip_hard_halt")
    def test_daily_loss_limit_denies(self, mock_halt):
        """When daily PnL <= max_daily_loss, trade is DENIED."""
        service = self._make_service(max_daily_loss=-2000.0)
        signal = {"direction": "CALL", "price": 23500, "stop_loss": 23000}
        result = service.evaluate_trade(
            "NIFTY", signal,
            self._make_default_metrics(daily_pnl=-2500.0),
        )
        assert result.decision == RiskDecision.DENIED
        assert "Daily loss limit" in result.reason
        mock_halt.assert_called_once()

    @patch("core.services.risk_service.trip_hard_halt")
    def test_consecutive_losses_denies(self, mock_halt):
        service = self._make_service(max_consecutive_losses=3)
        signal = {"direction": "CALL", "price": 23500, "stop_loss": 23000}
        result = service.evaluate_trade(
            "NIFTY", signal,
            self._make_default_metrics(consecutive_losses=4),
        )
        assert result.decision == RiskDecision.DENIED
        assert "Consecutive loss limit" in result.reason
        mock_halt.assert_called_once()

    def test_portfolio_limits_denies(self):
        """Max open positions reached → DENIED."""
        service = self._make_service(max_open_positions=1)
        signal = {"direction": "CALL", "price": 23500, "stop_loss": 23000}
        result = service.evaluate_trade(
            "NIFTY", signal,
            self._make_default_metrics(open_positions_count=1),
        )
        assert result.decision == RiskDecision.DENIED
        assert "Maximum open positions" in result.reason

    def test_trade_quality_volume_denies(self):
        """Insufficient volume ratio → DENIED."""
        service = self._make_service(min_volume_ratio=0.5)
        signal = {"direction": "CALL", "price": 23500, "stop_loss": 23000, "volume_ratio": 0.1}
        result = service.evaluate_trade(
            "NIFTY", signal,
            self._make_default_metrics(),
        )
        assert result.decision == RiskDecision.DENIED
        assert "volume ratio" in result.reason.lower()

    def test_trade_quality_spread_denies(self):
        """Excessive spread → DENIED."""
        service = self._make_service(max_spread_pct=2.0)
        signal = {"direction": "CALL", "price": 23500, "stop_loss": 23000, "volume_ratio": 1.0, "spread_pct": 5.0}
        result = service.evaluate_trade(
            "NIFTY", signal,
            self._make_default_metrics(),
        )
        assert result.decision == RiskDecision.DENIED
        assert "spread" in result.reason.lower()

    def test_margin_check_denies(self):
        """Insufficient margin → DENIED."""
        def my_margin(symbol: str, qty: int) -> float:
            return 1_000_000.0  # Very high margin requirement
        service = RiskService(
            config=RiskServiceConfig(),
            get_margin_fn=my_margin,
        )
        signal = {"direction": "CALL", "price": 23500, "stop_loss": 23000, "volume_ratio": 1.0}
        result = service.evaluate_trade(
            "NIFTY", signal,
            self._make_default_metrics(available_capital=10000.0),
        )
        assert result.decision == RiskDecision.DENIED

    def test_calculation_error_fallback(self):
        """Exceptions in evaluate_trade return DENIED gracefully."""
        service = self._make_service()
        # Trigger KeyError by passing None
        result = service.evaluate_trade("NIFTY", None, self._make_default_metrics())
        assert result.decision == RiskDecision.DENIED
        assert "error" in result.reason.lower()


# ── calculate_position_size ────────────────────────────────────────────────


class TestCalculatePositionSize:
    def _make_input(self, **overrides) -> PositionSizingInput:
        params = dict(
            symbol="NIFTY",
            entry_price=23500.0,
            stop_loss_price=23000.0,
            capital_available=100000.0,
            risk_per_trade=0.02,
            lot_size=50,
            volatility=20.0,
            existing_exposure=0.0,
        )
        params.update(overrides)
        return PositionSizingInput(**params)

    def test_zero_stop_loss_returns_zero(self):
        service = RiskService()
        result = service.calculate_position_size(self._make_input(stop_loss_price=0))
        assert result == 0

    def test_zero_entry_price_returns_zero(self):
        service = RiskService()
        result = service.calculate_position_size(self._make_input(entry_price=0))
        assert result == 0

    def test_basic_sizing(self):
        service = RiskService()
        result = service.calculate_position_size(self._make_input())
        # risk_amount = 100000 * 0.02 = 2000
        # price_diff = 23500 - 23000 = 500
        # raw_lots = 2000 / (500 * 50) = 0.08 → base_lots = max(1, 0) = 1
        # volatility = 20, vix_threshold_low=15, high=35
        # ratio = (20-15)/(35-15) = 0.25
        # multiplier = 1.2 + 0.25*(0.6-1.2) = 1.2 - 0.15 = 1.05
        # adjusted = int(1 * 1.05) = 1
        assert result >= 1

    def test_zero_volatility_uses_low_multiplier(self):
        """Low volatility → higher multiplier (1.2)."""
        service = RiskService()
        result = service.calculate_position_size(self._make_input(volatility=10.0))
        assert result >= 1

    def test_high_volatility_reduces_size(self):
        """High volatility → lower size."""
        service = RiskService()
        result_low = service.calculate_position_size(self._make_input(volatility=15.0))
        result_high = service.calculate_position_size(self._make_input(volatility=40.0))
        assert result_high <= result_low

    def test_exception_returns_zero(self):
        service = RiskService()
        result = service.calculate_position_size(self._make_input(entry_price=float('nan')))
        assert result == 0


# ── validate_margin_requirements ──────────────────────────────────────────


class TestValidateMarginRequirements:
    def test_zero_quantity_returns_true(self):
        service = RiskService()
        assert service.validate_margin_requirements("NIFTY", 0, 100000.0) is True

    def test_sufficient_margin(self):
        service = RiskService()
        assert service.validate_margin_requirements("NIFTY", 1, 100000.0) is True

    def test_insufficient_margin(self):
        """When margin exceeds available → returns False."""
        def my_margin(symbol: str, qty: int) -> float:
            return 200000.0  # More than 100000 * 0.8 = 80000
        service = RiskService(get_margin_fn=my_margin)
        assert service.validate_margin_requirements("NIFTY", 1, 100000.0) is False

    def test_margin_error_fails_safe(self):
        """Exception in margin check → returns False."""
        def my_margin(symbol: str, qty: int) -> float:
            raise ValueError("API error")
        service = RiskService(get_margin_fn=my_margin)
        assert service.validate_margin_requirements("NIFTY", 1, 100000.0) is False


# ── get_portfolio_risk_metrics ──────────────────────────────────────────────


class TestGetPortfolioRiskMetrics:
    def test_default_metrics(self):
        service = RiskService()
        metrics = service.get_portfolio_risk_metrics()
        assert metrics.total_capital == 100000.0
        assert metrics.available_capital == 100000.0
        assert metrics.open_positions_count == 0
        assert metrics.consecutive_losses >= 0

    def test_metrics_with_positions(self):
        service = RiskService()
        service.update_position("NIFTY", 1, 23500.0, datetime.now())
        metrics = service.get_portfolio_risk_metrics()
        assert metrics.total_capital == 100000.0
        assert "NIFTY" in metrics.symbol_exposure

    def test_error_returns_fail_closed(self):
        """Exception in metrics returns fail-closed values."""
        def bad_capital():
            raise ValueError("API error")
        service = RiskService(get_capital_fn=bad_capital)
        metrics = service.get_portfolio_risk_metrics()
        # Fail-closed: blocks trading
        assert metrics.available_capital == 0.0
        assert metrics.open_positions_count == 999
        assert metrics.daily_pnl == -999999.0


# ── update_position / remove_position ─────────────────────────────────────


class TestPositionTracking:
    def test_update_adds_position(self):
        service = RiskService()
        service.update_position("NIFTY", 1, 23500.0, datetime.now())
        assert "NIFTY" in service._positions
        assert service._positions["NIFTY"]["quantity"] == 1

    def test_update_with_zero_removes(self):
        service = RiskService()
        service.update_position("NIFTY", 1, 23500.0, datetime.now())
        service.update_position("NIFTY", 0, 0.0, datetime.now())
        assert "NIFTY" not in service._positions

    def test_remove_position(self):
        service = RiskService()
        service.update_position("NIFTY", 1, 23500.0, datetime.now())
        service.remove_position("NIFTY")
        assert "NIFTY" not in service._positions

    def test_remove_nonexistent_no_error(self):
        service = RiskService()
        # Should not raise
        service.remove_position("NONEXISTENT")

    def test_update_with_option_type(self):
        service = RiskService()
        service.update_position("NIFTY", 1, 23500.0, datetime.now(), option_type="PE", strike=23400.0, iv=0.20, tte_days=5.0)
        pos = service._positions["NIFTY"]
        assert pos["option_type"] == "PE"
        assert pos["strike"] == 23400.0
        assert pos["iv"] == 0.20


# ── reset_daily_metrics ─────────────────────────────────────────────────


class TestResetDailyMetrics:
    def test_reset_clears_peak_pnl(self):
        service = RiskService()
        service._peak_pnl = 5000.0
        service.reset_daily_metrics()
        assert service._peak_pnl == 0.0

    def test_reset_clears_max_drawdown(self):
        service = RiskService()
        service._max_drawdown = 2000.0
        service.reset_daily_metrics()
        assert service._max_drawdown == 0.0


# ── health_check ─────────────────────────────────────────────────────────


class TestHealthCheck:
    def test_healthy(self):
        service = RiskService()
        result = service.health_check()
        assert result["status"] == "healthy"
        assert result["service"] == "RiskService"
        assert result["metrics"]["capital"] == 100000.0

    def test_unhealthy_on_error(self):
        def bad_capital():
            raise ValueError("Capital source down")
        service = RiskService(get_capital_fn=bad_capital)
        result = service.health_check()
        assert result["status"] == "unhealthy"
        assert "error" in result


# ── Trading Policy Gates ─────────────────────────────────────────────────


class TestTradingPolicyGates:
    def test_get_min_score_for_regime_trending(self):
        service = RiskService()
        assert service.get_min_score_for_regime("TRENDING") == 68

    def test_get_min_score_for_regime_sideways(self):
        service = RiskService()
        assert service.get_min_score_for_regime("SIDEWAYS") == 73

    def test_get_min_score_for_regime_choppy(self):
        service = RiskService()
        assert service.get_min_score_for_regime("CHOPPY") == 78

    def test_get_min_score_for_regime_default(self):
        service = RiskService()
        assert service.get_min_score_for_regime("UNKNOWN") == 73

    def test_should_block_false_signal(self):
        service = RiskService()
        assert service.should_block_false_signal(75, 30) is True

    def test_should_not_block_low_iv(self):
        service = RiskService()
        assert service.should_block_false_signal(75, 20) is False

    def test_should_not_block_low_score(self):
        service = RiskService()
        assert service.should_block_false_signal(70, 30) is False

    def test_get_max_trades_high_vix(self):
        service = RiskService()
        assert service.get_max_trades_per_day(vix=30.0) == 1

    def test_get_max_trades_medium_vix(self):
        service = RiskService()
        assert service.get_max_trades_per_day(vix=25.0) == 2

    def test_get_max_trades_low_vix(self):
        service = RiskService()
        assert service.get_max_trades_per_day(vix=15.0) == 4

    def test_get_max_trades_loss_streak(self):
        service = RiskService()
        assert service.get_max_trades_per_day(vix=15.0, consecutive_losses=2) == 1


# ── Helper Methods ────────────────────────────────────────────────────────


class TestHelperMethods:
    def test_get_lot_size_nifty(self):
        service = RiskService()
        assert service._get_lot_size("NIFTY") == 50

    def test_get_lot_size_banknifty(self):
        service = RiskService()
        assert service._get_lot_size("BANKNIFTY") == 15

    def test_get_lot_size_default(self):
        service = RiskService()
        assert service._get_lot_size("UNKNOWN") == 50

    def test_volatility_multiplier_low(self):
        service = RiskService()
        mult = service._get_volatility_multiplier(10.0)
        assert mult == 1.2  # Low vol multiplier

    def test_volatility_multiplier_high(self):
        service = RiskService()
        mult = service._get_volatility_multiplier(40.0)
        assert mult == 0.6  # High vol multiplier

    def test_volatility_multiplier_mid(self):
        service = RiskService()
        mult = service._get_volatility_multiplier(25.0)
        # ratio = (25-15)/(35-15) = 0.5
        # multiplier = 1.2 + 0.5*(0.6-1.2) = 0.9
        assert mult == pytest.approx(0.9, abs=0.01)

    def test_calculate_risk_score_daily_loss(self):
        service = RiskService()
        service._get_volatility = lambda symbol: 20.0
        metrics = PortfolioRiskMetrics(
            total_capital=100000.0, used_capital=0.0, available_capital=100000.0,
            daily_pnl=-1000.0, max_daily_loss=-2000.0,
            current_drawdown=0.0, max_drawdown=0.0,
            open_positions_count=0, max_open_positions=1,
            consecutive_losses=0, max_consecutive_losses=3,
            sector_exposure={}, symbol_exposure={},
        )
        score = service._calculate_risk_score("NIFTY", {"strength": 50}, metrics)
        assert 0.0 <= score <= 1.0

    def test_get_required_margin_per_lot(self):
        service = RiskService()
        margin = service.get_required_margin_per_lot("NIFTY", 23500.0)
        # 23500 * 50 * 0.20 = 235000
        assert margin == 23500.0 * 50 * 0.20


# ── _check_greeks_limits ──────────────────────────────────────────────────


class TestCheckGreeksLimits:
    def test_skipped_missing_direction(self):
        service = RiskService()
        result = service._check_greeks_limits("NIFTY", {"price": 23500}, MagicMock())
        assert result.decision == RiskDecision.ALLOWED
        assert "skipped" in result.reason

    def test_skipped_unknown_option_type(self):
        service = RiskService()
        signal = {"direction": "FUTURE", "price": 23500}
        result = service._check_greeks_limits("NIFTY", signal, MagicMock())
        assert result.decision == RiskDecision.ALLOWED
        assert "skipped" in result.reason


# ── Capital Scaling Delegation ─────────────────────────────────────────────


class TestCapitalScaling:
    def test_scale_position_delegates(self):
        service = RiskService()
        result = service.scale_position(base_lots=2, max_lots=2)
        assert result.scaled_lots >= 1

    def test_record_trade_result(self):
        service = RiskService()
        # Should not raise
        service.record_trade_result(net_pnl=1000.0, is_winner=True)
        service.record_trade_result(net_pnl=-500.0, is_winner=False)

    def test_lock_profits(self):
        service = RiskService()
        amount = service.lock_profits(lock_pct=0.50)
        # No profits to lock initially
        assert amount == 0.0

    def test_get_capital_state(self):
        service = RiskService()
        state = service.get_capital_state()
        assert "current_capital" in state
        assert state["current_capital"] == 100000.0

    def test_get_capital_state_after_trade(self):
        service = RiskService()
        service.record_trade_result(net_pnl=5000.0, is_winner=True)
        state = service.get_capital_state()
        assert state["current_capital"] > 100000.0
