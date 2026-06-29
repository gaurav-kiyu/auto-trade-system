"""Tests for core/risk/limits/manager.py - Risk Limits Manager.

Covers:
- LimitConfig dataclass with defaults
- check_daily_loss (allowed, breached)
- check_consecutive_losses (allowed, breached)
- check_portfolio_limits (position count, portfolio risk)
- Hard halt tripping on limit breaches
"""
from __future__ import annotations

from unittest.mock import patch

from core.ports.risk.risk_port import RiskDecision
from core.risk.limits.manager import LimitConfig, RiskLimitsManager

# =============================================================================
# LimitConfig Tests
# =============================================================================

class TestLimitConfig:
    def test_defaults(self):
        cfg = LimitConfig()
        assert cfg.max_daily_loss == -2000.0
        assert cfg.max_daily_trades == 10
        assert cfg.max_open_positions == 5
        assert cfg.max_portfolio_risk == 0.25
        assert cfg.max_consecutive_losses == 3

    def test_custom_values(self):
        cfg = LimitConfig(
            max_daily_loss=-5000.0,
            max_daily_trades=20,
            max_open_positions=10,
            max_portfolio_risk=0.50,
            max_consecutive_losses=5,
        )
        assert cfg.max_daily_loss == -5000.0
        assert cfg.max_daily_trades == 20
        assert cfg.max_open_positions == 10
        assert cfg.max_portfolio_risk == 0.50
        assert cfg.max_consecutive_losses == 5


# =============================================================================
# RiskLimitsManager Tests
# =============================================================================

class TestInit:
    def test_stores_config(self):
        cfg = LimitConfig(max_daily_loss=-1000.0)
        mgr = RiskLimitsManager(cfg)
        assert mgr.config is cfg

    def test_default_config(self):
        mgr = RiskLimitsManager(LimitConfig())
        assert mgr.config.max_daily_loss == -2000.0


class TestCheckDailyLoss:
    def test_allows_under_limit(self):
        mgr = RiskLimitsManager(LimitConfig(max_daily_loss=-2000.0))
        result = mgr.check_daily_loss(-1500.0)
        assert result.decision == RiskDecision.ALLOWED
        assert "passed" in result.reason.lower()

    def test_allows_profit(self):
        mgr = RiskLimitsManager(LimitConfig())
        result = mgr.check_daily_loss(5000.0)
        assert result.decision == RiskDecision.ALLOWED

    def test_allows_zero(self):
        mgr = RiskLimitsManager(LimitConfig())
        result = mgr.check_daily_loss(0.0)
        assert result.decision == RiskDecision.ALLOWED

    def test_denies_at_exact_limit(self):
        """Loss exactly at limit should be denied."""
        mgr = RiskLimitsManager(LimitConfig(max_daily_loss=-2000.0))
        with patch("core.risk.limits.manager.trip_hard_halt") as mock_halt:
            result = mgr.check_daily_loss(-2000.0)
            assert result.decision == RiskDecision.DENIED
            assert result.risk_score == 1.0
            mock_halt.assert_called_once()

    def test_denies_below_limit(self):
        """Loss greater than limit should be denied."""
        mgr = RiskLimitsManager(LimitConfig(max_daily_loss=-2000.0))
        with patch("core.risk.limits.manager.trip_hard_halt") as mock_halt:
            result = mgr.check_daily_loss(-2500.0)
            assert result.decision == RiskDecision.DENIED
            assert result.risk_score == 1.0
            mock_halt.assert_called_once()

    def test_halt_reason_contains_values(self):
        mgr = RiskLimitsManager(LimitConfig(max_daily_loss=-2000.0))
        with patch("core.risk.limits.manager.trip_hard_halt") as mock_halt:
            mgr.check_daily_loss(-3000.0)
            args, kwargs = mock_halt.call_args
            assert "Daily loss limit breached" in args[0]
            assert "-3000" in args[0]
            assert "check_daily_loss" in kwargs.get("source", "")


class TestCheckConsecutiveLosses:
    def test_allows_under_limit(self):
        mgr = RiskLimitsManager(LimitConfig(max_consecutive_losses=3))
        result = mgr.check_consecutive_losses(2)
        assert result.decision == RiskDecision.ALLOWED
        assert result.risk_score == 0.0

    def test_allows_zero(self):
        mgr = RiskLimitsManager(LimitConfig())
        result = mgr.check_consecutive_losses(0)
        assert result.decision == RiskDecision.ALLOWED

    def test_denies_at_limit(self):
        mgr = RiskLimitsManager(LimitConfig(max_consecutive_losses=3))
        with patch("core.risk.limits.manager.trip_hard_halt") as mock_halt:
            result = mgr.check_consecutive_losses(3)
            assert result.decision == RiskDecision.DENIED
            assert result.risk_score == 1.0
            mock_halt.assert_called_once()

    def test_denies_above_limit(self):
        mgr = RiskLimitsManager(LimitConfig(max_consecutive_losses=3))
        with patch("core.risk.limits.manager.trip_hard_halt") as mock_halt:
            result = mgr.check_consecutive_losses(5)
            assert result.decision == RiskDecision.DENIED
            mock_halt.assert_called_once()

    def test_halt_reason_contains_values(self):
        mgr = RiskLimitsManager(LimitConfig(max_consecutive_losses=3))
        with patch("core.risk.limits.manager.trip_hard_halt") as mock_halt:
            mgr.check_consecutive_losses(4)
            args, kwargs = mock_halt.call_args
            assert "Consecutive loss limit breached" in args[0]
            assert "4" in args[0] or "4.0" in args[0]
            assert "check_consecutive_losses" in kwargs.get("source", "")


class TestCheckPortfolioLimits:
    def test_allows_under_all_limits(self):
        mgr = RiskLimitsManager(LimitConfig(max_open_positions=5, max_portfolio_risk=0.25))
        result = mgr.check_portfolio_limits(open_positions_count=2, current_risk=0.10)
        assert result.decision == RiskDecision.ALLOWED
        assert result.risk_score == 0.1

    def test_denies_max_positions_reached(self):
        mgr = RiskLimitsManager(LimitConfig(max_open_positions=5))
        result = mgr.check_portfolio_limits(open_positions_count=5, current_risk=0.10)
        assert result.decision == RiskDecision.DENIED
        assert result.risk_score == 0.8

    def test_denies_exceeds_max_positions(self):
        mgr = RiskLimitsManager(LimitConfig(max_open_positions=5))
        result = mgr.check_portfolio_limits(open_positions_count=6, current_risk=0.10)
        assert result.decision == RiskDecision.DENIED

    def test_denies_portfolio_risk_exceeded(self):
        mgr = RiskLimitsManager(LimitConfig(max_portfolio_risk=0.25))
        result = mgr.check_portfolio_limits(open_positions_count=1, current_risk=0.50)
        assert result.decision == RiskDecision.DENIED
        assert result.risk_score == 0.9

    def test_allows_at_exact_risk_limit(self):
        """Exactly at risk limit should be denied (check is strict >)."""
        mgr = RiskLimitsManager(LimitConfig(max_portfolio_risk=0.25))
        result = mgr.check_portfolio_limits(open_positions_count=1, current_risk=0.25)
        assert result.decision == RiskDecision.ALLOWED  # Not strictly greater

    def test_denied_reason_contains_value(self):
        mgr = RiskLimitsManager(LimitConfig(max_open_positions=3))
        result = mgr.check_portfolio_limits(open_positions_count=3, current_risk=0.10)
        assert "3" in result.reason
        assert result.decision == RiskDecision.DENIED
