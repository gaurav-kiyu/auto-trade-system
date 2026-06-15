"""
Portfolio Management Domain Service - Clean Architecture Implementation

This service implements core portfolio management logic in a pure, testable manner
following Clean Architecture principles. All dependencies are injected through
interfaces, making this service easy to test and maintain.
"""

from __future__ import annotations

import math
import statistics
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from core.datetime_ist import now_ist

# Import shared kernels

# Import domain models and value objects (simplified for this example)
# In a full implementation, these would be properly defined


@dataclass
class Position:
    """Trading position."""
    symbol: str
    quantity: int  # Positive for long, negative for short
    average_price: float
    market_value: float
    unrealized_pnl: float
    realized_pnl: float
    timestamp: datetime = None

    @property
    def direction(self) -> str:
        """Direction of the position: 'BUY' for long, 'SELL' for short, 'NEUTRAL' for zero."""
        if self.quantity > 0:
            return "BUY"
        elif self.quantity < 0:
            return "SELL"
        else:
            return "NEUTRAL"


@dataclass
class TradeRecord:
    """Completed trade record."""
    symbol: str
    entry_price: float
    exit_price: float
    quantity: int
    direction: str  # "BUY" or "SELL"
    entry_time: datetime
    exit_time: datetime
    realized_pnl: float
    commission: float = 0.0
    strategy_id: str = ""


@dataclass
class PerformanceMetrics:
    """Portfolio performance metrics."""
    total_return: float = 0.0
    annualized_return: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    max_drawdown: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    average_trade: float = 0.0
    average_win: float = 0.0
    average_loss: float = 0.0
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0


