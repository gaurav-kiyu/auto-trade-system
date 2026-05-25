"""
Trades Persistence Manager.

Handles all operations related to saving and retrieving trade records.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from core.datetime_ist import now_ist
from core.ports.persistence.persistence_port import ConnectionError, ValidationError
from infrastructure.adapters.persistence.sqlite_adapter import SQLiteAdapter


class TradesPersistenceManager:
    def __init__(self, db_path: str):
        self._adapter = SQLiteAdapter(db_path)
        self._initialize_table()

    def _initialize_table(self):
        if not self._adapter.connect():
            raise ConnectionError(f"Failed to connect to trades database: {self._adapter.db_path}")

        if not self._adapter.table_exists('trades'):
            schema = {
                'id': 'INTEGER PRIMARY KEY AUTOINCREMENT',
                'symbol': 'TEXT NOT NULL',
                'direction': 'TEXT NOT NULL',
                'entry_price': 'REAL NOT NULL',
                'exit_price': 'REAL',
                'quantity': 'INTEGER NOT NULL',
                'pnl': 'REAL DEFAULT 0',
                'timestamp': 'TEXT NOT NULL',
                'status': 'TEXT DEFAULT \"OPEN\"',
                'stop_loss': 'REAL',
                'target': 'REAL',
                'strategy_id': 'TEXT',
                'exchange': 'TEXT',
                'product_type': 'TEXT'
            }
            self._adapter.create_table('trades', schema)

    def save_trade(self, trade_data: dict[str, Any]) -> str:
        required_fields = ['symbol', 'direction', 'entry_price', 'quantity']
        for field in required_fields:
            if field not in trade_data:
                raise ValidationError(f"Missing required field: {field}")

        if 'timestamp' not in trade_data:
            trade_data['timestamp'] = now_ist().isoformat()

        return self._adapter.create('trades', trade_data)

    def get_trade(self, trade_id: str) -> dict[str, Any] | None:
        return self._adapter.read('trades', trade_id)

    def get_trades(self, symbol: str | None = None, start_date: datetime | None = None,
                  end_date: datetime | None = None, limit: int | None = None) -> list[dict[str, Any]]:
        filters = {}
        if symbol: filters['symbol'] = symbol
        if start_date: filters['timestamp__gte'] = start_date.isoformat()
        if end_date: filters['timestamp__lte'] = end_date.isoformat()

        return self._adapter.read_many(table='trades', filters=filters, limit=limit, order_by='-timestamp')

    def update_trade(self, trade_id: str, trade_data: dict[str, Any]) -> bool:
        return self._adapter.update('trades', trade_id, trade_data)

    def health_check(self) -> dict[str, Any]:
        return self._adapter.health_check()
