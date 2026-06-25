import logging
from typing import Any

from core.adapters.base_adapter import BrokerAdapter, OrderRequest, OrderResponse, OrderStatus

log = logging.getLogger("broker_gateway")

class BrokerGateway:
    """
    The 'Air Gap' between the Trading Brain and the Broker SDKs.
    Handles routing, failover, and ensures no broker-specific logic
    leaks into the core strategy.
    """

    def __init__(self):
        self._active_adapter: BrokerAdapter | None = None
        self._adapter_registry: dict[str, type[BrokerAdapter]] = {}
        self._current_broker_name: str | None = None

    def register_adapter(self, name: str, adapter_class: type[BrokerAdapter]):
        """Registers a broker adapter class for runtime instantiation."""
        self._adapter_registry[name] = adapter_class
        log.info(f"Broker adapter '{name}' registered.")

    def connect(self, broker_name: str, credentials: dict[str, Any]) -> bool:
        """Instantiates and authenticates the chosen broker."""
        if broker_name not in self._adapter_registry:
            log.error(f"Broker '{broker_name}' is not registered in the gateway.")
            return False

        try:
            adapter_cls = self._adapter_registry[broker_name]
            adapter = adapter_cls()
            if adapter.authenticate(credentials):
                self._active_adapter = adapter
                self._current_broker_name = broker_name
                log.info(f"Successfully connected to broker: {broker_name}")
                return True
        except (ValueError, TypeError, KeyError, AttributeError, OSError, ConnectionError, TimeoutError) as e:
            log.exception(f"Connection failed for broker {broker_name}: {e}")

        return False

    def place_order(self, request: OrderRequest) -> OrderResponse:
        """Routes order request to the active adapter with safety checks."""
        if not self._active_adapter:
            return OrderResponse(
                order_id="NONE",
                status=OrderStatus.FAILED,
                error="No active broker connected"
            )

        try:
            return self._active_adapter.place_order(request)
        except (ValueError, TypeError, OSError, ConnectionError, TimeoutError, AttributeError) as e:
            log.exception(f"Order placement failed via {self._current_broker_name}: {e}")
            return OrderResponse(
                order_id="ERROR",
                status=OrderStatus.FAILED,
                error=str(e)
            )

    def get_ltp(self, symbol: str) -> float:
        """Fetches LTP via the active adapter."""
        if not self._active_adapter:
            return 0.0
        try:
            return self._active_adapter.get_ltp(symbol)
        except Exception as e:
            log.error(f"LTP fetch failed for {symbol}: {e}")
            return 0.0

    def get_positions(self) -> list:
        """Fetches positions via the active adapter."""
        if not self._active_adapter:
            return []
        try:
            return self._active_adapter.get_positions()
        except Exception as e:
            log.error(f"Position fetch failed: {e} (type: {type(e).__name__})")
            return []

    def switch_broker(self, new_broker_name: str, credentials: dict[str, Any]) -> bool:
        """Allows runtime switching of brokers (e.g., for failover)."""
        log.info(f"Switching broker from {self._current_broker_name} to {new_broker_name}...")
        return self.connect(new_broker_name, credentials)

# Singleton instance
broker_gateway = BrokerGateway()


__all__ = [
    "BrokerGateway",
    "broker_gateway",
]
