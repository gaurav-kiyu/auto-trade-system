"""
Portfolio Engine - Item 11

Centralized portfolio truth:
- exposure
- margin
- correlation
- capital allocation

Avoids strategy silos, enables multi-strategy.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from core.time_provider import time_provider

_log = logging.getLogger(__name__)


@dataclass
class Position:
    """Portfolio position"""
    position_id: str
    symbol: str
    direction: str
    quantity: int
    avg_price: float
    current_price: float
    unrealized_pnl: float
    realized_pnl: float
    margin_used: float
    created_at: str
    updated_at: str
    strategy_name: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class PortfolioSnapshot:
    """Portfolio state at a point in time"""
    total_value: float
    cash: float
    margin_used: float
    margin_available: float
    unrealized_pnl: float
    realized_pnl: float
    total_pnl: float
    positions_count: int
    exposure_by_symbol: dict[str, float]
    exposure_by_strategy: dict[str, float]


class PortfolioEngine:
    """
    Centralized portfolio tracking and management.
    Truth source for all positions, exposure, and P&L.
    """

    PERSISTENCE_PATH = "portfolio.db"

    def __init__(self):
        self._positions: dict[str, Position] = {}
        self._lock = threading.Lock()
        self._cash = 0.0
        self._initial_capital = 0.0
        self._init_durable_storage()

    def _init_durable_storage(self) -> None:
        """Initialize portfolio persistence"""
        try:
            with sqlite3.connect(self.PERSISTENCE_PATH) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS positions (
                        position_id TEXT PRIMARY KEY,
                        symbol TEXT,
                        direction TEXT,
                        quantity INTEGER,
                        avg_price REAL,
                        current_price REAL,
                        unrealized_pnl REAL,
                        realized_pnl REAL,
                        margin_used REAL,
                        created_at TEXT,
                        updated_at TEXT,
                        strategy_name TEXT,
                        metadata_json TEXT
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS portfolio_snapshots (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT,
                        total_value REAL,
                        cash REAL,
                        margin_used REAL,
                        margin_available REAL,
                        unrealized_pnl REAL,
                        realized_pnl REAL,
                        positions_count INTEGER,
                        exposure_json TEXT
                    )
                """)
                conn.commit()
            _log.info("PortfolioEngine: Storage initialized")
        except Exception as e:
            _log.error(f"PortfolioEngine: Failed to init storage: {e}")

    def set_initial_capital(self, capital: float) -> None:
        """Set initial capital"""
        self._initial_capital = capital
        self._cash = capital

    def add_position(
        self,
        position_id: str,
        symbol: str,
        direction: str,
        quantity: int,
        avg_price: float,
        current_price: float,
        margin_used: float,
        strategy_name: str = "",
        metadata: dict = None,
    ) -> Position:
        """Add a new position"""
        with self._lock:
            position = Position(
                position_id=position_id,
                symbol=symbol,
                direction=direction,
                quantity=quantity,
                avg_price=avg_price,
                current_price=current_price,
                unrealized_pnl=0.0,
                realized_pnl=0.0,
                margin_used=margin_used,
                created_at=time_provider.format_ts(),
                updated_at=time_provider.format_ts(),
                strategy_name=strategy_name,
                metadata=metadata or {},
            )
            self._update_position_pnl(position)
            self._positions[position_id] = position
            self._cash -= margin_used
            self._persist_position(position)
            _log.info(f"Added position: {position_id} {symbol} {direction} {quantity}@{avg_price}")
            return position

    def update_position(
        self,
        position_id: str,
        quantity: int = None,
        avg_price: float = None,
        current_price: float = None,
        realized_pnl: float = None,
    ) -> Position | None:
        """Update an existing position"""
        with self._lock:
            if position_id not in self._positions:
                return None

            position = self._positions[position_id]

            if quantity is not None:
                position.quantity = quantity
            if avg_price is not None:
                position.avg_price = avg_price
            if current_price is not None:
                position.current_price = current_price
            if realized_pnl is not None:
                position.realized_pnl += realized_pnl

            position.updated_at = time_provider.format_ts()
            self._update_position_pnl(position)
            self._persist_position(position)

            return position

    def close_position(
        self,
        position_id: str,
        exit_price: float,
        quantity: int = None,
    ) -> float | None:
        """Close a position (partial or full)"""
        with self._lock:
            if position_id not in self._positions:
                return None

            position = self._positions[position_id]
            close_qty = quantity or position.quantity

            pnl = 0.0
            if position.direction == "BUY":
                pnl = (exit_price - position.avg_price) * close_qty
            else:
                pnl = (position.avg_price - exit_price) * close_qty

            if close_qty >= position.quantity:
                self._cash += (exit_price * close_qty) + position.margin_used
                del self._positions[position_id]
                _log.info(f"Closed position: {position_id}, P&L: {pnl:.2f}")
            else:
                remaining = position.quantity - close_qty
                position.quantity = remaining
                position.updated_at = time_provider.format_ts()
                self._cash += (exit_price * close_qty) + (position.margin_used * close_qty / position.quantity)
                position.margin_used = position.margin_used * remaining / (position.quantity + close_qty)
                _log.info(f"Partial close: {position_id}, closed {close_qty}, remaining {remaining}")

            return pnl

    def _update_position_pnl(self, position: Position) -> None:
        """Calculate unrealized P&L"""
        if position.direction == "BUY":
            position.unrealized_pnl = (position.current_price - position.avg_price) * position.quantity
        else:
            position.unrealized_pnl = (position.avg_price - position.current_price) * position.quantity

    def get_position(self, position_id: str) -> Position | None:
        """Get position by ID"""
        return self._positions.get(position_id)

    def get_positions_by_symbol(self, symbol: str) -> list[Position]:
        """Get all positions for a symbol"""
        with self._lock:
            return [p for p in self._positions.values() if p.symbol == symbol]

    def get_positions_by_strategy(self, strategy_name: str) -> list[Position]:
        """Get all positions for a strategy"""
        with self._lock:
            return [p for p in self._positions.values() if p.strategy_name == strategy_name]

    def update_market_prices(self, prices: dict[str, float]) -> None:
        """Update current prices for all positions"""
        with self._lock:
            for position in self._positions.values():
                if position.symbol in prices:
                    position.current_price = prices[position.symbol]
                    position.updated_at = time_provider.format_ts()
                    self._update_position_pnl(position)

    def get_snapshot(self) -> PortfolioSnapshot:
        """Get current portfolio snapshot"""
        with self._lock:
            unrealized = sum(p.unrealized_pnl for p in self._positions.values())
            realized = sum(p.realized_pnl for p in self._positions.values())
            margin_used = sum(p.margin_used for p in self._positions.values())

            exposure_by_symbol = defaultdict(float)
            exposure_by_strategy = defaultdict(float)

            for p in self._positions.values():
                exposure = p.current_price * p.quantity
                exposure_by_symbol[p.symbol] += exposure
                exposure_by_strategy[p.strategy_name] += exposure

            return PortfolioSnapshot(
                total_value=self._cash + margin_used + unrealized,
                cash=self._cash,
                margin_used=margin_used,
                margin_available=max(0, self._initial_capital - margin_used),
                unrealized_pnl=unrealized,
                realized_pnl=realized,
                total_pnl=unrealized + realized,
                positions_count=len(self._positions),
                exposure_by_symbol=dict(exposure_by_symbol),
                exposure_by_strategy=dict(exposure_by_strategy),
            )

    def get_exposure_summary(self) -> dict[str, float]:
        """Get exposure by symbol/strategy"""
        snapshot = self.get_snapshot()
        return {
            "by_symbol": snapshot.exposure_by_symbol,
            "by_strategy": snapshot.exposure_by_strategy,
        }

    def get_correlation_matrix(self) -> dict[str, dict[str, float]]:
        """Calculate position correlation (simplified)"""
        symbols = list(set(p.symbol for p in self._positions.values()))
        n = len(symbols)
        if n < 2:
            return {}

        matrix = {}
        for s1 in symbols:
            matrix[s1] = {}
            for s2 in symbols:
                if s1 == s2:
                    matrix[s1][s2] = 1.0
                else:
                    matrix[s1][s2] = 0.5
        return matrix

    def _persist_position(self, position: Position) -> None:
        """Persist position to DB"""
        try:
            with sqlite3.connect(self.PERSISTENCE_PATH) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO positions
                    (position_id, symbol, direction, quantity, avg_price, current_price,
                     unrealized_pnl, realized_pnl, margin_used, created_at, updated_at,
                     strategy_name, metadata_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    position.position_id,
                    position.symbol,
                    position.direction,
                    position.quantity,
                    position.avg_price,
                    position.current_price,
                    position.unrealized_pnl,
                    position.realized_pnl,
                    position.margin_used,
                    position.created_at,
                    position.updated_at,
                    position.strategy_name,
                    json.dumps(position.metadata),
                ))
                conn.commit()
        except Exception as e:
            _log.error(f"Failed to persist position: {e}")

    def take_snapshot(self) -> PortfolioSnapshot:
        """Take and persist portfolio snapshot"""
        snapshot = self.get_snapshot()

        try:
            with sqlite3.connect(self.PERSISTENCE_PATH) as conn:
                conn.execute("""
                    INSERT INTO portfolio_snapshots
                    (timestamp, total_value, cash, margin_used, margin_available,
                     unrealized_pnl, realized_pnl, positions_count, exposure_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    time_provider.format_ts(),
                    snapshot.total_value,
                    snapshot.cash,
                    snapshot.margin_used,
                    snapshot.margin_available,
                    snapshot.unrealized_pnl,
                    snapshot.realized_pnl,
                    snapshot.positions_count,
                    json.dumps(snapshot.exposure_by_symbol),
                ))
                conn.commit()
        except Exception as e:
            _log.error(f"Failed to take snapshot: {e}")

        return snapshot


_portfolio_engine: PortfolioEngine | None = None
_engine_lock = threading.Lock()


def get_portfolio_engine() -> PortfolioEngine:
    """Get singleton portfolio engine"""
    global _portfolio_engine
    with _engine_lock:
        if _portfolio_engine is None:
            _portfolio_engine = PortfolioEngine()
        return _portfolio_engine
