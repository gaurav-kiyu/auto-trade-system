"""Multi-Asset Strategy Dispatcher — Routes signals to the correct trading engine.

Implements the Phase 10 (Market Coverage) dispatcher that routes trading
signals to the appropriate asset-specific engine based on symbol/asset class.

Asset Classes Supported:
  - INDEX_OPTIONS → IndexTrader (existing)
  - EQUITY       → EquityTrader
  - ETF          → EquityTrader (ETF)
  - REIT         → EquityTrader (REIT)
  - INVIT        → EquityTrader (InvIT)
  - SME          → EquityTrader (SME)
  - FUTURES      → FuturesTrader (new)
  - COMMODITY    → CommodityTrader (new)
  - CURRENCY     → CurrencyTrader (new)

Usage:
    from core.strategy.multi_asset_dispatcher import MultiAssetStrategyDispatcher

    dispatcher = MultiAssetStrategyDispatcher(config)
    result = dispatcher.route(symbol="RELIANCE", signal={...})
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pandas as pd

from core.common.models import AssetType

_log = logging.getLogger(__name__)


# Backward-compatible alias — AssetClass is now AssetType from shared models
AssetClass = AssetType


# ── Convenience factory: wire all registered trading engines ─────────────────

def _build_broker_executor_for_dispatcher(
    cfg: dict[str, Any],
) -> tuple[Callable, Callable]:
    """Build dispatcher callbacks through canonical ExecutionService.

    The dispatcher retains its existing callback contract:

        (symbol, direction, quantity, price) -> bool

    The canonical ExecutionPort is resolved lazily when a callback
    is invoked. This is required because the dispatcher can be
    constructed before the application-level trading DI container
    registers ExecutionPort.

    ExecutionService itself is never constructed here.
    """
    def _resolve_execution_service():
        from core.di_container import get_container
        from core.ports.execution.execution_port import (
            ExecutionPort,
        )

        return get_container().resolve(
            ExecutionPort
        )

    def _execution_mode():
        from core.ports.execution.execution_port import (
            ExecutionMode,
        )

        mode = str(
            cfg.get(
                "EXECUTION_MODE",
                "MANUAL",
            )
        ).upper()

        if mode == "PAPER":
            return ExecutionMode.PAPER

        if mode in {
            "AUTO",
            "AUTOMATIC",
        }:
            return ExecutionMode.AUTOMATIC

        return ExecutionMode.MANUAL

    def _execute_entry(
        symbol: str,
        direction: str,
        quantity: int,
        entry_price: float = 0.0,
        **kwargs: Any,
    ) -> bool:
        try:
            from core.ports.execution.execution_port import (
                ExecutionContext,
                OrderRequest,
                OrderType,
            )

            execution_service = (
                _resolve_execution_service()
            )

            price = float(
                entry_price or 0.0
            )

            request = OrderRequest(
                symbol=str(symbol),
                direction=str(direction).upper(),
                strike_price=price,
                lot_size=int(quantity),
                order_type=OrderType.MARKET,
                price=price,
                strategy_id=str(
                    kwargs.get(
                        "strategy_id",
                        "multi_asset_dispatcher",
                    )
                ),
                idempotency_key=kwargs.get(
                    "idempotency_key"
                ),
            )

            context = ExecutionContext(
                strategy_name="multi_asset_dispatcher",
                execution_mode=_execution_mode(),
                metadata={
                    "source": "multi_asset_dispatcher",
                },
            )

            result = execution_service.execute_order(
                request,
                context,
            )

            status = str(
                getattr(
                    result,
                    "status",
                    "",
                )
            ).upper()

            return bool(
                getattr(
                    result,
                    "success",
                    False,
                )
                or status in {
                    "FILLED",
                    "SUBMITTED",
                    "PARTIALLY_FILLED",
                }
            )

        except (
            ImportError,
            AttributeError,
            KeyError,
            RuntimeError,
            TypeError,
            ValueError,
        ) as exc:
            _log.warning(
                "[DISPATCH] Canonical execution unavailable: %s",
                exc,
            )

            # Fail closed: canonical execution failure must
            # never be reported as a successful trade entry.
            return False

    def _execute_exit(
        symbol: str,
        direction: str,
        quantity: int,
        exit_price: float = 0.0,
        **kwargs: Any,
    ) -> bool:
        current_direction = str(
            direction
        ).upper()

        exit_direction = (
            "SELL"
            if current_direction == "BUY"
            else "BUY"
        )

        return _execute_entry(
            symbol,
            exit_direction,
            quantity,
            exit_price,
            **kwargs,
        )

    return (
        _execute_entry,
        _execute_exit,
    )




def get_dispatcher_with_all_engines(config: dict[str, Any] | None = None) -> MultiAssetStrategyDispatcher:
    """Create a dispatcher and register all available trading engines.

    Auto-detects which engines are available and wires them to the dispatcher
    with broker execution callbacks for paper or real trading.
    Engines are only registered if their symbols are configured.

    Args:
        config: Optional config dict with asset class settings.

    Returns:
        Configured MultiAssetStrategyDispatcher with registered engines.
    """
    dispatcher = get_dispatcher(config)
    cfg = config or {}

    # Build broker execution callbacks (paper mode by default)
    exec_entry, exec_exit = _build_broker_executor_for_dispatcher(cfg)

    # Register EquityTrader (handles EQUITY, ETF, REIT, INVIT, SME)
    try:
        from core.equity_trader import EquityTrader
        et = EquityTrader(cfg=cfg, execute_entry_fn=exec_entry, execute_exit_fn=exec_exit)
        dispatcher.register_engine(AssetClass.EQUITY, _make_handler_for_equity(et, "equity_trader", "EQUITY"), engine_name="equity_trader")
        _log.info("[DISPATCH] Registered EquityTrader with %d symbols", len(et.all_symbols))
    except (ImportError, ValueError, TypeError) as exc:
        _log.debug("[DISPATCH] EquityTrader registration skipped: %s", exc)

    # Register FuturesTrader (handles FUTURES, and COMMODITY/CURRENCY as fallback)
    try:
        from core.strategy.futures_trader import FuturesTrader
        ft = FuturesTrader(cfg=cfg, execute_entry_fn=exec_entry, execute_exit_fn=exec_exit)
        dispatcher.register_engine(AssetClass.FUTURES, _make_handler(ft, "futures_trader", "FUTURES"), engine_name="futures_trader")
        _log.info("[DISPATCH] Registered FuturesTrader with %d symbols", len(ft.all_symbols))
    except (ImportError, ValueError, TypeError) as exc:
        _log.debug("[DISPATCH] FuturesTrader registration skipped: %s", exc)

    # Register CommodityTrader
    try:
        from core.commodity_trader import CommodityTrader
        ct = CommodityTrader(cfg=cfg, execute_entry_fn=exec_entry, execute_exit_fn=exec_exit)
        dispatcher.register_engine(AssetClass.COMMODITY, _make_handler(ct, "commodity_trader", "COMMODITY"), engine_name="commodity_trader")
        _log.info("[DISPATCH] Registered CommodityTrader with %d symbols", len(ct.all_symbols))
    except (ImportError, ValueError, TypeError) as exc:
        _log.debug("[DISPATCH] CommodityTrader registration skipped: %s", exc)

    # Register CurrencyTrader
    try:
        from core.currency_trader import CurrencyTrader
        cct = CurrencyTrader(cfg=cfg, execute_entry_fn=exec_entry, execute_exit_fn=exec_exit)
        dispatcher.register_engine(AssetClass.CURRENCY, _make_handler(cct, "currency_trader", "CURRENCY"), engine_name="currency_trader")
        _log.info("[DISPATCH] Registered CurrencyTrader with %d symbols", len(cct.all_symbols))
    except (ImportError, ValueError, TypeError) as exc:
        _log.debug("[DISPATCH] CurrencyTrader registration skipped: %s", exc)

    # Register ETFTrader (dedicated ETF engine with NAV/premium monitoring)
    try:
        from core.etf_trader import ETFTrader
        etf = ETFTrader(cfg=cfg, execute_entry_fn=exec_entry, execute_exit_fn=exec_exit)
        dispatcher.register_engine(AssetClass.ETF, _make_handler(etf, "etf_trader", "ETF"), engine_name="etf_trader")
        _log.info("[DISPATCH] Registered ETFTrader with %d symbols", len(etf.all_symbols))
    except (ImportError, ValueError, TypeError) as exc:
        _log.debug("[DISPATCH] ETFTrader registration skipped: %s", exc)

    # Register REITTrader (dedicated REIT/InvIT engine with distribution yield tracking)
    try:
        from core.reit_trader import REITTrader
        reit = REITTrader(cfg=cfg, execute_entry_fn=exec_entry, execute_exit_fn=exec_exit)
        dispatcher.register_engine(AssetClass.REIT, _make_handler(reit, "reit_trader", "REIT"), engine_name="reit_trader")
        dispatcher.register_engine(AssetClass.INVIT, _make_handler(reit, "reit_trader", "INVIT"), engine_name="reit_trader")
        _log.info("[DISPATCH] Registered REITTrader with %d symbols", len(reit.all_symbols))
    except (ImportError, ValueError, TypeError) as exc:
        _log.debug("[DISPATCH] REITTrader registration skipped: %s", exc)

    # Register IPOTrader (IPO/FPO/OFS/QIP tracking and listing-day trading)
    try:
        from core.ipo_trader import IPOTrader
        ipot = IPOTrader(cfg=cfg, execute_entry_fn=exec_entry, execute_exit_fn=exec_exit)
        dispatcher.register_engine(AssetClass.IPO, _make_handler(ipot, "ipo_trader", "IPO"), engine_name="ipo_trader")
        _log.info("[DISPATCH] Registered IPOTrader with %d symbols", len(ipot.all_symbols))
    except (ImportError, ValueError, TypeError) as exc:
        _log.debug("[DISPATCH] IPOTrader registration skipped: %s", exc)

    # Register IndexOptions handler (INDEX_OPTIONS — always available for NIFTY/BANKNIFTY/FINNIFTY)
    try:
        dispatcher.register_engine(
            AssetClass.INDEX_OPTIONS,
            _make_index_options_handler(),
            engine_name="index_trader",
        )
        _log.info("[DISPATCH] Registered IndexOptions handler")
    except (ValueError, TypeError) as exc:
        _log.debug("[DISPATCH] IndexOptions handler registration skipped: %s", exc)

    return dispatcher


def _make_handler(trader: Any, engine_name: str, asset_class: str) -> Callable:
    """Create a handler adapter for any trading engine with enter_position.

    Args:
        trader: Trading engine instance (must have enter_position method).
        engine_name: Name to report in RoutingResult.
        asset_class: Asset class string to report in RoutingResult.

    Returns:
        Handler function compatible with MultiAssetStrategyDispatcher.route().
    """
    def handler(symbol: str, signal: dict[str, Any] | None = None, direction: str = "",
                score: float = 0.0, **kwargs: Any) -> RoutingResult:
        sig = signal or {}
        dir_ = direction or sig.get("direction", "BUY")
        sc = int(score or sig.get("score", 50))
        price = float(sig.get("price", 0) or kwargs.get("entry_price", 0))
        ok = trader.enter_position(symbol, dir_, sc, entry_price=price)
        return RoutingResult(
            handled=ok,
            engine=engine_name,
            asset_class=asset_class,
            action="ENTER" if ok else "SKIP",
            message=f"Entered {symbol} {dir_}" if ok else f"Failed {symbol}",
        )
    return handler


def _make_handler_for_equity(trader: Any, engine_name: str, asset_class: str) -> Callable:
    """Create a handler adapter for EquityTrader (which uses reason= instead of entry_price=).

    EquityTrader.enter_position(symbol, direction, score, reason="") does
    its own price fetching internally, so we don't pass entry_price.

    Args:
        trader: EquityTrader instance.
        engine_name: Name to report in RoutingResult.
        asset_class: Asset class string to report in RoutingResult.

    Returns:
        Handler function compatible with MultiAssetStrategyDispatcher.route().
    """
    def handler(symbol: str, signal: dict[str, Any] | None = None, direction: str = "",
                score: float = 0.0, **kwargs: Any) -> RoutingResult:
        sig = signal or {}
        dir_ = direction or sig.get("direction", "BUY")
        sc = int(score or sig.get("score", 50))
        reason = str(sig.get("reason", "") or kwargs.get("reason", "via_dispatcher"))
        ok = trader.enter_position(symbol, dir_, sc, reason=reason)
        return RoutingResult(
            handled=ok,
            engine=engine_name,
            asset_class=asset_class,
            action="ENTER" if ok else "SKIP",
            message=f"Entered {symbol} {dir_}" if ok else f"Failed {symbol}",
        )
    return handler


def _make_index_options_handler() -> Callable:
    """Create a handler adapter for INDEX_OPTIONS signals.

    Forwards signals to the existing index trading infrastructure via the
    ``index_app.index_trader_interface`` module (lazy-imported). Falls back
    to advisory/logging mode if the interface is unavailable.

    Returns:
        Handler function compatible with ``MultiAssetStrategyDispatcher.route()``.
    """
    # Try to connect to the index trader interface lazily at handler creation time
    _index_controller: Any | None = None
    try:
        from index_app.index_trader_interface import start_trader
        _index_controller = start_trader(paper=True)
    except (ImportError, ValueError, TypeError, AttributeError, OSError) as exc:
        _log.debug("[INDEX_OPTIONS] IndexTrader interface unavailable: %s", exc)

    def handler(
        symbol: str,
        signal: dict[str, Any] | None = None,
        direction: str = "",
        score: float = 0.0,
        **kwargs: Any,
    ) -> RoutingResult:
        sig = signal or {}
        dir_ = direction or sig.get("direction", "")
        sc = int(score or sig.get("score", 50))
        price = float(sig.get("price", 0) or kwargs.get("entry_price", 0))

        if not dir_:
            return RoutingResult(
                handled=False,
                asset_class="INDEX_OPTIONS",
                action="SKIP",
                message=f"No direction for {symbol}",
            )

        # Forward to index trader controller if available
        if _index_controller is not None:
            try:
                _index_controller.scan_signals()
            except (ValueError, TypeError, OSError, RuntimeError) as exc:
                _log.debug("[INDEX_OPTIONS] Controller scan failed: %s", exc)

        # Log advisory signal
        _log.info("[INDEX_OPTIONS] Advisory signal: %s %s score=%d price=%.2f",
                  symbol, dir_, sc, price)

        return RoutingResult(
            handled=True,
            engine="index_trader",
            asset_class="INDEX_OPTIONS",
            action="ENTER",
            message=f"Signal accepted for {symbol} {dir_} score={sc}",
        )

    return handler


class AssetClassDetector:
    """Detects asset class from symbol name and config maps."""

    @staticmethod
    def detect(symbol: str, asset_map_index: dict[str, str] | None = None) -> AssetClass:
        """Detect asset class from a symbol name.

        Args:
            symbol: Trading symbol (e.g., "RELIANCE", "NIFTYBEES", "TCS").
            asset_map_index: Optional pre-built map of symbol -> asset class.

        Returns:
            Detected AssetClass.
        """
        if asset_map_index and symbol in asset_map_index:
            return AssetClass(asset_map_index[symbol])

        # Heuristic detection by symbol name patterns
        if symbol.upper() in ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX"):
            return AssetClass.INDEX_OPTIONS
        if symbol.upper().endswith("BEES") or symbol.upper().endswith("ETF"):
            return AssetClass.ETF
        if symbol.upper().endswith("REIT") and len(symbol) > 4:
            return AssetClass.REIT
        if "INVIT" in symbol.upper():
            return AssetClass.INVIT
        if symbol.upper().startswith("FUT:"):
            return AssetClass.FUTURES
        if symbol.upper().startswith("COM:") or symbol.upper() in ("GOLD", "SILVER", "CRUDEOIL", "NATURALGAS"):
            return AssetClass.COMMODITY
        if symbol.upper().startswith("CUR:") or symbol.upper() in ("USDINR", "EURINR", "GBPINR", "JPYINR"):
            return AssetClass.CURRENCY
        # Known REIT symbols that do not have REIT suffix
        if symbol.upper() in ("EMBASSY", "MINDSPACE", "BROOKFIELD"):
            return AssetClass.REIT
        # Default to EQUITY for single uppercase tickers (most common case)
        if symbol.isupper() and len(symbol) <= 12:
            return AssetClass.EQUITY
        return AssetClass.UNKNOWN


@dataclass
class RoutingResult:
    """Result of routing a signal to a trading engine.

    Attributes:
        handled: Whether the signal was routed to a handler.
        engine: Name of the engine that handled the signal.
        asset_class: Detected asset class.
        action: Action taken (ENTER, EXIT, SKIP, ERROR).
        message: Human-readable result message.
        error: Error message if routing failed.
    """
    handled: bool
    engine: str = ""
    asset_class: str = ""
    action: str = "SKIP"
    message: str = ""
    error: str = ""


class MultiAssetStrategyDispatcher:
    """Routes trading signals to the appropriate asset-specific engine.

    Acts as the single entry point for all trading signals across all
    supported asset classes. Routes to:
      - ETFTrader for ETF
      - REITTrader for REIT, INVIT
      - IPOTrader for IPO/FPO/OFS/QIP
      - EquityTrader for EQUITY, SME
      - IndexTrader for INDEX_OPTIONS (NIFTY, BANKNIFTY, etc.)
      - FuturesTrader for FUTURES
      - CommodityTrader for COMMODITY
      - CurrencyTrader for CURRENCY
      - (Additional traders can be registered dynamically)

    Also provides signal evaluation via the unified SignalEvaluator,
    enabling end-to-end signal→route pipelines.
    """

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        asset_map_index: dict[str, str] | None = None,
    ) -> None:
        self._config = config or {}
        self._lock = threading.RLock()
        self._detector = AssetClassDetector()
        self._asset_map_index = asset_map_index or {}

        # Registered engine handlers: asset_class -> callable(symbol, signal) -> RoutingResult
        self._engines: dict[AssetClass, Callable] = {}
        self._engine_names: dict[AssetClass, str] = {}
        self._routing_log: list[dict[str, Any]] = []
        self._max_log = 1000

        # Signal evaluator (lazy-initialized)
        self._signal_evaluator: Any | None = None

    def _get_signal_evaluator(self) -> Any | None:
        """Get or create the unified SignalEvaluator."""
        if self._signal_evaluator is None:
            try:
                from core.services.signal_evaluator import SignalEvaluator
                self._signal_evaluator = SignalEvaluator(config=self._config)
            except (ImportError, ValueError, TypeError, OSError) as exc:
                _log.warning("[DISPATCH] SignalEvaluator unavailable: %s", exc)
                return None
        return self._signal_evaluator

    def register_engine(
        self,
        asset_class: AssetClass,
        handler: Callable,
        engine_name: str = "",
    ) -> None:
        """Register a trading engine for an asset class.

        Args:
            asset_class: Asset class to handle.
            handler: Callable that accepts (symbol, signal_dict) and returns RoutingResult.
            engine_name: Human-readable engine name for logging.
        """
        with self._lock:
            self._engines[asset_class] = handler
            self._engine_names[asset_class] = engine_name or f"{asset_class.value}_trader"
            _log.info("[DISPATCH] Registered %s for %s", engine_name, asset_class.value)

    def route(
        self,
        symbol: str,
        signal: dict[str, Any] | None = None,
        direction: str = "",
        score: float = 0.0,
        **kwargs: Any,
    ) -> RoutingResult:
        """Route a trading signal to the appropriate engine.

        Args:
            symbol: Trading symbol.
            signal: Signal dict (optional, can use direction/score instead).
            direction: Trade direction (BUY/SELL).
            score: Signal score.
            **kwargs: Additional kwargs passed to the engine handler.

        Returns:
            RoutingResult with routing outcome.
        """
        signal = signal or {}
        if not direction:
            direction = signal.get("direction", "")

        with self._lock:
            asset_class = self._detector.detect(symbol, self._asset_map_index)

            handler = self._engines.get(asset_class)
            if handler is None:
                # Try broader match: FUTURES handler for all derivative classes
                if asset_class in (AssetClass.COMMODITY, AssetClass.CURRENCY, AssetClass.BOND):
                    handler = self._engines.get(AssetClass.FUTURES)
                    if handler:
                        self._engine_names.get(AssetClass.FUTURES, "futures_trader")
                        _log.info("[DISPATCH] Falling back futures handler for %s -> %s", symbol, asset_class.value)

            if handler is None:
                msg = f"No engine registered for {symbol} (asset_class={asset_class.value})"
                _log.warning("[DISPATCH] %s", msg)
                self._log_routing(symbol, asset_class.value, "SKIP", msg)
                return RoutingResult(
                    handled=False,
                    asset_class=asset_class.value,
                    message=msg,
                )

            try:
                result = handler(symbol=symbol, signal=signal, direction=direction, score=score, **kwargs)
                if not isinstance(result, RoutingResult):
                    result = RoutingResult(
                        handled=True,
                        engine=self._engine_names.get(asset_class, "unknown"),
                        asset_class=asset_class.value,
                        action="ENTER",
                        message=f"Signal routed to {self._engine_names.get(asset_class, 'unknown')}",
                    )
                self._log_routing(symbol, asset_class.value, result.action, result.message)
                return result
            except (ValueError, TypeError, AttributeError, OSError) as exc:
                error_msg = f"Engine error for {symbol}: {exc}"
                _log.error("[DISPATCH] %s", error_msg)
                self._log_routing(symbol, asset_class.value, "ERROR", error_msg)
                return RoutingResult(
                    handled=False,
                    engine=self._engine_names.get(asset_class, "unknown"),
                    asset_class=asset_class.value,
                    action="ERROR",
                    error=str(exc),
                    message=error_msg,
                )

    def detect_asset_class(self, symbol: str) -> str:
        """Detect the asset class for a symbol (without routing).

        Args:
            symbol: Trading symbol.

        Returns:
            Asset class name as string.
        """
        return self._detector.detect(symbol, self._asset_map_index).value

    def get_routing_log(self, limit: int = 50) -> list[dict[str, Any]]:
        """Get recent routing log entries.

        Args:
            limit: Max entries to return.

        Returns:
            List of routing log entries.
        """
        with self._lock:
            return list(reversed(self._routing_log))[:limit]

    def get_status(self) -> dict[str, Any]:
        """Get dispatcher status with registered engines.

        Returns:
            Dict with engine registrations and routing stats.
        """
        with self._lock:
            return {
                "registered_engines": {
                    k.value: {
                        "name": self._engine_names.get(k, ""),
                        "asset_class": k.value,
                    }
                    for k in self._engines
                },
                "total_routes": len(self._routing_log),
            }

    def evaluate_and_route(
        self,
        symbol: str,
        df1m: pd.DataFrame | None = None,
        df5m: pd.DataFrame | None = None,
        df15m: pd.DataFrame | None = None,
        asset_type: AssetType | None = None,
        min_score: int = 35,
        **kwargs: Any,
    ) -> RoutingResult:
        """Evaluate a signal and route to the appropriate engine in one step.

        Combines the unified ``SignalEvaluator`` with the dispatcher ``route()``
        for an end-to-end signal→route pipeline. If no ``asset_type`` is specified,
        it will be auto-detected from the symbol name.

        Args:
            symbol: Trading symbol.
            df1m: 1-minute OHLCV DataFrame.
            df5m: 5-minute OHLCV DataFrame.
            df15m: 15-minute OHLCV DataFrame.
            asset_type: Optional asset class (auto-detected if None).
            min_score: Minimum score for actionable signals (default 35).
            **kwargs: Additional kwargs passed to SignalEvaluator.evaluate().

        Returns:
            RoutingResult with signal evaluation + routing outcome.
        """
        # Auto-detect asset type if not specified
        if asset_type is None:
            asset_type = self._detector.detect(symbol, self._asset_map_index)

        # Step 1: Evaluate signal
        evaluator = self._get_signal_evaluator()
        if evaluator is None:
            return RoutingResult(
                handled=False,
                asset_class=asset_type.value,
                action="ERROR",
                message=f"SignalEvaluator unavailable for {symbol}",
            )

        signal_result = evaluator.evaluate(
            symbol=symbol,
            asset_type=asset_type,
            df1m=df1m,
            df5m=df5m,
            df15m=df15m,
            **kwargs,
        )

        if signal_result is None:
            return RoutingResult(
                handled=False,
                asset_class=asset_type.value,
                action="SKIP",
                message=f"No actionable signal for {symbol}",
            )

        if not signal_result.is_actionable(min_score=min_score):
            return RoutingResult(
                handled=False,
                asset_class=asset_type.value,
                action="SKIP",
                message=f"Signal below threshold for {symbol}: score={signal_result.score} < {min_score}",
            )

        # Step 2: Route the signal
        return self.route(
            symbol=symbol,
            signal=signal_result.to_dict(),
        )

    def _log_routing(self, symbol: str, asset_class: str, action: str, message: str) -> None:
        """Log a routing event."""
        import time
        self._routing_log.append({
            "timestamp": time.time(),
            "symbol": symbol,
            "asset_class": asset_class,
            "action": action,
            "message": message,
        })
        if len(self._routing_log) > self._max_log:
            self._routing_log.pop(0)


# ── Singleton factory ─────────────────────────────────────────────────────────

_dispatcher: MultiAssetStrategyDispatcher | None = None
_dispatcher_lock = threading.RLock()


def get_dispatcher(config: dict[str, Any] | None = None) -> MultiAssetStrategyDispatcher:
    """Get singleton MultiAssetStrategyDispatcher instance.

    Args:
        config: Optional config dict.

    Returns:
        Shared dispatcher instance.
    """
    global _dispatcher
    with _dispatcher_lock:
        if _dispatcher is None:
            _dispatcher = MultiAssetStrategyDispatcher(config=config)
        return _dispatcher


__all__ = [
    "AssetClass",
    "AssetClassDetector",
    "MultiAssetStrategyDispatcher",
    "RoutingResult",
    "get_dispatcher",
]
