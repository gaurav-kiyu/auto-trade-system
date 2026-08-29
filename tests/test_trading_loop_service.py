"""Tests for index_app/domains/trading/service.py — TradingLoopService.

Covers the two new opt-in wire-ins added alongside this test:
- loop_watchdog_enabled -> core.loop_watchdog.LoopWatchdog heartbeat/check tick
- EXCEPTION_ALERT_THRESHOLD -> per-type exception counting + one alert per
  type once the threshold is crossed, with IST-day reset

Both follow the "disabled by default -> no effect" / "enabled -> real
effect observed" pairing used elsewhere in this test suite (see
TestIntradayPerformanceMonitorWiring in tests/test_position_service.py).
"""
from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch

import pytest
from index_app.domains.trading.service import TradingLoopService


def _make_service(cfg: dict | None = None, **overrides) -> TradingLoopService:
    kwargs = {
        "cfg": cfg if cfg is not None else {},
        "shutdown_event": threading.Event(),
        "is_hard_halted_fn": lambda: False,
        "market_status_fn": lambda: "OPEN",
        "fetch_intraday_data_cached_fn": lambda idx: ({}, {}),
        "fetch_vix_fn": lambda: 15.0,
        "generate_trading_signal_fn": lambda idx, frames, vix: {},
        "enter_trade_fn": lambda idx, sig: None,
        "monitor_positions_fn": lambda: None,
        "periodic_reconcile_fn": lambda: None,
        "check_mandate_trade_allowed_fn": lambda *a, **k: (True, ""),
        "check_portfolio_correlation_fn": lambda *a, **k: (True, ""),
        "reentry_trackers": {},
        "decision_log": {},
        "index_priority": [],
        "positions": {},
        "pos_lock": threading.Lock(),
        "send_fn": None,
        "dashboard_notify_fn": None,
    }
    kwargs.update(overrides)
    return TradingLoopService(**kwargs)


@pytest.fixture(autouse=True)
def _reset_loop_watchdog_singleton():
    from core.loop_watchdog import reset_loop_watchdog
    reset_loop_watchdog()
    yield
    reset_loop_watchdog()


@pytest.fixture(autouse=True)
def _reset_signal_tracker_singleton():
    from core.signals.signal_tracker import SignalTracker
    SignalTracker.reset_instance()
    yield
    SignalTracker.reset_instance()


# =============================================================================
# loop_watchdog_enabled wiring
# =============================================================================

class TestLoopWatchdogWiring:
    def test_disabled_by_default_watchdog_never_touched(self):
        """Regression guard: with loop_watchdog_enabled left at its default
        (False), get_loop_watchdog() must never even be imported/called."""
        svc = _make_service(cfg={})
        with patch("core.loop_watchdog.get_loop_watchdog") as mock_get:
            svc._loop_watchdog_tick()
            mock_get.assert_not_called()

    def test_enabled_calls_check_then_heartbeat(self):
        svc = _make_service(cfg={"loop_watchdog_enabled": True, "WATCHDOG_TIMEOUT": 300})
        mock_wd = MagicMock()
        with patch("core.loop_watchdog.get_loop_watchdog", return_value=mock_wd) as mock_get:
            svc._loop_watchdog_tick()
            mock_get.assert_called_once()
            mock_wd.check.assert_called_once()
            mock_wd.heartbeat.assert_called_once()

    def test_enabled_real_stall_detection_fires_notify(self):
        """End-to-end (no mocking of LoopWatchdog itself): with the flag on
        and a zero timeout, the very first tick must detect a "stall" and
        invoke send_fn."""
        sent = []
        svc = _make_service(
            cfg={"loop_watchdog_enabled": True, "WATCHDOG_TIMEOUT": 0},
            send_fn=sent.append,
        )
        svc._loop_watchdog_tick()
        assert len(sent) == 1
        assert "stalled" in sent[0]

    def test_watchdog_internal_error_is_swallowed(self):
        svc = _make_service(cfg={"loop_watchdog_enabled": True})
        with patch("core.loop_watchdog.get_loop_watchdog", side_effect=ValueError("boom")):
            svc._loop_watchdog_tick()  # must not raise


# =============================================================================
# CONFIG_DRIFT_AUTO_RELOAD wiring
# =============================================================================

