"""
Kite Broker Adapter - Zerodha Kite Connect implementation of BrokerPort.

This adapter implements the ``BrokerPort`` interface (from
``core.ports.broker``) for the Zerodha Kite Connect API.  It is injected
via ``create_broker_adapter()`` in ``core/adapters/broker_adapters.py``
and wrapped in the legacy ``BrokerAdapter`` compatibility layer.

Architecture invariant
---------------------
ALL broker API calls MUST go through a ``BrokerPort`` implementation.
Never call the Kite Connect SDK directly from core modules.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any

from core.common.kernels.models import Position, Quote
from core.ports.broker import LegacyBrokerPort, Order

_log = logging.getLogger(__name__)

# ── Kite Connect availability ────────────────────────────────────────────────

try:
    import kiteconnect.exceptions as KiteExceptions
    from kiteconnect import KiteConnect

    KITE_AVAILABLE = True
except ImportError:
    KITE_AVAILABLE = False
    KiteConnect = None  # type: ignore[assignment]
    KiteExceptions = None  # type: ignore[assignment]


# ── Runtime context for broker factory (subset of BrokerRuntimeContext) ──────

class _KiteContext:
    """Minimal context needed by the Kite adapter, extracted from
    ``BrokerRuntimeContext`` by :func:`create_kite_adapter`."""

    __slots__ = (
        "api_key", "access_token", "log_fn",
        "enable_rate_limit", "max_retries",
    )

    def __init__(
        self,
        api_key: str,
        access_token: str,
        log_fn: Callable[[str], None],
        enable_rate_limit: bool = True,
        max_retries: int = 3,
    ) -> None:
        self.api_key = api_key
        self.access_token = access_token
        self.log_fn = log_fn
        self.enable_rate_limit = enable_rate_limit
        self.max_retries = max_retries


# ── Helper: map Kite exception to readable message ──────────────────────────

def _kite_isinstance(exc: Exception, exc_cls_name: str) -> bool:
    """Safe ``isinstance()`` check for Kite exception types.

    Guards against:
    - ``KiteExceptions`` being ``None`` (library not installed)
    - Mock or non-type objects returned from ``getattr(KiteExceptions, name)``
    """
    if KiteExceptions is None:
        return False
    cls = getattr(KiteExceptions, exc_cls_name, None)
    if cls is None:
        return False
    try:
        return isinstance(exc, cls)
    except TypeError:
        # cls is not a proper exception type (e.g., a MagicMock from tests)
        return False


def _classify_kite_error(exc: Exception) -> str:
    """Return a human-readable classification of a Kite API error."""
    msg = str(exc).lower()

    # Type-based classification (safe against missing / mocked SDK)
    if _kite_isinstance(exc, "TokenException"):
        return "TOKEN_EXPIRED"
    if _kite_isinstance(exc, "OrderException"):
        return "ORDER_ERROR"
    if _kite_isinstance(exc, "NetworkException"):
        return "NETWORK"
    if _kite_isinstance(exc, "InputException"):
        return "INPUT_ERROR"
    if _kite_isinstance(exc, "DataException"):
        return "DATA_ERROR"
    if _kite_isinstance(exc, "PermissionException"):
        return "PERMISSION_ERROR"

    # Fallback: message-based classification
    if "token" in msg or "auth" in msg:
        return "TOKEN_EXPIRED"
    if "timeout" in msg or "timed out" in msg:
        return "TIMEOUT"
    if "rate" in msg or "limit" in msg:
        return "RATE_LIMITED"
    if "rejected" in msg:
        return "ORDER_REJECTED"
    if "margin" in msg or "insufficient" in msg:
        return "MARGIN_INSUFFICIENT"
    return "UNKNOWN"


class KiteBrokerAdapter(LegacyBrokerPort):
    """Zerodha Kite Connect broker adapter.

    The constructor accepts a ``_KiteContext`` (or duck-typed object with
    the same attributes) to decouple from the full ``BrokerRuntimeContext``.
    The factory function :func:`create_kite_adapter` bridges between the two.
    """

    def __init__(
        self,
        ctx: _KiteContext,
    ) -> None:
        if not KITE_AVAILABLE:
            raise ImportError(
                "KiteConnect library is not available. "
                "Install it with: pip install kiteconnect"
            )

        self._api_key = ctx.api_key
        self._access_token = ctx.access_token
        self._log_fn = ctx.log_fn
        self._enable_rate_limit = ctx.enable_rate_limit
        self._max_retries = ctx.max_retries

        # Kite client
        self._kite: KiteConnect | None = None
        self._connected = False

        # Rate-limit state
        self._last_request_time: float = 0.0
        self._min_request_interval: float = 0.1  # 100 ms

        # Instrument cache
        self._instruments_cache: dict[str, int] | None = None
        self._instruments_cache_time: float = 0.0
        self._cache_ttl: float = 300.0  # 5 minutes

    # ── Connection management ────────────────────────────────────────────────

    def connect(self) -> bool:
        """Initialise the Kite client and verify credentials by calling
        ``profile()``."""
        try:
            self._kite = KiteConnect(api_key=self._api_key)
            self._kite.set_access_token(self._access_token)
            profile = self._make_request(self._kite.profile)
            if profile is not None:
                self._connected = True
                self._log_fn("[KITE] Connected - profile verified")
                return True
            self._connected = False
            self._log_fn("[KITE] connect() returned None profile")
            return False
        except (OSError, ConnectionError, TimeoutError, RuntimeError, ValueError, TypeError) as exc:
            self._connected = False
            self._log_fn(f"[KITE] connect() failed: {_classify_kite_error(exc)} - {exc}")
            return False

    def disconnect(self) -> None:
        """Clear the Kite client reference.  Kite Connect uses HTTP sessions
        managed internally; there is no explicit disconnect."""
        self._kite = None
        self._connected = False
        self._instruments_cache = None
        self._instruments_cache_time = 0.0
        self._log_fn("[KITE] Disconnected")

    # ── Rate limiting & retries ──────────────────────────────────────────────

    def _rate_limit(self) -> None:
        if not self._enable_rate_limit:
            return
        elapsed = time.time() - self._last_request_time
        if elapsed < self._min_request_interval:
            time.sleep(self._min_request_interval - elapsed)
        self._last_request_time = time.time()

    def _make_request(self, func: Callable, *args: Any, **kwargs: Any) -> Any:
        """Execute a Kite API call with rate limiting and retry logic.

        Raises ``RuntimeError`` after exhausting retries.
        """
        last_exc: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                self._rate_limit()
                return func(*args, **kwargs)
            # Controlled supervisor boundary: catch Exception to handle all SDK error types
            # (TokenException, OrderException, NetworkException, etc.) and retry.
            # Re-raises as RuntimeError after exhausting retries - NOT a silent failure.
            except Exception as exc:
                last_exc = exc
                category = _classify_kite_error(exc)
                # Token / auth errors are not retried.
                if category in ("TOKEN_EXPIRED", "PERMISSION_ERROR", "INPUT_ERROR"):
                    break
                if attempt < self._max_retries - 1:
                    backoff = (2.0 ** attempt) * 0.5
                    self._log_fn(
                        f"[KITE] Retry {attempt + 1}/{self._max_retries} "
                        f"after {category} - backing off {backoff:.1f}s"
                    )
                    time.sleep(backoff)
        raise RuntimeError(
            f"Kite API call failed after {self._max_retries} retries: "
            f"{_classify_kite_error(last_exc)} - {last_exc}"
        ) from last_exc

    # ── Instrument token resolution ──────────────────────────────────────────

    def _get_instrument_token(
        self, symbol: str, exchange: str = "NSE"
    ) -> int | None:
        """Resolve a trading symbol to a Kite instrument token."""
        now = time.time()
        if (
            self._instruments_cache is not None
            and now - self._instruments_cache_time < self._cache_ttl
        ):
            instruments = self._instruments_cache
        else:
            try:
                data = self._make_request(self._kite.instruments, exchange)  # type: ignore[union-attr]
            except RuntimeError:
                return None
            instruments = {
                f"{item['tradingsymbol']}|{item['exchange']}": item["instrument_token"]
                for item in data
            }
            self._instruments_cache = instruments
            self._instruments_cache_time = now

        key = f"{symbol}|{exchange}"
        return instruments.get(key)

    # ── BrokerPort interface ─────────────────────────────────────────────────

    def place_order(self, order: Order) -> str:
        """Place a Kite order and return the order ID."""
        if not self._connected or self._kite is None:
            raise RuntimeError("Kite adapter is not connected - call connect() first")

        symbol = getattr(order, "symbol", "")
        instrument_token = self._get_instrument_token(symbol)
        if instrument_token is None:
            raise RuntimeError(f"Cannot resolve instrument token for {symbol}")

        direction = getattr(order, "direction", "BUY")
        transaction_type = (
            self._kite.TRANSACTION_TYPE_BUY
            if direction.upper() == "BUY"
            else self._kite.TRANSACTION_TYPE_SELL
        )

        kite_order_type = {
            "MARKET": self._kite.ORDER_TYPE_MARKET,
            "LIMIT": self._kite.ORDER_TYPE_LIMIT,
            "SL": self._kite.ORDER_TYPE_SL,
            "SL-M": self._kite.ORDER_TYPE_SL_M,
        }.get(getattr(order, "order_type", "MARKET"), self._kite.ORDER_TYPE_MARKET)

        try:
            order_id: str = self._make_request(
                self._kite.place_order,
                variety=self._kite.VARIETY_REGULAR,
                exchange=getattr(order, "exchange", self._kite.EXCHANGE_NSE),
                tradingsymbol=symbol,
                transaction_type=transaction_type,
                quantity=int(getattr(order, "quantity", 1)),
                product=getattr(order, "product", self._kite.PRODUCT_MIS),
                order_type=kite_order_type,
                price=float(getattr(order, "price", 0.0) or 0.0),
                trigger_price=float(getattr(order, "trigger_price", 0.0) or 0.0),
                validity=self._kite.VALIDITY_DAY,
                tag=getattr(order, "tag", ""),
            )
            return order_id
        except RuntimeError:
            raise
        except (OSError, ConnectionError, TimeoutError, ValueError, TypeError) as exc:
            raise RuntimeError(
                f"place_order failed for {symbol}: {_classify_kite_error(exc)} - {exc}"
            ) from exc

    def cancel_order(self, order_id: str) -> bool:
        """Cancel a Kite order.  Returns True on success."""
        if not self._connected or self._kite is None:
            return False
        try:
            self._make_request(
                self._kite.cancel_order,
                variety=self._kite.VARIETY_REGULAR,
                order_id=order_id,
            )
            return True
        except (OSError, ConnectionError, TimeoutError, RuntimeError, ValueError, TypeError):
            return False

    def modify_order(
        self,
        order_id: str,
        quantity: int | None = None,
        price: float | None = None,
        trigger_price: float | None = None,
    ) -> bool:
        """Modify a Kite order.  Returns True on success."""
        if not self._connected or self._kite is None:
            return False
        try:
            self._make_request(
                self._kite.modify_order,
                variety=self._kite.VARIETY_REGULAR,
                order_id=order_id,
                quantity=quantity,
                price=price or 0.0,
                trigger_price=trigger_price or 0.0,
            )
            return True
        except (OSError, ConnectionError, TimeoutError, RuntimeError, ValueError, TypeError):
            return False

    def get_order_status(self, order_id: str) -> str:
        """Return the status string of a Kite order."""
        if not self._connected or self._kite is None:
            return "ERROR"
        try:
            orders = self._make_request(self._kite.orders)
            for o in orders:
                if o.get("order_id") == order_id:
                    return str(o.get("status", "UNKNOWN"))
            return "UNKNOWN"
        except (OSError, ConnectionError, TimeoutError, RuntimeError, ValueError, TypeError, KeyError):
            return "ERROR"

    def get_positions(self) -> list[Position]:
        """Return current net positions from Kite."""
        if not self._connected or self._kite is None:
            return []
        try:
            data = self._make_request(self._kite.positions)
            positions: list[Position] = []
            for net in data.get("net", []):
                qty = int(net.get("quantity", 0))
                if qty == 0:
                    continue
                ts: datetime | None = None
                if "exchange_update_time" in net:
                    try:
                        ts = datetime.fromtimestamp(
                            net["exchange_update_time"] / 1000.0
                        )
                    except (TypeError, ValueError, KeyError, OSError):
                        ts = None
                positions.append(
                    Position(
                        symbol=str(net.get("tradingsymbol", "")),
                        quantity=qty,
                        average_price=float(net.get("average_price", 0.0)),
                        market_value=float(qty) * float(net.get("last_price", 0.0)),
                        unrealized_pnl=float(net.get("pnl", 0.0)),
                        realized_pnl=0.0,
                        timestamp=ts,
                    )
                )
            return positions
        except (OSError, ConnectionError, TimeoutError, RuntimeError, ValueError, TypeError, KeyError):
            return []

    def get_quote(self, symbol: str) -> Quote:
        """Return the current market quote for a symbol."""
        if not self._connected or self._kite is None:
            raise RuntimeError("Kite adapter is not connected - call connect() first")

        instrument_token = self._get_instrument_token(symbol)
        if instrument_token is None:
            raise RuntimeError(f"Cannot resolve instrument token for {symbol}")

        try:
            data = self._make_request(self._kite.quote, [instrument_token])
            info = data.get(str(instrument_token), {})
            return Quote(
                symbol=symbol,
                bid=float(info.get("bid", 0.0) or 0.0),
                ask=float(info.get("ask", 0.0) or 0.0),
                last=float(info.get("last_price", 0.0) or 0.0),
                volume=int(info.get("volume", 0) or 0),
                timestamp=datetime.now(),
            )
        except RuntimeError:
            raise
        except (OSError, ConnectionError, TimeoutError, ValueError, TypeError, KeyError) as exc:
            raise RuntimeError(
                f"get_quote failed for {symbol}: {exc}"
            ) from exc

    def subscribe_to_market_data(
        self,
        symbols: list[str],
        callback: Callable[[Quote], None],
    ) -> bool:
        """Subscribe to real-time ticks.

        .. note::
           Kite Connect requires the separate ``KiteTicker`` WebSocket client
           for streaming ticks.  This method returns ``False`` to indicate
           that streaming is not yet implemented in the synchronous adapter.
        """
        return False

    def unsubscribe_from_market_data(self, symbol: str) -> bool:
        """Unsubscribe from ticks.  Not implemented in the synchronous adapter."""
        return False

    def get_historical_data(
        self,
        symbol: str,
        from_date: datetime,
        to_date: datetime,
        interval: str = "day",
    ) -> list[dict[str, Any]]:
        """Return historical OHLCV bars from Kite."""
        if not self._connected or self._kite is None:
            raise RuntimeError("Kite adapter is not connected - call connect() first")

        instrument_token = self._get_instrument_token(symbol)
        if instrument_token is None:
            raise RuntimeError(f"Cannot resolve instrument token for {symbol}")

        interval_map = {
            "minute": self._kite.INTERVAL_MINUTE,
            "3minute": self._kite.INTERVAL_3MINUTE,
            "5minute": self._kite.INTERVAL_5MINUTE,
            "15minute": self._kite.INTERVAL_15MINUTE,
            "30minute": self._kite.INTERVAL_30MINUTE,
            "60minute": self._kite.INTERVAL_60MINUTE,
            "day": self._kite.INTERVAL_DAY,
        }
        kite_interval = interval_map.get(interval, self._kite.INTERVAL_DAY)

        try:
            result: list[dict[str, Any]] = self._make_request(
                self._kite.historical_data,
                instrument_token,
                from_date,
                to_date,
                kite_interval,
            )
            return result
        except RuntimeError:
            raise
        except (OSError, ConnectionError, TimeoutError, ValueError, TypeError, KeyError) as exc:
            raise RuntimeError(
                f"get_historical_data failed for {symbol}: {exc}"
            ) from exc

    def health_check(self) -> dict[str, Any]:
        """Verify the Kite connection and return status metadata."""
        if not self._connected or self._kite is None:
            return {
                "status": "unhealthy",
                "connected": False,
                "error": "Adapter not connected",
            }
        try:
            start = time.time()
            profile = self._make_request(self._kite.profile)
            latency = (time.time() - start) * 1000.0
            if profile is not None:
                return {
                    "status": "healthy",
                    "connected": True,
                    "latency_ms": round(latency, 1),
                    "auth_status": "connected",
                    "user_id": str(getattr(profile, "user_id", "")),
                }
            return {
                "status": "degraded",
                "connected": False,
                "latency_ms": round(latency, 1),
                "error": "Profile returned None",
            }
        except (OSError, ConnectionError, TimeoutError, RuntimeError, ValueError, TypeError) as exc:
            return {
                "status": "unhealthy",
                "connected": False,
                "error": _classify_kite_error(exc),
                "detail": str(exc),
            }


# ── Factory function ─────────────────────────────────────────────────────────

def create_kite_adapter(
    *,
    api_key: str,
    access_token: str,
    log_fn: Callable[[str], None] = _log.info,
    enable_rate_limit: bool = True,
    max_retries: int = 3,
) -> KiteBrokerAdapter:
    """Factory: build a fully-connected KiteBrokerAdapter from raw credentials.

    This is the primary entry point for tests and manual setup.

    Usage::

        adapter = create_kite_adapter(
            api_key="xxx",
            access_token="yyy",
        )
        adapter.connect()
        positions = adapter.get_positions()
    """
    ctx = _KiteContext(
        api_key=api_key,
        access_token=access_token,
        log_fn=log_fn,
        enable_rate_limit=enable_rate_limit,
        max_retries=max_retries,
    )
    return KiteBrokerAdapter(ctx)


def create_kite_adapter_from_context(
    context: Any,  # BrokerRuntimeContext (duck-typed for import safety)
) -> KiteBrokerAdapter:
    """Factory: build a KiteBrokerAdapter from ``BrokerRuntimeContext``.

    Used by ``create_broker_adapter()`` in ``core/adapters/broker_adapters.py``.

    The *context* object must have at least:
        - ``cfg`` (dict) - config containing ``BROKER_CONFIG`` / ``KITE_*`` keys
        - ``log_fn`` (callable) - logging function
    """
    cfg = context.cfg
    log_fn = context.log_fn

    # Extract credentials in priority: BROKER_CONFIG > KITE_* top-level keys
    bc = cfg.get("BROKER_CONFIG") or {}
    api_key = str(
        bc.get("api_key")
        or cfg.get("KITE_API_KEY")
        or ""
    ).strip()
    access_token = str(
        bc.get("access_token")
        or cfg.get("KITE_ACCESS_TOKEN")
        or ""
    ).strip()

    if not api_key:
        raise ValueError(
            "KITE_API_KEY not found in BROKER_CONFIG or top-level config"
        )
    if not access_token:
        raise ValueError(
            "KITE_ACCESS_TOKEN not found in BROKER_CONFIG or top-level config"
        )

    return create_kite_adapter(
        api_key=api_key,
        access_token=access_token,
        log_fn=log_fn,
        enable_rate_limit=bool(cfg.get("enable_rate_limit", True)),
        max_retries=int(cfg.get("max_retries", 3)),
    )
