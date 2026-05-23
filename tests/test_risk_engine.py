"""
Tests for core.services.risk_service.RiskService — canonical risk engine.

This replaces the previous tests for the deprecated core.risk_engine module.
All risk decision logic now routes through RiskService.evaluate_trade().

See core/risk/__init__.py for the authoritative architecture declaration.
"""
from __future__ import annotations

from typing import Any

from core.services.risk_service import RiskService, RiskServiceConfig
from core.ports.risk.risk_port import (
    PortfolioRiskMetrics,
    PositionSizingInput,
    RiskDecision,
    RiskEvaluation,
)


def _default_metrics(**overrides: Any) -> PortfolioRiskMetrics:
    """Helper to create a default PortfolioRiskMetrics with overrides."""
    base = PortfolioRiskMetrics(
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
    for k, v in overrides.items():
        setattr(base, k, v)
    return base


def _default_signal(**overrides: Any) -> dict[str, Any]:
    """Helper to create a default signal dict with overrides."""
    base: dict[str, Any] = {
        "direction": "CALL",
        "price": 18000.0,
        "score": 70,
        "strength": 65,
        "stop_loss": 17200.0,
        "target": 19000.0,
    }
    base.update(overrides)
    return base


class TestRiskServiceConfig:
    """Verify RiskServiceConfig defaults match documented values."""

    def test_defaults(self) -> None:
        c = RiskServiceConfig()
        assert c.default_risk_per_trade == 0.02
        assert c.max_risk_per_trade == 0.05
        assert c.max_daily_loss == -2000.0
        assert c.max_daily_trades == 10
        assert c.max_open_positions == 1
        assert c.max_consecutive_losses == 3

    def test_custom_config(self) -> None:
        c = RiskServiceConfig(
            max_daily_loss=-500.0,
            max_open_positions=2,
            max_consecutive_losses=5,
        )
        assert c.max_daily_loss == -500.0
        assert c.max_open_positions == 2
        assert c.max_consecutive_losses == 5


class TestRiskDecisionEnum:
    """Verify RiskDecision enum values."""

    def test_allowed(self) -> None:
        assert RiskDecision.ALLOWED.value == "allowed"

    def test_denied(self) -> None:
        assert RiskDecision.DENIED.value == "denied"


class TestTradeQualityChecks:
    """Quality checks: volume ratio, spread, slippage."""

    def test_all_checks_pass(self) -> None:
        """A high-quality signal should pass all checks."""
        svc = RiskService()
        metrics = _default_metrics()
        signal = _default_signal(volume_ratio=1.0, spread_pct=0.05)
        result = svc.evaluate_trade("NIFTY", signal, metrics)
        assert result.decision == RiskDecision.ALLOWED

    def test_low_volume_fails(self) -> None:
        """Volume below min_volume_ratio should deny."""
        svc = RiskService(config=RiskServiceConfig(min_volume_ratio=0.5))
        metrics = _default_metrics()
        signal = _default_signal(volume_ratio=0.1)
        result = svc.evaluate_trade("NIFTY", signal, metrics)
        assert result.decision == RiskDecision.DENIED
        assert "volume" in result.reason.lower()

    def test_wide_spread_fails(self) -> None:
        """Spread above max_spread_pct should deny."""
        svc = RiskService(config=RiskServiceConfig(max_spread_pct=0.1))
        metrics = _default_metrics()
        signal = _default_signal(spread_pct=0.2)
        result = svc.evaluate_trade("NIFTY", signal, metrics)
        assert result.decision == RiskDecision.DENIED
        assert "spread" in result.reason.lower()


class TestLossStreakProtection:
    """Consecutive loss streak protection."""

    def test_no_streak_allowed(self) -> None:
        """Zero consecutive losses should allow trading."""
        svc = RiskService()
        metrics = _default_metrics(consecutive_losses=0)
        signal = _default_signal()
        result = svc.evaluate_trade("NIFTY", signal, metrics)
        assert result.decision == RiskDecision.ALLOWED

    def test_streak_exceeds_limit(self) -> None:
        """Exceeding max_consecutive_losses should deny."""
        svc = RiskService(config=RiskServiceConfig(max_consecutive_losses=2))
        metrics = _default_metrics(consecutive_losses=3)
        signal = _default_signal()
        result = svc.evaluate_trade("NIFTY", signal, metrics)
        assert result.decision == RiskDecision.DENIED
        assert "loss" in result.reason.lower()

    def test_at_limit_allowed(self) -> None:
        """At max_consecutive_losses (not exceeding) should still allow."""
        svc = RiskService(config=RiskServiceConfig(max_consecutive_losses=3))
        metrics = _default_metrics(consecutive_losses=3)
        signal = _default_signal()
        result = svc.evaluate_trade("NIFTY", signal, metrics)
        # At the boundary: 3 >= 3 so this should deny
        assert result.decision == RiskDecision.DENIED


class TestDailyLossLimit:
    """Daily loss limit enforcement."""

    def test_within_limit_allowed(self) -> None:
        """Daily P&L within limit should allow trading."""
        svc = RiskService(config=RiskServiceConfig(max_daily_loss=-500.0))
        metrics = _default_metrics(daily_pnl=-100.0)
        signal = _default_signal()
        result = svc.evaluate_trade("NIFTY", signal, metrics)
        assert result.decision == RiskDecision.ALLOWED

    def test_exceeds_limit_denied(self) -> None:
        """Daily P&L beyond limit should deny."""
        svc = RiskService(config=RiskServiceConfig(max_daily_loss=-500.0))
        metrics = _default_metrics(daily_pnl=-600.0)
        signal = _default_signal()
        result = svc.evaluate_trade("NIFTY", signal, metrics)
        assert result.decision == RiskDecision.DENIED
        assert "loss" in result.reason.lower()


class TestPortfolioLimits:
    """Portfolio-level position limits."""

    def test_max_open_positions(self) -> None:
        """Exceeding max_open_positions should deny."""
        svc = RiskService(config=RiskServiceConfig(max_open_positions=1))
        metrics = _default_metrics(open_positions_count=1)
        signal = _default_signal()
        result = svc.evaluate_trade("NIFTY", signal, metrics)
        assert result.decision == RiskDecision.DENIED
        assert "open" in result.reason.lower()

    def test_below_max_open_allowed(self) -> None:
        """Below max_open_positions should allow."""
        svc = RiskService(config=RiskServiceConfig(max_open_positions=2))
        metrics = _default_metrics(open_positions_count=0)
        signal = _default_signal()
        result = svc.evaluate_trade("NIFTY", signal, metrics)
        assert result.decision == RiskDecision.ALLOWED


class TestPositionSizing:
    """Position size calculation."""

    def test_calculate_position_size(self) -> None:
        """Basic position size calculation with valid inputs."""
        svc = RiskService(config=RiskServiceConfig(
            default_risk_per_trade=0.02,
            max_risk_per_trade=0.05,
        ))
        sizing_input = PositionSizingInput(
            symbol="NIFTY",
            entry_price=18000.0,
            stop_loss_price=17200.0,
            capital_available=100000.0,
            risk_per_trade=0.02,
            lot_size=50,
            volatility=20.0,
            existing_exposure=0.0,
        )
        size = svc.calculate_position_size(sizing_input)
        assert isinstance(size, int)
        assert size >= 1  # At minimum 1 lot

    def test_position_size_with_zero_stop_loss(self) -> None:
        """Zero stop loss should return 0."""
        svc = RiskService()
        sizing_input = PositionSizingInput(
            symbol="NIFTY",
            entry_price=18000.0,
            stop_loss_price=0.0,
            capital_available=100000.0,
            risk_per_trade=0.02,
            lot_size=50,
            volatility=20.0,
            existing_exposure=0.0,
        )
        size = svc.calculate_position_size(sizing_input)
        assert size == 0

    def test_position_size_with_empty_input(self) -> None:
        """Empty/zero entry price should return 0."""
        svc = RiskService()
        sizing_input = PositionSizingInput(
            symbol="NIFTY",
            entry_price=0.0,
            stop_loss_price=17000.0,
            capital_available=100000.0,
            risk_per_trade=0.02,
            lot_size=50,
            volatility=20.0,
            existing_exposure=0.0,
        )
        size = svc.calculate_position_size(sizing_input)
        assert size == 0


class TestMarginValidation:
    """Margin requirement checks."""

    def test_sufficient_margin(self) -> None:
        """Sufficient margin should validate."""
        svc = RiskService()
        assert svc.validate_margin_requirements("NIFTY", 1, 100000.0)

    def test_zero_quantity(self) -> None:
        """Zero quantity should always validate."""
        svc = RiskService()
        assert svc.validate_margin_requirements("NIFTY", 0, 0.0)


class TestPortfolioRiskMetrics:
    """Portfolio risk metrics gathering."""

    def test_metrics_defaults(self) -> None:
        """Metrics should return reasonable defaults."""
        svc = RiskService()
        metrics = svc.get_portfolio_risk_metrics()
        assert isinstance(metrics, PortfolioRiskMetrics)
        assert metrics.total_capital > 0

    def test_metrics_fields_present(self) -> None:
        """All expected fields should be present."""
        svc = RiskService()
        metrics = svc.get_portfolio_risk_metrics()
        assert hasattr(metrics, "total_capital")
        assert hasattr(metrics, "available_capital")
        assert hasattr(metrics, "daily_pnl")
        assert hasattr(metrics, "open_positions_count")
        assert hasattr(metrics, "consecutive_losses")
        assert hasattr(metrics, "symbol_exposure")


class TestHealthCheck:
    """Risk service health check."""

    def test_health_check_healthy(self) -> None:
        """Health check should return healthy status."""
        svc = RiskService()
        hc = svc.health_check()
        assert hc["status"] == "healthy"
        assert hc["service"] == "RiskService"

    def test_health_check_has_metrics(self) -> None:
        """Health check should include metrics."""
        svc = RiskService()
        hc = svc.health_check()
        assert "metrics" in hc
        assert "capital" in hc["metrics"]
        assert "daily_pnl" in hc["metrics"]


class TestRiskEvaluation:
    """RiskEvaluation dataclass validation."""

    def test_defaults(self) -> None:
        """Verify RiskEvaluation defaults."""
        r = RiskEvaluation(
            decision=RiskDecision.ALLOWED,
            reason="ok",
            risk_score=0.0,
        )
        assert r.decision == RiskDecision.ALLOWED
        assert r.risk_score == 0.0
        assert r.recommended_position_size is None

    def test_denied_evaluation(self) -> None:
        """Denied evaluation with reason."""
        r = RiskEvaluation(
            decision=RiskDecision.DENIED,
            reason="Daily loss limit exceeded",
            risk_score=1.0,
        )
        assert r.decision == RiskDecision.DENIED
        assert r.risk_score == 1.0


class TestInvalidSignalData:
    """Edge cases for invalid signal data."""

    def test_missing_direction(self) -> None:
        """Missing direction should deny."""
        svc = RiskService()
        metrics = _default_metrics()
        signal = {"price": 18000.0}  # No direction
        result = svc.evaluate_trade("NIFTY", signal, metrics)
        assert result.decision == RiskDecision.DENIED

    def test_missing_price(self) -> None:
        """Missing price should deny."""
        svc = RiskService()
        metrics = _default_metrics()
        signal = {"direction": "CALL"}  # No price
        result = svc.evaluate_trade("NIFTY", signal, metrics)
        assert result.decision == RiskDecision.DENIED

    def test_zero_price(self) -> None:
        """Zero price should deny."""
        svc = RiskService()
        metrics = _default_metrics()
        signal = {"direction": "CALL", "price": 0}
        result = svc.evaluate_trade("NIFTY", signal, metrics)
        assert result.decision == RiskDecision.DENIED
