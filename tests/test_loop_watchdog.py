"""Tests for core.loop_watchdog — LoopWatchdog stall detector.

Covers:
- heartbeat()/check()/get_lag() basic mechanics
- disabled (default) never alerts, never reads heartbeat state
- enabled + timeout exceeded -> CRITICAL log + notify_fn called once per episode
- heartbeat() clears the alert flag so a later stall can re-alert
- singleton accessor get_loop_watchdog()/reset_loop_watchdog()
"""
from __future__ import annotations

import time

import pytest
from core.loop_watchdog import LoopWatchdog, get_loop_watchdog, reset_loop_watchdog


@pytest.fixture(autouse=True)
def _reset_singleton():
    reset_loop_watchdog()
    yield
    reset_loop_watchdog()


class TestHeartbeatAndLag:
    def test_heartbeat_resets_lag_near_zero(self):
        wd = LoopWatchdog(cfg={"loop_watchdog_enabled": True})
        time.sleep(0.05)
        wd.heartbeat()
        assert wd.get_lag() < 0.05

    def test_lag_grows_without_heartbeat(self):
        wd = LoopWatchdog(cfg={})
        time.sleep(0.05)
        assert wd.get_lag() >= 0.05


class TestCheckDisabledByDefault:
    def test_disabled_default_never_alerts(self):
        wd = LoopWatchdog(cfg={"WATCHDOG_TIMEOUT": 0})
        # Even with a zero timeout (always "stalled" if enabled), disabled
        # (the default) must return False and do nothing.
        assert wd.check() is False

    def test_missing_flag_defaults_disabled(self):
        wd = LoopWatchdog(cfg={"WATCHDOG_TIMEOUT": 0})
        assert wd.check() is False
        assert wd.check() is False  # idempotent, still no-op


class TestCheckEnabled:
    def test_no_stall_within_timeout(self):
        wd = LoopWatchdog(cfg={"loop_watchdog_enabled": True, "WATCHDOG_TIMEOUT": 300})
        assert wd.check() is False

    def test_stall_detected_and_alert_fires_once(self):
        notified = []
        wd = LoopWatchdog(
            cfg={"loop_watchdog_enabled": True, "WATCHDOG_TIMEOUT": 0},
            notify_fn=notified.append,
        )
        assert wd.check() is True
        assert wd.check() is True  # still stalled
        # Alert (notify_fn) must only fire once per stall episode.
        assert len(notified) == 1
        assert "stalled" in notified[0]

    def test_heartbeat_clears_alert_and_allows_re_alert(self):
        notified = []
        wd = LoopWatchdog(
            cfg={"loop_watchdog_enabled": True, "WATCHDOG_TIMEOUT": 0},
            notify_fn=notified.append,
        )
        assert wd.check() is True
        assert len(notified) == 1
        wd.heartbeat()
        assert wd.check() is True  # timeout=0 so immediately "stalled" again
        assert len(notified) == 2

    def test_notify_fn_exception_is_swallowed(self):
        def _boom(_msg: str) -> None:
            raise ValueError("notify failed")

        wd = LoopWatchdog(cfg={"loop_watchdog_enabled": True, "WATCHDOG_TIMEOUT": 0}, notify_fn=_boom)
        # Must not raise even though notify_fn blows up.
        assert wd.check() is True

    def test_bad_timeout_value_falls_back_to_default(self):
        wd = LoopWatchdog(cfg={"loop_watchdog_enabled": True, "WATCHDOG_TIMEOUT": "not-a-number"})
        # Falls back to 300s default; freshly-created watchdog has ~0s lag.
        assert wd.check() is False


class TestUpdateConfigAndNotifyFn:
    def test_update_config_takes_effect(self):
        wd = LoopWatchdog(cfg={"loop_watchdog_enabled": False})
        assert wd.check() is False
        wd.update_config({"loop_watchdog_enabled": True, "WATCHDOG_TIMEOUT": 0})
        assert wd.check() is True

    def test_set_notify_fn(self):
        notified = []
        wd = LoopWatchdog(cfg={"loop_watchdog_enabled": True, "WATCHDOG_TIMEOUT": 0})
        wd.set_notify_fn(notified.append)
        wd.check()
        assert len(notified) == 1


class TestSingleton:
    def test_returns_same_instance(self):
        w1 = get_loop_watchdog({"loop_watchdog_enabled": True})
        w2 = get_loop_watchdog()
        assert w1 is w2

    def test_new_cfg_updates_existing_instance(self):
        w1 = get_loop_watchdog({"loop_watchdog_enabled": True, "WATCHDOG_TIMEOUT": 300})
        w2 = get_loop_watchdog({"loop_watchdog_enabled": True, "WATCHDOG_TIMEOUT": 0})
        assert w1 is w2
        assert w1._cfg.get("WATCHDOG_TIMEOUT") == 0

    def test_reset_drops_singleton(self):
        w1 = get_loop_watchdog({"loop_watchdog_enabled": True})
        reset_loop_watchdog()
        w2 = get_loop_watchdog({"loop_watchdog_enabled": True})
        assert w1 is not w2
