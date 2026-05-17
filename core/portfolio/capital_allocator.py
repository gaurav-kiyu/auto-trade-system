"""
Capital Allocator - Item 12

Dynamic allocation per strategy:
- momentum: 40%
- premium_selling: 35%
- hedge_strategy: 25%

Enables multi-strategy scaling with proper capital management.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
from dataclasses import dataclass
from typing import Any

from core.time_provider import time_provider

_log = logging.getLogger(__name__)


@dataclass
class AllocationRule:
    """Capital allocation rule for a strategy"""
    strategy_name: str
    allocation_pct: float
    min_allocation: float = 0.0
    max_allocation: float = float('inf')
    min_trades: int = 0
    max_trades: int = 100
    enabled: bool = True


@dataclass
class AllocationDecision:
    """Capital allocation decision"""
    strategy_name: str
    allocated_capital: float
    max_position_size: float
    available_margin: float
    timestamp: str


class CapitalAllocator:
    """
    Dynamic capital allocator.
    Manages capital distribution across multiple strategies.
    """

    PERSISTENCE_PATH = "capital_allocator.db"

    def __init__(self, total_capital: float = 1000000.0):
        self._total_capital = total_capital
        self._available_capital = total_capital
        self._rules: dict[str, AllocationRule] = {}
        self._allocated: dict[str, float] = {}
        self._lock = threading.Lock()
        self._init_durable_storage()

    def _init_durable_storage(self) -> None:
        """Initialize allocator storage"""
        try:
            with sqlite3.connect(self.PERSISTENCE_PATH) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS allocation_rules (
                        strategy_name TEXT PRIMARY KEY,
                        allocation_pct REAL,
                        min_allocation REAL,
                        max_allocation REAL,
                        min_trades INTEGER,
                        max_trades INTEGER,
                        enabled INTEGER
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS allocation_log (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT,
                        strategy_name TEXT,
                        allocated_capital REAL,
                        max_position_size REAL,
                        decision_json TEXT
                    )
                """)
                conn.commit()
            _log.info("CapitalAllocator: Storage initialized")
        except Exception as e:
            _log.error(f"CapitalAllocator: Failed to init storage: {e}")

    def set_total_capital(self, capital: float) -> None:
        """Set total capital"""
        with self._lock:
            self._total_capital = capital
            self._available_capital = capital
            _log.info(f"Total capital set to: {capital}")

    def add_rule(self, rule: AllocationRule) -> None:
        """Add allocation rule"""
        with self._lock:
            self._rules[rule.strategy_name] = rule
            self._persist_rule(rule)
            _log.info(f"Added allocation rule: {rule.strategy_name} = {rule.allocation_pct}%")

    def remove_rule(self, strategy_name: str) -> bool:
        """Remove allocation rule"""
        with self._lock:
            if strategy_name in self._rules:
                del self._rules[strategy_name]
                return True
            return False

    def enable_rule(self, strategy_name: str) -> bool:
        """Enable allocation rule"""
        with self._lock:
            if strategy_name in self._rules:
                self._rules[strategy_name].enabled = True
                self._persist_rule(self._rules[strategy_name])
                return True
            return False

    def disable_rule(self, strategy_name: str) -> bool:
        """Disable allocation rule"""
        with self._lock:
            if strategy_name in self._rules:
                self._rules[strategy_name].enabled = False
                self._persist_rule(self._rules[strategy_name])
                return True
            return False

    def get_allocation(self, strategy_name: str) -> AllocationDecision | None:
        """Get capital allocation for strategy"""
        with self._lock:
            rule = self._rules.get(strategy_name)

            if not rule or not rule.enabled:
                return None

            allocated = self._allocated.get(strategy_name, 0)
            available = self._total_capital - sum(self._allocated.values())

            max_position = (self._total_capital * rule.allocation_pct / 100.0) - allocated
            max_position = max(rule.min_allocation, min(max_position, rule.max_allocation))

            if available <= 0:
                max_position = 0

            decision = AllocationDecision(
                strategy_name=strategy_name,
                allocated_capital=allocated,
                max_position_size=max_position,
                available_margin=available,
                timestamp=time_provider.format_ts(),
            )

            self._log_decision(decision)
            return decision

    def allocate(self, strategy_name: str, amount: float) -> bool:
        """Allocate capital to strategy"""
        with self._lock:
            decision = self.get_allocation(strategy_name)

            if not decision or amount > decision.max_position_size:
                _log.warning(f"Allocation denied: {strategy_name} requested {amount}, max {decision.max_position_size if decision else 0}")
                return False

            self._allocated[strategy_name] = self._allocated.get(strategy_name, 0) + amount
            self._available_capital -= amount
            _log.info(f"Allocated {amount} to {strategy_name}")
            return True

    def release(self, strategy_name: str, amount: float) -> bool:
        """Release capital from strategy"""
        with self._lock:
            current = self._allocated.get(strategy_name, 0)
            release_amount = min(amount, current)

            self._allocated[strategy_name] = current - release_amount
            self._available_capital += release_amount
            _log.info(f"Released {release_amount} from {strategy_name}")
            return True

    def get_available_capital(self) -> float:
        """Get available capital"""
        return self._available_capital

    def get_total_allocated(self) -> float:
        """Get total allocated capital"""
        return sum(self._allocated.values())

    def get_allocation_summary(self) -> dict[str, Any]:
        """Get allocation summary"""
        with self._lock:
            return {
                "total_capital": self._total_capital,
                "available_capital": self._available_capital,
                "allocated_capital": sum(self._allocated.values()),
                "by_strategy": self._allocated.copy(),
                "rules": {
                    name: {
                        "allocation_pct": rule.allocation_pct,
                        "enabled": rule.enabled,
                    }
                    for name, rule in self._rules.items()
                },
            }

    def rebalance(self) -> dict[str, float]:
        """Rebalance allocations to match rules"""
        with self._lock:
            new_allocations = {}

            for name, rule in self._rules.items():
                if not rule.enabled:
                    continue

                target = self._total_capital * rule.allocation_pct / 100.0
                new_allocations[name] = max(rule.min_allocation, min(target, rule.max_allocation))

            diff = self._total_capital - sum(new_allocations.values())

            for name in new_allocations:
                new_allocations[name] += diff / len(new_allocations) if new_allocations else 0

            self._allocated = new_allocations
            _log.info(f"Rebalanced allocations: {new_allocations}")
            return new_allocations

    def _persist_rule(self, rule: AllocationRule) -> None:
        """Persist rule to DB"""
        try:
            with sqlite3.connect(self.PERSISTENCE_PATH) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO allocation_rules
                    (strategy_name, allocation_pct, min_allocation, max_allocation, min_trades, max_trades, enabled)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    rule.strategy_name,
                    rule.allocation_pct,
                    rule.min_allocation,
                    rule.max_allocation,
                    rule.min_trades,
                    rule.max_trades,
                    1 if rule.enabled else 0,
                ))
                conn.commit()
        except Exception as e:
            _log.error(f"Failed to persist rule: {e}")

    def _log_decision(self, decision: AllocationDecision) -> None:
        """Log allocation decision"""
        try:
            with sqlite3.connect(self.PERSISTENCE_PATH) as conn:
                conn.execute("""
                    INSERT INTO allocation_log
                    (timestamp, strategy_name, allocated_capital, max_position_size, decision_json)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    decision.timestamp,
                    decision.strategy_name,
                    decision.allocated_capital,
                    decision.max_position_size,
                    json.dumps(decision.__dict__),
                ))
                conn.commit()
        except Exception as e:
            _log.error(f"Failed to log decision: {e}")


_allocator: CapitalAllocator | None = None
_allocator_lock = threading.Lock()


def get_capital_allocator(total_capital: float = 1000000.0) -> CapitalAllocator:
    """Get singleton capital allocator"""
    global _allocator
    with _allocator_lock:
        if _allocator is None:
            _allocator = CapitalAllocator(total_capital)
        return _allocator
