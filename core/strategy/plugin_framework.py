"""
Plugin Strategy Framework - Item 4

Clean interface for strategies as pluggable modules:
- on_market_data()
- generate_signal()
- on_fill()
- on_risk_update()

Benefits:
- Easier experimentation
- Multi-strategy scaling
- Cleaner architecture
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

_log = logging.getLogger(__name__)


class StrategySignal(Enum):
    """Strategy signal output"""
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"
    CLOSE = "CLOSE"


class StrategyState(Enum):
    """Strategy lifecycle state"""
    INITIALIZED = "INITIALIZED"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    STOPPED = "STOPPED"


@dataclass
class MarketData:
    """Market data input for strategy"""
    symbol: str
    timestamp: str
    last_price: float
    bid: float
    ask: float
    volume: int
    open_interest: int = 0
    iv: float = 0.0
    delta: float = 0.0
    gamma: float = 0.0
    theta: float = 0.0
    vega: float = 0.0
    additional: dict[str, Any] = field(default_factory=dict)


@dataclass
class StrategySignalOutput:
    """Strategy signal output"""
    signal: StrategySignal
    confidence: float
    score: float
    price: float = 0.0
    strike: int | None = None
    expiry: str | None = None
    quantity: int = 1
    reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class FillInfo:
    """Fill information"""
    order_id: str
    symbol: str
    direction: str
    quantity: int
    price: float
    timestamp: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class RiskUpdate:
    """Risk update information"""
    portfolio_pnl: float
    daily_pnl: float
    max_drawdown: float
    positions_count: int
    margin_used: float
    available_capital: float


class BaseStrategy(ABC):
    """
    Abstract base class for all strategies.
    All strategies must implement this interface.
    """

    def __init__(self, config: dict[str, Any]):
        self.config = config
        self._state = StrategyState.INITIALIZED
        self._lock = threading.RLock()
        self._stats = {
            "signals_generated": 0,
            "signals_buy": 0,
            "signals_sell": 0,
            "signals_close": 0,
            "trades_executed": 0,
            "version": "1.0.0",
        }

    @property
    @abstractmethod
    def name(self) -> str:
        """Strategy name - must be unique"""
        pass

    @property
    def version(self) -> str:
        """Strategy version for tracking"""
        return self._stats["version"]

    @property
    def state(self) -> StrategyState:
        """Current strategy state"""
        return self._state

    @property
    def stats(self) -> dict[str, Any]:
        """Strategy statistics"""
        return self._stats.copy()

    @abstractmethod
    def on_market_data(self, data: MarketData) -> None:
        """
        Called on each market data update.
        Use to update internal state/indicators.
        """
        pass

    @abstractmethod
    def generate_signal(self, data: MarketData) -> StrategySignalOutput | None:
        """
        Generate trading signal based on current market data.
        Return None for HOLD, or StrategySignalOutput for actionable signals.
        """
        pass

    @abstractmethod
    def on_fill(self, fill: FillInfo) -> None:
        """
        Called when an order is filled.
        Use to update position tracking.
        """
        pass

    @abstractmethod
    def on_risk_update(self, risk: RiskUpdate) -> None:
        """
        Called on risk engine updates.
        Use to adjust position sizing or pause trading.
        """
        pass

    def on_start(self) -> None:
        """Called when strategy is started"""
        with self._lock:
            self._state = StrategyState.ACTIVE
        _log.info(f"Strategy {self.name} started")

    def on_stop(self) -> None:
        """Called when strategy is stopped"""
        with self._lock:
            self._state = StrategyState.STOPPED
        _log.info(f"Strategy {self.name} stopped")

    def on_pause(self) -> None:
        """Called when strategy is paused"""
        with self._lock:
            self._state = StrategyState.PAUSED
        _log.info(f"Strategy {self.name} paused")

    def on_resume(self) -> None:
        """Called when strategy is resumed"""
        with self._lock:
            self._state = StrategyState.ACTIVE
        _log.info(f"Strategy {self.name} resumed")

    def get_config_hash(self) -> str:
        """Get deterministic hash of strategy config for versioning"""
        config_str = json.dumps(self.config, sort_keys=True)
        return hashlib.sha256(config_str.encode()).hexdigest()[:16]

    def validate_config(self) -> bool:
        """Validate strategy configuration"""
        return True

    def __repr__(self):
        return f"{self.name}(version={self.version}, state={self._state.value})"


class StrategyRegistry:
    """
    Registry for managing multiple strategies.
    Enables multi-strategy scaling.
    """

    def __init__(self):
        self._strategies: dict[str, BaseStrategy] = {}
        self._lock = threading.RLock()
        self._active_signals: list[StrategySignalOutput] = []

    def register(self, strategy: BaseStrategy) -> bool:
        """Register a strategy"""
        with self._lock:
            if strategy.name in self._strategies:
                _log.warning(f"Strategy {strategy.name} already registered")
                return False

            if not strategy.validate_config():
                _log.error(f"Strategy {strategy.name} config validation failed")
                return False

            self._strategies[strategy.name] = strategy
            _log.info(f"Registered strategy: {strategy.name} v{strategy.version}")
            return True

    def unregister(self, name: str) -> bool:
        """Unregister a strategy"""
        with self._lock:
            if name in self._strategies:
                del self._strategies[name]
                _log.info(f"Unregistered strategy: {name}")
                return True
            return False

    def get(self, name: str) -> BaseStrategy | None:
        """Get strategy by name"""
        return self._strategies.get(name)

    def get_all(self) -> list[BaseStrategy]:
        """Get all registered strategies"""
        return list(self._strategies.values())

    def get_active(self) -> list[BaseStrategy]:
        """Get all active strategies"""
        with self._lock:
            return [s for s in self._strategies.values() if s.state == StrategyState.ACTIVE]

    def generate_signals(self, data: MarketData) -> list[StrategySignalOutput]:
        """Generate signals from all active strategies"""
        signals = []
        with self._lock:
            for strategy in self._strategies.values():
                if strategy.state == StrategyState.ACTIVE:
                    try:
                        strategy.on_market_data(data)
                        signal = strategy.generate_signal(data)
                        if signal and signal.signal != StrategySignal.HOLD:
                            signal.metadata["strategy_name"] = strategy.name
                            signal.metadata["strategy_version"] = strategy.version
                            signals.append(signal)
                            strategy._stats["signals_generated"] += 1
                            if signal.signal == StrategySignal.BUY:
                                strategy._stats["signals_buy"] += 1
                            elif signal.signal == StrategySignal.SELL:
                                strategy._stats["signals_sell"] += 1
                            elif signal.signal == StrategySignal.CLOSE:
                                strategy._stats["signals_close"] += 1
                    except Exception as e:
                        _log.error(f"Error generating signal from {strategy.name}: {e} (type: {type(e).__name__})")
        return signals

    def on_fill(self, fill: FillInfo) -> None:
        """Forward fill to all strategies"""
        with self._lock:
            for strategy in self._strategies.values():
                try:
                    strategy.on_fill(fill)
                    strategy._stats["trades_executed"] += 1
                except Exception as e:
                    _log.error(f"Error forwarding fill to {strategy.name}: {e} (type: {type(e).__name__})")

    def on_risk_update(self, risk: RiskUpdate) -> None:
        """Forward risk update to all strategies"""
        with self._lock:
            for strategy in self._strategies.values():
                try:
                    strategy.on_risk_update(risk)
                except Exception as e:
                    _log.error(f"Error forwarding risk update to {strategy.name}: {e} (type: {type(e).__name__})")

    def start_all(self) -> None:
        """Start all registered strategies"""
        with self._lock:
            for strategy in self._strategies.values():
                strategy.on_start()

    def stop_all(self) -> None:
        """Stop all strategies"""
        with self._lock:
            for strategy in self._strategies.values():
                strategy.on_stop()

    def pause_all(self) -> None:
        """Pause all active strategies"""
        with self._lock:
            for strategy in self._strategies.values():
                if strategy.state == StrategyState.ACTIVE:
                    strategy.on_pause()

    def resume_all(self) -> None:
        """Resume all paused strategies"""
        with self._lock:
            for strategy in self._strategies.values():
                if strategy.state == StrategyState.PAUSED:
                    strategy.on_resume()

    def get_all_stats(self) -> dict[str, dict[str, Any]]:
        """Get stats from all strategies"""
        with self._lock:
            return {name: s.stats.copy() for name, s in self._strategies.items()}


class StrategyLoader:
    """
    Dynamic strategy loader.
    Loads strategies from plugins directory.
    """

    def __init__(self, registry: StrategyRegistry):
        self._registry = registry

    def load_from_module(self, module_path: str, class_name: str, config: dict[str, Any]) -> BaseStrategy | None:
        """Load strategy from module path"""
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location("strategy_module", module_path)
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)

                strategy_class = getattr(module, class_name, None)
                if strategy_class and issubclass(strategy_class, BaseStrategy):
                    strategy = strategy_class(config)
                    if self._registry.register(strategy):
                        return strategy
            return None
        except Exception as e:
            _log.error(f"Failed to load strategy from {module_path}: {e} (type: {type(e).__name__})")
            return None


_strategy_registry: StrategyRegistry | None = None
_registry_lock = threading.RLock()


def get_strategy_registry() -> StrategyRegistry:
    """Get singleton strategy registry"""
    global _strategy_registry
    with _registry_lock:
        if _strategy_registry is None:
            _strategy_registry = StrategyRegistry()
        return _strategy_registry