class TestConfigDriftAutoReloadWiring:
    def test_disabled_by_default_reloader_never_touched(self):
        """Regression guard: with config_drift_auto_reload_enabled left at
        its default (False), get_config_drift_reloader() must never even be
        imported/called."""
        svc = _make_service(cfg={})
        with patch("core.config_drift_reloader.get_config_drift_reloader") as mock_get:
            svc._config_drift_auto_reload_tick()
            mock_get.assert_not_called()

    def test_enabled_calls_check(self):
        svc = _make_service(cfg={"config_drift_auto_reload_enabled": True})
        mock_reloader = MagicMock()
        with patch("core.config_drift_reloader.get_config_drift_reloader", return_value=mock_reloader) as mock_get:
            svc._config_drift_auto_reload_tick()
            mock_get.assert_called_once()
            mock_reloader.check.assert_called_once()

    def test_enabled_real_hot_apply_end_to_end(self, tmp_path):
        """End-to-end (no mocking of ConfigDriftReloader itself): a changed
        safe-allowlisted key on disk must land in the live cfg dict after
        one tick."""
        from core.config_drift_reloader import reset_config_drift_reloader
        reset_config_drift_reloader()
        config_path = tmp_path / "config.json"
        config_path.write_text('{"BREAKOUT_BONUS": 99}', encoding="utf-8")
        cfg = {"config_drift_auto_reload_enabled": True, "BREAKOUT_BONUS": 8}
        svc = _make_service(cfg=cfg)
        with patch("core.config_drift_reloader.os.environ.get", return_value=str(config_path)):
            svc._config_drift_auto_reload_tick()
        assert cfg["BREAKOUT_BONUS"] == 99
        reset_config_drift_reloader()

    def test_reloader_internal_error_is_swallowed(self):
        svc = _make_service(cfg={"config_drift_auto_reload_enabled": True})
        with patch("core.config_drift_reloader.get_config_drift_reloader", side_effect=ValueError("boom")):
            svc._config_drift_auto_reload_tick()  # must not raise


# =============================================================================
# timeseries_lake_enabled wiring
# =============================================================================

class TestTimeseriesLakeWiring:
    """timeseries_lake_enabled opt-in (default False): per-cycle tick
    recording into core.persistence.timeseries_db.TimeSeriesDataLake via
    _record_tick_to_lake(), called once per index from _fetch_all_frames().
    Mirrors TestLoopWatchdogWiring's disabled/enabled/error-swallowed shape."""

    def _make_df1m(self):
        import pandas as pd
        return pd.DataFrame({"Close": [100.0, 101.0, 102.5], "Volume": [10, 20, 30]})

    def test_disabled_by_default_lake_never_touched(self):
        """Regression guard: with timeseries_lake_enabled left at its
        default (False), get_timeseries_lake() must never even be
        imported/called."""
        svc = _make_service(cfg={})
        with patch("core.persistence.timeseries_db.get_timeseries_lake") as mock_get:
            svc._record_tick_to_lake("NIFTY", self._make_df1m())
            mock_get.assert_not_called()

    def test_enabled_calls_insert_tick_with_latest_price_and_volume(self):
        svc = _make_service(cfg={"timeseries_lake_enabled": True})
        mock_lake = MagicMock()
        with patch("core.persistence.timeseries_db.get_timeseries_lake", return_value=mock_lake) as mock_get:
            svc._record_tick_to_lake("NIFTY", self._make_df1m())
            mock_get.assert_called_once()
            mock_lake.insert_tick.assert_called_once()
            args, kwargs = mock_lake.insert_tick.call_args
            assert args[0] == "NIFTY"
            assert args[1] == 102.5  # latest Close
            assert args[2] == 30  # latest Volume

    def test_enabled_real_tick_actually_recorded(self, tmp_path):
        """End-to-end (no mocking of TimeSeriesDataLake itself): with the
        flag on, a real tick lands in a real DuckDB-backed lake."""
        from core.persistence.timeseries_db import (
            get_timeseries_lake,
            reset_timeseries_lake,
        )
        reset_timeseries_lake()
        db_path = str(tmp_path / "ts.duckdb")
        svc = _make_service(cfg={"timeseries_lake_enabled": True})
        with patch(
            "core.persistence.timeseries_db.get_timeseries_lake",
            side_effect=lambda: get_timeseries_lake(db_path),
        ):
            svc._record_tick_to_lake("NIFTY", self._make_df1m())
        lake = get_timeseries_lake(db_path)
        candles = lake.get_historical_candles("NIFTY", minutes=60)
        assert len(candles) == 1
        assert candles[0]["close"] == 102.5
        reset_timeseries_lake()

    def test_disabled_with_none_frame_is_a_safe_noop(self):
        svc = _make_service(cfg={})
        svc._record_tick_to_lake("NIFTY", None)  # must not raise

    def test_enabled_with_empty_frame_is_a_safe_noop(self):
        import pandas as pd
        svc = _make_service(cfg={"timeseries_lake_enabled": True})
        mock_lake = MagicMock()
        with patch("core.persistence.timeseries_db.get_timeseries_lake", return_value=mock_lake):
            svc._record_tick_to_lake("NIFTY", pd.DataFrame())
            mock_lake.insert_tick.assert_not_called()

    def test_lake_internal_error_is_swallowed(self):
        svc = _make_service(cfg={"timeseries_lake_enabled": True})
        with patch("core.persistence.timeseries_db.get_timeseries_lake", side_effect=ValueError("boom")):
            svc._record_tick_to_lake("NIFTY", self._make_df1m())  # must not raise


