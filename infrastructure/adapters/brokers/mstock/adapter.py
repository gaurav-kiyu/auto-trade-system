"""
mStock Broker Adapter - m.Stock (Mirae Asset / Sharekhan) Trading API
implementation of ``LegacyBrokerPort``.

Built from mStock's published REST API documentation (Type A variant,
verified 2026-08-20 against https://tradingapi.mstock.com/docs/v1/typeA/):
Orders, Position, User (login/session) pages. mStock has no official
KiteConnect-style Python SDK maintained by the broker itself (only a
third-party PyPI package of unverified provenance), so this adapter calls
the documented REST endpoints directly via ``requests`` rather than adding
an unverified SDK dependency.

Architecture invariant
-----------------------
ALL broker API calls MUST go through a ``BrokerPort`` implementation.
Never call the mStock REST API directly from core modules.

Verified endpoints (do not add endpoints below without re-checking the
docs - do not guess a URL and ship it as if verified):
    POST   /connect/login              - step 1: username/password -> triggers OTP
    POST   /session/token              - step 2: api_key + OTP + checksum -> access_token
    POST   /session/verifytotp         - step 2 (TOTP alternative) -> access_token
    POST   /orders/{variety}           - place order
    PUT    /orders/regular/{order_id}  - modify order
    DELETE /orders/regular/{order_id}  - cancel order
    GET    /orders                     - order book (status, average_price, filled_quantity)
    GET    /portfolio/positions        - net positions

NOT verified against real docs (left unimplemented rather than guessed -
see get_quote/get_historical_data below): live quote/market-data and
historical-data endpoints. Do not fill these in from memory; re-verify
against https://tradingapi.mstock.com/docs/v1/typeA/ first.
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

# ── requests availability ────────────────────────────────────────────────────

try:
    import requests

    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False
    requests = None  # type: ignore[assignment]

_BASE_URL = "https://api.mstock.trade/openapi/typea"


# ── Runtime context ───────────────────────────────────────────────────────────

class _MStockContext:
    """Minimal context needed by the mStock adapter."""

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


def _classify_mstock_error(exc: Exception) -> str:
    """Return a human-readable classification of an mStock API error."""
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


class MStockBrokerAdapter(LegacyBrokerPort):
    """m.Stock (Mirae Asset) broker adapter — Type A REST API.

    The constructor accepts an already-obtained ``api_key``/``access_token``
    pair (same convention as ``KiteBrokerAdapter``) — the multi-step
    OTP/TOTP login exchange documented at
    https://tradingapi.mstock.com/docs/v1/typeA/User/ happens outside this
    adapter (same as Kite Connect's own browser-based login flow), not
    inside ``connect()``.
    """

    def __init__(self, ctx: _MStockContext) -> None:
        if not REQUESTS_AVAILABLE:
            raise ImportError(
                "requests library is not available. Install it with: pip install requests"
            )

        self._api_key = ctx.api_key
        self._access_token = ctx.access_token
        self._log_fn = ctx.log_fn
        self._enable_rate_limit = ctx.enable_rate_limit
        self._max_retries = ctx.max_retries

        self._session: Any = None
        self._connected = False

        self._last_request_time: float = 0.0
        self._min_request_interval: float = 0.05  # order APIs allow 30/sec

    # ── Connection management ────────────────────────────────────────────────

    def _headers(self, form_encoded: bool = True) -> dict[str, str]:
        headers = {
            "X-Mirae-Version": "1",
            "Authorization": f"token {self._api_key}:{self._access_token}",
        }
        if form_encoded:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        return headers

    def connect(self) -> bool:
        """Verify credentials by calling the order-book endpoint (mStock has
        no dedicated lightweight 'profile' verification endpoint in the
        documented API - the order book is the cheapest authenticated GET
        that confirms the access_token is accepted)."""
        try:
            self._session = requests.Session()
            resp = self._make_request("GET", "/orders")
            if resp is not None:
                self._connected = True
                self._log_fn("[MSTOCK] Connected - order book reachable")
                return True
            self._connected = False
            return False
        except (OSError, ConnectionError, TimeoutError, RuntimeError, ValueError, TypeError) as exc:
            self._connected = False
            self._log_fn(f"[MSTOCK] connect() failed: {_classify_mstock_error(exc)} - {exc}")
            return False

    def disconnect(self) -> None:
        if self._session is not None:
            try:
                self._session.close()
            except (OSError, RuntimeError):
                pass
        self._session = None
        self._connected = False
        self._log_fn("[MSTOCK] Disconnected")

    # ── Rate limiting & retries ──────────────────────────────────────────────

    def _rate_limit(self) -> None:
        if not self._enable_rate_limit:
            return
        elapsed = time.time() - self._last_request_time
        if elapsed < self._min_request_interval:
            time.sleep(self._min_request_interval - elapsed)
        self._last_request_time = time.time()

    def _make_request(
        self, method: str, path: str, *, data: dict[str, Any] | None = None,
    ) -> Any:
        """Execute an mStock REST call with rate limiting and retry logic.

        Raises ``RuntimeError`` after exhausting retries.
        """
        if self._session is None:
            self._session = requests.Session()
        url = f"{_BASE_URL}{path}"
        last_exc: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                self._rate_limit()
                response = self._session.request(
                    method,
                    url,
                    data=data,
                    headers=self._headers(form_encoded=method in ("POST", "PUT")),
                    timeout=10,
                )
                if response.status_code == 401:
                    raise RuntimeError(f"401 Unauthorized: {response.text[:200]}")
                if response.status_code == 429:
                    raise RuntimeError(f"429 Rate limited: {response.text[:200]}")
                if response.status_code >= 400:
                    raise RuntimeError(
                        f"{response.status_code} error: {response.text[:200]}"
                    )
                return response.json()
            except Exception as exc:  # noqa: BLE001 - classify below, then re-raise/retry
                last_exc = exc
                category = _classify_mstock_error(exc)
                if category in ("TOKEN_EXPIRED",):
                    break
                if attempt < self._max_retries - 1:
                    backoff = (2.0 ** attempt) * 0.5
                    self._log_fn(
                        f"[MSTOCK] Retry {attempt + 1}/{self._max_retries} "
                        f"after {category} - backing off {backoff:.1f}s"
                    )
                    time.sleep(backoff)
        raise RuntimeError(
            f"mStock API call failed after {self._max_retries} retries: "
            f"{_classify_mstock_error(last_exc)} - {last_exc}"
        ) from last_exc

    # ── BrokerPort interface ─────────────────────────────────────────────────

    def place_order(self, order: Order) -> str:
        """Place an mStock order and return the order ID."""
        if not self._connected:
            raise RuntimeError("mStock adapter is not connected - call connect() first") from None

        symbol = getattr(order, "symbol", "")
        direction = str(getattr(order, "direction", "BUY")).upper()
        transaction_type = "BUY" if direction == "BUY" else "SELL"
        order_type = str(getattr(order, "order_type", "MARKET")).upper()
        if order_type not in ("MARKET", "LIMIT", "SL", "SL-M"):
            order_type = "MARKET"

        try:
            result = self._make_request(
                "POST",
                "/orders/regular",
                data={
                    "tradingsymbol": symbol,
                    "exchange": getattr(order, "exchange", "NSE"),
                    "transaction_type": transaction_type,
                    "order_type": order_type,
                    "quantity": int(getattr(order, "quantity", 1)),
                    "product": getattr(order, "product", "MIS"),
                    "validity": "DAY",
                    "price": float(getattr(order, "price", 0.0) or 0.0),
                    "trigger_price": float(getattr(order, "trigger_price", 0.0) or 0.0),
                    "variety": "regular",
                },
            )
            order_id = str((result or {}).get("data", {}).get("order_id", ""))
            if not order_id:
                raise RuntimeError(f"place_order returned no order_id: {result}")
            return order_id
        except RuntimeError:
            raise
        except (OSError, ConnectionError, TimeoutError, ValueError, TypeError) as exc:
            raise RuntimeError(
                f"place_order failed for {symbol}: {_classify_mstock_error(exc)} - {exc}"
            ) from exc

    def cancel_order(self, order_id: str) -> bool:
        if not self._connected:
            return False
        try:
            self._make_request("DELETE", f"/orders/regular/{order_id}")
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
            data: dict[str, Any] = {"validity": "DAY"}
            if quantity is not None:
                data["quantity"] = quantity
            if price is not None:
                data["price"] = price
                data["order_type"] = "LIMIT"
            if trigger_price is not None:
                data["trigger_price"] = trigger_price
            self._make_request("PUT", f"/orders/regular/{order_id}", data=data)
            return True
        except (OSError, ConnectionError, TimeoutError, RuntimeError, ValueError, TypeError):
            return False

    def _find_order(self, order_id: str) -> dict[str, Any] | None:
        orders = self._make_request("GET", "/orders")
        rows = (orders or {}).get("data", orders) or []
        if not isinstance(rows, list):
            return None
        for row in rows:
            if str(row.get("order_id", "")) == str(order_id):
                return row
        return None

    def get_order_status(self, order_id: str) -> str:
        if not self._connected:
            return "ERROR"
        try:
            row = self._find_order(order_id)
            return str(row.get("status", "UNKNOWN")) if row else "UNKNOWN"
        except (OSError, ConnectionError, TimeoutError, RuntimeError, ValueError, TypeError, KeyError):
            return "ERROR"

    def get_fill_price(self, order_id: str) -> float | None:
        """Average fill price for an mStock order - see KiteBrokerAdapter's
        equivalent method for why this must exist on every broker adapter,
        not just be assumed available via a generic wrapper."""
        if not self._connected:
            return None
        try:
            row = self._find_order(order_id)
            if row is None:
                return None
            return float(row.get("average_price") or 0) or None
        except (OSError, ConnectionError, TimeoutError, RuntimeError, ValueError, TypeError, KeyError):
            return None

    def get_filled_quantity(self, order_id: str) -> int | None:
        if not self._connected:
            return None
        try:
            row = self._find_order(order_id)
            if row is None:
                return None
            return int(row.get("filled_quantity") or 0)
        except (OSError, ConnectionError, TimeoutError, RuntimeError, ValueError, TypeError, KeyError):
            return None

    def get_positions(self) -> list[Position]:
        if not self._connected:
            return []
        try:
            data = self._make_request("GET", "/portfolio/positions")
            rows = (data or {}).get("data", data) or []
            positions: list[Position] = []
            if not isinstance(rows, list):
                return []
            for net in rows:
                qty = int(net.get("quantity", 0) or 0)
                if qty == 0:
                    continue
                positions.append(
                    Position(
                        symbol=str(net.get("tradingsymbol", "")),
                        quantity=qty,
                        average_price=float(net.get("average_price", 0.0) or 0.0),
                        market_value=float(qty) * float(net.get("last_price", 0.0) or 0.0),
                        unrealized_pnl=float(net.get("pnl", 0.0) or 0.0),
                        realized_pnl=0.0,
                        timestamp=None,
                    )
                )
            return positions
        except (OSError, ConnectionError, TimeoutError, RuntimeError, ValueError, TypeError, KeyError):
            return []

    def get_quote(self, symbol: str) -> Quote:
        """Not implemented - mStock's live-quote/market-data endpoint was
        not part of the docs verified for this adapter (Orders/Position/User
        pages only). Do not fabricate a URL here; verify against
        https://tradingapi.mstock.com/docs/v1/typeA/ (look for a Market
        Data / LTP / Quote page) before implementing. The core bot's
        signal pipeline uses yfinance for quotes regardless, so this only
        matters if something calls this adapter's get_quote() directly."""
        raise NotImplementedError(
            "MStockBrokerAdapter.get_quote: mStock quote endpoint not yet "
            "verified against real API docs - see module docstring"
        )

    def subscribe_to_market_data(
        self, symbols: list[str], callback: Callable[[Quote], None],
    ) -> bool:
        """Streaming not implemented - same as KiteBrokerAdapter's synchronous adapter."""
        return False

    def unsubscribe_from_market_data(self, symbol: str) -> bool:
        return False

    def get_historical_data(
        self, symbol: str, from_date: datetime, to_date: datetime, interval: str = "day",
    ) -> list[dict[str, Any]]:
        """Not implemented - see get_quote() docstring; same verification gap."""
        raise NotImplementedError(
            "MStockBrokerAdapter.get_historical_data: mStock historical-data "
            "endpoint not yet verified against real API docs - see module docstring"
        )

    def health_check(self) -> dict[str, Any]:
        if not self._connected:
            return {
                "status": "unhealthy",
                "connected": False,
                "error": "Adapter not connected",
            }
        try:
            start = time.time()
            self._make_request("GET", "/orders")
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
                "error": _classify_mstock_error(exc),
                "detail": str(exc),
            }


