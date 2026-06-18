"""WebSocket-based market data adapters - real-time streaming for NSE indices."""

from __future__ import annotations

from infrastructure.adapters.market_data.websocket.nse_index_ws_adapter import (
    NseIndexWebSocketAdapter,
)

__all__ = [
    "NseIndexWebSocketAdapter",
]