# =============================================================================
# EXCEPTION_ALERT_THRESHOLD wiring
# =============================================================================

class TestExceptionAlertThreshold:
    def test_below_threshold_no_alert(self):
        sent = []
        svc = _make_service(cfg={"EXCEPTION_ALERT_THRESHOLD": 3}, send_fn=sent.append)
        for _ in range(2):
            svc._record_exception_and_maybe_alert(ValueError("x"))
        assert sent == []
        assert svc._exception_counts["ValueError"] == 2

    def test_crossing_threshold_fires_alert_once(self):
        sent = []
        svc = _make_service(cfg={"EXCEPTION_ALERT_THRESHOLD": 3}, send_fn=sent.append)
        for _ in range(5):
            svc._record_exception_and_maybe_alert(ValueError("x"))
        assert len(sent) == 1
        assert "ValueError" in sent[0]
        assert "3" in sent[0]  # threshold referenced in the message

    def test_different_exception_types_tracked_independently(self):
        sent = []
        svc = _make_service(cfg={"EXCEPTION_ALERT_THRESHOLD": 2}, send_fn=sent.append)
        svc._record_exception_and_maybe_alert(ValueError("x"))
        svc._record_exception_and_maybe_alert(ValueError("x"))
        svc._record_exception_and_maybe_alert(KeyError("y"))
        assert svc._exception_counts == {"ValueError": 2, "KeyError": 1}
        assert len(sent) == 1  # only ValueError crossed threshold=2

    def test_dashboard_notify_also_called(self):
        sent = []
        dash = []
        svc = _make_service(
            cfg={"EXCEPTION_ALERT_THRESHOLD": 1},
            send_fn=sent.append,
            dashboard_notify_fn=lambda msg, **kw: dash.append((msg, kw)),
        )
        svc._record_exception_and_maybe_alert(ValueError("x"))
        assert len(sent) == 1
        assert len(dash) == 1
        assert dash[0][1].get("severity") == "WARNING"

    def test_day_rollover_resets_counts(self):
        import datetime as _dt

        from core import datetime_ist

        sent = []
        svc = _make_service(cfg={"EXCEPTION_ALERT_THRESHOLD": 3}, send_fn=sent.append)
        svc._record_exception_and_maybe_alert(ValueError("x"))
        svc._record_exception_and_maybe_alert(ValueError("x"))
        assert svc._exception_counts["ValueError"] == 2

        tomorrow = datetime_ist.now_ist() + _dt.timedelta(days=1)
        with patch("core.datetime_ist.now_ist", return_value=tomorrow):
            svc._record_exception_and_maybe_alert(ValueError("x"))
        assert svc._exception_counts["ValueError"] == 1  # reset then incremented

    def test_threshold_zero_disables_alerting(self):
        sent = []
        svc = _make_service(cfg={"EXCEPTION_ALERT_THRESHOLD": 0}, send_fn=sent.append)
        for _ in range(10):
            svc._record_exception_and_maybe_alert(ValueError("x"))
        assert sent == []

    def test_internal_error_does_not_raise(self):
        svc = _make_service(cfg={"EXCEPTION_ALERT_THRESHOLD": "not-an-int"})
        svc._record_exception_and_maybe_alert(ValueError("x"))  # must not raise


