"""
Paper Trading Broker Adapter

This adapter implements the BrokerPort interface for paper/simulated trading.
It allows testing trading strategies without risking real capital.
"""

from __future__ import annotations

import random
import threading
import time
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from core.datetime_ist import now_ist

# Import the broker port interface this adapter implements
from core.ports.broker import BrokerPort, Fill, Order, OrderResult, Position, Quote

# Import market data port for getting real/simulated prices
# In a real implementation, this would be injected
try:
    from core.ports.market_data import MarketDataPort
except ImportError:
    # Placeholder for type hinting
    MarketDataPort = Any


class PaperBrokerAdapter(BrokerPort):
    """
    Paper trading broker adapter implementation.

    This adapter simulates broker functionality for testing and development.
    It maintains internal state for positions, orders, and uses either
    provided market data or simulated prices for execution.
    """

    def __init__(self,
                 initial_capital: float = 100000.0,
                 market_data_port: MarketDataPort | None = None,
                 simulate_latency: bool = True,
                 latency_range_ms: tuple = (50, 200),
                 fill_probability: float = 0.95,
                 slippage_model: str = "linear",
                 commission_per_trade: float = 0.0):
        """
        Initialize the paper trading broker adapter.

        Args:
            initial_capital: Starting capital for the paper account
            market_data_port: Optional market data provider for real prices
            simulate_latency: Whether to simulate network latency
            latency_range_ms: Range of latency to simulate in milliseconds
            fill_probability: Probability that an order gets filled (0-1)
            slippage_model: Model for slippage ("linear", "volatility_based", "fixed")
            commission_per_trade: Commission charged per trade
        """
        self._initial_capital = initial_capital
        self._market_data_port = market_data_port
        self._simulate_latency = simulate_latency
        self._latency_range_ms = latency_range_ms
        self._fill_probability = fill_probability
        self._slippage_model = slippage_model
        self._commission_per_trade = commission_per_trade

        # Internal state
        self._positions: dict[str, Position] = {}
        self._orders: dict[str, Order] = {}
        self._order_results: dict[str, OrderResult] = {}
        self._fills: list[Fill] = []
        self._cash = initial_capital
        self._margin_used = 0.0
        self._order_counter = 0

        # Thread safety
        self._lock = threading.RLock()

        # Symbol to instrument info cache (would come from market data in reality)
        self._symbol_info: dict[str, dict[str, Any]] = {}

    def _simulate_network_latency(self):
        """Simulate network latency if enabled."""
        if self._simulate_latency:
            min_lat, max_lat = self._latency_range_ms
            latency_ms = random.uniform(min_lat, max_lat)
            time.sleep(latency_ms / 1000.0)

    def _generate_order_id(self) -> str:
        """Generate a unique order ID."""
        with self._lock:
            self._order_counter += 1
            return f"PAPER_{self._order_counter:08d}_{int(time.time())}"

    def _get_current_price(self, symbol: str) -> float | None:
        """
        Get current price for a symbol.

        Uses market data port if available, otherwise falls back to simulated price.
        """
        if self._market_data_port:
            try:
                quote = self._market_data_port.get_quote(symbol)
                if quote:
                    return quote.last
            except Exception:
                pass  # Fall back to simulated price

        # Fall back to simulated price
        # In reality, this would use a proper price simulation model
        base_price = self._symbol_info.get(symbol, {}).get('base_price', 100.0)
        volatility = self._symbol_info.get(symbol, {}).get('volatility', 0.02)
        # Random walk simulation
        price_change = random.gauss(0, volatility) * base_price
        return base_price + price_change

    def _calculate_slippage(self, symbol: str, quantity: int,
                          is_buy: bool, market_price: float) -> float:
        """
        Calculate slippage for an order.

        Args:
            symbol: Trading symbol
            quantity: Order quantity
            is_buy: True for buy order, False for sell
            market_price: Current market price

        Returns:
            Slippage amount (positive means worse price for trader)
        """
        if self._slippage_model == "fixed":
            return 0.01  # Fixed 1 penny slippage
        elif self._slippage_model == "linear":
            # Slippage increases with order size
            size_factor = min(abs(quantity) / 1000.0, 0.05)  # Cap at 5%
            return market_price * size_factor * (0.01 if is_buy else -0.01)
        elif self._slippage_model == "volatility_based":
            # Slippage based on volatility and volume
            volatility = self._symbol_info.get(symbol, {}).get('volatility', 0.02)
            volume_factor = min(abs(quantity) / 10000.0, 0.1)  # Normalize by typical volume
            return market_price * volatility * volume_factor * (0.005 if is_buy else -0.005)
        else:
            return 0.0

    def _should_fill_order(self) -> bool:
        """Determine if an order should be filled based on fill probability."""
        return random.random() < self._fill_probability

    def connect(self) -> bool:
        """
        Establish connection to the paper broker.

        Returns:
            Always True for paper broker (no real connection needed)
        """
        self._simulate_network_latency()
        return True

    def disconnect(self) -> None:
        """Close connection to the paper broker."""
        # No cleanup needed for paper broker
        pass

    def place_order(self, order: Order) -> str:
        """
        Place an order with the paper broker.

        Args:
            order: Order object containing order details

        Returns:
            Order ID from the paper broker

        Raises:
            Exception: If order placement fails
        """
        self._simulate_network_latency()

        try:
            with self._lock:
                # Validate order
                if order.quantity <= 0:
                    raise ValueError("Order quantity must be positive")

                if order.direction not in ["BUY", "SELL"]:
                    raise ValueError("Order direction must be BUY or SELL")

                # Generate order ID
                order_id = self._generate_order_id()
                order.order_id = order_id  # Set the order ID on the order object

                # Store the order
                self._orders[order_id] = order

                # Attempt to fill the order immediately (or simulate delay)
                if self._should_fill_order():
                    self._process_order_fill(order_id)
                else:
                    # Order remains open
                    pass

                return order_id

        except Exception as e:
            raise Exception(f"Failed to place order: {str(e)}") from e

    def _process_order_fill(self, order_id: str):
        """Process the filling of an order."""
        order = self._orders[order_id]
        symbol = order.symbol
        quantity = order.quantity
        is_buy = order.direction == "BUY"

        # Get current market price
        market_price = self._get_current_price(symbol)
        if market_price is None:
            # If we can't get a price, we can't fill the order
            return

        # Calculate slippage
        slippage = self._calculate_slippage(symbol, quantity, is_buy, market_price)

        # Calculate fill price
        if is_buy:
            fill_price = market_price + slippage  # Pay more for buys
        else:
            fill_price = market_price - slippage  # Receive less for sells

        # Calculate commission
        commission = self._commission_per_trade

        # Calculate total cost
        total_cost = (fill_price * quantity) + commission

        # Check if we have sufficient cash (for buys) or position (for sells)
        if is_buy and total_cost > self._cash:
            # Insufficient funds - reject order
            self._reject_order(order_id, "Insufficient funds")
            return

        if not is_buy:
            # Check if we have sufficient position to sell
            current_position = self._positions.get(symbol)
            if not current_position or current_position.quantity < quantity:
                # Insufficient position - reject order
                self._reject_order(order_id, "Insufficient position")
                return

        # Create the fill
        fill = Fill(
            order_id=order_id,
            symbol=symbol,
            quantity=quantity,
            price=fill_price,
            timestamp=now_ist(),
            commission=commission
        )

        # Update internal state
        self._fills.append(fill)

        # Update cash
        if is_buy:
            self._cash -= total_cost
        else:
            self._cash += (fill_price * quantity) - commission

        # Update position
        self._update_position_from_fill(fill)

        # Create order result
        order_result = OrderResult(
            order_id=order_id,
            status="FILLED",
            filled_quantity=quantity,
            average_price=fill_price,
            commission=commission,
            timestamp=now_ist()
        )
        self._order_results[order_id] = order_result

        # Remove from open orders
        del self._orders[order_id]

    def _reject_order(self, order_id: str, reason: str):
        """Reject an order."""
        order = self._orders[order_id]
        order_result = OrderResult(
            order_id=order_id,
            status="REJECTED",
            filled_quantity=0,
            average_price=0.0,
            commission=0.0,
            timestamp=now_ist(),
            reject_reason=reason
        )
        self._order_results[order_id] = order_result
        del self._orders[order_id]

    def _update_position_from_fill(self, fill: Fill):
        """Update position based on a fill."""
        symbol = fill.symbol
        quantity = fill.quantity if fill.direction == "BUY" else -fill.quantity
        price = fill.price

        # Get existing position or create new one
        existing_position = self._positions.get(symbol)
        if existing_position is None:
            # New position
            new_position = Position(
                symbol=symbol,
                quantity=quantity,
                average_price=price,
                market_value=quantity * price,
                unrealized_pnl=0.0,
                realized_pnl=0.0,
                timestamp=fill.timestamp
            )
            self._positions[symbol] = new_position
        else:
            # Update existing position
            old_quantity = existing_position.quantity
            old_avg_price = existing_position.average_price
            new_quantity = old_quantity + quantity

            if new_quantity == 0:
                # Position closed
                realized_pnl = (price - old_avg_price) * old_quantity
                closed_position = Position(
                    symbol=symbol,
                    quantity=0,
                    average_price=0.0,
                    market_value=0.0,
                    unrealized_pnl=0.0,
                    realized_pnl=existing_position.realized_pnl + realized_pnl,
                    timestamp=fill.timestamp
                )
                self._positions[symbol] = closed_position
                # Note: In a real system, we'd move this to trade history
            else:
                # Position still open
                if old_quantity * quantity > 0:
                    # Same direction - weighted average price
                    total_cost = (old_quantity * old_avg_price) + (quantity * price)
                    new_avg_price = total_cost / new_quantity
                else:
                    # Opposite direction - this is a partial or full close
                    # For simplicity, we'll keep the original average price
                    # A more sophisticated implementation would layer prices
                    new_avg_price = old_avg_price

                updated_position = Position(
                    symbol=symbol,
                    quantity=new_quantity,
                    average_price=new_avg_price,
                    market_value=new_quantity * price,
                    unrealized_pnl=0.0,  # Would be calculated based on current price
                    realized_pnl=existing_position.realized_pnl,
                    timestamp=fill.timestamp
                )
                self._positions[symbol] = updated_position

    def cancel_order(self, order_id: str) -> bool:
        """
        Cancel an existing order.

        Args:
            order_id: ID of the order to cancel

        Returns:
            True if cancellation successful, False otherwise
        """
        self._simulate_network_latency()

        with self._lock:
            if order_id in self._orders:
                # Remove from open orders
                del self._orders[order_id]
                # Create cancelled order result
                order_result = OrderResult(
                    order_id=order_id,
                    status="CANCELLED",
                    filled_quantity=0,
                    average_price=0.0,
                    commission=0.0,
                    timestamp=now_ist()
                )
                self._order_results[order_id] = order_result
                return True
            return False

    def modify_order(self, order_id: str,
                    quantity: int | None = None,
                    price: float | None = None,
                    trigger_price: float | None = None) -> bool:
        """
        Modify an existing order.

        Args:
            order_id: ID of the order to modify
            quantity: New quantity (optional)
            price: New price (optional)
            trigger_price: New trigger price (optional)

        Returns:
            True if modification successful, False otherwise
        """
        self._simulate_network_latency()

        with self._lock:
            if order_id not in self._orders:
                return False

            order = self._orders[order_id]

            # Apply modifications
            if quantity is not None:
                order.quantity = quantity
            if price is not None:
                order.price = price
            if trigger_price is not None:
                order.trigger_price = trigger_price

            # For simplicity, we don't re-evaluate the order immediately
            # In a real system, this might trigger a re-check against market conditions
            return True

    def get_order_status(self, order_id: str) -> str:
        """
        Get the status of an order.

        Args:
            order_id: ID of the order to check

        Returns:
            Order status string
        """
        self._simulate_network_latency()

        if order_id in self._order_results:
            return self._order_results[order_id].status
        elif order_id in self._orders:
            return "OPEN"
        else:
            return "UNKNOWN"

    def get_positions(self) -> list[Position]:
        """
        Get current positions from the paper broker.

        Returns:
            List of Position objects
        """
        self._simulate_network_latency()

        with self._lock:
            # Update positions with current market prices for unrealized P&L
            positions = []
            for symbol, position in self._positions.items():
                if position.quantity == 0:
                    continue

                current_price = self._get_current_price(symbol)
                if current_price is not None:
                    # Calculate unrealized P&L
                    market_value = position.quantity * current_price
                    cost_basis = position.quantity * position.average_price
                    unrealized_pnl = market_value - cost_basis

                    # Update position with current market data
                    updated_position = Position(
                        symbol=symbol,
                        quantity=position.quantity,
                        average_price=position.average_price,
                        market_value=market_value,
                        unrealized_pnl=unrealized_pnl,
                        realized_pnl=position.realized_pnl,
                        timestamp=position.timestamp
                    )
                    positions.append(updated_position)
                else:
                    # If we can't get a price, return position as-is
                    positions.append(position)

            return positions

    def get_quote(self, symbol: str) -> Quote:
        """
        Get current quote for a symbol.

        Args:
            symbol: Trading symbol

        Returns:
            Quote object with bid, ask, last price, etc.
        """
        self._simulate_network_latency()

        # Get current price
        last_price = self._get_current_price(symbol)
        if last_price is None:
            # Return empty quote if we can't get a price
            return Quote(
                symbol=symbol,
                bid=0.0,
                ask=0.0,
                last=0.0,
                volume=0,
                timestamp=now_ist()
            )

        # Simulate bid/ask spread
        spread = last_price * 0.0005  # 0.05% spread
        bid = last_price - spread / 2
        ask = last_price + spread / 2

        # Simulate volume
        volume = random.randint(100, 10000)

        return Quote(
            symbol=symbol,
            bid=bid,
            ask=ask,
            last=last_price,
            volume=volume,
            timestamp=now_ist()
        )

    def subscribe_to_market_data(self, symbols: list[str],
                               callback: Callable[[Quote], None]) -> bool:
        """
        Subscribe to real-time market data for symbols.

        For paper trading, we'll simulate periodic updates.

        Args:
            symbols: List of symbols to subscribe to
            callback: Function to call when market data arrives

        Returns:
            True if subscription setup successful
        """
        # In a full implementation, this would start a background thread
        # that periodically generates quotes and calls the callback
        # For this example, we'll just return True to indicate it's supported
        return True

    def unsubscribe_from_market_data(self, symbol: str) -> bool:
        """
        Unsubscribe from market data for a symbol.

        Args:
            symbol: Symbol to unsubscribe from

        Returns:
            True if unsubscription successful, False otherwise
        """
        # Would clean up subscription resources
        return True

    def get_historical_data(self, symbol: str,
                          from_date: datetime,
                          to_date: datetime,
                          interval: str = "day") -> list[dict[str, Any]]:
        """
        Get historical market data for backtesting and analysis.

        Args:
            symbol: Trading symbol
            from_date: Start date for historical data
            to_date: End date for historical data
            interval: Data interval (minute, 3minute, 5minute, 15minute, 30minute, 60minute, day)

        Returns:
            List of historical data candles
        """
        self._simulate_network_latency()

        # Generate simulated historical data
        # In a real implementation, this would either:
        # 1. Use the market_data_port if it provides historical data
        # 2. Load from a historical data database/files
        # 3. Generate realistic simulated data

        # For this example, we'll generate simple simulated data
        historical_data = []
        current_date = from_date
        base_price = self._symbol_info.get(symbol, {}).get('base_price', 100.0)
        volatility = self._symbol_info.get(symbol, {}).get('volatility', 0.02)

        price = base_price
        while current_date <= to_date:
            # Generate OHLCV data
            daily_volatility = volatility * price
            open_price = price * (1 + random.gauss(0, daily_volatility))
            close_price = open_price * (1 + random.gauss(0, daily_volatility))
            high_price = max(open_price, close_price) * (1 + abs(random.gauss(0, daily_volatility * 0.5)))
            low_price = min(open_price, close_price) * (1 - abs(random.gauss(0, daily_volatility * 0.5)))
            volume = random.randint(1000, 100000)

            historical_data.append({
                'date': current_date.strftime('%Y-%m-%d'),
                'open': round(open_price, 2),
                'high': round(high_price, 2),
                'low': round(low_price, 2),
                'close': round(close_price, 2),
                'volume': volume
            })

            # Update price for next day (random walk)
            price = close_price
            current_date += timedelta(days=1)

        return historical_data

    def get_account_info(self) -> dict[str, Any]:
        """
        Get paper account information.

        Returns:
            Dictionary with account details
        """
        self._simulate_network_latency()

        with self._lock:
            # Calculate total equity
            positions_value = sum(
                pos.market_value for pos in self._positions.values()
                if pos.quantity != 0
            )
            total_equity = self._cash + positions_value

            return {
                'account_id': 'PAPER_ACCOUNT_001',
                'cash': round(self._cash, 2),
                'positions_value': round(positions_value, 2),
                'total_equity': round(total_equity, 2),
                'initial_capital': round(self._initial_capital, 2),
                'pnl': round(total_equity - self._initial_capital, 2),
                'pnl_percent': round(((total_equity - self._initial_capital) / self._initial_capital) * 100, 2),
                'open_positions': len([p for p in self._positions.values() if p.quantity != 0]),
                'timestamp': now_ist().isoformat()
            }

    def health_check(self) -> dict[str, Any]:
        """Implement BrokerPort.health_check() — returns broker health status."""
        with self._lock:
            total_equity = self._cash + sum(
                p.market_value for p in self._positions.values() if p.quantity != 0
            )
            return {
                "status": "healthy",
                "mode": "PAPER",
                "initial_capital": self._initial_capital,
                "current_capital": total_equity,
                "open_positions": len([p for p in self._positions.values() if p.quantity != 0]),
                "cash": self._cash,
                "timestamp": now_ist().isoformat(),
            }

    def reset_account(self):
        """Reset the paper account to initial state."""
        with self._lock:
            self._positions.clear()
            self._orders.clear()
            self._order_results.clear()
            self._fills.clear()
            self._cash = self._initial_capital
            self._margin_used = 0.0
            self._order_counter = 0


# Factory function for creating paper broker adapter instances
def create_paper_broker_adapter(config: dict[str, Any]) -> PaperBrokerAdapter:
    """
    Factory function to create a PaperBrokerAdapter from configuration.

    Args:
        config: Configuration dictionary containing:
                - initial_capital: Starting capital (optional, default 100000.0)
                - simulate_latency: Whether to simulate latency (optional, default True)
                - latency_range_ms: Latency range tuple (optional, default (50, 200))
                - fill_probability: Fill probability (optional, default 0.95)
                - slippage_model: Slippage model (optional, default "linear")
                - commission_per_trade: Commission per trade (optional, default 0.0)

    Returns:
        Configured PaperBrokerAdapter instance
    """
    return PaperBrokerAdapter(
        initial_capital=config.get('initial_capital', 100000.0),
        simulate_latency=config.get('simulate_latency', True),
        latency_range_ms=tuple(config.get('latency_range_ms', [50, 200])),
        fill_probability=config.get('fill_probability', 0.95),
        slippage_model=config.get('slippage_model', 'linear'),
        commission_per_trade=config.get('commission_per_trade', 0.0)
    )
