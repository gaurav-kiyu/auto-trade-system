"""
Dhan Broker Adapter - DhanHQ API v2 implementation of ``LegacyBrokerPort``.

Built from the official DhanHQ-py Python SDK source (verified 2026-08-21,
https://github.com/dhan-oss/DhanHQ-py: dhan_http.py, _order.py,
_portfolio.py, _statement.py) rather than the marketing docs site, which
didn't expose raw endpoint/field details on the pages checked. First-party
product with a fixed base URL (like Kite/mStock/Groww/Upstox).

Architecture invariant
-----------------------
ALL broker API calls MUST go through a ``BrokerPort`` implementation.
Never call the Dhan REST API directly from core modules.

Verified endpoints (do not add endpoints below without re-checking the
SDK source first - do not guess a URL and ship it as if verified):
    POST   https://api.dhan.co/v2/orders            - place order
    PUT    https://api.dhan.co/v2/orders/{order_id}  - modify order
    DELETE https://api.dhan.co/v2/orders/{order_id}  - cancel order
    GET    https://api.dhan.co/v2/orders/{order_id}  - order status
    GET    https://api.dhan.co/v2/trades/{order_id}  - trade/fill detail for an order
    GET    https://api.dhan.co/v2/positions          - net positions

Authentication headers (confirmed from dhan_http.py's DhanHTTP.__init__):
    "access-token": <token>
    "client-id": <dhan client id>
(Not a Bearer scheme - Dhan uses two separate plain headers, unlike every
other broker adapter in this codebase.)

IMPORTANT CONFIDENCE NOTE ON FILL REPORTING: unlike Kite/mStock/IIFL/
Groww/Upstox, Dhan's order-detail response does NOT appear to carry an
average-fill-price field directly (confirmed absent from the v1 docs
example checked) - per-fill price/quantity instead lives in the separate
"trade book" endpoint (``GET /trades/{order_id}``), confirmed to exist in
the SDK source with a `tradedPrice` field. The exact per-trade *quantity*
field name in that response was NOT independently confirmed (only the
price field name was) - ``get_filled_quantity()`` below is therefore a
best-effort implementation, not a fully-verified one like the other
adapters' equivalent methods. Verify the real trade-book response shape
against a live/sandbox order before trusting this for real capital.

NOT verified against real docs (left unimplemented rather than guessed):
live quote/LTP and historical-data endpoints, and securityId resolution
from a plain trading symbol (Dhan's instrument master CSV/search wasn't
checked here). ``place_order()`` requires the caller to supply an
already-resolved ``security_id``, same pattern as IIFL/Upstox.
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

_BASE_URL = "https://api.dhan.co/v2"


class _DhanContext:
    """Minimal context needed by the Dhan adapter."""

    __slots__ = ("client_id", "access_token", "log_fn", "enable_rate_limit", "max_retries")

    def __init__(
        self,
        client_id: str,
        access_token: str,
        log_fn: Callable[[str], None],
        enable_rate_limit: bool = True,
        max_retries: int = 3,
    ) -> None:
        self.client_id = client_id
        self.access_token = access_token
        self.log_fn = log_fn
        self.enable_rate_limit = enable_rate_limit
        self.max_retries = max_retries


def _classify_dhan_error(exc: Exception) -> str:
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


class DhanBrokerAdapter(LegacyBrokerPort):
    """Dhan broker adapter - DhanHQ API v2.

    ``order.security_id`` (an extra, duck-typed attribute beyond the base
    ``Order`` dataclass fields - same pattern IIFL/Upstox use for their own
    instrument-ID fields) must already be resolved by the caller; see the
    module docstring for why this adapter doesn't resolve it itself.
    """

    def __init__(self, ctx: _DhanContext) -> None:
        if not REQUESTS_AVAILABLE:
            raise ImportError(
                "requests library is not available. Install it with: pip install requests"
            )

        self._client_id = ctx.client_id
        self._access_token = ctx.access_token
        self._log_fn = ctx.log_fn
        self._enable_rate_limit = ctx.enable_rate_limit
        self._max_retries = ctx.max_retries

        self._session: Any = None
        self._connected = False

        self._last_request_time: float = 0.0
        self._min_request_interval: float = 0.1

    # ── Connection management ────────────────────────────────────────────────

    def _headers(self) -> dict[str, str]:
        return {
            "access-token": self._access_token,
            "client-id": self._client_id,
            "Content-type": "application/json",
            "Accept": "application/json",
        }

    def connect(self) -> bool:
        """Verify credentials by calling the positions endpoint."""
        try:
            self._session = requests.Session()
            self._make_request("GET", "/positions")
            self._connected = True
            self._log_fn("[DHAN] Connected - positions endpoint reachable")
            return True
        except (OSError, ConnectionError, TimeoutError, RuntimeError, ValueError, TypeError) as exc:
            self._connected = False
            self._log_fn(f"[DHAN] connect() failed: {_classify_dhan_error(exc)} - {exc}")
            return False

    def disconnect(self) -> None:
        if self._session is not None:
            try:
                self._session.close()
            except (OSError, RuntimeError):
                pass
        self._session = None
        self._connected = False
        self._log_fn("[DHAN] Disconnected")

    # ── Rate limiting & retries ──────────────────────────────────────────────

    def _rate_limit(self) -> None:
        if not self._enable_rate_limit:
            return
        elapsed = time.time() - self._last_request_time
        if elapsed < self._min_request_interval:
            time.sleep(self._min_request_interval - elapsed)
        self._last_request_time = time.time()

    def _make_request(
        self, method: str, path: str, *, json_body: dict[str, Any] | None = None,
    ) -> Any:
        if self._session is None:
            self._session = requests.Session()
        url = f"{_BASE_URL}{path}"
        last_exc: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                self._rate_limit()
                response = self._session.request(
                    method, url, json=json_body, headers=self._headers(), timeout=10,
                )
                if response.status_code == 401:
                    raise RuntimeError(f"401 Unauthorized: {response.text[:200]}")
                if response.status_code == 429:
                    raise RuntimeError(f"429 Rate limited: {response.text[:200]}")
                if response.status_code >= 400:
                    raise RuntimeError(f"{response.status_code} error: {response.text[:200]}")
                return response.json()
            except Exception as exc:  # noqa: BLE001 - classify below, then re-raise/retry
                last_exc = exc
                category = _classify_dhan_error(exc)
                if category == "TOKEN_EXPIRED":
                    break
                if attempt < self._max_retries - 1:
                    backoff = (2.0 ** attempt) * 0.5
                    self._log_fn(
                        f"[DHAN] Retry {attempt + 1}/{self._max_retries} "
                        f"after {category} - backing off {backoff:.1f}s"
                    )
                    time.sleep(backoff)
        raise RuntimeError(
            f"Dhan API call failed after {self._max_retries} retries: "
            f"{_classify_dhan_error(last_exc)} - {last_exc}"
        ) from last_exc

    # ── BrokerPort interface ─────────────────────────────────────────────────

    def place_order(self, order: Order) -> str:
        if not self._connected:
            raise RuntimeError("Dhan adapter is not connected - call connect() first") from None

        security_id = getattr(order, "security_id", None)
        if security_id is None:
            raise RuntimeError(
                "Dhan place_order requires order.security_id to be "
                "pre-resolved by the caller - see module docstring, this "
                "adapter does not implement symbol->security-ID lookup"
            )

        direction = str(getattr(order, "direction", "BUY")).upper()
        order_type = str(getattr(order, "order_type", "MARKET")).upper()
        if order_type not in ("MARKET", "LIMIT", "SL", "SL-M"):
            order_type = "MARKET"

        try:
            result = self._make_request(
                "POST", "/orders",
                json_body={
                    "dhanClientId": self._client_id,
                    "transactionType": "BUY" if direction == "BUY" else "SELL",
                    "exchangeSegment": getattr(order, "exchange_segment", "NSE_FNO"),
                    "productType": getattr(order, "product", "INTRADAY"),
                    "orderType": order_type,
                    "validity": "DAY",
                    "securityId": str(security_id),
                    "quantity": int(getattr(order, "quantity", 1)),
                    "disclosedQuantity": 0,
                    "price": float(getattr(order, "price", 0.0) or 0.0),
                    "triggerPrice": float(getattr(order, "trigger_price", 0.0) or 0.0),
                    "afterMarketOrder": False,
                },
            )
            order_id = str((result or {}).get("orderId", ""))
            if not order_id:
                raise RuntimeError(f"place_order returned no orderId: {result}")
            return order_id
        except RuntimeError:
            raise
        except (OSError, ConnectionError, TimeoutError, ValueError, TypeError) as exc:
            raise RuntimeError(
                f"place_order failed: {_classify_dhan_error(exc)} - {exc}"
            ) from exc

    def cancel_order(self, order_id: str) -> bool:
        if not self._connected:
            return False
        try:
            self._make_request("DELETE", f"/orders/{order_id}")
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
                "dhanClientId": self._client_id,
                "orderId": order_id,
                "validity": "DAY",
                "orderType": "LIMIT" if price is not None else "MARKET",
            }
            if quantity is not None:
                body["quantity"] = quantity
            if price is not None:
                body["price"] = price
            if trigger_price is not None:
                body["triggerPrice"] = trigger_price
            self._make_request("PUT", f"/orders/{order_id}", json_body=body)
            return True
        except (OSError, ConnectionError, TimeoutError, RuntimeError, ValueError, TypeError):
            return False

    def get_order_status(self, order_id: str) -> str:
        if not self._connected:
            return "ERROR"
        try:
            result = self._make_request("GET", f"/orders/{order_id}")
            return str((result or {}).get("orderStatus", "UNKNOWN"))
        except (OSError, ConnectionError, TimeoutError, RuntimeError, ValueError, TypeError, KeyError):
            return "ERROR"

    def get_fill_price(self, order_id: str) -> float | None:
        """Average fill price for a Dhan order, from the trade book
        endpoint (NOT the order-detail endpoint - see module docstring's
        confidence note; unlike every other adapter here, this required a
        second endpoint since Dhan's order object doesn't carry fill price).
        Averages across all trade fills for this order_id if there were
        multiple partial fills.
        """
        if not self._connected:
            return None
        try:
            result = self._make_request("GET", f"/trades/{order_id}")
            trades = result if isinstance(result, list) else [result] if result else []
            filled = [(float(t.get("tradedPrice") or 0), int(t.get("tradedQuantity") or 0))
                      for t in trades if t.get("tradedPrice")]
            filled = [(p, q) for p, q in filled if q > 0]
            if not filled:
                return None
            total_qty = sum(q for _, q in filled)
            if total_qty <= 0:
                return None
            return sum(p * q for p, q in filled) / total_qty
        except (OSError, ConnectionError, TimeoutError, RuntimeError, ValueError, TypeError, KeyError):
            return None

    def get_filled_quantity(self, order_id: str) -> int | None:
        """Best-effort - see get_fill_price() docstring re: unconfirmed
        per-trade quantity field name. Falls back to the order object's
        own quantity fields if the trade book gives nothing usable."""
        if not self._connected:
            return None
        try:
            result = self._make_request("GET", f"/trades/{order_id}")
            trades = result if isinstance(result, list) else [result] if result else []
            total = sum(int(t.get("tradedQuantity") or 0) for t in trades)
            if total > 0:
                return total
            order_result = self._make_request("GET", f"/orders/{order_id}")
            return int((order_result or {}).get("filledQty", (order_result or {}).get("filled_qty", 0)) or 0)
        except (OSError, ConnectionError, TimeoutError, RuntimeError, ValueError, TypeError, KeyError):
            return None

    def get_positions(self) -> list[Position]:
        """Field names below are inferred from Dhan's documented camelCase
        convention elsewhere (orderStatus, disclosedQuantity, etc.) since
        the positions response schema itself wasn't independently
        confirmed - verify against a real response before trusting this."""
        if not self._connected:
            return []
        try:
            result = self._make_request("GET", "/positions")
            rows = result if isinstance(result, list) else []
            positions: list[Position] = []
            for net in rows:
                qty = int(net.get("netQty", 0) or 0)
                if qty == 0:
                    continue
                positions.append(
                    Position(
                        symbol=str(net.get("tradingSymbol", net.get("securityId", ""))),
                        quantity=qty,
                        average_price=float(net.get("costPrice", 0.0) or 0.0),
                        market_value=float(qty) * float(net.get("lastTradedPrice", 0.0) or 0.0),
                        unrealized_pnl=float(net.get("unrealizedProfit", 0.0) or 0.0),
                        realized_pnl=float(net.get("realizedProfit", 0.0) or 0.0),
                        timestamp=None,
                    )
                )
            return positions
        except (OSError, ConnectionError, TimeoutError, RuntimeError, ValueError, TypeError, KeyError):
            return []

    def get_quote(self, symbol: str) -> Quote:
        """Not implemented - Dhan's market-quote endpoint and the
        symbol->security_id lookup weren't part of the SDK source verified
        for this adapter. Do not fabricate a URL; the core bot's signal
        pipeline uses yfinance for quotes regardless."""
        raise NotImplementedError(
            "DhanBrokerAdapter.get_quote: Dhan market-data/instrument "
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
            "DhanBrokerAdapter.get_historical_data: Dhan historical-data "
            "endpoint not yet verified against real docs - see module docstring"
        )

    def health_check(self) -> dict[str, Any]:
        if not self._connected:
            return {"status": "unhealthy", "connected": False, "error": "Adapter not connected"}
        try:
            start = time.time()
            self._make_request("GET", "/positions")
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
                "error": _classify_dhan_error(exc),
                "detail": str(exc),
            }


# ── Factory functions ─────────────────────────────────────────────────────────

def create_dhan_adapter(
    *,
    client_id: str,
    access_token: str,
    log_fn: Callable[[str], None] = _log.info,
    enable_rate_limit: bool = True,
    max_retries: int = 3,
) -> DhanBrokerAdapter:
    """Factory: build a fully-connected DhanBrokerAdapter from raw credentials."""
    ctx = _DhanContext(
        client_id=client_id,
        access_token=access_token,
        log_fn=log_fn,
        enable_rate_limit=enable_rate_limit,
        max_retries=max_retries,
    )
    return DhanBrokerAdapter(ctx)


def create_dhan_adapter_from_context(context: Any) -> DhanBrokerAdapter:
    """Factory: build a DhanBrokerAdapter from ``BrokerRuntimeContext``,
    mirroring ``create_kite_adapter_from_context``/``create_mstock_adapter_from_context``.
    """
    cfg = context.cfg
    log_fn = context.log_fn

    bc = cfg.get("BROKER_CONFIG") or {}
    client_id = str(bc.get("user_id") or cfg.get("DHAN_CLIENT_ID") or "").strip()
    access_token = str(bc.get("access_token") or cfg.get("DHAN_ACCESS_TOKEN") or "").strip()

    if not client_id:
        raise ValueError("DHAN_CLIENT_ID not found in BROKER_CONFIG.user_id or top-level config")
    if not access_token:
        raise ValueError("DHAN_ACCESS_TOKEN not found in BROKER_CONFIG.access_token or top-level config")

    return create_dhan_adapter(
        client_id=client_id,
        access_token=access_token,
        log_fn=log_fn,
        enable_rate_limit=bool(cfg.get("enable_rate_limit", True)),
        max_retries=int(cfg.get("max_retries", 3)),
    )
