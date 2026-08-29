"""
Upstox Broker Adapter - Upstox API v2 implementation of ``LegacyBrokerPort``.

Built from Upstox's official first-party REST API docs (verified
2026-08-21, https://upstox.com/developer/api-documentation/): Place
Order, Modify Order, Cancel Order, Get Order Details, and Get Positions
pages. First-party product with fixed base URLs (like Kite/mStock/Groww),
so those URLs are safely hardcoded here.

Architecture invariant
-----------------------
ALL broker API calls MUST go through a ``BrokerPort`` implementation.
Never call the Upstox REST API directly from core modules.

Verified endpoints (do not add endpoints below without re-checking the
docs first - do not guess a URL and ship it as if verified). Note the
**two different hosts** - order mutation calls use the low-latency
"api-hft" host, reads use the regular "api" host:
    POST   https://api-hft.upstox.com/v2/order/place   - place order
    PUT    https://api-hft.upstox.com/v2/order/modify  - modify order
    DELETE https://api-hft.upstox.com/v2/order/cancel  - cancel order (order_id query param)
    GET    https://api.upstox.com/v2/order/details     - order status/fill (order_id query param)
    GET    https://api.upstox.com/v2/portfolio/short-term-positions - net positions

Authentication: this adapter accepts an already-obtained ``access_token``
(same convention as Kite/mStock/Groww) - Upstox's login is a browser-based
OAuth2 redirect flow (authorize URL + code exchange), handled outside this
adapter, same as Kite Connect's own browser login isn't handled inside
``KiteBrokerAdapter`` either.

NOT verified against real docs (left unimplemented rather than guessed):
live quote/LTP and historical-data endpoints, and ``instrument_token``
resolution from a plain trading symbol - Upstox's instrument master/search
endpoint wasn't part of the docs pages checked here. ``place_order()``
requires the caller to supply an already-resolved ``instrument_token``
(same pattern as IIFL's ``exchange_instrument_id`` gap).
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

try:
    import requests

    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False
    requests = None  # type: ignore[assignment]

_HFT_BASE_URL = "https://api-hft.upstox.com/v2"
_BASE_URL = "https://api.upstox.com/v2"


class _UpstoxContext:
    """Minimal context needed by the Upstox adapter."""

    __slots__ = ("access_token", "log_fn", "enable_rate_limit", "max_retries")

    def __init__(
        self,
        access_token: str,
        log_fn: Callable[[str], None],
        enable_rate_limit: bool = True,
        max_retries: int = 3,
    ) -> None:
        self.access_token = access_token
        self.log_fn = log_fn
        self.enable_rate_limit = enable_rate_limit
        self.max_retries = max_retries


def _classify_upstox_error(exc: Exception) -> str:
    msg = str(exc).lower()
    if "401" in msg or "token" in msg or "auth" in msg:
        return "TOKEN_EXPIRED"
    if "timeout" in msg or "timed out" in msg:
        return "TIMEOUT"
    if "429" in msg or "rate" in msg or "limit" in msg:
        return "RATE_LIMITED"
    if "rejected" in msg:
        return "ORDER_REJECTED"
    if "margin" in msg or "insufficient" in msg:
        return "MARGIN_INSUFFICIENT"
    return "UNKNOWN"


class UpstoxBrokerAdapter(LegacyBrokerPort):
    """Upstox broker adapter - first-party REST API v2.

    ``order.instrument_token`` (an extra, duck-typed attribute beyond the
    base ``Order`` dataclass fields - same pattern IIFL's adapter uses for
    ``order.exchange_instrument_id``) must already be resolved by the
    caller; see the module docstring for why this adapter doesn't resolve
    it itself.
    """

    def __init__(self, ctx: _UpstoxContext) -> None:
        if not REQUESTS_AVAILABLE:
            raise ImportError(
                "requests library is not available. Install it with: pip install requests"
            )

        self._access_token = ctx.access_token
        self._log_fn = ctx.log_fn
        self._enable_rate_limit = ctx.enable_rate_limit
        self._max_retries = ctx.max_retries

        self._session: Any = None
        self._connected = False

        self._last_request_time: float = 0.0
        self._min_request_interval: float = 0.05

    # ── Connection management ────────────────────────────────────────────────

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {self._access_token}",
        }

    def connect(self) -> bool:
        """Verify credentials by calling the positions endpoint."""
        try:
            self._session = requests.Session()
            self._make_request("GET", _BASE_URL, "/portfolio/short-term-positions")
            self._connected = True
            self._log_fn("[UPSTOX] Connected - positions endpoint reachable")
            return True
        except (OSError, ConnectionError, TimeoutError, RuntimeError, ValueError, TypeError) as exc:
            self._connected = False
            self._log_fn(f"[UPSTOX] connect() failed: {_classify_upstox_error(exc)} - {exc}")
            return False

    def disconnect(self) -> None:
        if self._session is not None:
            try:
                self._session.close()
            except (OSError, RuntimeError):
                pass
        self._session = None
        self._connected = False
        self._log_fn("[UPSTOX] Disconnected")

    # ── Rate limiting & retries ──────────────────────────────────────────────

    def _rate_limit(self) -> None:
        if not self._enable_rate_limit:
            return
        elapsed = time.time() - self._last_request_time
        if elapsed < self._min_request_interval:
            time.sleep(self._min_request_interval - elapsed)
        self._last_request_time = time.time()

    def _make_request(
        self, method: str, base: str, path: str, *,
        json_body: dict[str, Any] | None = None, params: dict[str, Any] | None = None,
    ) -> Any:
        if self._session is None:
            self._session = requests.Session()
        url = f"{base}{path}"
        last_exc: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                self._rate_limit()
                response = self._session.request(
                    method, url, json=json_body, params=params, headers=self._headers(), timeout=10,
                )
                if response.status_code == 401:
                    raise RuntimeError(f"401 Unauthorized: {response.text[:200]}")
                if response.status_code == 429:
                    raise RuntimeError(f"429 Rate limited: {response.text[:200]}")
                body = response.json()
                if body.get("status") == "error":
                    raise RuntimeError(f"Upstox error: {body}")
                if response.status_code >= 400:
                    raise RuntimeError(f"{response.status_code} error: {response.text[:200]}")
                return body.get("data")
            except Exception as exc:  # noqa: BLE001 - classify below, then re-raise/retry
                last_exc = exc
                category = _classify_upstox_error(exc)
                if category == "TOKEN_EXPIRED":
                    break
                if attempt < self._max_retries - 1:
                    backoff = (2.0 ** attempt) * 0.5
                    self._log_fn(
                        f"[UPSTOX] Retry {attempt + 1}/{self._max_retries} "
                        f"after {category} - backing off {backoff:.1f}s"
                    )
                    time.sleep(backoff)
        raise RuntimeError(
            f"Upstox API call failed after {self._max_retries} retries: "
            f"{_classify_upstox_error(last_exc)} - {last_exc}"
        ) from last_exc

    # ── BrokerPort interface ─────────────────────────────────────────────────

    def place_order(self, order: Order) -> str:
        if not self._connected:
            raise RuntimeError("Upstox adapter is not connected - call connect() first") from None

        instrument_token = getattr(order, "instrument_token", None)
        if instrument_token is None:
            raise RuntimeError(
                "Upstox place_order requires order.instrument_token to be "
                "pre-resolved by the caller - see module docstring, this "
                "adapter does not implement symbol->instrument-token lookup"
            )

        direction = str(getattr(order, "direction", "BUY")).upper()
        order_type = str(getattr(order, "order_type", "MARKET")).upper()
        if order_type not in ("MARKET", "LIMIT", "SL", "SL-M"):
            order_type = "MARKET"

        try:
            result = self._make_request(
                "POST", _HFT_BASE_URL, "/order/place",
                json_body={
                    "quantity": int(getattr(order, "quantity", 1)),
                    "product": getattr(order, "product", "I"),
                    "validity": "DAY",
                    "price": float(getattr(order, "price", 0.0) or 0.0),
                    "instrument_token": str(instrument_token),
                    "order_type": order_type,
                    "transaction_type": "BUY" if direction == "BUY" else "SELL",
                    "disclosed_quantity": 0,
                    "trigger_price": float(getattr(order, "trigger_price", 0.0) or 0.0),
                    "is_amo": False,
                },
            )
            order_id = str((result or {}).get("order_id", ""))
            if not order_id:
                raise RuntimeError(f"place_order returned no order_id: {result}")
            return order_id
        except RuntimeError:
            raise
        except (OSError, ConnectionError, TimeoutError, ValueError, TypeError) as exc:
            raise RuntimeError(
                f"place_order failed: {_classify_upstox_error(exc)} - {exc}"
            ) from exc

    def cancel_order(self, order_id: str) -> bool:
        if not self._connected:
            return False
        try:
            self._make_request("DELETE", _HFT_BASE_URL, "/order/cancel", params={"order_id": order_id})
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
        if not self._connected:
            return False
        try:
            body: dict[str, Any] = {
                "order_id": order_id,
                "validity": "DAY",
                "order_type": "LIMIT" if price is not None else "MARKET",
                "price": price if price is not None else 0.0,
                "trigger_price": trigger_price if trigger_price is not None else 0.0,
            }
            if quantity is not None:
                body["quantity"] = quantity
            self._make_request("PUT", _HFT_BASE_URL, "/order/modify", json_body=body)
            return True
        except (OSError, ConnectionError, TimeoutError, RuntimeError, ValueError, TypeError):
            return False

    def get_order_status(self, order_id: str) -> str:
        if not self._connected:
            return "ERROR"
        try:
            result = self._make_request("GET", _BASE_URL, "/order/details", params={"order_id": order_id})
            return str((result or {}).get("status", "UNKNOWN"))
        except (OSError, ConnectionError, TimeoutError, RuntimeError, ValueError, TypeError, KeyError):
            return "ERROR"

    def get_fill_price(self, order_id: str) -> float | None:
        """Average fill price for an Upstox order - see KiteBrokerAdapter's
        equivalent method for why every broker adapter must implement this
        itself rather than relying on a generic wrapper default."""
        if not self._connected:
            return None
        try:
            result = self._make_request("GET", _BASE_URL, "/order/details", params={"order_id": order_id})
            return float((result or {}).get("average_price") or 0) or None
        except (OSError, ConnectionError, TimeoutError, RuntimeError, ValueError, TypeError, KeyError):
            return None

    def get_filled_quantity(self, order_id: str) -> int | None:
        if not self._connected:
            return None
        try:
            result = self._make_request("GET", _BASE_URL, "/order/details", params={"order_id": order_id})
            return int((result or {}).get("filled_quantity") or 0)
        except (OSError, ConnectionError, TimeoutError, RuntimeError, ValueError, TypeError, KeyError):
            return None

    def get_positions(self) -> list[Position]:
        if not self._connected:
            return []
        try:
            result = self._make_request("GET", _BASE_URL, "/portfolio/short-term-positions")
            rows = result if isinstance(result, list) else []
            positions: list[Position] = []
            for net in rows:
                qty = int(net.get("quantity", 0) or 0)
                if qty == 0:
                    continue
                positions.append(
                    Position(
                        symbol=str(net.get("trading_symbol", "")),
                        quantity=qty,
                        average_price=float(net.get("average_price", 0.0) or 0.0),
                        market_value=float(qty) * float(net.get("last_price", 0.0) or 0.0),
                        unrealized_pnl=float(net.get("unrealised", 0.0) or 0.0),
                        realized_pnl=float(net.get("realised", 0.0) or 0.0),
                        timestamp=None,
                    )
                )
            return positions
        except (OSError, ConnectionError, TimeoutError, RuntimeError, ValueError, TypeError, KeyError):
            return []

    def get_quote(self, symbol: str) -> Quote:
        """Not implemented - Upstox's market-quote endpoint and the
        symbol->instrument_token lookup weren't part of the docs pages
        verified for this adapter. Do not fabricate a URL; the core bot's
        signal pipeline uses yfinance for quotes regardless."""
        raise NotImplementedError(
            "UpstoxBrokerAdapter.get_quote: Upstox market-data/instrument "
            "lookup not yet verified against real docs - see module docstring"
        )

    def subscribe_to_market_data(
        self, symbols: list[str], callback: Callable[[Quote], None],
    ) -> bool:
        return False

    def unsubscribe_from_market_data(self, symbol: str) -> bool:
        return False

    def get_historical_data(
        self, symbol: str, from_date: datetime, to_date: datetime, interval: str = "day",
    ) -> list[dict[str, Any]]:
        """Not implemented - see get_quote() docstring; same verification gap."""
        raise NotImplementedError(
            "UpstoxBrokerAdapter.get_historical_data: Upstox historical-data "
            "endpoint not yet verified against real docs - see module docstring"
        )

    def health_check(self) -> dict[str, Any]:
        if not self._connected:
            return {"status": "unhealthy", "connected": False, "error": "Adapter not connected"}
        try:
            start = time.time()
            self._make_request("GET", _BASE_URL, "/portfolio/short-term-positions")
            latency = (time.time() - start) * 1000.0
            return {
                "status": "healthy",
                "connected": True,
                "latency_ms": round(latency, 1),
                "auth_status": "connected",
            }
        except (OSError, ConnectionError, TimeoutError, RuntimeError, ValueError, TypeError) as exc:
            return {
                "status": "unhealthy",
                "connected": False,
                "error": _classify_upstox_error(exc),
                "detail": str(exc),
            }


# ── Factory functions ─────────────────────────────────────────────────────────

def create_upstox_adapter(
    *,
    access_token: str,
    log_fn: Callable[[str], None] = _log.info,
    enable_rate_limit: bool = True,
    max_retries: int = 3,
) -> UpstoxBrokerAdapter:
    """Factory: build a fully-connected UpstoxBrokerAdapter from a raw access token."""
    ctx = _UpstoxContext(
        access_token=access_token,
        log_fn=log_fn,
        enable_rate_limit=enable_rate_limit,
        max_retries=max_retries,
    )
    return UpstoxBrokerAdapter(ctx)


def create_upstox_adapter_from_context(context: Any) -> UpstoxBrokerAdapter:
    """Factory: build an UpstoxBrokerAdapter from ``BrokerRuntimeContext``,
    mirroring ``create_kite_adapter_from_context``/``create_mstock_adapter_from_context``.
    """
    cfg = context.cfg
    log_fn = context.log_fn

    bc = cfg.get("BROKER_CONFIG") or {}
    access_token = str(bc.get("access_token") or cfg.get("UPSTOX_ACCESS_TOKEN") or "").strip()

    if not access_token:
        raise ValueError("UPSTOX_ACCESS_TOKEN not found in BROKER_CONFIG.access_token or top-level config")

    return create_upstox_adapter(
        access_token=access_token,
        log_fn=log_fn,
        enable_rate_limit=bool(cfg.get("enable_rate_limit", True)),
        max_retries=int(cfg.get("max_retries", 3)),
    )