# ── Factory functions ─────────────────────────────────────────────────────────

def create_mstock_adapter(
    *,
    api_key: str,
    access_token: str,
    log_fn: Callable[[str], None] = _log.info,
    enable_rate_limit: bool = True,
    max_retries: int = 3,
) -> MStockBrokerAdapter:
    """Factory: build a fully-connected MStockBrokerAdapter from raw credentials.

    Usage::

        adapter = create_mstock_adapter(api_key="xxx", access_token="yyy")
        adapter.connect()
        positions = adapter.get_positions()
    """
    ctx = _MStockContext(
        api_key=api_key,
        access_token=access_token,
        log_fn=log_fn,
        enable_rate_limit=enable_rate_limit,
        max_retries=max_retries,
    )
    return MStockBrokerAdapter(ctx)


def create_mstock_adapter_from_context(context: Any) -> MStockBrokerAdapter:
    """Factory: build an MStockBrokerAdapter from ``BrokerRuntimeContext``.

    Used by ``create_broker_adapter()`` in ``core/adapters/broker_adapters.py``,
    mirroring ``create_kite_adapter_from_context``.
    """
    cfg = context.cfg
    log_fn = context.log_fn

    bc = cfg.get("BROKER_CONFIG") or {}
    api_key = str(bc.get("api_key") or cfg.get("MSTOCK_API_KEY") or "").strip()
    access_token = str(bc.get("access_token") or cfg.get("MSTOCK_ACCESS_TOKEN") or "").strip()

    if not api_key:
        raise ValueError("MSTOCK_API_KEY not found in BROKER_CONFIG or top-level config")
    if not access_token:
        raise ValueError("MSTOCK_ACCESS_TOKEN not found in BROKER_CONFIG or top-level config")

    return create_mstock_adapter(
        api_key=api_key,
        access_token=access_token,
        log_fn=log_fn,
        enable_rate_limit=bool(cfg.get("enable_rate_limit", True)),
        max_retries=int(cfg.get("max_retries", 3)),
    )
