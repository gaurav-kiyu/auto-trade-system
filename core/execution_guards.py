"""
Execution Guards - Pre-trade validation and risk controls

Implements:
- Slippage guard (live vs model price validation)
- Stale data watchdog (quote age validation)
- NaN/invalid price sanitizer
- Trade frequency limiter
- Max consecutive loss breaker
- Time-based risk reduction

All guards are checked before order submission.
"""
from __future__ import annotations

import logging
import threading
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from core.datetime_ist import now_ist

log = logging.getLogger("execution_guards")


@dataclass
class GuardResult:
    """Result of a guard check."""
    passed: bool
    reason: str = ""
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class TradeFrequencyRecord:
    """Tracks trade frequency."""
    timestamp: datetime
    symbol: str
    direction: str
    qty: int
    pnl: float = 0.0  # Realized P&L after trade completes


class ExecutionGuards:
    """
    Pre-trade validation and risk controls.
    Thread-safe for concurrent order submission.
    """

    def __init__(self, config: dict | None = None):
        self._config = config or {}
        self._lock = threading.RLock()

        # Slippage guard config
        self._slippage_threshold_pct = self._config.get("SLIPPAGE_GUARD_THRESHOLD_PCT", 2.0)

        # Stale data config
        self._max_quote_age_seconds = self._config.get("MAX_QUOTE_AGE_SECONDS", 2.0)

        # Trade frequency config
        self._max_trades_per_day = self._config.get("MAX_TRADES_PER_DAY", 10)
        self._min_trade_interval_seconds = self._config.get("MIN_TRADE_INTERVAL_SECONDS", 30)
        self._trade_history: deque[TradeFrequencyRecord] = deque(maxlen=1000)

        # Consecutive loss config
        self._max_consecutive_losses = self._config.get("MAX_CONSECUTIVE_LOSSES", 3)
        self._consecutive_losses = 0
        self._last_trade_time: datetime | None = None

        # Time-based risk reduction config
        self._late_session_threshold = self._config.get("LATE_SESSION_THRESHOLD", "14:30")
        self._late_session_size_mult = self._config.get("LATE_SESSION_SIZE_MULT", 0.5)

        # Price sanitizer config
        self._allow_zero_price = self._config.get("ALLOW_ZERO_PRICE", False)
        self._allow_negative_price = False

        # Callbacks
        self._alert_callback: Callable | None = None

    def set_alert_callback(self, callback: Callable) -> None:
        """Set callback for guard violations."""
        self._alert_callback = callback

    def check_all_guards(
        self,
        symbol: str,
        direction: str,
        model_price: float,
        live_price: float,
        quote_timestamp: datetime | None = None,
        order_qty: int = 1
    ) -> tuple[bool, str, dict[str, Any]]:
        """
        Run all guard checks.
        Returns (all_passed, failure_reason, details_dict).
        """
        with self._lock:
            details = {}

            # 1. Price sanitization
            price_result = self._check_price_sanitizer(symbol, live_price)
            if not price_result.passed:
                return False, price_result.reason, price_result.details

            # 2. Slippage guard
            slippage_result = self._check_slippage_guard(symbol, model_price, live_price)
            if not slippage_result.passed:
                details["slippage_check"] = slippage_result.details
                return False, slippage_result.reason, details

            # 3. Stale data watchdog
            stale_result = self._check_stale_data(symbol, quote_timestamp)
            if not stale_result.passed:
                details["stale_check"] = stale_result.details
                return False, stale_result.reason, details

            # 4. Trade frequency
            freq_result = self._check_trade_frequency(symbol)
            if not freq_result.passed:
                return False, freq_result.reason, details

            # 5. Consecutive losses
            loss_result = self._check_consecutive_losses()
            if not loss_result.passed:
                return False, loss_result.reason, details

            # 6. Time-based risk reduction
            time_result = self._get_time_based_multiplier()
            if time_result < 1.0:
                details["time_multiplier"] = time_result

            return True, "", details

    def _check_price_sanitizer(self, symbol: str, price: float) -> GuardResult:
        """Check for invalid prices (NaN, inf, negative, zero)."""
        import math

        if price is None:
            return GuardResult(False, f"Null price for {symbol}", {"symbol": symbol, "price": None})

        if isinstance(price, float):
            if math.isnan(price):
                return GuardResult(False, f"NaN price for {symbol}", {"symbol": symbol, "price": price})
            if math.isinf(price):
                return GuardResult(False, f"Inf price for {symbol}", {"symbol": symbol, "price": price})

        if price < 0 and not self._allow_negative_price:
            return GuardResult(False, f"Negative price for {symbol}: {price}",
                             {"symbol": symbol, "price": price})

        if price == 0 and not self._allow_zero_price:
            return GuardResult(False, f"Zero price for {symbol}", {"symbol": symbol, "price": price})

        return GuardResult(True, details={"price": price})

    def _check_slippage_guard(self, symbol: str, model_price: float, live_price: float) -> GuardResult:
        """Check if live price deviates too much from model price."""
        if model_price <= 0 or live_price <= 0:
            return GuardResult(True)  # Skip check if either is invalid

        deviation_pct = abs(live_price - model_price) / model_price * 100

        if deviation_pct > self._slippage_threshold_pct:
            reason = f"Slippage guard: {symbol} live={live_price} vs model={model_price} ({deviation_pct:.2f}% > {self._slippage_threshold_pct}%)"
            log.warning(reason)

            if self._alert_callback:
                self._alert_callback(reason)

            return GuardResult(
                False,
                reason,
                {"symbol": symbol, "model_price": model_price, "live_price": live_price,
                 "deviation_pct": deviation_pct, "threshold_pct": self._slippage_threshold_pct}
            )

        return GuardResult(True, details={"deviation_pct": deviation_pct})

    def _check_stale_data(self, symbol: str, quote_timestamp: datetime | None) -> GuardResult:
        """Check if quote data is fresh enough."""
        if quote_timestamp is None:
            # No timestamp provided - assume fresh (backward compatibility)
            return GuardResult(True)

        now = now_ist()
        age_seconds = (now - quote_timestamp).total_seconds()

        if age_seconds > self._max_quote_age_seconds:
            reason = f"Stale quote: {symbol} age={age_seconds:.1f}s > {self._max_quote_age_seconds}s"
            log.warning(reason)

            if self._alert_callback:
                self._alert_callback(reason)

            return GuardResult(
                False,
                reason,
                {"symbol": symbol, "quote_age_seconds": age_seconds,
                 "max_age_seconds": self._max_quote_age_seconds}
            )

        return GuardResult(True, details={"quote_age_seconds": age_seconds})

    def _check_trade_frequency(self, symbol: str) -> GuardResult:
        """Check trade frequency limits."""
        now = now_ist()

        # Check min interval between trades
        if self._last_trade_time is not None:
            interval = (now - self._last_trade_time).total_seconds()
            if interval < self._min_trade_interval_seconds:
                return GuardResult(
                    False,
                    f"Trade frequency: {interval:.0f}s < {self._min_trade_interval_seconds}s min interval",
                    {"seconds_since_last_trade": interval}
                )

        # Count trades today
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        trades_today = sum(1 for r in self._trade_history if r.timestamp >= today_start)

        if trades_today >= self._max_trades_per_day:
            return GuardResult(
                False,
                f"Trade frequency: {trades_today} trades today >= {self._max_trades_per_day} limit",
                {"trades_today": trades_today, "limit": self._max_trades_per_day}
            )

        return GuardResult(True, details={"trades_today": trades_today})

    def _check_consecutive_losses(self) -> GuardResult:
        """Check max consecutive losses limit."""
        if self._consecutive_losses >= self._max_consecutive_losses:
            return GuardResult(
                False,
                f"Consecutive losses: {self._consecutive_losses} >= {self._max_consecutive_losses} limit",
                {"consecutive_losses": self._consecutive_losses, "limit": self._max_consecutive_losses}
            )

        return GuardResult(True, details={"consecutive_losses": self._consecutive_losses})

    def _get_time_based_multiplier(self) -> float:
        """Get position size multiplier based on time of day."""
        try:
            threshold = datetime.strptime(self._late_session_threshold, "%H:%M").time()
            now = now_ist().time()

            if now >= threshold:
                return self._late_session_size_mult
        except Exception:
            pass

        return 1.0

    def record_trade(
        self,
        symbol: str,
        direction: str,
        qty: int,
        pnl: float = 0.0
    ) -> None:
        """Record a trade for frequency tracking."""
        with self._lock:
            record = TradeFrequencyRecord(
                timestamp=now_ist(),
                symbol=symbol,
                direction=direction,
                qty=qty,
                pnl=pnl
            )
            self._trade_history.append(record)
            self._last_trade_time = now_ist()

            # Update consecutive losses
            if pnl < 0:
                self._consecutive_losses += 1
            else:
                self._consecutive_losses = 0

    def record_win(self) -> None:
        """Record a winning trade to reset consecutive loss counter."""
        with self._lock:
            self._consecutive_losses = 0

    def record_loss(self) -> None:
        """Record a losing trade."""
        with self._lock:
            self._consecutive_losses += 1

    def reset_daily(self) -> None:
        """Reset daily counters (call at start of trading day)."""
        with self._lock:
            self._trade_history.clear()
            self._consecutive_losses = 0
            self._last_trade_time = None

    def get_trades_today(self) -> int:
        """Get number of trades today."""
        with self._lock:
            now = now_ist()
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            return sum(1 for r in self._trade_history if r.timestamp >= today_start)

    def health_check(self) -> dict:
        """Return guard status."""
        with self._lock:
            return {
                "consecutive_losses": self._consecutive_losses,
                "max_consecutive_losses": self._max_consecutive_losses,
                "trades_today": self.get_trades_today(),
                "max_trades_per_day": self._max_trades_per_day,
                "late_session_multiplier": self._get_time_based_multiplier(),
            }


# Singleton
_execution_guards: ExecutionGuards | None = None


def get_execution_guards(config: dict | None = None) -> ExecutionGuards:
    """Get or create singleton execution guards."""
    global _execution_guards
    if _execution_guards is None:
        _execution_guards = ExecutionGuards(config)
    return _execution_guards
