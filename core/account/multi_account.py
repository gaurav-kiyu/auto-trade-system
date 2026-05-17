"""
Multi-Account Architecture - Item 25

Trade across multiple accounts cleanly:
- Account abstraction
- Per-account state
- Cross-account risk
- Account-level reporting

Enables future scaling.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

_log = logging.getLogger(__name__)


class AccountStatus(Enum):
    """Account status"""
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    DISABLED = "DISABLED"
    CLOSED = "CLOSED"


@dataclass
class TradingAccount:
    """Trading account"""
    account_id: str
    name: str
    broker: str
    initial_capital: float
    current_capital: float
    status: AccountStatus
    max_positions: int = 5
    risk_limit: float = 25000.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AccountPosition:
    """Position in an account"""
    position_id: str
    account_id: str
    symbol: str
    direction: str
    quantity: int
    avg_price: float


class MultiAccountManager:
    """
    Multi-account management.
    Handles trading across multiple accounts.
    """

    PERSISTENCE_PATH = "multi_account.db"

    def __init__(self):
        self._accounts: dict[str, TradingAccount] = {}
        self._positions: dict[str, AccountPosition] = {}
        self._lock = threading.Lock()
        self._init_durable_storage()

    def _init_durable_storage(self) -> None:
        """Initialize multi-account storage"""
        try:
            with sqlite3.connect(self.PERSISTENCE_PATH) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS accounts (
                        account_id TEXT PRIMARY KEY,
                        name TEXT,
                        broker TEXT,
                        initial_capital REAL,
                        current_capital REAL,
                        status TEXT,
                        max_positions INTEGER,
                        risk_limit REAL,
                        metadata_json TEXT
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS account_positions (
                        position_id TEXT PRIMARY KEY,
                        account_id TEXT,
                        symbol TEXT,
                        direction TEXT,
                        quantity INTEGER,
                        avg_price REAL
                    )
                """)
                conn.commit()
            _log.info("MultiAccountManager: Storage initialized")
        except Exception as e:
            _log.error(f"MultiAccountManager: Failed to init storage: {e}")

    def create_account(
        self,
        account_id: str,
        name: str,
        broker: str,
        initial_capital: float,
        **kwargs,
    ) -> TradingAccount:
        """Create new trading account"""
        account = TradingAccount(
            account_id=account_id,
            name=name,
            broker=broker,
            initial_capital=initial_capital,
            current_capital=initial_capital,
            status=AccountStatus.ACTIVE,
            **kwargs,
        )

        with self._lock:
            self._accounts[account_id] = account

        self._persist_account(account)
        _log.info(f"Created account: {account_id} ({name})")

        return account

    def get_account(self, account_id: str) -> TradingAccount | None:
        """Get account by ID"""
        return self._accounts.get(account_id)

    def get_all_accounts(self) -> list[TradingAccount]:
        """Get all accounts"""
        return list(self._accounts.values())

    def get_active_accounts(self) -> list[TradingAccount]:
        """Get active accounts"""
        with self._lock:
            return [a for a in self._accounts.values() if a.status == AccountStatus.ACTIVE]

    def update_capital(self, account_id: str, capital: float) -> bool:
        """Update account capital"""
        with self._lock:
            if account_id in self._accounts:
                self._accounts[account_id].current_capital = capital
                self._persist_account(self._accounts[account_id])
                return True
        return False

    def pause_account(self, account_id: str) -> bool:
        """Pause account trading"""
        with self._lock:
            if account_id in self._accounts:
                self._accounts[account_id].status = AccountStatus.PAUSED
                self._persist_account(self._accounts[account_id])
                return True
        return False

    def resume_account(self, account_id: str) -> bool:
        """Resume account trading"""
        with self._lock:
            if account_id in self._accounts:
                self._accounts[account_id].status = AccountStatus.ACTIVE
                self._persist_account(self._accounts[account_id])
                return True
        return False

    def can_trade(self, account_id: str, required_capital: float) -> bool:
        """Check if account can trade"""
        account = self.get_account(account_id)
        if not account or account.status != AccountStatus.ACTIVE:
            return False

        return account.current_capital >= required_capital

    def get_total_exposure(self) -> float:
        """Get total exposure across all accounts"""
        with self._lock:
            return sum(a.current_capital for a in self._accounts.values())

    def get_account_summary(self) -> dict[str, Any]:
        """Get summary of all accounts"""
        active = self.get_active_accounts()
        return {
            "total_accounts": len(self._accounts),
            "active_accounts": len(active),
            "total_capital": sum(a.current_capital for a in active),
            "accounts": {
                a.account_id: {
                    "name": a.name,
                    "capital": a.current_capital,
                    "status": a.status.value,
                }
                for a in self._accounts.values()
            },
        }

    def _persist_account(self, account: TradingAccount) -> None:
        """Persist account to DB"""
        try:
            with sqlite3.connect(self.PERSISTENCE_PATH) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO accounts
                    (account_id, name, broker, initial_capital, current_capital, status,
                     max_positions, risk_limit, metadata_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    account.account_id,
                    account.name,
                    account.broker,
                    account.initial_capital,
                    account.current_capital,
                    account.status.value,
                    account.max_positions,
                    account.risk_limit,
                    json.dumps(account.metadata),
                ))
                conn.commit()
        except Exception as e:
            _log.error(f"Failed to persist account: {e}")


_account_manager: MultiAccountManager | None = None
_manager_lock = threading.Lock()


def get_multi_account_manager() -> MultiAccountManager:
    """Get singleton multi-account manager"""
    global _account_manager
    with _manager_lock:
        if _account_manager is None:
            _account_manager = MultiAccountManager()
        return _account_manager
