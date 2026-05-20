"""
NSE Circuit Breaker Detection (Phase 3).

NSE halts the entire market at 10%, 15%, and 20% index drops.
If open positions exist when market halts, no exit orders can go through.

Detection:
- Monitor index movement
- On halt: pause monitoring loop, Telegram alert, resume on reopening
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from core.datetime_ist import now_ist
from core.safety_state import trip_hard_halt
from core.logging import LoggingService


@dataclass
class CircuitBreakerState:
    """Current circuit breaker status."""
    level: str  # NONE, 10%, 15%, 20%, HALTED
    index_change_pct: float
    last_update: datetime
    is_market_halted: bool


class NSECircuitBreakerMonitor:
    """
    Monitors NSE circuit breakers and alerts on market halts.

    NSE Circuit Breaker Levels:
    - 10% drop: 15 min halt
    - 15% drop: 15 min halt
    - 20% drop: trading suspended for the day

    This monitor checks index levels and detects when market is halted.
    """

    CB_LEVELS = {
        "10%": -10.0,
        "15%": -15.0,
        "20%": -20.0,
    }

    def __init__(
        self,
        send_fn: callable | None = None,
        get_index_price_fn: callable | None = None,
        cfg: dict[str, Any] | None = None,
    ):
        self._send_fn = send_fn or (lambda x: None)
        self._get_index_price = get_index_price_fn or (lambda: None)
        self._cfg = cfg or {}
        self._running = False
        self._thread: threading.Thread | None = None
        self._logger = LoggingService(
            log_dir="logs",
            log_filename_prefix="cb_monitor_",
            retain_days=30,
            json_log_file="",
            version="UNKNOWN",
        )

        self._state = CircuitBreakerState(
            level="NONE",
            index_change_pct=0.0,
            last_update=now_ist(),
            is_market_halted=False,
        )
        self._baseline_price: float | None = None
        self._last_halt_time: datetime | None = None

    def start(self) -> None:
        """Start the circuit breaker monitor."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        self._logger.info("NSE circuit breaker monitor started")

    def stop(self) -> None:
        """Stop the circuit breaker monitor."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        self._logger.info("NSE circuit breaker monitor stopped")

    def get_state(self) -> CircuitBreakerState:
        """Get current circuit breaker state."""
        return self._state

    def _run_loop(self) -> None:
        """Main monitoring loop."""
        while self._running:
            try:
                self._check_circuit_breaker()
                time.sleep(30)  # Check every 30 seconds
            except Exception as e:
                self._logger.error(f"Error in circuit breaker monitor: {e}")
                time.sleep(60)

    def _check_circuit_breaker(self) -> None:
        """Check current circuit breaker level against previous close baseline."""
        try:
            current_price = self._get_index_price()
            if current_price is None:
                return

            # Set baseline from previous close (using first-tick fallback if unavailable)
            if self._baseline_price is None:
                self._baseline_price = current_price
                self._logger.warning(
                    "Circuit breaker baseline set from first intraday tick (prev close unavailable). "
                    "Gap openings will be invisible to circuit breaker until market open baseline is configured."
                )
                return

            # Calculate percentage change from baseline
            change_pct = ((current_price - self._baseline_price) / self._baseline_price) * 100
            self._state.index_change_pct = change_pct
            self._state.last_update = now_ist()

            # Determine circuit breaker level
            new_level = "NONE"
            is_halted = False

            if change_pct <= -20:
                new_level = "20%"
                is_halted = True
                self._handle_market_halt("20%")
            elif change_pct <= -15:
                new_level = "15%"
                is_halted = True
                self._handle_market_halt("15%")
            elif change_pct <= -10:
                new_level = "10%"
                is_halted = True
                self._handle_market_halt("10%")

            self._state.level = new_level
            self._state.is_market_halted = is_halted

            # Log significant changes
            if new_level != "NONE" and new_level != self._state.level:
                self._logger.warning(
                    f"Circuit breaker triggered: {new_level} drop ({change_pct:.2f}%)"
                )

        except Exception as e:
            self._logger.error(f"Error checking circuit breaker: {e}")

    def _handle_market_halt(self, level: str) -> None:
        """Handle market halt event — blocks ALL new entries."""
        self._last_halt_time = now_ist()

        alert = f"""
🚨 NSE CIRCUIT BREAKER TRIGGERED
================================
Level: {level} drop
Time: {self._last_halt_time.strftime('%H:%M:%S')}

⚠️ ALL EXIT ORDERS ARE FROZEN
⚠️ Position monitoring continues
⚠️ Resume trading after market reopens

Check: https://www.nseindia.com/market-data/live-market-indices
"""
        self._send_fn(alert)

        # Trip hard halt — block all new entries until manually cleared
        trip_hard_halt(
            f"NSE circuit breaker triggered: {level} drop at {self._last_halt_time.strftime('%H:%M:%S')}",
            source="NSECircuitBreakerMonitor._handle_market_halt",
        )

    def reset_baseline(self) -> None:
        """Reset baseline price (call at market open)."""
        self._baseline_price = None
        self._state = CircuitBreakerState(
            level="NONE",
            index_change_pct=0.0,
            last_update=now_ist(),
            is_market_halted=False,
        )
        self._logger.info("Circuit breaker baseline reset")


def create_circuit_breaker_monitor(
    send_fn: callable | None = None,
    get_index_price_fn: callable | None = None,
    cfg: dict[str, Any] | None = None,
) -> NSECircuitBreakerMonitor:
    """Create and start the circuit breaker monitor."""
    monitor = NSECircuitBreakerMonitor(
        send_fn=send_fn,
        get_index_price_fn=get_index_price_fn,
        cfg=cfg,
    )
    monitor.start()
    return monitor
