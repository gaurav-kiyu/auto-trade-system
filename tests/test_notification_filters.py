"""Tests for core/notification_filters.py.

Covers the wiring of six previously-dead config keys:
    TG_QUIET_MODE, TG_TRADE_ONLY, TG_TRADE_ALERTS_STRICT, TG_CACHE_TTL_SEC,
    TG_HEARTBEAT_INTERVAL, TG_PERIODIC_SUMMARY_TELEGRAM

Every gate follows the "disabled by default -> no effect" / "enabled ->
real effect observed" pairing used elsewhere in this suite (see
TestIntradayPerformanceMonitorWiring in tests/test_position_service.py).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.notification_filters import (
    IntervalGate,
    maybe_send_heartbeat,
    maybe_send_periodic_summary,
    reset_dedupe_cache,
    should_send_notification,
)


@pytest.fixture(autouse=True)
def _reset_cache():
    reset_dedupe_cache()
    yield
    reset_dedupe_cache()


# =============================================================================
# should_send_notification() -- master switch (notification_filters_enabled)
# =============================================================================

class TestMasterSwitchDisabledByDefault:
    """Regression guard: with notification_filters_enabled left at its
    default (False, since it's a brand-new key), nothing is ever suppressed
    -- byte-for-byte the pre-existing behavior."""

    def test_empty_cfg_never_suppresses(self):
        assert should_send_notification("any message", critical=False, cfg={}) is True
        assert should_send_notification("any message", critical=True, cfg={}) is True

    def test_explicit_false_never_suppresses_even_with_quiet_mode_true(self):
        cfg = {
            "notification_filters_enabled": False,
            "TG_QUIET_MODE": True,
            "TG_TRADE_ONLY": True,
        }
        assert should_send_notification("random chatter", critical=False, cfg=cfg) is True

    def test_none_cfg_never_suppresses(self):
        assert should_send_notification("any message", critical=False, cfg=None) is True


class TestMasterSwitchEnabledRealEffect:
    """With notification_filters_enabled=True, the shipped defaults
    (TG_QUIET_MODE=True) actually suppress non-critical chatter -- proving
    this is wired with real effect, not advisory."""

    def test_quiet_mode_suppresses_noncritical(self):
        cfg = {"notification_filters_enabled": True, "TG_QUIET_MODE": True}
        assert should_send_notification("some informational text", critical=False, cfg=cfg) is False

    def test_critical_always_bypasses_quiet_mode(self):
        cfg = {"notification_filters_enabled": True, "TG_QUIET_MODE": True}
        assert should_send_notification("HARD_HALT tripped", critical=True, cfg=cfg) is True

    def test_quiet_mode_off_trade_only_on_strict_blocks_non_trade(self):
        cfg = {
            "notification_filters_enabled": True,
            "TG_QUIET_MODE": False,
            "TG_TRADE_ONLY": True,
            "TG_TRADE_ALERTS_STRICT": True,
        }
        assert should_send_notification("Health check OK", critical=False, cfg=cfg) is False

    def test_quiet_mode_off_trade_only_on_strict_allows_real_trade_text(self):
        cfg = {
            "notification_filters_enabled": True,
            "TG_QUIET_MODE": False,
            "TG_TRADE_ONLY": True,
            "TG_TRADE_ALERTS_STRICT": True,
        }
        assert should_send_notification("EXIT NIFTY: TARGET_HIT @ 120.5 P&L=450", critical=False, cfg=cfg) is True
        assert should_send_notification("[MANUAL SIGNAL] NIFTY CALL @ 23500 RR=2.0", critical=False, cfg=cfg) is True

    def test_strict_mode_rejects_loose_keyword_only_message(self):
        cfg = {
            "notification_filters_enabled": True,
            "TG_QUIET_MODE": False,
            "TG_TRADE_ONLY": True,
            "TG_TRADE_ALERTS_STRICT": True,
        }
        # "signal" alone is a loose-only marker, not a strict trade marker.
        assert should_send_notification("New signal generated for review", critical=False, cfg=cfg) is False

    def test_non_strict_mode_accepts_loose_keyword_message(self):
        cfg = {
            "notification_filters_enabled": True,
            "TG_QUIET_MODE": False,
            "TG_TRADE_ONLY": True,
            "TG_TRADE_ALERTS_STRICT": False,
        }
        assert should_send_notification("New signal generated for review", critical=False, cfg=cfg) is True

    def test_trade_only_off_allows_any_noncritical_message(self):
        cfg = {
            "notification_filters_enabled": True,
            "TG_QUIET_MODE": False,
            "TG_TRADE_ONLY": False,
        }
        assert should_send_notification("Just a generic status ping", critical=False, cfg=cfg) is True

    def test_cache_ttl_dedupes_repeated_message(self):
        cfg = {
            "notification_filters_enabled": True,
            "TG_QUIET_MODE": False,
            "TG_TRADE_ONLY": False,
            "TG_CACHE_TTL_SEC": 55,
        }
        assert should_send_notification("Repeated status", critical=False, cfg=cfg) is True
        # Same message again immediately -> suppressed as a duplicate.
        assert should_send_notification("Repeated status", critical=False, cfg=cfg) is False

    def test_cache_ttl_allows_after_ttl_elapsed(self):
        cfg = {
            "notification_filters_enabled": True,
            "TG_QUIET_MODE": False,
            "TG_TRADE_ONLY": False,
            "TG_CACHE_TTL_SEC": 1,
        }
        import time as _time
        assert should_send_notification("Repeated status 2", critical=False, cfg=cfg) is True
        _time.sleep(1.1)
        assert should_send_notification("Repeated status 2", critical=False, cfg=cfg) is True

    def test_critical_bypasses_dedupe_cache(self):
        cfg = {
            "notification_filters_enabled": True,
            "TG_QUIET_MODE": False,
            "TG_TRADE_ONLY": False,
            "TG_CACHE_TTL_SEC": 9999,
        }
        assert should_send_notification("HARD HALT", critical=True, cfg=cfg) is True
        assert should_send_notification("HARD HALT", critical=True, cfg=cfg) is True


class TestFailOpen:
    """A bug in the filter must never be able to block the underlying send()
    call it's guarding."""

    def test_message_without_upper_fails_open(self):
        class _NotAString:
            def upper(self):
                raise ValueError("boom")

        cfg = {
            "notification_filters_enabled": True,
            "TG_QUIET_MODE": False,
            "TG_TRADE_ONLY": True,
        }
        assert should_send_notification(_NotAString(), critical=False, cfg=cfg) is True

    def test_cfg_get_raising_fails_open(self):
        class _BadCfg:
            def get(self, *_a, **_k):
                raise KeyError("boom")

        assert should_send_notification("msg", critical=False, cfg=_BadCfg()) is True


# =============================================================================
# IntervalGate
# =============================================================================

class TestIntervalGate:
    def test_due_immediately_on_fresh_gate(self):
        gate = IntervalGate()
        assert gate.due(3600, now=1000.0) is True

    def test_not_due_right_after_firing(self):
        gate = IntervalGate()
        gate.mark_fired(now=1000.0)
        assert gate.due(3600, now=1000.5) is False

    def test_due_again_after_interval_elapses(self):
        gate = IntervalGate()
        gate.mark_fired(now=1000.0)
        assert gate.due(3600, now=1000.0 + 3600.0) is True

    def test_reset_makes_it_due_again(self):
        gate = IntervalGate()
        gate.mark_fired(now=1000.0)
        gate.reset()
        assert gate.due(3600, now=1000.5) is True


# =============================================================================
# maybe_send_heartbeat() -- TG_HEARTBEAT_ENABLED / TG_HEARTBEAT_INTERVAL
# =============================================================================

class TestHeartbeatDisabledByDefault:
    def test_empty_cfg_never_sends(self):
        gate = IntervalGate()
        sent = []
        assert maybe_send_heartbeat({}, sent.append, gate) is False
        assert sent == []

    def test_explicit_false_never_sends(self):
        gate = IntervalGate()
        sent = []
        cfg = {"TG_HEARTBEAT_ENABLED": False, "TG_HEARTBEAT_INTERVAL": 1}
        assert maybe_send_heartbeat(cfg, sent.append, gate, now=1000.0) is False
        assert sent == []

    def test_none_send_fn_never_raises(self):
        gate = IntervalGate()
        cfg = {"TG_HEARTBEAT_ENABLED": True}
        assert maybe_send_heartbeat(cfg, None, gate) is False


class TestHeartbeatEnabledRealEffect:
    def test_enabled_and_due_sends_once_and_marks_gate(self):
        gate = IntervalGate()
        sent = []
        cfg = {"TG_HEARTBEAT_ENABLED": True, "TG_HEARTBEAT_INTERVAL": 3600}
        assert maybe_send_heartbeat(cfg, sent.append, gate, now=1000.0) is True
        assert len(sent) == 1
        assert "Heartbeat" in sent[0]

    def test_enabled_but_not_due_yet_does_not_resend(self):
        gate = IntervalGate()
        sent = []
        cfg = {"TG_HEARTBEAT_ENABLED": True, "TG_HEARTBEAT_INTERVAL": 3600}
        assert maybe_send_heartbeat(cfg, sent.append, gate, now=1000.0) is True
        assert maybe_send_heartbeat(cfg, sent.append, gate, now=1001.0) is False
        assert len(sent) == 1

    def test_enabled_and_interval_elapsed_sends_again(self):
        gate = IntervalGate()
        sent = []
        cfg = {"TG_HEARTBEAT_ENABLED": True, "TG_HEARTBEAT_INTERVAL": 100}
        assert maybe_send_heartbeat(cfg, sent.append, gate, now=1000.0) is True
        assert maybe_send_heartbeat(cfg, sent.append, gate, now=1101.0) is True
        assert len(sent) == 2

    def test_send_fn_error_fails_open_no_raise(self):
        gate = IntervalGate()

        def _boom(_msg):
            raise OSError("network down")

        cfg = {"TG_HEARTBEAT_ENABLED": True, "TG_HEARTBEAT_INTERVAL": 3600}
        assert maybe_send_heartbeat(cfg, _boom, gate, now=1000.0) is False


# =============================================================================
# maybe_send_periodic_summary() -- TG_PERIODIC_SUMMARY_TELEGRAM
# =============================================================================

class TestPeriodicSummaryDisabledByDefault:
    def test_empty_cfg_never_sends(self):
        gate = IntervalGate()
        sent = []
        assert maybe_send_periodic_summary({}, sent.append, gate) is False
        assert sent == []

    def test_explicit_false_never_sends(self):
        gate = IntervalGate()
        sent = []
        cfg = {"TG_PERIODIC_SUMMARY_TELEGRAM": False}
        assert maybe_send_periodic_summary(cfg, sent.append, gate, now=1000.0) is False
        assert sent == []


class TestPeriodicSummaryEnabledRealEffect:
    def test_enabled_and_due_sends_summary_text_and_marks_gate(self):
        gate = IntervalGate()
        sent = []
        cfg = {"TG_PERIODIC_SUMMARY_TELEGRAM": True, "TG_PERIODIC_SUMMARY_INTERVAL_SEC": 3600}
        fake_summary = MagicMock(return_value="Trades: 5  WR: 60%")
        assert maybe_send_periodic_summary(cfg, sent.append, gate, summary_fn=fake_summary, now=1000.0) is True
        fake_summary.assert_called_once()
        assert len(sent) == 1
        assert "Trades: 5" in sent[0]

    def test_enabled_but_not_due_yet_does_not_resend(self):
        gate = IntervalGate()
        sent = []
        cfg = {"TG_PERIODIC_SUMMARY_TELEGRAM": True, "TG_PERIODIC_SUMMARY_INTERVAL_SEC": 3600}
        fake_summary = MagicMock(return_value="x")
        assert maybe_send_periodic_summary(cfg, sent.append, gate, summary_fn=fake_summary, now=1000.0) is True
        assert maybe_send_periodic_summary(cfg, sent.append, gate, summary_fn=fake_summary, now=1001.0) is False
        assert len(sent) == 1

    def test_uses_real_performance_metrics_by_default(self, tmp_path, monkeypatch):
        """No summary_fn override -> falls back to
        core.performance_metrics.periodic_summary (no new metrics math invented)."""
        gate = IntervalGate()
        sent = []
        db_path = str(tmp_path / "trades.db")
        cfg = {
            "TG_PERIODIC_SUMMARY_TELEGRAM": True,
            "TG_PERIODIC_SUMMARY_INTERVAL_SEC": 1,
            "DB_PATH": db_path,
            "EXECUTION_MODE": "PAPER",
        }
        # No trades.db exists at db_path -> real periodic_summary() should
        # degrade gracefully rather than raising.
        result = maybe_send_periodic_summary(cfg, sent.append, gate, now=1000.0)
        assert result is True
        assert len(sent) == 1
        assert "Periodic summary" in sent[0]

    def test_summary_fn_error_fails_open_no_raise(self):
        gate = IntervalGate()
        sent = []
        cfg = {"TG_PERIODIC_SUMMARY_TELEGRAM": True, "TG_PERIODIC_SUMMARY_INTERVAL_SEC": 3600}

        def _boom(**_kw):
            raise ValueError("db error")

        assert maybe_send_periodic_summary(cfg, sent.append, gate, summary_fn=_boom, now=1000.0) is False
        assert sent == []
