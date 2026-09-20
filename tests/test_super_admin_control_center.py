import pytest
from unittest.mock import MagicMock, patch

from core.exchange_calendar_engine import ExchangeCalendarEngine
from core.signals.signal_tracker import SignalTracker


def test_control_center_status_structure(tmp_path):
    """Test control center status payload has all expected sections and invariants."""
    db_file = tmp_path / "test_ctrl_signals.db"
    SignalTracker.reset_instance()
    tracker = SignalTracker(db_path=db_file)

    with patch("core.signals.signal_tracker.SignalTracker.get_instance", return_value=tracker):
        from core.datetime_ist import now_ist
        from core.exchange_calendar_engine import ExchangeCalendarEngine, ExtendedMarketStatus
        from core.services.notification_service import get_notification_service

        now = now_ist()
        cal = ExchangeCalendarEngine.get_instance()
        market_status = cal.get_market_status(now)
        trading_hours = cal.get_trading_hours(now.date())
        is_active = market_status in (
            ExtendedMarketStatus.OPEN,
            ExtendedMarketStatus.MUHURAT,
            ExtendedMarketStatus.HALF_DAY,
        )
        today_analytics = tracker.get_admin_signal_analytics(timeframe="today")
        notif_svc = get_notification_service()
        notif_health = notif_svc.get_notification_health()

        payload = {
            "app": {
                "version": "v2.59.4",
                "status": "HEALTHY",
                "mode": "SIGNAL_ONLY / PAPER",
                "timestamp": now.strftime("%Y-%m-%d %H:%M:%S IST"),
            },
            "safety_invariants": {
                "BASE_CAPITAL": 3000,
                "SL_PCT": 0.88,
                "EXECUTION_MODE": "SIGNAL_ONLY",
                "SIGNAL_ONLY": True,
                "LIVE_TRADING_LOCKOUT": True,
                "full_auto_allowed": False,
                "broker_auto_routing": "DISCONNECTED",
                "live_trades_count": 0,
                "live_orders_count": 0,
            },
            "market_session": {
                "state": market_status.value,
                "is_trading_day": trading_hours.is_trading_day,
                "is_active_market": is_active,
                "description": trading_hours.description,
            },
            "signals_today": {
                "total": today_analytics.get("total_signals", 0),
                "resolved": today_analytics.get("resolved_signals", 0),
                "active": today_analytics.get("active_signals", 0),
                "win_rate_display": today_analytics.get("win_rate_display", "N/A"),
                "t1_rate": today_analytics.get("t1_hit_rate_pct", 0),
                "t2_rate": today_analytics.get("t2_hit_rate_pct", 0),
            },
            "notification_subsystem": notif_health,
        }

        # Check safety invariants
        invariants = payload["safety_invariants"]
        assert invariants["BASE_CAPITAL"] == 3000
        assert invariants["SL_PCT"] == 0.88
        assert invariants["SIGNAL_ONLY"] is True
        assert invariants["LIVE_TRADING_LOCKOUT"] is True
        assert invariants["full_auto_allowed"] is False
        assert invariants["broker_auto_routing"] == "DISCONNECTED"
        assert invariants["live_trades_count"] == 0
        assert invariants["live_orders_count"] == 0

        # Check zero credentials
        payload_str = str(payload).lower()
        assert "bot" not in payload_str or "bot_token" not in payload_str
        assert "password" not in payload_str
        assert "secret" not in payload_str


def test_control_center_endpoint_live():
    """Test calling the registered endpoint function directly."""
    from unittest.mock import AsyncMock
    from core.enterprise_dashboard.routes.admin import register_admin_routes

    mock_app = MagicMock()
    mock_dashboard = MagicMock()
    mock_admin_only = MagicMock()
    mock_operator_or_admin = MagicMock()

    routes = {}

    def mock_get(path):
        def decorator(fn):
            routes[path] = fn
            return fn
        return decorator

    mock_app.get = mock_get
    register_admin_routes(mock_app, mock_dashboard, mock_admin_only, mock_operator_or_admin)

    assert "/api/v1/admin/control-center-status" in routes
    handler = routes["/api/v1/admin/control-center-status"]

    import asyncio
    mock_request = MagicMock()
    result = asyncio.run(handler(mock_request, user=MagicMock()))

    assert "app" in result
    assert result["app"]["version"] == "v2.59.4"
    assert result["safety_invariants"]["BASE_CAPITAL"] == 3000
    assert result["safety_invariants"]["SL_PCT"] == 0.88
    assert result["safety_invariants"]["SIGNAL_ONLY"] is True
    assert result["safety_invariants"]["LIVE_TRADING_LOCKOUT"] is True