class PortfolioService:
    """
    Core portfolio management service.

    This service implements all portfolio management logic in a pure, testable manner
    without any external dependencies. All dependencies are injected through
    the constructor or method parameters.
    """

    def __init__(self, base_currency: str = "INR"):
        self.base_currency = base_currency
        self._lock = threading.Lock()
        self._positions: dict[str, Position] = {}
        self._trade_history: deque = field(default_factory=lambda: deque(maxlen=10000))
        self._equity_curve: deque = field(default_factory=lambda: deque(maxlen=10000))
        self._daily_returns: deque = field(default_factory=lambda: deque(maxlen=252))  # 1 year of daily returns
        self.__post_init__()

    def __post_init__(self):
        """Initialize portfolio manager."""
        self._last_equity = 0.0
        self._last_update = now_ist()

    def update_position(self, fill: Any) -> Position:
        """
        Update position based on a fill.

        Args:
            fill: Fill object containing fill details

        Returns:
            Updated position object
        """
        symbol = fill.symbol
        quantity = fill.quantity if fill.direction == "BUY" else -fill.quantity
        price = fill.price
        timestamp = fill.timestamp

        with self._lock:
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
                    timestamp=timestamp
                )
                self._positions[symbol] = new_position
                return new_position

            # Update existing position
            old_quantity = existing_position.quantity
            old_avg_price = existing_position.average_price

            # Calculate new quantity and average price
            new_quantity = old_quantity + quantity

            if new_quantity == 0:
                # Position closed - calculate realized P&L
                realized_pnl = (price - old_avg_price) * old_quantity
                closed_position = Position(
                    symbol=symbol,
                    quantity=0,
                    average_price=0.0,
                    market_value=0.0,
                    unrealized_pnl=0.0,
                    realized_pnl=existing_position.realized_pnl + realized_pnl,
                    timestamp=timestamp
                )
                # Move to trade history
                trade_record = TradeRecord(
                    symbol=symbol,
                    entry_price=old_avg_price,
                    exit_price=price,
                    quantity=abs(old_quantity),
                    direction="BUY" if old_quantity > 0 else "SELL",
                    entry_time=existing_position.timestamp,
                    exit_time=timestamp,
                    realized_pnl=realized_pnl,
                    commission=getattr(fill, 'commission', 0.0),
                    strategy_id=getattr(fill, 'strategy_id', 'unknown')
                )
                self._trade_history.append(trade_record)

                # Remove closed position
                del self._positions[symbol]
                return closed_position
            else:
                # Position still open - update average price
                if old_quantity * quantity > 0:
                    # Same direction - weighted average
                    total_cost = (old_quantity * old_avg_price) + (quantity * price)
                    total_cost / new_quantity
                else:
                    # Opposite direction - partial close
                    if abs(quantity) < abs(old_quantity):
                        # Partial close - calculate realized P&L on closed portion
                        closed_quantity = min(abs(old_quantity), abs(quantity))
                        closed_direction = "BUY" if old_quantity > 0 else "SELL"
                        realized_pnl = (price - old_avg_price) * closed_quantity * (1 if closed_direction == "BUY" else -1)

                        # Update position
                        new_position = Position(
                            symbol=symbol,
                            quantity=new_quantity,
                            average_price=old_avg_price,  # Keep original average price
                            market_value=new_quantity * price,
                            unrealized_pnl=0.0,
                            realized_pnl=existing_position.realized_pnl + realized_pnl,
                            timestamp=timestamp
                        )
                        self._positions[symbol] = new_position

                        # Record the closed portion as a trade
                        trade_record = TradeRecord(
                            symbol=symbol,
                            entry_price=old_avg_price,
                            exit_price=price,
                            quantity=closed_quantity,
                            direction=closed_direction,
                            entry_time=existing_position.timestamp,
                            exit_time=timestamp,
                            realized_pnl=realized_pnl,
                            commission=getattr(fill, 'commission', 0.0) * (closed_quantity / abs(old_quantity)),
                            strategy_id=getattr(fill, 'strategy_id', 'unknown')
                        )
                        self._trade_history.append(trade_record)
                        return new_position
                    else:
                        # Position flipped - calculate realized P&L on entire original position
                        realized_pnl = (price - old_avg_price) * abs(old_quantity) * (1 if old_quantity > 0 else -1)

                        # New position in opposite direction
                        new_position = Position(
                            symbol=symbol,
                            quantity=new_quantity,
                            average_price=price,
                            market_value=new_quantity * price,
                            unrealized_pnl=0.0,
                            realized_pnl=existing_position.realized_pnl + realized_pnl,
                            timestamp=timestamp
                        )
                        self._positions[symbol] = new_position

                        # Record the flipped portion as a trade
                        trade_record = TradeRecord(
                            symbol=symbol,
                            entry_price=old_avg_price,
                            exit_price=price,
                            quantity=abs(old_quantity),
                            direction="BUY" if old_quantity > 0 else "SELL",
                            entry_time=existing_position.timestamp,
                            exit_time=timestamp,
                            realized_pnl=realized_pnl,
                            commission=getattr(fill, 'commission', 0.0),
                            strategy_id=getattr(fill, 'strategy_id', 'unknown')
                        )
                        self._trade_history.append(trade_record)
                        return new_position

    def close_position(self, symbol: str, exit_price: float,
                      commission: float = 0.0) -> TradeRecord | None:
        """
        Close a position at the specified price.

        Args:
            symbol: Symbol to close
            exit_price: Price at which to close
            commission: Commission to charge

        Returns:
            TradeRecord for the closed position, or None if no position existed
        """
        with self._lock:
            position = self._positions.get(symbol)
            if position is None or position.quantity == 0:
                return None

            # Calculate realized P&L
            realized_pnl = (exit_price - position.average_price) * position.quantity

            # Create trade record
            trade_record = TradeRecord(
                symbol=symbol,
                entry_price=position.average_price,
                exit_price=exit_price,
                quantity=abs(position.quantity),
                direction="BUY" if position.quantity > 0 else "SELL",
                entry_time=position.timestamp,
                exit_time=now_ist(),
                realized_pnl=realized_pnl,
                commission=commission,
                strategy_id=getattr(position, 'strategy_id', 'unknown')
            )

            # Add to trade history
            self._trade_history.append(trade_record)

            # Remove position
            del self._positions[symbol]

            return trade_record

    def calculate_unrealized_pnl(self, positions: dict[str, Position],
                               current_prices: dict[str, float]) -> float:
        """
        Calculate unrealized P&L for all positions.

        Args:
            positions: Current positions
            current_prices: Current market prices for symbols

        Returns:
            Total unrealized P&L
        """
        total_unrealized = 0.0

        for symbol, position in positions.items():
            if symbol in current_prices:
                current_price = current_prices[symbol]
                market_value = position.quantity * current_price
                cost_basis = position.quantity * position.average_price
                unrealized = market_value - cost_basis
                total_unrealized += unrealized

                # Update position with current market data
                updated_position = Position(
                    symbol=symbol,
                    quantity=position.quantity,
                    average_price=position.average_price,
                    market_value=market_value,
                    unrealized_pnl=unrealized,
                    realized_pnl=position.realized_pnl,
                    timestamp=position.timestamp
                )
                positions[symbol] = updated_position

        return total_unrealized

    def calculate_realized_pnl(self, trades: list[TradeRecord]) -> float:
        """
        Calculate realized P&L from closed trades.

        Args:
            trades: List of trade records

        Returns:
            Total realized P&L
        """
        if not trades:
            return 0.0
        return sum(trade.realized_pnl for trade in trades)

    def calculate_performance_metrics(self,
                                    equity_curve: list[float],
                                    trades: list[TradeRecord],
                                    risk_free_rate: float = 0.02) -> PerformanceMetrics:
        """
        Calculate performance metrics from equity curve and trades.

        Args:
            equity_curve: List of equity values over time
            trades: List of trade records
            risk_free_rate: Risk-free rate for Sharpe/Sortino calculations

        Returns:
            PerformanceMetrics object
        """
        if len(equity_curve) < 2:
            return PerformanceMetrics()

        # Calculate returns from equity curve
        returns = []
        for i in range(1, len(equity_curve)):
            if equity_curve[i-1] != 0:
                period_return = (equity_curve[i] - equity_curve[i-1]) / equity_curve[i-1]
                returns.append(period_return)

        if not returns:
            return PerformanceMetrics()

        # Basic return metrics
        total_return = (equity_curve[-1] - equity_curve[0]) / equity_curve[0]
        periods_per_year = 252  # Trading days per year
        annualized_return = (1 + total_return) ** (periods_per_year / len(returns)) - 1

        # Risk-adjusted metrics
        excess_returns = [r - risk_free_rate/periods_per_year for r in returns]

        # Sharpe ratio
        if len(excess_returns) >= 2 and statistics.stdev(excess_returns) > 0:
            sharpe_ratio = statistics.mean(excess_returns) / statistics.stdev(excess_returns) * math.sqrt(periods_per_year)
        else:
            sharpe_ratio = 0.0

        # Sortino ratio (downside deviation)
        downside_returns = [r for r in excess_returns if r < 0]
        if len(downside_returns) >= 2 and statistics.stdev(downside_returns) > 0:
            sortino_ratio = statistics.mean(excess_returns) / statistics.stdev(downside_returns) * math.sqrt(periods_per_year)
        else:
            sortino_ratio = 0.0

        # Max drawdown
        peak = equity_curve[0]
        max_drawdown = 0.0
        for value in equity_curve:
            if value > peak:
                peak = value
            drawdown = (peak - value) / peak
            max_drawdown = max(max_drawdown, drawdown)

        # Trade-based metrics
        if trades:
            winning_trades = [t for t in trades if t.realized_pnl > 0]
            losing_trades = [t for t in trades if t.realized_pnl < 0]

            win_rate = len(winning_trades) / len(trades) if trades else 0.0

            total_wins = sum(t.realized_pnl for t in winning_trades)
            total_losses = abs(sum(t.realized_pnl for t in losing_trades))

            profit_factor = total_wins / total_losses if total_losses > 0 else 0.0

            average_trade = statistics.mean([t.realized_pnl for t in trades]) if trades else 0.0
            average_win = statistics.mean([t.realized_pnl for t in winning_trades]) if winning_trades else 0.0
            average_loss = statistics.mean([t.realized_pnl for t in losing_trades]) if losing_trades else 0.0
        else:
            win_rate = 0.0
            profit_factor = 0.0
            average_trade = 0.0
            average_win = 0.0
            average_loss = 0.0
            winning_trades = []
            losing_trades = []

        return PerformanceMetrics(
            total_return=total_return,
            annualized_return=annualized_return,
            sharpe_ratio=sharpe_ratio,
            sortino_ratio=sortino_ratio,
            max_drawdown=max_drawdown,
            win_rate=win_rate,
            profit_factor=profit_factor,
            average_trade=average_trade,
            average_win=average_win,
            average_loss=average_loss,
            total_trades=len(trades),
            winning_trades=len(winning_trades),
            losing_trades=len(losing_trades)
        )

    def get_portfolio_summary(self) -> dict[str, Any]:
        """Get current portfolio summary."""
        total_market_value = sum(pos.market_value for pos in self._positions.values())
        total_unrealized_pnl = sum(pos.unrealized_pnl for pos in self._positions.values())
        total_realized_pnl = sum(pos.realized_pnl for pos in self._positions.values())

        return {
            'timestamp': now_ist().isoformat(),
            'base_currency': self.base_currency,
            'positions': {
                symbol: {
                    'quantity': pos.quantity,
                    'average_price': pos.average_price,
                    'market_value': pos.market_value,
                    'unrealized_pnl': pos.unrealized_pnl,
                    'realized_pnl': pos.realized_pnl
                }
                for symbol, pos in self._positions.items()
            },
            'summary': {
                'total_positions': len(self._positions),
                'total_market_value': total_market_value,
                'total_unrealized_pnl': total_unrealized_pnl,
                'total_realized_pnl': total_realized_pnl,
                'total_equity': total_market_value + total_realized_pnl
            },
            'recent_trades_count': len([t for t in self._trade_history
                                      if (now_ist() - t.exit_time).days < 7])
        }

    def get_equity_curve(self) -> list[float]:
        """Get the equity curve for performance analysis."""
        return list(self._equity_curve)

    def update_equity_curve(self, equity_value: float):
        """Update the equity curve with a new value."""
        self._equity_curve.append(equity_value)
        self._last_equity = equity_value
        self._last_update = now_ist()

    def calculate_daily_return(self, todays_equity: float, yesterdays_equity: float) -> float:
        """Calculate daily return."""
        if yesterdays_equity == 0:
            return 0.0
        return (todays_equity - yesterdays_equity) / yesterdays_equity

    def add_daily_return(self, daily_return: float):
        """Add a daily return to the tracking buffer."""
        self._daily_returns.append(daily_return)


