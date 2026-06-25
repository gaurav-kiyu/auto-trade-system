"""
Exposure Concentration Limits

Prevents over-concentration in:
- Symbol (single index)
- Expiry (same expiration)
- Direction (CALL vs PUT)
- Strategy (straddle, iron condor, etc.)

Config keys:
- max_exposure_per_symbol_pct: float (default 30.0)
- max_exposure_per_expiry_pct: float (default 50.0)
- max_exposure_per_direction_pct: float (default 80.0)
- max_exposure_per_strategy_pct: float (default 40.0)
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from core.datetime_ist import now_ist

log = logging.getLogger("exposure_limits")


@dataclass
class ExposureSnapshot:
    """Current exposure breakdown."""
    total_value: float = 0.0
    by_symbol: dict[str, float] = field(default_factory=dict)
    by_expiry: dict[str, float] = field(default_factory=dict)
    by_direction: dict[str, float] = field(default_factory=dict)  # CALL/PUT
    by_strategy: dict[str, float] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=now_ist)


@dataclass
class ExposureCheckResult:
    """Result of exposure limit check."""
    allowed: bool
    reason: str = ""
    current_exposure_pct: float = 0.0
    limit_pct: float = 0.0
    suggested_reduction: float = 0.0


class ExposureConcentrationLimiter:
    """
    Enforces exposure concentration limits to prevent single-point failures.
    """

    def __init__(self, config: dict | None = None):
        self._config = config or {}
        self._lock = threading.RLock()

        # Limits (percentages of total capital)
        self._max_per_symbol_pct = self._config.get("max_exposure_per_symbol_pct", 30.0)
        self._max_per_expiry_pct = self._config.get("max_exposure_per_expiry_pct", 50.0)
        self._max_per_direction_pct = self._config.get("max_exposure_per_direction_pct", 80.0)
        self._max_per_strategy_pct = self._config.get("max_exposure_per_strategy_pct", 40.0)

        # Current positions tracked
        self._positions: dict[str, dict[str, Any]] = {}  # symbol -> position data

    def update_position(
        self,
        symbol: str,
        expiry: str,
        direction: str,
        strategy: str,
        value: float
    ) -> None:
        """Update position tracking."""
        with self._lock:
            if value <= 0:
                self._positions.pop(symbol, None)
            else:
                self._positions[symbol] = {
                    "expiry": expiry,
                    "direction": direction,
                    "strategy": strategy,
                    "value": value,
                    "updated_at": now_ist()
                }

    def remove_position(self, symbol: str) -> None:
        """Remove position tracking."""
        with self._lock:
            self._positions.pop(symbol, None)

    def get_exposure_snapshot(self, total_capital: float) -> ExposureSnapshot:
        """Calculate current exposure breakdown."""
        with self._lock:
            snapshot = ExposureSnapshot(total_value=0.0)

            for symbol, pos in self._positions.items():
                value = pos.get("value", 0)
                snapshot.total_value += value

                # By symbol
                snapshot.by_symbol[symbol] = value

                # By expiry
                expiry = pos.get("expiry", "UNKNOWN")
                snapshot.by_expiry[expiry] = snapshot.by_expiry.get(expiry, 0) + value

                # By direction
                direction = pos.get("direction", "UNKNOWN")
                snapshot.by_direction[direction] = snapshot.by_direction.get(direction, 0) + value

                # By strategy
                strategy = pos.get("strategy", "UNKNOWN")
                snapshot.by_strategy[strategy] = snapshot.by_strategy.get(strategy, 0) + value

            return snapshot

    def check_limits(
        self,
        symbol: str,
        expiry: str,
        direction: str,
        strategy: str,
        new_value: float,
        total_capital: float
    ) -> ExposureCheckResult:
        """
        Check if adding new position would breach concentration limits.
        Returns result with details.
        """
        if total_capital <= 0:
            return ExposureCheckResult(allowed=True, reason="No capital")

        with self._lock:
            # Calculate current totals
            current_total = sum(p.get("value", 0) for p in self._positions.values())
            proposed_total = current_total + new_value

            # Check symbol limit
            current_symbol_value = self._positions.get(symbol, {}).get("value", 0)
            proposed_symbol_value = current_symbol_value + new_value
            proposed_symbol_pct = (proposed_symbol_value / total_capital) * 100

            if proposed_symbol_pct > self._max_per_symbol_pct:
                return ExposureCheckResult(
                    allowed=False,
                    reason=f"Symbol exposure {proposed_symbol_pct:.1f}% > {self._max_per_symbol_pct}% limit",
                    current_exposure_pct=proposed_symbol_pct,
                    limit_pct=self._max_per_symbol_pct,
                    suggested_reduction=proposed_symbol_value - (total_capital * self._max_per_symbol_pct / 100)
                )

            # Check expiry limit
            current_expiry_value = sum(
                p.get("value", 0) for p in self._positions.values()
                if p.get("expiry") == expiry
            )
            proposed_expiry_value = current_expiry_value + new_value
            proposed_expiry_pct = (proposed_expiry_value / total_capital) * 100

            if proposed_expiry_pct > self._max_per_expiry_pct:
                return ExposureCheckResult(
                    allowed=False,
                    reason=f"Expiry exposure {proposed_expiry_pct:.1f}% > {self._max_per_expiry_pct}% limit",
                    current_exposure_pct=proposed_expiry_pct,
                    limit_pct=self._max_per_expiry_pct
                )

            # Check direction limit
            current_direction_value = sum(
                p.get("value", 0) for p in self._positions.values()
                if p.get("direction") == direction
            )
            proposed_direction_value = current_direction_value + new_value
            proposed_direction_pct = (proposed_direction_value / total_capital) * 100

            if proposed_direction_pct > self._max_per_direction_pct:
                return ExposureCheckResult(
                    allowed=False,
                    reason=f"Direction exposure {proposed_direction_pct:.1f}% > {self._max_per_direction_pct}% limit",
                    current_exposure_pct=proposed_direction_pct,
                    limit_pct=self._max_per_direction_pct
                )

            # Check strategy limit
            current_strategy_value = sum(
                p.get("value", 0) for p in self._positions.values()
                if p.get("strategy") == strategy
            )
            proposed_strategy_value = current_strategy_value + new_value
            proposed_strategy_pct = (proposed_strategy_value / total_capital) * 100

            if proposed_strategy_pct > self._max_per_strategy_pct:
                return ExposureCheckResult(
                    allowed=False,
                    reason=f"Strategy exposure {proposed_strategy_pct:.1f}% > {self._max_per_strategy_pct}% limit",
                    current_exposure_pct=proposed_strategy_pct,
                    limit_pct=self._max_per_strategy_pct
                )

            return ExposureCheckResult(
                allowed=True,
                reason="All exposure limits OK",
                current_exposure_pct=(proposed_total / total_capital * 100) if total_capital > 0 else 0
            )

    def get_limits_config(self) -> dict:
        """Return current limits configuration."""
        return {
            "max_per_symbol_pct": self._max_per_symbol_pct,
            "max_per_expiry_pct": self._max_per_expiry_pct,
            "max_per_direction_pct": self._max_per_direction_pct,
            "max_per_strategy_pct": self._max_per_strategy_pct,
        }

    def reset(self) -> None:
        """Reset all position tracking (for new day)."""
        with self._lock:
            self._positions.clear()
            log.info("Exposure concentration limits reset")


# Singleton
_exposure_limiter: ExposureConcentrationLimiter | None = None


def get_exposure_limiter(config: dict | None = None) -> ExposureConcentrationLimiter:
    """Get or create singleton exposure limiter."""
    global _exposure_limiter
    if _exposure_limiter is None:
        _exposure_limiter = ExposureConcentrationLimiter(config)
    return _exposure_limiter


__all__ = [
    "ExposureCheckResult",
    "ExposureConcentrationLimiter",
    "ExposureSnapshot",
    "get_exposure_limiter",
    "log",
]

