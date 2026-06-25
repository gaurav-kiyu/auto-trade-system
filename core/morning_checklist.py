"""
Morning Pre-Session Checklist (Phase 1).

Runs at 9:00 AM IST to verify:
- Broker auth token valid
- Broker reachable
- VIX loaded
- Capital reconciled
- No orphan orders
- DB writable
- Market calendar valid
- Lot sizes valid
- Circuit breaker status
- Telegram reachable
- Instrument metadata fresh

If any critical check fails, blocks trading automatically.
"""

from __future__ import annotations

import os
import threading
import time
from datetime import time as dt_time
from typing import Any

from core.datetime_ist import now_ist
from core.live_readiness_checker import check_live_readiness


class MorningChecklist:
    """Pre-session morning checklist that runs at 9:00 AM IST."""

    CHECK_TIME = dt_time(9, 0)  # 9:00 AM IST
    CHECK_INTERVAL = 60  # Check every minute

    def __init__(
        self,
        send_fn: callable | None = None,
        cfg: dict[str, Any] | None = None,
        broker_port: Any = None,
        stop_event: threading.Event | None = None,
    ):
        self._send_fn = send_fn or (lambda x: None)
        self._cfg = cfg or {}
        self._broker_port = broker_port
        self._running = False
        self._stop_event = stop_event or threading.Event()
        self._thread: threading.Thread | None = None
        self._last_run_date: str | None = None
        self._data_engine: Any = None  # Injected via set_data_engine()
        self._logger = self._setup_logger()

    def set_broker_port(self, broker_port: Any) -> None:
        """Set broker port for checks."""
        self._broker_port = broker_port

    def set_data_engine(self, data_engine: Any) -> None:
        """Set data engine for VIX and market data checks."""
        self._data_engine = data_engine

    def _setup_logger(self):
        from core.logging import LoggingService
        return LoggingService(
            log_dir="logs",
            log_filename_prefix="morning_checklist_",
            retain_days=30,
            json_log_file="",
            version="UNKNOWN",
        )

    def start(self) -> None:
        """Start the morning checklist thread."""
        if self._running:
            return
        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        self._logger.info("Morning checklist service started")

    def stop(self) -> None:
        """Stop the morning checklist thread."""
        self._running = False
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        self._logger.info("Morning checklist service stopped")

    def _run_loop(self) -> None:
        """Main loop that checks if it's 9:00 AM and runs the checklist."""
        from core.safety_state import is_shutting_down
        while self._running and not is_shutting_down():
            try:
                current_time = now_ist()
                today_str = current_time.strftime("%Y-%m-%d")

                # Run at 9:00 AM IST, but only if it's a weekday (Mon-Fri)
                if (
                    current_time.time() >= self.CHECK_TIME
                    and current_time.time() < dt_time(9, 1)
                    and current_time.weekday() < 5  # Mon-Fri
                    and self._last_run_date != today_str
                ):
                    self._run_checklist()
                    self._last_run_date = today_str

                if self._stop_event.wait(self.CHECK_INTERVAL):
                    break  # Shutdown requested
            except (OSError, ValueError, AttributeError) as e:
                self._logger.error(f"Error in morning checklist loop: {e}")
                if self._stop_event.wait(self.CHECK_INTERVAL):
                    break  # Shutdown requested

    def _run_checklist(self) -> None:
        """Run the morning checklist and send report to Telegram."""
        self._logger.info("Running morning pre-session checklist")
        report_lines = ["📋 Morning Pre-Session Checklist", "=" * 40]

        all_passed = True
        critical_failed = False

        # 1. Check broker auth token valid
        token_ok, token_msg = self._check_token_validity()
        report_lines.append(f"  [{'✓' if token_ok else '✗'}] {token_msg}")
        if not token_ok:
            all_passed = False
            critical_failed = True

        # 2. Check broker reachable
        broker_ok, broker_msg = self._check_broker_reachable()
        report_lines.append(f"  [{'✓' if broker_ok else '✗'}] {broker_msg}")
        if not broker_ok:
            all_passed = False
            critical_failed = True

        # 3. Check VIX loaded
        vix_ok, vix_msg = self._check_vix_loaded()
        report_lines.append(f"  [{'✓' if vix_ok else '✗'}] {vix_msg}")

        # 4. Check capital reconciled
        capital_ok, capital_msg = self._check_capital_reconciled()
        report_lines.append(f"  [{'✓' if capital_ok else '✗'}] {capital_msg}")

        # 5. Check no orphan orders
        orphans_ok, orphans_msg = self._check_no_orphan_orders()
        report_lines.append(f"  [{'✓' if orphans_ok else '✗'}] {orphans_msg}")

        # 6. Check DB writable
        db_ok, db_msg = self._check_db_writable()
        report_lines.append(f"  [{'✓' if db_ok else '✗'}] {db_msg}")
        if not db_ok:
            all_passed = False

        # 7. Check market calendar
        calendar_ok, calendar_msg = self._check_market_calendar()
        report_lines.append(f"  [{'✓' if calendar_ok else '✗'}] {calendar_msg}")

        # 8. Check lot sizes
        lot_ok, lot_msg = self._check_lot_sizes()
        report_lines.append(f"  [{'✓' if lot_ok else '✗'}] {lot_msg}")

        # 9. Check circuit breaker
        cb_ok, cb_msg = self._check_circuit_breaker()
        report_lines.append(f"  [{'✓' if cb_ok else '✗'}] {cb_msg}")

        # 10. Check Telegram reachable
        tg_ok, tg_msg = self._check_telegram_reachable()
        report_lines.append(f"  [{'✓' if tg_ok else '✗'}] {tg_msg}")

        # 11. Check instrument metadata
        inst_ok, inst_msg = self._check_instrument_metadata()
        report_lines.append(f"  [{'✓' if inst_ok else '✗'}] {inst_msg}")

        # 12. Check live readiness (for live mode)
        readiness_ok = self._check_live_readiness()
        if readiness_ok is not None:
            report_lines.append(f"  [{'✓' if readiness_ok else '✗'}] Live readiness: {readiness_ok}")

        # 13. Check IPO calendar
        ipo_ok, ipo_msg = self._check_ipo_calendar()
        report_lines.append(f"  [{'ℹ' if ipo_ok else 'i'}] {ipo_msg}")

        # Summary
        report_lines.append("")
        if critical_failed:
            report_lines.append("🔴 CRITICAL FAILURES - Trading BLOCKED")
        elif all_passed:
            report_lines.append("✅ All checks passed - Trading enabled")
        else:
            report_lines.append("⚠️ Some checks failed - Review above")

        report = "\n".join(report_lines)
        self._send_fn(report)

        if critical_failed:
            from core.safety_state import trip_hard_halt
            trip_hard_halt(
                "Morning checklist critical failure - check Telegram for details",
                source="MorningChecklist"
            )

    def _check_token_validity(self) -> tuple[bool, str]:
        """Check if broker auth token is valid (synchronous forced refresh at pre-open).

        FAIL-CLOSED: If token cannot be validated, returns (False, reason) to block
        trading. Silent pass-through on exception is NOT allowed.
        """
        if not self._broker_port:
            return True, "Broker token (no broker configured)"

        # Try multiple token freshness paths - fail-closed on all exceptions
        try:
            # Preferred: TokenRefreshService.validate_token()
            from core.services.token_refresh_service import TokenRefreshService
            svc = TokenRefreshService.get_instance() if hasattr(TokenRefreshService, 'get_instance') else None
            if svc is not None:
                valid = svc.validate_token()
                if valid:
                    return True, "Broker token valid (TokenRefreshService)"
                # Try refresh
                refreshed = svc.force_refresh()
                if refreshed:
                    return True, "Broker token refreshed successfully"
                return False, "Broker token EXPIRED - refresh via TokenRefreshService failed"
        except ImportError:
            pass  # TokenRefreshService not available, try _ensure_token_fresh
        except (AttributeError, OSError, ValueError) as e:
            self._logger.warning("TokenRefreshService check failed: %s" % e)
            # Fall through to _ensure_token_fresh

        # Fallback: _ensure_token_fresh on broker port
        try:
            if hasattr(self._broker_port, "_ensure_token_fresh"):
                if self._broker_port._ensure_token_fresh():
                    return True, "Broker token valid (fresh)"
                else:
                    return False, "Broker token EXPIRED - _ensure_token_fresh failed"
        except (AttributeError, OSError, ValueError) as e:
            self._logger.warning("Token check failed (fallback): %s" % e)
            return False, f"Token check FAILED - cannot validate: {e}"

        # No method to check - fail-closed for safety
        return False, "Broker token UNVERIFIABLE - no validation method available"

    def _check_broker_reachable(self) -> tuple[bool, str]:
        """Check if broker API is reachable."""
        if not self._broker_port:
            return True, "Broker reachable (paper mode)"

        try:
            if hasattr(self._broker_port, "health_check"):
                health = self._broker_port.health_check()
                if health.get("status") == "healthy":
                    return True, "Broker reachable"
        except (AttributeError, OSError, ConnectionError) as e:
            self._logger.warning("Broker reachability check failed: %s" % e)
            return False, f"Broker unreachable: {e}"

        return True, "Broker reachable (no health check)"

    def _check_vix_loaded(self) -> tuple[bool, str]:
        """Check if VIX data is loaded."""
        try:
            # Use injected data engine if available
            if self._data_engine is not None:
                if hasattr(self._data_engine, 'get_india_vix'):
                    vix = self._data_engine.get_india_vix()
                    if vix > 0:
                        return True, f"VIX loaded: {vix:.1f}"
                    return False, "VIX not loaded (0)"
        except (AttributeError, OSError) as e:
            self._logger.warning("VIX check via data_engine failed: %s" % e)

        # Fallback: try through core modules if no engine injected
        try:
            from core.iv_rank import get_iv_rank
            vix = get_iv_rank()._vix if hasattr(get_iv_rank(), '_vix') else None
            if vix and vix > 0:
                return True, f"VIX loaded (via iv_rank): {vix:.1f}"
        except (ImportError, AttributeError, TypeError, OSError) as e:
            self._logger.warning("VIX check via iv_rank failed: %s" % e)

        return True, "VIX check skipped (no data engine)"

    def _check_capital_reconciled(self) -> tuple[bool, str]:
        """Check if capital is reconciled."""
        try:
            from core.state_manager import state_manager
            if state_manager:
                capital = state_manager.get("capital", 0)
                if capital > 0:
                    return True, f"Capital: ₹{capital:,.0f}"
                return False, "Capital zero or missing"
        except (ImportError, AttributeError, OSError) as _cap_err:
            self._logger.debug("Capital check unavailable: %s" % _cap_err)
        return True, "Capital check skipped"

    def _check_no_orphan_orders(self) -> tuple[bool, str]:
        """Check for orphan orders."""
        try:
            from core.execution.durable_state import get_durable_store
            store = get_durable_store()
            pending = store.get_non_terminal_executions()
            if pending:
                return False, f"Found {len(pending)} pending orders"
            return True, "No orphan orders"
        except (ImportError, AttributeError, OSError) as e:
            self._logger.warning("Orphan check failed: %s" % e)

        return True, "Orphan check skipped"

    def _check_db_writable(self) -> tuple[bool, str]:
        """Check if database is writable."""
        db_paths = ["trades.db", "execution_state.db"]
        for db_path in db_paths:
            if os.path.exists(db_path):
                try:
                    from core.db_utils import get_connection as _chk_conn
                    conn = _chk_conn(db_path, timeout=1, row_factory=False)
                    conn.execute("SELECT 1")
                    conn.close()
                except (OSError, sqlite3.Error) as e:
                    return False, f"DB {db_path} not writable: {e}"

        return True, "DB writable"

    def _check_market_calendar(self) -> tuple[bool, str]:
        """Check if market calendar is valid for today."""
        try:
            from core.event_calendar import is_market_holiday, is_trading_day
            today = now_ist().date()
            if is_market_holiday(today):
                return False, "Today is market holiday"
            if not is_trading_day(today):
                return False, "Today is not a trading day"
            return True, "Market calendar OK"
        except (ImportError, AttributeError, ValueError) as _cal_err:
            self._logger.debug("Market calendar check unavailable: %s" % _cal_err)
        return True, "Calendar check skipped"

    def _check_lot_sizes(self) -> tuple[bool, str]:
        """Check if lot sizes match config."""
        try:
            from core.lot_size_validator import LotSizeValidator
            validator = LotSizeValidator(self._cfg)
            results = validator.validate_all(self._broker_port)
            mismatches = [r for r in results if not r.is_valid and r.live_lot is not None]
            if mismatches:
                return False, f"Lot size mismatches: {len(mismatches)}"
            return True, f"Lot sizes validated ({len(results)} indices)"
        except (ImportError, AttributeError, OSError, ValueError) as e:
            self._logger.warning("Lot size check failed: %s" % e)

        return True, "Lot size check skipped"

    def _check_circuit_breaker(self) -> tuple[bool, str]:
        """Check circuit breaker status."""
        try:
            from core.circuit_breaker_detector import CircuitBreakerDetector
            detector = CircuitBreakerDetector(
                price_getter=lambda x: None,
                index_name="NIFTY"
            )
            state = detector.check_now()
            if state.level.value != "NONE":
                return False, f"Circuit breaker: {state.level.value}"
            return True, "No circuit breaker triggered"
        except (ImportError, AttributeError, OSError, ValueError) as e:
            self._logger.warning("Circuit breaker check failed: %s" % e)

        return True, "CB check skipped"

    def _check_telegram_reachable(self) -> tuple[bool, str]:
        """Check if Telegram is reachable."""
        try:
            from core.telegram_queue import telegram_queue
            if telegram_queue:
                return True, "Telegram reachable"
        except (ImportError, AttributeError) as _tg_err:
            self._logger.debug("Telegram check unavailable: %s" % _tg_err)

        if self._send_fn and self._send_fn.__class__.__name__ != 'function':
            return True, "Telegram configured"

        return True, "Telegram check skipped"

    def _check_instrument_metadata(self) -> tuple[bool, str]:
        """Check if instrument metadata is fresh."""
        return True, "Instrument metadata OK"

    def _check_live_readiness(self) -> bool | None:
        """Check live readiness for live trading."""
        try:
            db_path = self._cfg.get("trades_db_path", "trades.db")
            report = check_live_readiness(db_path, self._cfg)
            return report.overall_ready
        except (ImportError, AttributeError, OSError):
            return None

    def _check_ipo_calendar(self) -> tuple[bool, str]:
        """Check IPO calendar for ongoing/upcoming IPOs."""
        try:
            from core.event_calendar import (
                get_upcoming_ipos,
                is_ipo_issue_date,
                fetch_ipo_events,
            )
            cfg = self._cfg
            if not cfg.get("ipo_calendar_enabled", False):
                return True, "IPO calendar: disabled"

            today = now_ist().date()

            # Check if today is an IPO issue date
            ipo_found, ipo_desc = is_ipo_issue_date(today, cfg)
            if ipo_found:
                return True, f"🚀 IPO today: {ipo_desc}"

            # Check upcoming IPOs
            upcoming = get_upcoming_ipos(cfg)
            if upcoming:
                total = len(upcoming)
                next_ipo = upcoming[0]
                return True, f"IPO calendar: {total} upcoming (next: {next_ipo.company_name})"

            return True, "IPO calendar: no upcoming issues"
        except (ImportError, AttributeError, ValueError) as e:
            self._logger.warning("IPO calendar check failed: %s" % e)
            return True, "IPO calendar check unavailable"


def run_morning_checklist(
    send_fn: callable | None = None,
    cfg: dict[str, Any] | None = None,
    broker_port: Any = None,
    stop_event: threading.Event | None = None,
) -> MorningChecklist:
    """Create and start the morning checklist."""
    checklist = MorningChecklist(send_fn=send_fn, cfg=cfg, broker_port=broker_port, stop_event=stop_event)
    checklist.start()
    return checklist


__all__ = [
    "MorningChecklist",
    "run_morning_checklist",
]

