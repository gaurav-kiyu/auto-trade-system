"""Tests for core/services/notification_service.py."""

from __future__ import annotations

from unittest.mock import patch

import core.services.notification_service as _mod
from core.notification_filters import reset_dedupe_cache


class TestServicesNotification_service:
    """Test suite for core/services/notification_service.py."""

    def test_import(self):
        """Verify module imports successfully."""
        assert _mod is not None


def _make_running_service(cfg: dict) -> _mod.NotificationService:
    """A NotificationService with status forced RUNNING and no adapters,
    so send() reaches the enqueue path without spinning up real worker
    threads or network calls -- isolates the filter-gate wiring under test."""
    svc = _mod.NotificationService(cfg=cfg)
    svc._status = _mod.ServiceStatus.RUNNING
    svc._adapters = {}
    return svc


class TestNotificationFilterWiring:
    """core/notification_filters.py wiring into NotificationService.send() --
    disabled by default (notification_filters_enabled=False), so a fresh
    install sends exactly as many messages as before this module existed.
    See TestIntradayPerformanceMonitorWiring in tests/test_position_service.py
    for the pairing convention this follows."""

    def setup_method(self):
        reset_dedupe_cache()

    def teardown_method(self):
        reset_dedupe_cache()

    def test_disabled_by_default_message_reaches_dispatch(self):
        """Regression guard: cfg={} -> notification_filters_enabled defaults
        False -> send() must reach send_notification(), never short-circuit
        to None via the filter."""
        svc = _make_running_service(cfg={})
        with patch.object(svc, "send_notification", return_value=None) as mock_sn:
            result = svc.send("Some informational message", critical=False)
        mock_sn.assert_called_once()
        assert result is None  # send_notification(blocking=False) itself returns None

    def test_enabled_quiet_mode_suppresses_noncritical_before_dispatch(self):
        """With the master switch on, the shipped TG_QUIET_MODE=True default
        actually suppresses -- proving this is wired with real effect, not
        advisory. send_notification must never even be reached."""
        svc = _make_running_service(cfg={"notification_filters_enabled": True})
        with patch.object(svc, "send_notification") as mock_sn:
            result = svc.send("Some informational message", critical=False)
        mock_sn.assert_not_called()
        assert result is None

    def test_enabled_critical_message_still_dispatched(self):
        """Critical alerts always bypass the filter, master switch on or off."""
        svc = _make_running_service(cfg={"notification_filters_enabled": True})
        with patch.object(svc, "send_notification", return_value=None) as mock_sn:
            svc.send("HARD_HALT triggered", critical=True)
        mock_sn.assert_called_once()

    def test_enabled_trade_only_allows_real_trade_message(self):
        cfg = {
            "notification_filters_enabled": True,
            "TG_QUIET_MODE": False,
            "TG_TRADE_ONLY": True,
            "TG_TRADE_ALERTS_STRICT": True,
        }
        svc = _make_running_service(cfg=cfg)
        with patch.object(svc, "send_notification", return_value=None) as mock_sn:
            svc.send("EXIT NIFTY: TARGET_HIT @ 120.5 P&L=450", critical=False)
        mock_sn.assert_called_once()

    def test_no_cfg_defaults_to_empty_dict_and_never_suppresses(self):
        """NotificationService() with no cfg arg at all (every pre-existing
        call site) must behave exactly like cfg={}."""
        svc = _mod.NotificationService()
        svc._status = _mod.ServiceStatus.RUNNING
        svc._adapters = {}
        with patch.object(svc, "send_notification", return_value=None) as mock_sn:
            svc.send("Some informational message", critical=False)
        mock_sn.assert_called_once()
