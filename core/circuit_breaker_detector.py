"""
Circuit Breaker Detector (Phase 1).

Detects NSE market halts and circuit breaker triggers.
Critical for trading during market volatility events.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any

from core.datetime_ist import now_ist

log = logging.getLogger(__name__)


class CircuitBreakerLevel(str, Enum):
    NONE = "NONE"
    LEVEL_1 = "LEVEL_1"
    LEVEL_2 = "LEVEL_2"
    LEVEL_3 = "LEVEL_3"
    MARKET_HALT = "MARKET_HALT"


class MarketStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    PRE_OPEN = "PRE_OPEN"
    POST_CLOSE = "POST_CLOSE"
    HALTED = "HALTED"
    UNKNOWN = "UNKNOWN"


@dataclass
class CircuitBreakerState:
    level: CircuitBreakerLevel
    market_status: MarketStatus
    last_check: datetime
    trigger_price: float | None = None
    current_price: float | None = None
    reference_price: float | None = None
    percent_change: float | None = None


class CircuitBreakerDetector:
    """
    Detects NSE circuit breaker triggers and market halts.

    NSE Circuit Breaker Levels:
    - Level 1: 10% change - 1 hour halt
    - Level 2: 15% change - 2 hour halt
    - Level 3: 20% change - trading halt for rest of day

    Also monitors market status (open/close/halted).
    """

    CB_LEVEL_1_PCT = 10.0
    CB_LEVEL_2_PCT = 15.0
    CB_LEVEL_3_PCT = 20.0
    CHECK_INTERVAL_SECONDS = 30

    NSE_OPEN_HOUR = 9
    NSE_OPEN_MINUTE = 15
    NSE_CLOSE_HOUR = 15
    NSE_CLOSE_MINUTE = 30

    def __init__(
        self,
        price_getter: Callable[[str], float | None] | None = None,
        index_name: str = "NIFTY",
        check_interval: int = CHECK_INTERVAL_SECONDS,
        on_circuit_breaker: Callable[[CircuitBreakerLevel, float], None] | None = None,
    ):
        self._price_getter = price_getter
        self._index_name = index_name
        self._check_interval = check_interval
        self._on_circuit_breaker = on_circuit_breaker
        self._lock = threading.RLock()
        self._state = CircuitBreakerState(
            level=CircuitBreakerLevel.NONE,
            market_status=MarketStatus.UNKNOWN,
            last_check=now_ist(),
        )
        self._reference_price: float | None = None
        self._last_trading_date: datetime | None = None
        self._running = False
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def start(self) -> None:
        """Start background monitoring."""
        if self._running:
            return
        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()
        log.info(f"Circuit breaker monitor started for {self._index_name}")

    def stop(self) -> None:
        """Stop background monitoring."""
        self._running = False
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        log.info("Circuit breaker monitor stopped")

    def set_price_getter(self, getter: Callable[[str], float | None]) -> None:
        """Set or update price getter callback."""
        self._price_getter = getter

    def get_state(self) -> CircuitBreakerState:
        """Get current circuit breaker state."""
        with self._lock:
            return CircuitBreakerState(
                level=self._state.level,
                market_status=self._state.market_status,
                last_check=self._state.last_check,
                trigger_price=self._state.trigger_price,
                current_price=self._state.current_price,
                reference_price=self._reference_price,
                percent_change=self._state.percent_change,
            )

    def check_market_status(self, now: datetime | None = None) -> MarketStatus:
        """Check current market status based on time."""
        if now is None:
            now = now_ist()

        if now.weekday() >= 5:
            return MarketStatus.CLOSED

        market_open = now.replace(
            hour=self.NSE_OPEN_HOUR,
            minute=self.NSE_OPEN_MINUTE,
            second=0,
            microsecond=0,
        )
        market_close = now.replace(
            hour=self.NSE_CLOSE_HOUR,
            minute=self.NSE_CLOSE_MINUTE,
            second=0,
            microsecond=0,
        )

        if now < market_open:
            if (market_open - now).total_seconds() < 900:
                return MarketStatus.PRE_OPEN
            return MarketStatus.CLOSED

        if now >= market_close:
            return MarketStatus.POST_CLOSE

        return MarketStatus.OPEN

    def check_now(self) -> CircuitBreakerState:
        """Perform immediate circuit breaker check."""
        current_price = self._get_current_price()
        market_status = self.check_market_status()

        with self._lock:
            self._state.market_status = market_status
            self._state.last_check = now_ist()
            self._state.current_price = current_price

            if market_status == MarketStatus.HALTED:
                self._state.level = CircuitBreakerLevel.MARKET_HALT
                return self.get_state()

            if market_status != MarketStatus.OPEN:
                self._state.level = CircuitBreakerLevel.NONE
                return self.get_state()

            if current_price is None:
                return self.get_state()

            if self._reference_price is None or self._last_trading_date != now_ist().date():
                self._reference_price = current_price
                self._last_trading_date = now_ist().date()

            if self._reference_price and self._reference_price > 0:
                pct_change = ((current_price - self._reference_price) / self._reference_price) * 100
                self._state.percent_change = pct_change

                if abs(pct_change) >= self.CB_LEVEL_3_PCT:
                    self._state.level = CircuitBreakerLevel.LEVEL_3
                    self._state.trigger_price = current_price
                    self._trigger_callback(CircuitBreakerLevel.LEVEL_3, pct_change)
                elif abs(pct_change) >= self.CB_LEVEL_2_PCT:
                    self._state.level = CircuitBreakerLevel.LEVEL_2
                    self._state.trigger_price = current_price
                    self._trigger_callback(CircuitBreakerLevel.LEVEL_2, pct_change)
                elif abs(pct_change) >= self.CB_LEVEL_1_PCT:
                    self._state.level = CircuitBreakerLevel.LEVEL_1
                    self._state.trigger_price = current_price
                    self._trigger_callback(CircuitBreakerLevel.LEVEL_1, pct_change)
                else:
                    self._state.level = CircuitBreakerLevel.NONE

        return self.get_state()

    def is_trading_allowed(self) -> tuple[bool, str]:
        """Check if trading is currently allowed."""
        state = self.get_state()

        if state.level == CircuitBreakerLevel.MARKET_HALT:
            return False, "Market halted - circuit breaker triggered"

        if state.market_status == MarketStatus.CLOSED:
            return False, "Market closed"

        if state.market_status == MarketStatus.POST_CLOSE:
            return False, "Market post-close"

        if state.level in (CircuitBreakerLevel.LEVEL_2, CircuitBreakerLevel.LEVEL_3):
            pct = state.percent_change or 0
            return False, f"Trading blocked - circuit breaker level {state.level.value} ({pct:.1f}%)"

        return True, "Trading allowed"

    def reset_reference_price(self) -> None:
        """Reset reference price for new trading session."""
        with self._lock:
            self._reference_price = None
            self._last_trading_date = None
            self._state.level = CircuitBreakerLevel.NONE
            self._state.percent_change = None
            log.info("Circuit breaker reference price reset")

    def _get_current_price(self) -> float | None:
        """Get current price from configured getter."""
        if self._price_getter is None:
            return None
        try:
            return self._price_getter(self._index_name)
        except (TypeError, ValueError, OSError, ConnectionError) as e:
            log.warning(f"Failed to get price for {self._index_name}: {e}")
            return None

    def _trigger_callback(self, level: CircuitBreakerLevel, pct_change: float) -> None:
        """Call registered callback on circuit breaker trigger."""
        if self._on_circuit_breaker:
            try:
                self._on_circuit_breaker(level, pct_change)
            except (TypeError, ValueError, OSError) as e:
                log.error(f"Circuit breaker callback failed: {e}")

    def _monitor_loop(self) -> None:
        """Background monitoring loop."""
        while self._running:
            try:
                self.check_now()
            except (OSError, ConnectionError, TimeoutError, ValueError) as e:
                log.error(f"Circuit breaker check failed: {e}")
            if self._stop_event.wait(self._check_interval):
                break


def create_circuit_breaker_detector(
    price_getter: Callable[[str], float | None] | None = None,
    index_name: str = "NIFTY",
    on_trigger: Callable[[CircuitBreakerLevel, float], None] | None = None,
) -> CircuitBreakerDetector:
    """Factory function to create circuit breaker detector."""
    return CircuitBreakerDetector(
        price_getter=price_getter,
        index_name=index_name,
        on_circuit_breaker=on_trigger,
    )


class NseHalts:
    """Static helper for NSE halt detection via broker API."""

    @staticmethod
    def check_halt_status(broker_port: Any) -> tuple[bool, str]:
        """
        Check if NSE is halted via broker API.

        Returns:
            (is_halted, reason)
        """
        if broker_port is None:
            return False, "No broker"

        try:
            if hasattr(broker_port, "get_market_status"):
                status = broker_port.get_market_status("NSE")
                if status and status.get("halted"):
                    return True, status.get("reason", "Market halt")

            if hasattr(broker_port, "is_market_halted"):
                halted = broker_port.is_market_halted()
                if halted:
                    return True, "Market halted"

        except (AttributeError, TypeError, OSError, ConnectionError) as e:
            log.warning(f"Failed to check halt status: {e}")

        return False, ""


__all__ = [
    "CircuitBreakerDetector",
    "CircuitBreakerLevel",
    "CircuitBreakerState",
    "MarketStatus",
    "NseHalts",
    "create_circuit_breaker_detector",
    "log",
]