# =============================================================================
# run() loop wiring smoke test
# =============================================================================

class TestPeriodicNotificationSchedulingWiring:
    """TG_HEARTBEAT_ENABLED / TG_PERIODIC_SUMMARY_TELEGRAM scheduling, called
    once per cycle from _execute_cycle() via
    _maybe_send_periodic_notifications(). Both default off; see
    core/notification_filters.py for the actual gating logic tested in
    tests/test_notification_filters.py -- this file only proves the
    per-cycle checkpoint wiring itself."""

    def test_disabled_by_default_no_send_fn_calls(self):
        svc = _make_service(cfg={"TG_HEARTBEAT_ENABLED": False, "TG_PERIODIC_SUMMARY_TELEGRAM": False})
        sent = []
        svc._send = sent.append
        svc._maybe_send_periodic_notifications()
        assert sent == []

    def test_no_send_fn_wired_is_a_safe_noop(self):
        svc = _make_service(cfg={"TG_HEARTBEAT_ENABLED": True})
        svc._send = None
        svc._maybe_send_periodic_notifications()  # must not raise

    def test_heartbeat_enabled_sends_via_wired_send_fn(self):
        svc = _make_service(cfg={"TG_HEARTBEAT_ENABLED": True, "TG_HEARTBEAT_INTERVAL": 3600})
        sent = []
        svc._send = sent.append
        svc._maybe_send_periodic_notifications()
        assert len(sent) == 1
        assert "Heartbeat" in sent[0]

    def test_heartbeat_gate_prevents_resend_within_same_service_instance(self):
        svc = _make_service(cfg={"TG_HEARTBEAT_ENABLED": True, "TG_HEARTBEAT_INTERVAL": 3600})
        sent = []
        svc._send = sent.append
        svc._maybe_send_periodic_notifications()
        svc._maybe_send_periodic_notifications()
        assert len(sent) == 1  # second call within the interval is suppressed

    def test_periodic_summary_enabled_sends_via_wired_send_fn(self, tmp_path):
        cfg = {
            "TG_PERIODIC_SUMMARY_TELEGRAM": True,
            "TG_PERIODIC_SUMMARY_INTERVAL_SEC": 3600,
            "DB_PATH": str(tmp_path / "trades.db"),
        }
        svc = _make_service(cfg=cfg)
        sent = []
        svc._send = sent.append
        svc._maybe_send_periodic_notifications()
        assert len(sent) == 1
        assert "summary" in sent[0].lower()

    def test_both_enabled_send_two_messages_in_one_cycle_checkpoint(self, tmp_path):
        cfg = {
            "TG_HEARTBEAT_ENABLED": True,
            "TG_HEARTBEAT_INTERVAL": 3600,
            "TG_PERIODIC_SUMMARY_TELEGRAM": True,
            "TG_PERIODIC_SUMMARY_INTERVAL_SEC": 3600,
            "DB_PATH": str(tmp_path / "trades.db"),
        }
        svc = _make_service(cfg=cfg)
        sent = []
        svc._send = sent.append
        svc._maybe_send_periodic_notifications()
        assert len(sent) == 2

    def test_internal_error_does_not_raise(self):
        svc = _make_service(cfg={"TG_HEARTBEAT_ENABLED": "not-a-bool-but-truthy-string"})
        svc._send = lambda *_a, **_k: (_ for _ in ()).throw(OSError("net down"))
        svc._maybe_send_periodic_notifications()  # must not raise -- fail-open


