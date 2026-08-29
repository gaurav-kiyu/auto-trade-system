"""Tests for core/mandate_service.py - MandateService."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from core.mandate_service import MandateService, get_mandate_service, reset_mandate_service


@pytest.fixture
def service():
    """Create a MandateService with mock dependencies."""
    risk_mock = MagicMock()
    risk_mock.is_in_trading_window.return_value = True
    risk_mock.should_skip_first_20_min.return_value = False
    risk_mock.should_skip_last_45_min.return_value = False
    risk_mock.get_min_score_for_regime.return_value = 60
    risk_mock.should_block_false_signal.return_value = False
    risk_mock.get_live_vix.return_value = 15.0

    metrics_mock = MagicMock()
    metrics_mock.open_positions_count = 0
    metrics_mock.consecutive_losses = 0
    metrics_mock.daily_pnl = 100.0
    metrics_mock.max_daily_loss = -2000.0
    metrics_mock.max_consecutive_losses = 3
    metrics_mock.available_capital = 5000.0
    risk_mock.get_portfolio_risk_metrics.return_value = metrics_mock
    risk_mock.get_max_trades_per_day.return_value = 5
    risk_mock.config.max_open_positions = 5
    risk_mock.config.default_risk_per_trade = 0.03
    risk_mock._get_lot_size.return_value = 25
    risk_mock.calculate_position_size.return_value = 1

    warmup_mock = MagicMock()
    warmup_mock.score_threshold_adjustment.return_value = 0

    yield MandateService(
        cfg={"SL_PCT": 0.92, "MAX_DAILY_LOSS": -2000},
        risk_service=risk_mock,
        warmup_manager=warmup_mock,
    )


class TestMarketStatus:
    """Tests for MandateService.market_status()."""

    def test_weekend_closed(self, service):
        """Weekend should return CLOSED."""
        with patch("core.mandate_service.now_ist") as mock_now:
            mock_now.return_value.weekday.return_value = 5  # Saturday
            assert service.market_status() == "CLOSED"

    def test_holiday(self, service):
        """Holiday date should return HOLIDAY."""
        service._holidays = {"2026-06-15"}
        with patch("core.mandate_service.now_ist") as mock_now:
            mock_now.return_value.weekday.return_value = 0  # Monday
            mock_now.return_value.strftime.return_value = "2026-06-15"
            assert service.market_status() == "HOLIDAY"

    def test_market_open(self, service):
        """Within trading hours should return OPEN."""
        with patch("core.mandate_service.now_ist") as mock_now:
            mock_now.return_value.weekday.return_value = 0  # Monday
            mock_now.return_value.hour = 11
            mock_now.return_value.minute = 0
            assert service.market_status() == "OPEN"

    def test_market_closed(self, service):
        """Outside trading hours should return CLOSED."""
        with patch("core.mandate_service.now_ist") as mock_now:
            mock_now.return_value.weekday.return_value = 0  # Monday
            mock_now.return_value.hour = 16
            mock_now.return_value.minute = 0
            assert service.market_status() == "CLOSED"

    def test_fallback_on_error(self, service):
        """Exception should fall back to OPEN."""
        with patch("core.mandate_service.now_ist") as mock_now:
            mock_now.side_effect = ValueError("test error")
            assert service.market_status() == "OPEN"


class TestPositionSizing:
    """Tests for MandateService.get_position_size()."""

    def test_uses_risk_service(self, service):
        """Should delegate to RiskService when available."""
        qty = service.get_position_size("NIFTY", 100.0)
        assert qty == 1
        service._risk_service.calculate_position_size.assert_called_once()

    def test_fallback_on_risk_error(self, service):
        """Should fall back to mandate enforcer on RiskService error."""
        service._risk_service.calculate_position_size.side_effect = ValueError("test")
        me_mock = MagicMock()
        me_mock.get_position_size.return_value = 2
        service._mandate_enforcer = me_mock
        qty = service.get_position_size("NIFTY", 100.0)
        assert qty == 2

    def test_ultimate_fallback(self, service):
        """Should return 1 when all services fail."""
        service._risk_service = None
        service._mandate_enforcer = None
        qty = service.get_position_size("NIFTY", 100.0)
        assert qty == 1


class TestMandateCheck:
    """Tests for MandateService.check_mandate_trade_allowed()."""

    def test_allowed(self, service):
        """All gates pass should return allowed."""
        allowed, reason = service.check_mandate_trade_allowed("TRENDING", 85)
        assert allowed is True
        assert "MANDATE_ALLOWED" in reason

    def test_blocked_outside_trading_window(self, service):
        """Outside trading window should block."""
        service._risk_service.is_in_trading_window.return_value = False
        allowed, reason = service.check_mandate_trade_allowed("TRENDING", 85)
        assert allowed is False
        assert "Outside trading window" in reason

    def test_blocked_first_20_min(self, service):
        """First 20 minutes should block."""
        service._risk_service.should_skip_first_20_min.return_value = True
        allowed, reason = service.check_mandate_trade_allowed("TRENDING", 85)
        assert allowed is False
        assert "First 20 minutes" in reason

    def test_blocked_last_45_min(self, service):
        """Last 45 minutes should block."""
        service._risk_service.should_skip_last_45_min.return_value = True
        allowed, reason = service.check_mandate_trade_allowed("TRENDING", 85)
        assert allowed is False
        assert "Last 45 minutes" in reason

    def test_blocked_low_score(self, service):
        """Score below regime threshold should block."""
        service._risk_service.get_min_score_for_regime.return_value = 80
        allowed, reason = service.check_mandate_trade_allowed("TRENDING", 70)
        assert allowed is False
        assert "Score 70 < 80" in reason

    def test_blocked_false_signal(self, service):
        """False signal filter should block."""
        service._risk_service.should_block_false_signal.return_value = True
        allowed, reason = service.check_mandate_trade_allowed("TRENDING", 85)
        assert allowed is False
        assert "False signal" in reason

    def test_blocked_max_trades(self, service):
        """Max trades reached should block."""
        metrics = service._risk_service.get_portfolio_risk_metrics()
        metrics.open_positions_count = 5
        service._risk_service.get_max_trades_per_day.return_value = 3
        allowed, reason = service.check_mandate_trade_allowed("TRENDING", 85)
        assert allowed is False
        assert "Max trades today" in reason

    def test_blocked_hard_stop(self, service):
        """Hard stop limit hit should block."""
        metrics = service._risk_service.get_portfolio_risk_metrics()
        metrics.daily_pnl = -2500.0
        metrics.max_daily_loss = -2000.0
        allowed, reason = service.check_mandate_trade_allowed("TRENDING", 85)
        assert allowed is False
        assert "Daily loss limit" in reason

    def test_fallback_mandate_enforcer(self, service):
        """Should fall back to mandate enforcer on RiskService error."""
        service._risk_service.is_in_trading_window.side_effect = ValueError("test")
        me_mock = MagicMock()
        me_mock.can_trade.return_value = (True, "OK")
        me_mock.is_in_trading_window.return_value = True
        me_mock.should_skip_first_20_min.return_value = False
        me_mock.should_skip_last_45_min.return_value = False
        me_mock.get_min_score.return_value = 60
        me_mock.should_block_false_signal.return_value = False
        me_mock.get_status.return_value = {"trades_today": 0, "max_trades_today": 10}
        service._mandate_enforcer = me_mock
        allowed, reason = service.check_mandate_trade_allowed("TRENDING", 85)
        assert allowed is True


class TestMandateStatus:
    """Tests for MandateService.get_mandate_status()."""

    def test_returns_dict(self, service):
        """Should return a dict with expected keys."""
        status = service.get_mandate_status()
        assert isinstance(status, dict)
        assert "trades_today" in status
        assert "max_trades_today" in status
        assert "can_trade" in status

    def test_can_trade_true_when_under_limit(self, service):
        """Should return can_trade=True when under max."""
        status = service.get_mandate_status()
        assert status["can_trade"] is True

    def test_can_trade_false_when_at_limit(self, service):
        """Should return can_trade=False when at max."""
        metrics = service._risk_service.get_portfolio_risk_metrics()
        metrics.open_positions_count = 5
        status = service.get_mandate_status()
        assert status["can_trade"] is False

    def test_fallback_without_risk_service(self, service):
        """Should return defaults when RiskService is None."""
        service._risk_service = None
        status = service.get_mandate_status()
        assert status["trades_today"] == 0
        assert status["can_trade"] is True


class TestWaitReasons:
    """Tests for MandateService.get_wait_reason_components()."""

    def test_pass_on_none(self, service):
        """None signal should return WAIT."""
        display, reasons = service.get_wait_reason_components(None)
        assert display == "WAIT"

    def test_pass_on_valid(self, service):
        """Signal with score above threshold should return PASS."""
        display, reasons = service.get_wait_reason_components({
            "score": 85, "threshold": 60, "market_status": "OPEN",
        })
        assert display == "PASS"

    def test_score_below_threshold(self, service):
        """Score below threshold should add Score reason."""
        display, reasons = service.get_wait_reason_components({
            "score": 50, "threshold": 60, "market_status": "OPEN",
        })
        assert "Score" in reasons

    def test_vix_too_high(self, service):
        """VIX above 27 should add VIX reason."""
        display, reasons = service.get_wait_reason_components({
            "score": 50, "threshold": 60, "market_status": "OPEN",
            "vix": 30.0,
        })
        assert "VIX" in reasons

    def test_market_closed(self, service):
        """Market not OPEN should add Market reason."""
        display, reasons = service.get_wait_reason_components({
            "score": 85, "threshold": 60, "market_status": "CLOSED",
        })
        assert "Market" in reasons


class TestGetMandateService:
    """Tests for get_mandate_service singleton factory."""

    def setup_method(self):
        reset_mandate_service()

    def test_get_instance(self):
        instance = get_mandate_service()
        assert isinstance(instance, MandateService)

    def test_singleton_behavior(self):
        s1 = get_mandate_service()
        s2 = get_mandate_service()
        assert s1 is s2

    def test_reset(self):
        s1 = get_mandate_service()
        reset_mandate_service()
        s2 = get_mandate_service()
        assert s1 is not s2
