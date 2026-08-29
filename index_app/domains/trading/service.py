"""Trading Loop Service — main trading cycle orchestration.

Extracted from ``index_trader.py`` ``_run_trading_loop()`` to reduce the
monolith and centralise trading-orchestration logic.

The ``TradingLoopService`` encapsulates the main trading loop:
1. Market status check (OPEN/HOLIDAY/CLOSED)
2. Intraday data fetching (with position-aware caching)
3. OI snapshot recording
4. Signal generation + entry gate pipeline (reentry, correlation)
5. Position monitoring + periodic reconciliation
6. Periodic invariant checks
7. Equity signal evaluation + position monitoring
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Any

__all__ = [
    "TradingLoopService",
]

_log = logging.getLogger(__name__)


class TradingLoopService:
    """Main trading loop orchestrator.

    Runs a continuous scan → evaluate → enter → monitor → reconcile cycle
    while the shutdown event is not set. Supports both index options and
    equity cash market trading via the optional equity_trader parameter.
    """

    def __init__(
        self,
        cfg: dict[str, Any],
        shutdown_event: threading.Event,
        is_hard_halted_fn: Callable[[], bool],
        market_status_fn: Callable[[], str],
        fetch_intraday_data_cached_fn: Callable[[str], tuple],
        fetch_vix_fn: Callable[[], float],
        generate_trading_signal_fn: Callable[[str, dict, float], dict],
        enter_trade_fn: Callable[[str, dict], None],
        monitor_positions_fn: Callable[[], None],
        periodic_reconcile_fn: Callable[[], None],
        check_mandate_trade_allowed_fn: Callable[..., tuple[bool, str]],
        check_portfolio_correlation_fn: Callable[..., tuple[bool, str]],
        reentry_trackers: dict[str, Any],
        decision_log: dict[str, Any],
        index_priority: list[str],
        positions: dict[str, Any],
        pos_lock: threading.Lock,
        stale_detector: Any = None,
        update_closes_fn: Callable | None = None,
        record_oi_fn: Callable | None = None,
        check_invariants_fn: Callable | None = None,
        send_fn: Callable | None = None,
        equity_trader: Any = None,
        dashboard_notify_fn: Callable | None = None,
    ):
        """Initialize the trading loop service.

        Args:
            cfg: Configuration dictionary.
            shutdown_event: Event that signals shutdown.
            is_hard_halted_fn: Returns True if hard halt is active.
            market_status_fn: Returns current market status string.
            fetch_intraday_data_cached_fn: Fetches cached intraday data.
            fetch_vix_fn: Fetches current VIX value.
            generate_trading_signal_fn: Generates trading signals.
            enter_trade_fn: Enters a trade for index options.
            monitor_positions_fn: Monitors index option positions.
            periodic_reconcile_fn: Periodic reconciliation.
            check_mandate_trade_allowed_fn: Checks mandate trade allowance.
            check_portfolio_correlation_fn: Checks portfolio correlation.
            reentry_trackers: Reentry tracker dict.
            decision_log: Decision log dict.
            index_priority: Index priority list.
            positions: Positions dict.
            pos_lock: Position lock.
            stale_detector: Optional stale account detector.
            update_closes_fn: Optional close price updater.
            record_oi_fn: Optional OI snapshot recorder.
            check_invariants_fn: Optional invariant checker.
            send_fn: Optional notification function.
            equity_trader: Optional EquityTrader instance (v2.54+).
            dashboard_notify_fn: Optional dashboard notification callback.
        """
        self._cfg = cfg
        self._shutdown = shutdown_event
        self._is_hard_halted = is_hard_halted_fn
        self._market_status = market_status_fn
        self._fetch_intraday_data_cached = fetch_intraday_data_cached_fn
        self._fetch_vix = fetch_vix_fn
        self._generate_trading_signal = generate_trading_signal_fn
        self._enter_trade = enter_trade_fn
        self._monitor_positions = monitor_positions_fn
        self._periodic_reconcile = periodic_reconcile_fn
        self._check_mandate_trade_allowed = check_mandate_trade_allowed_fn
        self._check_portfolio_correlation = check_portfolio_correlation_fn
        self._reentry_trackers = reentry_trackers
        self._decision_log = decision_log
        self._index_priority = index_priority
        self._positions = positions
        self._pos_lock = pos_lock
        self._stale_detector = stale_detector
        self._update_closes = update_closes_fn
        self._record_oi = record_oi_fn
        self._check_invariants = check_invariants_fn
        self._send = send_fn
        self._equity_trader = equity_trader
        self._dashboard_notify = dashboard_notify_fn

        # TG_HEARTBEAT_INTERVAL / TG_PERIODIC_SUMMARY_TELEGRAM scheduling
        # (core.notification_filters) -- both gated off by default; see
        # _maybe_send_periodic_notifications().
        from core.notification_filters import IntervalGate
        self._heartbeat_gate = IntervalGate()
        self._summary_gate = IntervalGate()

        # EXCEPTION_ALERT_THRESHOLD wire-in (previously a documented, dead
        # config key with zero readers). Counts trading-cycle exceptions by
        # type and fires one alert per type once the threshold is crossed,
        # resetting on IST calendar-day rollover. See
        # _record_exception_and_maybe_alert() below.
        self._exception_counts: dict[str, int] = {}
        self._exception_alerted: set[str] = set()
        self._exception_reset_date: str = ""
        self._exc_lock = threading.Lock()

    def run(self) -> None:
        """Run the main trading loop until shutdown is signalled."""
        scan_interval = max(5, int(self._cfg.get("SCAN_INTERVAL", 30)))
        _log.info("[TRADING LOOP] Entering main loop (interval=%ds)", scan_interval)
        if self._send:
            self._send("Bot started — entering trading loop")
        if self._dashboard_notify:
            self._dashboard_notify("Bot started — entering trading loop", severity="INFO", category="system")

        invariant_cycle_count = 0
        while not self._shutdown.is_set():
            cycle_start = time.time()

            # Record system heartbeat for stale account detector
            self._record_heartbeat()

            # loop_watchdog_enabled opt-in (default False): detect-and-alert
            # only, never kills/restarts anything. See core/loop_watchdog.py.
            self._loop_watchdog_tick()

            # config_drift_auto_reload_enabled opt-in (default False): hot-
            # applies a small safe-key allowlist from config.json. See
            # core/config_drift_reloader.py.
            self._config_drift_auto_reload_tick()

            try:
                self._execute_cycle()
            except (ValueError, TypeError, KeyError, AttributeError, IndexError, OSError) as e:
                _log.error("Trading cycle error: %s", e, exc_info=True)
                self._record_exception_and_maybe_alert(e)

            # Periodic invariant check (every 30 cycles)
            invariant_cycle_count += 1
            if invariant_cycle_count >= 30 and self._check_invariants is not None:
                invariant_cycle_count = 0
                try:
                    self._check_invariants()
                except (ValueError, TypeError, KeyError, AttributeError, IndexError, OSError) as inv_err:
                    _log.warning("Invariant check failed: %s", inv_err)

            elapsed = time.time() - cycle_start
            self._shutdown.wait(max(1, scan_interval - elapsed))

        _log.info("[TRADING LOOP] Shutdown signal received")
        if self._send:
            self._send("Bot shutting down")
        if self._dashboard_notify:
            self._dashboard_notify("Bot shutting down", severity="INFO", category="system")

    def execute_cycle(self) -> None:
        """Execute a single trading cycle.  Useful for testing."""
        self._execute_cycle()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _record_heartbeat(self) -> None:
        if self._stale_detector is not None:
            try:
                self._stale_detector.record_heartbeat()
            except (ValueError, TypeError, OSError) as err:
                _log.debug("Stale detector heartbeat failed: %s", err)

    def _loop_watchdog_tick(self) -> None:
        """check() reports on the gap since the previous heartbeat (i.e. the
        just-finished cycle + wait), then heartbeat() resets it for this
        cycle. Fail-open: a bug in this monitoring code must never break
        the trading loop it's attached to."""
        if not self._cfg.get("loop_watchdog_enabled", False):
            return
        try:
            from core.loop_watchdog import get_loop_watchdog
            watchdog = get_loop_watchdog(self._cfg, notify_fn=self._send)
            watchdog.check()
            watchdog.heartbeat()
        except (ValueError, TypeError, KeyError, AttributeError, IndexError, OSError):
            _log.debug("Loop watchdog tick failed", exc_info=True)

    def _config_drift_auto_reload_tick(self) -> None:
        """config key CONFIG_DRIFT_AUTO_RELOAD, opt-in via
        config_drift_auto_reload_enabled (default False). See
        core/config_drift_reloader.py - hot-applies only a small, explicit
        allowlist of non-risk-sensitive keys; everything else is logged as
        restart-required. Fail-open: never lets a bug here affect the loop."""
        if not self._cfg.get("config_drift_auto_reload_enabled", False):
            return
        try:
            from core.config_drift_reloader import get_config_drift_reloader
            get_config_drift_reloader(self._cfg).check()
        except (ValueError, TypeError, KeyError, AttributeError, IndexError, OSError):
            _log.debug("Config drift auto-reload tick failed", exc_info=True)

    def _record_exception_and_maybe_alert(self, exc: Exception) -> None:
        """Count trading-cycle exceptions by type; fire one alert per type
        once EXCEPTION_ALERT_THRESHOLD is crossed. Resets on IST calendar-day
        rollover (no other reset mechanism exists for this counter today).
        Fail-open: never lets a bug here mask the real exception being
        handled by the caller."""
        try:
            from core.datetime_ist import now_ist
            today = now_ist().date().isoformat()
            threshold = int(self._cfg.get("EXCEPTION_ALERT_THRESHOLD", 10))
            if threshold <= 0:
                return
            exc_type = type(exc).__name__
            alert = False
            count = 0
            with self._exc_lock:
                if today != self._exception_reset_date:
                    self._exception_reset_date = today
                    self._exception_counts.clear()
                    self._exception_alerted.clear()
                count = self._exception_counts.get(exc_type, 0) + 1
                self._exception_counts[exc_type] = count
                if count >= threshold and exc_type not in self._exception_alerted:
                    self._exception_alerted.add(exc_type)
                    alert = True
            if alert:
                msg = (
                    f"Exception alert: {exc_type} occurred {count}x in the trading "
                    f"loop today (threshold={threshold})"
                )
                if self._send:
                    self._send(msg)
                if self._dashboard_notify:
                    self._dashboard_notify(msg, severity="WARNING", category="system")
        except (ValueError, TypeError, KeyError, AttributeError, IndexError, OSError):
            _log.debug("Exception-alert-threshold tracking failed", exc_info=True)

    def _maybe_send_periodic_notifications(self) -> None:
        """Heartbeat (TG_HEARTBEAT_ENABLED) + periodic performance summary
        (TG_PERIODIC_SUMMARY_TELEGRAM), both opt-in and off by default. See
        core/notification_filters.py for the scheduling + fail-open logic;
        this is only the per-cycle checkpoint that calls it."""
        if self._send is None:
            return
        try:
            from core.notification_filters import (
                maybe_send_heartbeat,
                maybe_send_periodic_summary,
            )
            maybe_send_heartbeat(self._cfg, self._send, self._heartbeat_gate)
            maybe_send_periodic_summary(self._cfg, self._send, self._summary_gate)
        except (ValueError, TypeError, KeyError, AttributeError, IndexError, OSError):
            _log.debug("Periodic notification scheduling failed", exc_info=True)

    def _execute_cycle(self) -> None:
        """One iteration: check market → fetch data → evaluate signals → monitor → reconcile."""
        mkt_status = self._market_status()
        if mkt_status not in ("OPEN",):
            self._shutdown.wait(60 if mkt_status != "HOLIDAY" else 300)
            return
        if self._is_hard_halted():
            if self._dashboard_notify:
                self._dashboard_notify("Hard halt active — skipping cycle", severity="WARNING", category="risk")
            self._shutdown.wait(int(self._cfg.get("SCAN_INTERVAL", 30)))
            return

        # Fetch intraday data with cross-cycle caching
        frames = self._fetch_all_frames()

        # signal_outcome_tracking_enabled opt-in (default False): grade
        # ACTIVE signals against real price action. See
        # _update_signal_outcomes_tick()'s docstring.
        self._update_signal_outcomes_tick(frames)

        # Get VIX
        vix = self._fetch_vix()

        # Record OI snapshots
        self._record_oi_snapshots()

        # Generate signals and enter index trades
        self._evaluate_and_enter_trades(frames, vix)

        # Evaluate equity signals
        self._evaluate_equity_trades(frames)

        # Monitor positions (index + equity) and reconcile
        self._monitor_positions_with_equity()
        self._periodic_reconcile()

        # TG_HEARTBEAT_INTERVAL / TG_PERIODIC_SUMMARY_TELEGRAM (both opt-in,
        # default off -- see _maybe_send_periodic_notifications()).
        self._maybe_send_periodic_notifications()

    def _fetch_all_frames(self) -> dict[str, dict[str, Any]]:
        """Fetch intraday data for all indices with position-aware caching."""
        frames: dict[str, dict[str, Any]] = {}
        for name in self._index_priority:
            with self._pos_lock:
                has_position = name in self._positions
            df1m, df5m, df15m = self._fetch_intraday_data_cached(name)
            frames[name] = {"df1m": df1m, "df5m": df5m, "df15m": df15m}

            # timeseries_lake_enabled opt-in (default False): record this
            # cycle's latest tick per index. See _record_tick_to_lake().
            self._record_tick_to_lake(name, df1m)

            # Feed close data to correlation guard (skip if position exists)
            if not has_position and df1m is not None and len(df1m) > 0:
                if self._update_closes:
                    try:
                        self._update_closes(name, df1m["Close"].to_list())
                    except (ValueError, TypeError, KeyError, AttributeError, IndexError, OSError) as corr_err:
                        _log.debug("Correlation guard feed failed for %s: %s", name, corr_err)
        return frames

    def _record_tick_to_lake(self, name: str, df1m: Any) -> None:
        """config key timeseries_lake_enabled, opt-in (default False). Records
        the latest per-cycle price/volume tick for `name` into the
        DuckDB-backed TimeSeriesDataLake (core/persistence/timeseries_db.py)
        -- a raw tick-history store distinct from OI snapshots or trade
        journals. Fail-open: a bug in this brand-new analytics recorder must
        never affect the trading loop it's attached to."""
        if not self._cfg.get("timeseries_lake_enabled", False):
            return
        try:
            if df1m is None or len(df1m) == 0:
                return
            price = float(df1m["Close"].iloc[-1])
            volume = int(df1m["Volume"].iloc[-1]) if "Volume" in df1m.columns else 0
            from core.persistence.timeseries_db import get_timeseries_lake
            get_timeseries_lake().insert_tick(name, price, volume, source="trading_loop")
        except (ValueError, TypeError, KeyError, AttributeError, IndexError, OSError):
            _log.debug("Timeseries lake tick recording failed for %s", name, exc_info=True)

    def _update_signal_outcomes_tick(self, frames: dict[str, dict[str, Any]]) -> None:
        """config key signal_outcome_tracking_enabled, opt-in (default False).

        Grades ACTIVE signals recorded in SignalTracker (core/signals/
        signal_tracker.py) against real subsequent price action - closes a
        real gap where record_generated_signal() inserts status="ACTIVE"
        and nothing ever updated it, so signal-accuracy win-rate stayed
        stuck at 0 forever. This is the only track record that can
        accumulate at all while running purely SIGNAL_ONLY (no real fills
        ever land in db/trades.db in that mode) - it is a genuinely
        different, complementary thing to core.live_readiness_checker's
        paper/live trade-count gate, not a replacement for it.

        Only grades symbols this loop has fresh price data for
        (self._index_priority, via `frames`) - signals from the separate
        multi-asset scanner (equities/commodities/etc.) are not graded by
        this tick. Fail-open: a bug here must never affect the trading loop.
        """
        if not self._cfg.get("signal_outcome_tracking_enabled", False):
            return
        try:
            def _price_lookup(symbol: str) -> float | None:
                df1m = frames.get(symbol, {}).get("df1m")
                if df1m is None or len(df1m) == 0:
                    return None
                return float(df1m["Close"].iloc[-1])

            from core.signals.signal_tracker import SignalTracker
            SignalTracker.get_instance().update_active_signal_outcomes(_price_lookup)
        except (ValueError, TypeError, KeyError, AttributeError, IndexError, OSError):
            _log.debug("Signal outcome tracking tick failed", exc_info=True)

    def _record_oi_snapshots(self) -> None:
        """Record OI snapshots (best-effort)."""
        if self._record_oi:
            try:
                self._record_oi(self._index_priority, self._cfg)
            except (ValueError, TypeError, KeyError, AttributeError, IndexError, OSError) as oi_err:
                _log.debug("[OI] Snapshot recording skipped: %s", oi_err)

    def _monitor_positions_with_equity(self) -> None:
        """Monitor index and equity positions."""
        self._monitor_positions()
        if self._equity_trader is not None:
            try:
                self._equity_trader._monitor_positions()
            except (ValueError, TypeError, OSError) as eq_err:
                _log.debug("[EQUITY] Position monitoring failed: %s", eq_err)

    def _evaluate_equity_trades(self, frames: dict[str, dict[str, Any]]) -> None:
        """Evaluate equity signals using EquityTrader."""
        eq = self._equity_trader
        if eq is None:
            return

        try:
            allowed, reason = eq.can_trade()
            if not allowed:
                return

            for symbol in eq.equity_symbols:
                if self._is_hard_halted():
                    break

                # Skip if already have position
                if symbol in eq.positions:
                    continue

                # Get intraday data for signal generation
                df1m, _df5m, _df15m = self._fetch_intraday_data_cached(symbol)
                if df1m is None or len(df1m) < 20:
                    continue

                sig = eq.evaluate_equity_signal(symbol, df1m)
                if sig is None:
                    continue

                score = sig.get("score", 0)
                threshold = int(self._cfg.get("AI_THRESHOLD", 60))
                if score < threshold:
                    continue

                direction = sig.get("direction", "BUY")
                self._decision_log[symbol] = {
                    "msg": f"EQUITY_SIGNAL: {direction} score={score} rsi={sig.get('rsi', '?')}",
                }

                eq.enter_position(symbol, direction, score, reason="signal_pipeline")
        except (ValueError, TypeError, KeyError, AttributeError, IndexError, OSError) as eq_err:
            _log.warning("[EQUITY] Equity evaluation failed: %s", eq_err)

    def _evaluate_and_enter_trades(
        self, frames: dict[str, dict[str, Any]], vix: float
    ) -> None:
        """Evaluate signals for each index and enter qualified trades."""
        for name in self._index_priority:
            if self._is_hard_halted():
                break

            with self._pos_lock:
                if name in self._positions:
                    continue

            df1m = frames.get(name, {}).get("df1m")
            if df1m is None or len(df1m) < 30:
                continue

            sig = self._generate_trading_signal(name, frames.get(name, {}), vix)
            if not sig or sig.get("signal") == "HOLD":
                continue

            score = int(sig.get("score", 0))
            threshold = int(self._cfg.get("AI_THRESHOLD", 60))
            if score < threshold:
                continue

            allowed, reason = self._check_mandate_trade_allowed(
                regime=sig.get("regime", "SIDEWAYS"),
                score=score,
            )
            if not allowed:
                continue

            # Reentry evaluator
            rt = self._reentry_trackers.get(name)
            if rt is not None:
                reentry_dec = rt.evaluate_reentry(
                    current_score=score,
                    current_direction=sig.get("direction", "CALL"),
                    cfg=self._cfg,
                )
                if not reentry_dec.allowed:
                    self._decision_log[name] = {"msg": f"REENTRY_BLOCK: {reentry_dec.reason}"}
                    _log.warning("[REENTRY_BLOCK] %s: %s", name, reentry_dec.reason)
                    continue

            # Correlation guard
            allowed_corr, reason_corr = self._check_portfolio_correlation(
                name, sig.get("direction", "CALL"),
                dict(self._positions) if self._positions else {},
                self._cfg,
            )
            if not allowed_corr:
                self._decision_log[name] = {"msg": f"CORRELATION_BLOCK: {reason_corr}"}
                _log.warning("[CORRELATION_BLOCK] %s: %s", name, reason_corr)
                continue

            self._enter_trade(name, sig)
            if self._dashboard_notify:
                self._dashboard_notify(
                    f"Trade entered: {name} {sig.get('direction', 'CALL')} score={score}",
                    severity="INFO", category="trade",
                    details={"symbol": name, "score": score, "direction": sig.get("direction")},
                )
