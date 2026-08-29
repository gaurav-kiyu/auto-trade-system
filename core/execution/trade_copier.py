"""Master Multi-Account Trade Copier & Position Mirroring Engine (v3.0).

Allows a Super Admin or Master Portfolio Manager to execute a master order,
which is automatically replicated and prorated across all connected client broker accounts
based on individual risk multipliers, available margin, and max position limits.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

_log = logging.getLogger("TRADE_COPIER")


@dataclass
class LinkedClientAccount:
    account_id: str
    username: str
    broker_code: str  # zerodha, angelone, upstox, groww, kotakneo, dhan, etc.
    client_name: str
    risk_multiplier: float = 1.0  # 1.0 = 100%, 0.5 = 50%, 2.0 = 200%
    max_capital_per_trade: float = 100000.0  # Max ₹ allocated per trade
    is_active: bool = True
    mode: str = "PAPER"  # PAPER or LIVE


@dataclass
class CopiedOrderExecution:
    execution_id: str
    master_order_id: str
    account_id: str
    username: str
    broker_code: str
    symbol: str
    direction: str  # BUY / SELL
    master_quantity: int
    copied_quantity: int
    executed_price: float
    status: str  # FILLED, REJECTED, MARGIN_EXCEEDED, SIMULATED
    timestamp: float = field(default_factory=time.time)
    error_reason: str = ""


class MasterTradeCopier:
    """Thread-safe Multi-Account Order Mirroring Engine."""

    _instance: MasterTradeCopier | None = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._accounts: dict[str, LinkedClientAccount] = {}
        self._execution_history: list[CopiedOrderExecution] = []
        self._seed_default_accounts()

    @classmethod
    def get_instance(cls) -> MasterTradeCopier:
        with cls._lock:
            if cls._instance is None:
                cls._instance = MasterTradeCopier()
            return cls._instance

    def _seed_default_accounts(self) -> None:
        """Seed sample client accounts for multi-broker management."""
        sample_accounts = [
            LinkedClientAccount("ACC-001", "gaurav_hni", "zerodha", "Gaurav HNI Master", 2.0, 500000.0, True, "PAPER"),
            LinkedClientAccount("ACC-002", "vikram_prop", "angelone", "Vikram Prop Desk", 1.5, 300000.0, True, "PAPER"),
            LinkedClientAccount("ACC-003", "rahul_retail", "upstox", "Rahul Wealth Fund", 1.0, 150000.0, True, "PAPER"),
            LinkedClientAccount("ACC-004", "ananya_options", "dhan", "Ananya Growth Fund", 0.5, 75000.0, True, "PAPER"),
            LinkedClientAccount("ACC-005", "amit_alpha", "fyers", "Amit Quantitative Desk", 1.0, 200000.0, True, "PAPER"),
        ]
        for acc in sample_accounts:
            self._accounts[acc.account_id] = acc

    def get_linked_accounts(self) -> list[dict[str, Any]]:
        # These are seeded sample accounts (_seed_default_accounts) - there is
        # no real broker-account linking flow anywhere in this module. Flag it
        # explicitly rather than let the UI present them as real client accounts.
        return [{**asdict(a), "is_demo_data": True} for a in self._accounts.values()]

    def update_account(self, account_id: str, updates: dict[str, Any]) -> bool:
        with self._lock:
            if account_id in self._accounts:
                acc = self._accounts[account_id]
                for k, v in updates.items():
                    if hasattr(acc, k):
                        setattr(acc, k, v)
                return True
            return False

    def execute_master_order(
        self,
        symbol: str,
        direction: str,  # BUY / SELL
        entry_price: float,
        master_quantity: int = 100,
        order_type: str = "LIMIT",
    ) -> dict[str, Any]:
        """Replicate master order across all active client accounts."""
        with self._lock:
            master_order_id = f"MST-{int(time.time())}-{uuid.uuid4().hex[:4]}"
            child_executions: list[CopiedOrderExecution] = []

            for acc in self._accounts.values():
                if not acc.is_active:
                    continue

                # Calculate prorated position size
                prorated_qty = max(int(master_quantity * acc.risk_multiplier), 1)
                total_order_value = prorated_qty * entry_price

                # Check max capital safety cap
                if total_order_value > acc.max_capital_per_trade:
                    prorated_qty = max(int(acc.max_capital_per_trade / max(entry_price, 1.0)), 1)

                # This module has no real broker linkage at all - it never calls
                # core.adapters.broker_adapters.create_broker_adapter() (the one
                # designated chokepoint for every real order in this project) or
                # any broker SDK. Claiming "FILLED" for acc.mode == "LIVE" here
                # would assert a real fill that never happened. Until a real
                # per-account broker connection is built, every replication is
                # simulated regardless of the account's configured mode.
                exec_status = "SIMULATED"
                exec_id = f"CPY-{master_order_id}-{acc.account_id}"

                record = CopiedOrderExecution(
                    execution_id=exec_id,
                    master_order_id=master_order_id,
                    account_id=acc.account_id,
                    username=acc.username,
                    broker_code=acc.broker_code,
                    symbol=symbol,
                    direction=direction,
                    master_quantity=master_quantity,
                    copied_quantity=prorated_qty,
                    executed_price=entry_price,
                    status=exec_status,
                )
                child_executions.append(record)
                self._execution_history.append(record)

            _log.info("[COPIER] Master order %s executed for %s (%s). Replicated to %d client accounts.",
                      master_order_id, symbol, direction, len(child_executions))

            return {
                "master_order_id": master_order_id,
                "symbol": symbol,
                "direction": direction,
                "entry_price": entry_price,
                "master_quantity": master_quantity,
                "total_replications": len(child_executions),
                "replications": [asdict(e) for e in child_executions],
            }

    def get_execution_history(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            return [asdict(e) for e in reversed(self._execution_history[-limit:])]
