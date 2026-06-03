"""
Strategy Sandbox Environment - Item 7

Allow strategy development against:
- historical replay
- simulated live feed
- mock broker

Fast experimentation without touching production.
"""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from core.execution.event_system import get_event_bus
from core.strategy.plugin_framework import BaseStrategy, MarketData, StrategySignal, StrategySignalOutput
from core.time_provider import time_provider

_log = logging.getLogger(__name__)


class SandboxMode(Enum):
    """Sandbox execution modes"""
    HISTORICAL_REPLAY = "HISTORICAL_REPLAY"
    SIMULATED_LIVE = "SIMULATED_LIVE"
    MOCK_BROKER = "MOCK_BROKER"


@dataclass
class SandboxConfig:
    """Sandbox configuration"""
    mode: SandboxMode
    speed: float = 1.0
    mock_fills: bool = True
    slippage_pct: float = 0.001
    record_signals: bool = True


@dataclass
class SandboxResult:
    """Sandbox run result"""
    run_id: str
    strategy_name: str
    mode: SandboxMode
    start_time: str
    end_time: str
    total_signals: int
    total_trades: int
    simulated_pnl: float
    metadata: dict[str, Any] = field(default_factory=dict)


class StrategySandbox:
    """
    Strategy sandbox for safe strategy development and testing.
    Runs strategies in isolation without touching production.
    """

    def __init__(self):
        self._active = False
        self._config: SandboxConfig | None = None
        self._strategy: BaseStrategy | None = None
        self._results: list[SandboxResult] = []
        self._lock = threading.Lock()
        self._market_data_callback: Callable | None = None
        self._stop_event = threading.Event()

    def configure(self, mode: SandboxMode, **kwargs) -> None:
        """Configure sandbox"""
        self._config = SandboxConfig(
            mode=mode,
            speed=kwargs.get("speed", 1.0),
            mock_fills=kwargs.get("mock_fills", True),
            slippage_pct=kwargs.get("slippage_pct", 0.001),
            record_signals=kwargs.get("record_signals", True),
        )
        _log.info(f"Sandbox configured: {mode.value}")

    def load_strategy(self, strategy: BaseStrategy) -> bool:
        """Load strategy into sandbox"""
        try:
            strategy.on_start()
            self._strategy = strategy
            _log.info(f"Loaded strategy into sandbox: {strategy.name}")
            return True
        except Exception as e:
            _log.error(f"Failed to load strategy: {e}")
            return False

    def run_historical_replay(
        self,
        historical_data: list[dict[str, Any]],
        on_complete: Callable | None = None,
    ) -> SandboxResult | None:
        """Run strategy on historical data"""
        if not self._strategy or not self._config:
            _log.error("Sandbox not configured or no strategy loaded")
            return None

        run_id = f"SANDBOX-{int(time_provider.get_ts())}"
        start_time = time_provider.format_ts()

        self._active = True
        signals = []
        simulated_pnl = 0.0

        _log.info(f"Starting historical replay: {len(historical_data)} data points")

        for data_point in historical_data:
            if not self._active:
                break

            market_data = self._convert_to_market_data(data_point)

            self._strategy.on_market_data(market_data)

            signal = self._strategy.generate_signal(market_data)

            if signal and signal.signal != StrategySignal.HOLD:
                signals.append(signal)

                if self._config.mock_fills:
                    fill_result = self._simulate_fill(signal)
                    simulated_pnl += fill_result["pnl"]

                    if self._config.record_signals:
                        self._record_signal_event(signal, fill_result)

        end_time = time_provider.format_ts()

        result = SandboxResult(
            run_id=run_id,
            strategy_name=self._strategy.name,
            mode=self._config.mode,
            start_time=start_time,
            end_time=end_time,
            total_signals=len(signals),
            total_trades=len(signals),
            simulated_pnl=simulated_pnl,
            metadata={
                "data_points": len(historical_data),
                "speed": self._config.speed,
            },
        )

        with self._lock:
            self._results.append(result)

        if on_complete:
            on_complete(result)

        _log.info(f"Historical replay complete: {len(signals)} signals, P&L: {simulated_pnl:.2f}")

        self._active = False
        return result

    def run_simulated_live(
        self,
        data_source: Callable[[], MarketData],
        duration_seconds: int = 300,
    ) -> SandboxResult | None:
        """Run strategy in simulated live mode"""
        if not self._strategy or not self._config:
            _log.error("Sandbox not configured or no strategy loaded")
            return None

        run_id = f"SANDBOX-LIVE-{int(time_provider.get_ts())}"
        start_time = time_provider.format_ts()

        self._active = True
        signals = []
        simulated_pnl = 0.0
        start_ts = time.time()

        _log.info(f"Starting simulated live for {duration_seconds}s")

        while self._active and (time.time() - start_ts) < duration_seconds:
            try:
                market_data = data_source()

                self._strategy.on_market_data(market_data)

                signal = self._strategy.generate_signal(market_data)

                if signal and signal.signal != StrategySignal.HOLD:
                    signals.append(signal)

                    if self._config.mock_fills:
                        fill_result = self._simulate_fill(signal)
                        simulated_pnl += fill_result["pnl"]

                sleep_time = 1.0 / self._config.speed
                if self._stop_event.wait(sleep_time):
                    break

            except Exception as e:
                _log.error(f"Error in simulated live: {e}")
                break

        end_time = time_provider.format_ts()

        result = SandboxResult(
            run_id=run_id,
            strategy_name=self._strategy.name,
            mode=self._config.mode,
            start_time=start_time,
            end_time=end_time,
            total_signals=len(signals),
            total_trades=len(signals),
            simulated_pnl=simulated_pnl,
            metadata={
                "duration": duration_seconds,
            },
        )

        with self._lock:
            self._results.append(result)

        _log.info(f"Simulated live complete: {len(signals)} signals, P&L: {simulated_pnl:.2f}")

        self._active = False
        return result

    def stop(self) -> None:
        """Stop sandbox"""
        self._active = False
        self._stop_event.set()
        if self._strategy:
            self._strategy.on_stop()
        _log.info("Sandbox stopped")

    def get_results(self, limit: int = 10) -> list[SandboxResult]:
        """Get recent sandbox results"""
        with self._lock:
            return self._results[-limit:]

    def get_current_stats(self) -> dict[str, Any]:
        """Get current sandbox stats"""
        return {
            "active": self._active,
            "config": {
                "mode": self._config.mode.value if self._config else None,
                "speed": self._config.speed if self._config else 0,
            },
            "strategy": self._strategy.name if self._strategy else None,
            "total_runs": len(self._results),
        }

    def _convert_to_market_data(self, data: dict[str, Any]) -> MarketData:
        """Convert dict to MarketData"""
        return MarketData(
            symbol=data.get("symbol", ""),
            timestamp=data.get("timestamp", time_provider.format_ts()),
            last_price=data.get("last_price", 0.0),
            bid=data.get("bid", 0.0),
            ask=data.get("ask", 0.0),
            volume=data.get("volume", 0),
            open_interest=data.get("open_interest", 0),
            iv=data.get("iv", 0.0),
        )

    def _simulate_fill(self, signal: StrategySignalOutput) -> dict[str, Any]:
        """Simulate order fill with slippage"""
        slippage = self._config.slippage_pct if self._config else 0.001

        if signal.signal == StrategySignal.BUY:
            fill_price = signal.price * (1 + slippage)
        else:
            fill_price = signal.price * (1 - slippage)

        return {
            "price": fill_price,
            "quantity": signal.quantity,
            "pnl": 0.0,
        }

    def _record_signal_event(self, signal: StrategySignalOutput, fill: dict) -> None:
        """Record signal as event"""
        if self._config and self._config.record_signals:
            event_bus = get_event_bus()
            event_bus.publish_signal_generated(
                intent_id=f"sandbox-{signal.metadata.get('strategy_name', 'unknown')}",
                symbol=signal.metadata.get("symbol", ""),
                direction=signal.signal.value,
                quantity=signal.quantity,
                price=fill["price"],
                metadata={
                    "sandbox": True,
                    "confidence": signal.confidence,
                    "score": signal.score,
                },
            )


_sandbox: StrategySandbox | None = None
_sandbox_lock = threading.Lock()


def get_strategy_sandbox() -> StrategySandbox:
    """Get singleton strategy sandbox"""
    global _sandbox
    with _sandbox_lock:
        if _sandbox is None:
            _sandbox = StrategySandbox()
        return _sandbox