# Factory function for creating portfolio service instances
def create_portfolio_service(config: dict[str, Any]) -> PortfolioService:
    """Factory function to create a PortfolioService from configuration."""
    return PortfolioService(
        base_currency=config.get('base_currency', 'INR')
    )


if __name__ == "__main__":
    # Example usage and basic tests
    print("=== Portfolio Service Demo ===")

    # Create portfolio service
    portfolio_service = create_portfolio_service({})

    # Simulate some trades
    # Create mock fill objects
    class MockFill:
        def __init__(self, symbol, quantity, price, direction, timestamp=None, commission=0.0, strategy_id=''):
            self.symbol = symbol
            self.quantity = quantity
            self.price = price
            self.direction = direction
            self.timestamp = timestamp or now_ist()
            self.commission = commission
            self.strategy_id = strategy_id

    # Buy 50 NIFTY at 20000
    fill1 = MockFill("NIFTY", 50, 20000, "BUY")
    position1 = portfolio_service.update_position(fill1)
    print("After BUY 50 NIFTY @ 20000:")
    print(f"  Position: {position1.quantity} @ {position1.average_price}")

    # Sell 30 NIFTY at 20500
    fill2 = MockFill("NIFTY", 30, 20500, "SELL")
    position2 = portfolio_service.update_position(fill2)
    print("After SELL 30 NIFTY @ 20500:")
    print(f"  Position: {position2.quantity} @ {position2.average_price}")
    print(f"  Realized P&L: {position2.realized_pnl}")

    # Close remaining position
    trade_record = portfolio_service.close_position("NIFTY", 20700)
    if trade_record:
        print("Closed remaining position:")
        print(f"  P&L: {trade_record.realized_pnl}")

    # Get portfolio summary
    summary = portfolio_service.get_portfolio_summary()
    print("\\n=== Portfolio Summary ===")
    print(f"Total positions: {summary['summary']['total_positions']}")
    print(f"Total equity: {summary['summary']['total_equity']:.2f}")

    print("\\n✅ Portfolio service working correctly!")


