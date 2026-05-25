"""
mStock Broker Adapter Stub (BrokerPort).

Placeholder for Mirae Asset mStock API integration.
"""
from __future__ import annotations

import logging
from typing import Any

from core.ports.broker import BrokerPort, Order, Position, Quote

logger = logging.getLogger(__name__)


class MStockBrokerAdapter(BrokerPort):
    """mStock broker adapter stub (not yet implemented)."""

    def __init__(self, config: dict[str, Any]):
        self.config = config
        self._is_connected = False
        raise NotImplementedError("MStockBrokerAdapter is a stub — no implementation yet")

    def connect(self) -> bool:
        raise NotImplementedError

    def disconnect(self) -> None:
        raise NotImplementedError

    def place_order(self, order: Order) -> str:
        raise NotImplementedError

    def cancel_order(self, order_id: str) -> bool:
        raise NotImplementedError

    def modify_order(self, order_id: str, **kwargs) -> bool:
        raise NotImplementedError

    def get_order_status(self, order_id: str) -> str:
        raise NotImplementedError

    def get_positions(self) -> list[Position]:
        raise NotImplementedError

    def get_quote(self, symbol: str) -> Quote:
        raise NotImplementedError

    def subscribe_to_market_data(self, symbols: list[str], callback) -> bool:
        raise NotImplementedError

    def unsubscribe_from_market_data(self, symbol: str) -> bool:
        raise NotImplementedError

    def get_historical_data(self, symbol: str, from_date, to_date, interval="day") -> list[dict]:
        raise NotImplementedError
