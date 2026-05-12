# Broker Adapter Implementation Guide

This document shows how to implement and register broker adapters with the trading platform's dependency injection container.

## 1. BrokerPort Interface

All broker adapters must implement the `BrokerPort` interface defined in `core.ports.broker`:

```python
from core.ports.broker import BrokerPort, Order, OrderResult, Position, Quote, Fill

class MyBrokerAdapter(BrokerPort):
    def connect(self) -> bool:
        # Establish connection to broker
        pass
    
    def disconnect(self) -> None:
        # Close connection to broker
        pass
    
    def place_order(self, order: Order) -> str:
        # Place order and return order ID
        pass
    
    # ... implement all other abstract methods
```

## 2. Example Implementation

See `infrastructure/adapters/brokers/example/adapter.py` for a complete example implementation.

Key aspects of a broker adapter:
- Inherits from `BrokerPort`
- Implements all abstract methods
- Handles connection management
- Converts between broker-specific formats and shared models
- Provides proper error handling
- Supports both paper and live trading modes

## 3. Registering with DI Container

To make your broker adapter available to the trading system, register it with the DI container:

```python
# In your application setup or configuration module
from core.di_container import container
from infrastructure.adapters.brokers.example.adapter import (
    create_example_broker_adapter, ExampleBrokerAdapter
)
from core.ports.broker import BrokerPort

# Option 1: Register factory function (recommended for configurable adapters)
container.register_factory(
    BrokerPort,
    lambda: create_example_broker_adapter({
        'api_key': 'your_api_key',
        'api_secret': 'your_api_secret',
        'access_token': 'your_access_token',
        'paper_trading': True
    })
)

# Option 2: Register class directly (for simple adapters)
# container.register_singleton(BrokerPort, ExampleBrokerAdapter)

# Option 3: Register instance directly
# adapter = ExampleBrokerAdapter(api_key="...", ...)
# container.register_singleton(BrokerPort, type(adapter), adapter)
```

## 4. Configuration Integration

Brokers can be configured through the secure configuration system:

1. Set environment variables with `OPBUYING_*` prefix:
   ```
   OPBUYING_BROKER_API_KEY=your_key
   OPBUYING_BROKER_API_SECRET=your_secret
   OPBUYING_BROKER_ACCESS_TOKEN=your_token
   ```

2. Or use config.local.json (gitignored):
   ```json
   {
     "BROKER_DRIVER": "EXAMPLE",
     "BROKER_CONFIG": {
       "api_key": "your_key",
       "api_secret": "your_secret", 
       "access_token": "your_token"
     }
   }
   ```

3. The system will automatically load these values through `SecureConfig`.

## 5. Usage Example

Once registered, the broker adapter can be used throughout the system:

```python
# In execution services or trading logic
from core.ports.broker import BrokerPort
from core.di_container import container

# Get the broker adapter
broker = container.resolve(BrokerPort)

# Use it to place orders
order = Order(
    symbol="NIFTY26JULFUT",
    direction="BUY",
    quantity=25,
    order_type=OrderType.MARKET
)

order_id = broker.place_order(order)

# Check order status
status = broker.get_order_status(order_id)

# Get positions
positions = broker.get_positions()
```

## 6. Paper Trading vs Live Trading

The example adapter supports both modes:
- Set `paper_trading=True` for simulated trading (no real orders)
- Set `paper_trading=False` for live trading (real orders via broker API)

In live trading mode, you would replace the simulated API calls with actual broker API calls.

## 7. Error Handling and Resilience

Good broker implementations should:
- Handle network failures gracefully
- Implement retry mechanisms with exponential backoff
- Provide meaningful error messages
- Support reconnection logic
- Validate orders before submission
- Handle rate limiting and API restrictions

## 8. Testing Your Adapter

To test your broker adapter:
1. Create unit tests that mock external API calls
2. Test both success and failure scenarios
3. Verify all interface methods work correctly
4. Test with both paper and live trading configurations
5. Ensure thread safety if applicable

## 9. Adding a New Broker to the System

To add support for a new broker:
1. Create a new directory under `infrastructure/adapters/brokers/`
2. Implement the adapter inheriting from `BrokerPort`
3. Add any required dependencies to requirements.txt
4. Document the broker-specific configuration requirements
5. Add the broker to the `BrokerAdapterFactory` if using factory pattern
6. Update documentation and examples

## 10. Important Notes

- All broker adapters must be thread-safe if used in multi-threaded environments
- Never hardcode credentials - always use the secure configuration system
- Implement proper logging for debugging and audit trails
- Consider implementing circuit breaker patterns for external API calls
- Follow the same naming conventions as existing code