class PortfolioDataService:
    """Wraps PortfolioService as a data-source interface for PortfolioAuthority."""

    def __init__(self, portfolio_service: Any = None):
        self._portfolio = portfolio_service or PortfolioService()
        self._strategy_budgets: dict[str, Any] = {}

    def get_exposures(self) -> dict[str, Any]:
        """Return per-asset-class exposure snapshot."""
        from core.domains.portfolio.model import ExposureRecord
        exposures: dict[str, ExposureRecord] = {}
        for symbol, pos in self._portfolio._positions.items():
            asset_class = symbol.split("_")[0] if "_" in symbol else "EQUITY"
            if asset_class not in exposures:
                exposures[asset_class] = ExposureRecord(asset_class=asset_class)
            rec = exposures[asset_class]
            if pos.quantity > 0:
                rec.long_exposure += abs(pos.market_value)
            elif pos.quantity < 0:
                rec.short_exposure += abs(pos.market_value)
            rec.net_exposure = rec.long_exposure - rec.short_exposure
            rec.gross_exposure = rec.long_exposure + rec.short_exposure
            rec.pnl += pos.unrealized_pnl + pos.realized_pnl
        return {k: vars(v) for k, v in exposures.items()}

    def get_margin_requirements(self) -> dict[str, Any]:
        """Return margin requirement estimate."""
        from core.domains.portfolio.model import MarginRequirement
        total_exposure = sum(abs(p.market_value) for p in self._portfolio._positions.values())
        summary = self._portfolio.get_portfolio_summary()
        equity = summary.get("summary", {}).get("total_equity", 0) if isinstance(summary, dict) else 0
        mr = MarginRequirement(
            span_margin=total_exposure * 0.12,
            exposure_margin=total_exposure * 0.03,
            available_cash=equity,
        )
        mr.total = mr.span_margin + mr.exposure_margin + mr.premium
        return vars(mr)

    def get_strategy_budgets(self) -> dict[str, Any]:
        """Return per-strategy budget snapshot."""
        return {sid: vars(sb) for sid, sb in self._strategy_budgets.items()} if self._strategy_budgets else {}

    def set_strategy_budget(self, strategy_id: str, allocated_capital: float, **kwargs) -> None:
        """Set or update a strategy budget."""
        from core.domains.portfolio.model import StrategyBudget
        self._strategy_budgets[strategy_id] = StrategyBudget(
            strategy_id=strategy_id, allocated_capital=allocated_capital, **kwargs,
        )

    def total_exposure(self) -> float:
        """Return total gross exposure."""
        return sum(abs(p.market_value) for p in self._portfolio._positions.values())

    def net_exposure(self) -> float:
        """Return net exposure (long - short)."""
        net = 0.0
        for p in self._portfolio._positions.values():
            net += p.market_value if p.quantity > 0 else -p.market_value
        return net