class TestRunLoopWiring:
    def test_run_invokes_watchdog_tick_and_exception_tracking(self):
        """One iteration of run(): loop_watchdog_tick must run before
        _execute_cycle(), and a raised (ValueError,...) exception from
        _execute_cycle must be counted."""
        shutdown = threading.Event()

        def _boom(idx=None):
            shutdown.set()  # stop after first cycle
            raise ValueError("cycle failed")

        svc = _make_service(
            cfg={"loop_watchdog_enabled": True, "WATCHDOG_TIMEOUT": 0, "EXCEPTION_ALERT_THRESHOLD": 1},
            shutdown_event=shutdown,
        )
        sent = []
        svc._send = sent.append
        svc._market_status = lambda: "OPEN"
        svc._execute_cycle = _boom  # bypass the real pipeline entirely

        svc.run()

        assert svc._exception_counts.get("ValueError") == 1
        # send_fn is called for: start banner, exception alert, shutdown banner
        assert any("stalled" not in m and "ValueError" in m for m in sent)


# =============================================================================
# signal_outcome_tracking_enabled wiring
# =============================================================================

class TestSignalOutcomeTrackingWiring:
    """signal_outcome_tracking_enabled opt-in (default False): grades
    ACTIVE SignalTracker signals against real per-cycle price data via
    _update_signal_outcomes_tick(), called once per cycle from
    _execute_cycle(). Mirrors TestTimeseriesLakeWiring's disabled/enabled/
    error-swallowed shape."""

    def _frames_with_price(self, symbol: str, price: float) -> dict:
        import pandas as pd
        return {symbol: {"df1m": pd.DataFrame({"Close": [price]})}}

    def test_disabled_by_default_tracker_never_touched(self):
        """Regression guard: with signal_outcome_tracking_enabled left at
        its default (False), SignalTracker.get_instance() must never even
        be imported/called."""
        svc = _make_service(cfg={})
        with patch("core.signals.signal_tracker.SignalTracker.get_instance") as mock_get:
            svc._update_signal_outcomes_tick(self._frames_with_price("NIFTY", 100.0))
            mock_get.assert_not_called()

    def test_enabled_calls_update_active_signal_outcomes(self):
        svc = _make_service(cfg={"signal_outcome_tracking_enabled": True})
        mock_tracker = MagicMock()
        with patch("core.signals.signal_tracker.SignalTracker.get_instance", return_value=mock_tracker) as mock_get:
            svc._update_signal_outcomes_tick(self._frames_with_price("NIFTY", 100.0))
            mock_get.assert_called_once()
            mock_tracker.update_active_signal_outcomes.assert_called_once()

    def test_enabled_real_effect_end_to_end(self, tmp_path):
        """End-to-end (no mocking of SignalTracker itself): with the flag
        on, an ACTIVE signal for a symbol this cycle has fresh price data
        for actually gets graded."""
        from core.signals.signal_tracker import SignalTracker
        tracker = SignalTracker.get_instance(db_path=tmp_path / "signals.db")
        conn = tracker._get_conn()
        conn.execute("DELETE FROM system_signals")
        conn.commit()
        conn.close()
        sig_id = tracker.record_generated_signal({
            "symbol": "NIFTY", "direction": "CALL", "price": 100.0,
            "stop_loss": 92.0, "target_1": 130.0, "target_2": 180.0,
        })

        svc = _make_service(cfg={"signal_outcome_tracking_enabled": True})
        svc._update_signal_outcomes_tick(self._frames_with_price("NIFTY", 135.0))

        rows = tracker.get_admin_signal_analytics()["signals"]
        graded = next(r for r in rows if r["signal_id"] == sig_id)
        assert graded["status"] == "TARGET_1_HIT"

    def test_price_lookup_skips_symbols_with_no_frame_data(self):
        svc = _make_service(cfg={"signal_outcome_tracking_enabled": True})
        mock_tracker = MagicMock()
        with patch("core.signals.signal_tracker.SignalTracker.get_instance", return_value=mock_tracker):
            svc._update_signal_outcomes_tick({})  # no frames at all
            price_lookup_fn = mock_tracker.update_active_signal_outcomes.call_args[0][0]
            assert price_lookup_fn("NIFTY") is None

    def test_internal_error_is_swallowed(self):
        svc = _make_service(cfg={"signal_outcome_tracking_enabled": True})
        with patch("core.signals.signal_tracker.SignalTracker.get_instance", side_effect=ValueError("boom")):
            svc._update_signal_outcomes_tick(self._frames_with_price("NIFTY", 100.0))  # must not raise
