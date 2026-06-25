"""
Shadow Mode - Item 16

System computes signals but doesn't trade:
- Compare expected vs live behavior
- Safe way to validate new logic
- A/B testing infrastructure

Excellent for production validation before enabling.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading

from core.db_utils import get_connection
from dataclasses import dataclass, field
from typing import Any

from core.time_provider import time_provider

_log = logging.getLogger(__name__)


@dataclass
class ShadowSignal:
    """Shadow (non-executed) signal"""
    signal_id: str
    timestamp: str
    strategy_name: str
    symbol: str
    direction: str
    quantity: int
    price: float
    score: float
    reason: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ShadowComparison:
    """Comparison between shadow and real signals"""
    comparison_id: str
    timestamp: str
    shadow_signal: ShadowSignal
    real_signal: ShadowSignal | None
    match: bool
    divergence_reason: str


class ShadowModeEngine:
    """
    Shadow mode execution engine.
    Computes signals but doesn't execute, for validation.
    """

    PERSISTENCE_PATH = "shadow_mode.db"

    def __init__(self):
        self._enabled = False
        self._shadow_signals: dict[str, ShadowSignal] = {}
        self._comparisons: list[ShadowComparison] = []
        self._lock = threading.RLock()
        self._stats = {
            "shadow_signals": 0,
            "shadow_trades": 0,
            "comparisons": 0,
            "divergences": 0,
        }
        self._init_durable_storage()

    def _init_durable_storage(self) -> None:
        """Initialize shadow mode storage"""
        try:
            with get_connection(self.PERSISTENCE_PATH) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS shadow_signals (
                        signal_id TEXT PRIMARY KEY,
                        timestamp TEXT,
                        strategy_name TEXT,
                        symbol TEXT,
                        direction TEXT,
                        quantity INTEGER,
                        price REAL,
                        score REAL,
                        reason TEXT,
                        metadata_json TEXT
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS shadow_comparisons (
                        comparison_id TEXT PRIMARY KEY,
                        timestamp TEXT,
                        shadow_signal_json TEXT,
                        real_signal_json TEXT,
                        match INTEGER,
                        divergence_reason TEXT
                    )
                """)
                conn.commit()
            _log.info("ShadowModeEngine: Storage initialized")
        except (sqlite3.Error, OSError) as e:
            _log.error(f"ShadowModeEngine: Failed to init storage: {e}")

    def enable(self) -> None:
        """Enable shadow mode"""
        with self._lock:
            self._enabled = True
            _log.info("Shadow mode ENABLED - signals will be recorded but not executed")

    def disable(self) -> None:
        """Disable shadow mode"""
        with self._lock:
            self._enabled = False
            _log.info("Shadow mode DISABLED - signals will be executed normally")

    def is_enabled(self) -> bool:
        """Check if shadow mode is enabled"""
        return self._enabled

    def record_signal(
        self,
        strategy_name: str,
        symbol: str,
        direction: str,
        quantity: int,
        price: float,
        score: float,
        reason: str,
        metadata: dict = None,
    ) -> ShadowSignal | None:
        """Record a shadow signal"""
        if not self._enabled:
            return None

        signal_id = f"SHADOW-{strategy_name}-{int(time_provider.get_ts())}"

        signal = ShadowSignal(
            signal_id=signal_id,
            timestamp=time_provider.format_ts(),
            strategy_name=strategy_name,
            symbol=symbol,
            direction=direction,
            quantity=quantity,
            price=price,
            score=score,
            reason=reason,
            metadata=metadata or {},
        )

        with self._lock:
            self._shadow_signals[signal_id] = signal
            self._stats["shadow_signals"] += 1

        self._persist_signal(signal)
        _log.debug(f"Recorded shadow signal: {signal_id}")

        return signal

    def should_execute(self) -> bool:
        """Check if real execution should happen"""
        return not self._enabled

    def compare_with_real(
        self,
        shadow_signal: ShadowSignal,
        real_signal: ShadowSignal | None = None,
    ) -> ShadowComparison:
        """Compare shadow signal with real execution"""
        comparison_id = f"COMP-{int(time_provider.get_ts())}"

        match = real_signal is not None
        divergence_reason = ""

        if real_signal:
            if shadow_signal.direction != real_signal.direction:
                divergence_reason = f"Direction mismatch: {shadow_signal.direction} vs {real_signal.direction}"
            elif abs(shadow_signal.price - real_signal.price) / shadow_signal.price > 0.01:
                divergence_reason = f"Price divergence: {shadow_signal.price} vs {real_signal.price}"
            elif shadow_signal.quantity != real_signal.quantity:
                divergence_reason = f"Quantity mismatch: {shadow_signal.quantity} vs {real_signal.quantity}"
        else:
            divergence_reason = "No real signal executed (shadow only)"

        comparison = ShadowComparison(
            comparison_id=comparison_id,
            timestamp=time_provider.format_ts(),
            shadow_signal=shadow_signal,
            real_signal=real_signal,
            match=match,
            divergence_reason=divergence_reason,
        )

        with self._lock:
            self._comparisons.append(comparison)
            self._stats["comparisons"] += 1
            if not match:
                self._stats["divergences"] += 1

        self._persist_comparison(comparison)

        return comparison

    def get_shadow_signals(self, limit: int = 100) -> list[ShadowSignal]:
        """Get recent shadow signals"""
        with self._lock:
            signals = sorted(self._shadow_signals.values(), key=lambda s: s.timestamp, reverse=True)
            return signals[:limit]

    def get_comparisons(self, limit: int = 100) -> list[ShadowComparison]:
        """Get recent comparisons"""
        with self._lock:
            return self._comparisons[-limit:]

    def get_stats(self) -> dict[str, Any]:
        """Get shadow mode stats"""
        with self._lock:
            return {
                "enabled": self._enabled,
                "shadow_signals": self._stats["shadow_signals"],
                "comparisons": self._stats["comparisons"],
                "divergences": self._stats["divergences"],
                "divergence_rate": self._stats["divergences"] / max(1, self._stats["comparisons"]),
            }

    def get_signal_history(self, strategy_name: str = None, limit: int = 100) -> list[dict]:
        """Get signal history from DB"""
        try:
            with get_connection(self.PERSISTENCE_PATH) as conn:
                if strategy_name:
                    cursor = conn.execute("""
                        SELECT signal_id, timestamp, strategy_name, symbol, direction,
                               quantity, price, score, reason, metadata_json
                        FROM shadow_signals
                        WHERE strategy_name = ?
                        ORDER BY timestamp DESC
                        LIMIT ?
                    """, (strategy_name, limit))
                else:
                    cursor = conn.execute("""
                        SELECT signal_id, timestamp, strategy_name, symbol, direction,
                               quantity, price, score, reason, metadata_json
                        FROM shadow_signals
                        ORDER BY timestamp DESC
                        LIMIT ?
                    """, (limit,))

                results = []
                for row in cursor:
                    results.append({
                        "signal_id": row[0],
                        "timestamp": row[1],
                        "strategy_name": row[2],
                        "symbol": row[3],
                        "direction": row[4],
                        "quantity": row[5],
                        "price": row[6],
                        "score": row[7],
                        "reason": row[8],
                        "metadata": json.loads(row[9] or "{}"),
                    })
                return results
        except (sqlite3.Error, OSError, json.JSONDecodeError) as e:
            _log.error(f"Failed to get signal history: {e}")
            return []

    def clear_history(self) -> None:
        """Clear shadow signal history"""
        with self._lock:
            self._shadow_signals.clear()
            self._comparisons.clear()
            _log.info("Shadow mode history cleared")

    def _persist_signal(self, signal: ShadowSignal) -> None:
        """Persist shadow signal"""
        try:
            with get_connection(self.PERSISTENCE_PATH) as conn:
                conn.execute("""
                    INSERT INTO shadow_signals
                    (signal_id, timestamp, strategy_name, symbol, direction, quantity,
                     price, score, reason, metadata_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    signal.signal_id,
                    signal.timestamp,
                    signal.strategy_name,
                    signal.symbol,
                    signal.direction,
                    signal.quantity,
                    signal.price,
                    signal.score,
                    signal.reason,
                    json.dumps(signal.metadata),
                ))
                conn.commit()
        except (sqlite3.Error, OSError, json.JSONDecodeError) as e:
            _log.error(f"Failed to persist shadow signal: {e}")

    def _persist_comparison(self, comparison: ShadowComparison) -> None:
        """Persist comparison"""
        try:
            with get_connection(self.PERSISTENCE_PATH) as conn:
                conn.execute("""
                    INSERT INTO shadow_comparisons
                    (comparison_id, timestamp, shadow_signal_json, real_signal_json, match, divergence_reason)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    comparison.comparison_id,
                    comparison.timestamp,
                    json.dumps(comparison.shadow_signal.__dict__),
                    json.dumps(comparison.real_signal.__dict__) if comparison.real_signal else None,
                    1 if comparison.match else 0,
                    comparison.divergence_reason,
                ))
                conn.commit()
        except (sqlite3.Error, OSError, json.JSONDecodeError) as e:
            _log.error(f"Failed to persist comparison: {e}")


_shadow_engine: ShadowModeEngine | None = None
_engine_lock = threading.RLock()


def get_shadow_engine() -> ShadowModeEngine:
    """Get singleton shadow mode engine"""
    global _shadow_engine
    with _engine_lock:
        if _shadow_engine is None:
            _shadow_engine = ShadowModeEngine()
        return _shadow_engine


__all__ = [
    "ShadowSignal",
    "ShadowComparison",
    "ShadowModeEngine",
    "get_shadow_engine",
]
