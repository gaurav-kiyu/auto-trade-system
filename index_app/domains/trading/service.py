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
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable

_log = logging.getLogger(__name__)


class TradingLoopService:
    """Main trading loop orchestrator.

    Runs a continuous scan → evaluate → enter → monitor → reconcile cycle
    while the shutdown event is not set.
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
    ):
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

    def run(self) -> None:
        """Run the main trading loop until shutdown is signalled."""
        scan_interval = max(5, int(self._cfg.get("SCAN_INTERVAL", 30)))
        _log.info("[TRADING LOOP] Entering main loop (interval=%ds)", scan_interval)
        if self._send:
            self._send("Bot started — entering trading loop")

        invariant_cycle_count = 0
        while not self._shutdown.is_set():
            cycle_start = time.time()

            # Record system heartbeat for stale account detector
            self._record_heartbeat()

            try:
                self._execute_cycle()
            except (ValueError, TypeError, KeyError, AttributeError, IndexError, OSError) as e:
                _log.error("Trading cycle error: %s", e, exc_info=True)

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

    def _execute_cycle(self) -> None:
        """One iteration: check market → fetch data → evaluate signals → monitor → reconcile."""
        mkt_status = self._market_status()
        if mkt_status not in ("OPEN",):
            self._shutdown.wait(60 if mkt_status != "HOLIDAY" else 300)
            return
        if self._is_hard_halted():
            self._shutdown.wait(int(self._cfg.get("SCAN_INTERVAL", 30)))
            return

        # Fetch intraday data with cross-cycle caching
        frames = self._fetch_all_frames()

        # Get VIX
        vix = self._fetch_vix()

        # Record OI snapshots
        self._record_oi_snapshots()

        # Generate signals and enter trades
        self._evaluate_and_enter_trades(frames, vix)

        # Monitor positions and reconcile
        self._monitor_positions()
        self._periodic_reconcile()

    def _fetch_all_frames(self) -> dict[str, dict[str, Any]]:
        """Fetch intraday data for all indices with position-aware caching."""
        frames: dict[str, dict[str, Any]] = {}
        for name in self._index_priority:
            with self._pos_lock:
                has_position = name in self._positions
            df1m, df5m, df15m = self._fetch_intraday_data_cached(name)
            frames[name] = {"df1m": df1m, "df5m": df5m, "df15m": df15m}

            # Feed close data to correlation guard (skip if position exists)
            if not has_position and df1m is not None and len(df1m) > 0:
                if self._update_closes:
                    try:
                        self._update_closes(name, df1m["Close"].to_list())
                    except (ValueError, TypeError, KeyError, AttributeError, IndexError, OSError) as corr_err:
                        _log.debug("Correlation guard feed failed for %s: %s", name, corr_err)
        return frames

    def _record_oi_snapshots(self) -> None:
        """Record OI snapshots (best-effort)."""
        if self._record_oi:
            try:
                self._record_oi(self._index_priority, self._cfg)
            except (ValueError, TypeError, KeyError, AttributeError, IndexError, OSError) as oi_err:
                _log.debug("[OI] Snapshot recording skipped: %s", oi_err)

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
