"""
IIFL Broker Adapter - IIFL Markets "Interactive" (XTS) Trading API
implementation of ``LegacyBrokerPort``.

Built from the official Symphony Fintech XTS SDK source and interactive-API
docs (verified 2026-08-21):
    https://github.com/symphonyfintech/xts-pythonclient-api-sdk/blob/main/Connect.py
    https://developers.symphonyfintech.in/doc/interactive/

IIFL Markets runs on the white-labelled "XTS" trading platform (Symphony
Fintech). Endpoint paths, request fields, and the response envelope below
are taken directly from the SDK's own source and official docs, not
guessed.

Two things are explicitly NOT guessed and are left as real gaps rather
than fabricated:

1. **Base URL (``root_url``).** XTS is white-labelled - every broker
   running on it hosts their own instance at their own domain. The public
   SDK/docs default to Symphony's own demo host
   (``https://developers.symphonyfintech.in``), which is NOT IIFL's real
   endpoint. There is no publicly verifiable "the IIFL URL is X" answer -
   IIFL's own docs site (api.iiflsecurities.com) rejected an automated
   fetch, and IIFL has reportedly been migrating accounts from XTS to a
   newer "ONT" API (per third-party sources) which may use a different
   contract entirely. **Get the real root_url from IIFL directly** (your
   API onboarding email or relationship manager) and confirm whether your
   account is still on XTS or has moved to ONT before trusting this
   adapter - do not assume XTS just because this file exists.
2. **Symbol -> exchangeInstrumentID resolution.** The Interactive API's
   order endpoints require a numeric ``exchangeInstrumentID``, not a plain
   trading symbol - the search/resolution endpoint for this lives in XTS's
   separate Market Data API, which wasn't part of the docs verified for
   this adapter. ``place_order()`` therefore requires the caller to have
   already resolved this (via ``order.exchange_instrument_id`` - see
   below) rather than silently guessing a symbol-lookup endpoint.

Architecture invariant
-----------------------
ALL broker API calls MUST go through a ``BrokerPort`` implementation.
Never call the XTS REST API directly from core modules.

Verified endpoints (do not add endpoints below without re-checking the
docs/SDK source first - do not guess a URL and ship it as if verified):
    POST   /interactive/user/session   - login (appKey, secretKey, source) -> token
    POST   /interactive/orders         - place order
    PUT    /interactive/orders         - modify order
    DELETE /interactive/orders         - cancel order
    GET    /interactive/orders         - order book
    GET    /interactive/portfolio/positions?dayOrNet=NetWise - net positions

Response envelope (confirmed from official docs): every response is
``{"type": "success"|"error", "code": "...", "description": "...", "result": {...}}``
- notably different from Kite's and mStock's flatter response shapes.
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


class _IIFLContext:
    """Minimal context needed by the IIFL adapter."""

    __slots__ = (
        "root_url", "app_key", "secret_key", "source", "log_fn",
        "enable_rate_limit", "max_retries",
    )

    def __init__(
        self,
        root_url: str,
        app_key: str,
        secret_key: str,
        log_fn: Callable[[str], None],
        source: str = "WEBAPI",
        enable_rate_limit: bool = True,
        max_retries: int = 3,
    ) -> None:
        self.root_url = root_url
        self.app_key = app_key
        self.secret_key = secret_key
        self.source = source
        self.log_fn = log_fn
        self.enable_rate_limit = enable_rate_limit
        self.max_retries = max_retries


def _classify_iifl_error(exc: Exception) -> str:
    msg = str(exc).lower()
    if "401" in msg or "token" in msg or "auth" in msg or "session" in msg:
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


class IIFLBrokerAdapter(LegacyBrokerPort):
    """IIFL Markets broker adapter - XTS Interactive REST API.

    ``order.exchange_instrument_id`` (an extra, duck-typed attribute beyond
    the base ``Order`` dataclass fields - same pattern Kite's adapter uses
    for ``order.exchange``/``order.product``) must already be resolved by
    the caller; see the "NOT guessed" note in the module docstring for why
    this adapter doesn't resolve it itself.
    """

    def __init__(self, ctx: _IIFLContext) -> None:
        if not REQUESTS_AVAILABLE:
            raise ImportError(
                "requests library is not available. Install it with: pip install requests"
            )
        if not ctx.root_url:
            raise ValueError(
                "IIFL root_url is required and has no safe default - XTS is "
                "white-labelled per broker. Get the real URL from IIFL directly."
            )

        self._root_url = ctx.root_url.rstrip("/")
        self._app_key = ctx.app_key
        self._secret_key = ctx.secret_key
        self._source = ctx.source
        self._log_fn = ctx.log_fn
        self._enable_rate_limit = ctx.enable_rate_limit
        self._max_retries = ctx.max_retries

        self._session: Any = None
        self._token: str | None = None
        self._connected = False

        self._last_request_time: float = 0.0
        self._min_request_interval: float = 0.1

    # ── Connection management ────────────────────────────────────────────────

    def connect(self) -> bool:
        """Log in via /interactive/user/session and cache the session token."""
        try:
            self._session = requests.Session()
            result = self._make_request(
                "POST",
                "/interactive/user/session",
                json_body={
                    "appKey": self._app_key,
                    "secretKey": self._secret_key,
                    "source": self._source,
                },
                authenticated=False,
            )
            self._token = str((result or {}).get("token", ""))
            if self._token:
                self._connected = True
                self._log_fn("[IIFL] Connected - session token acquired")
                return True
            self._connected = False
            self._log_fn(f"[IIFL] connect() got no token in response: {result}")
            return False
        except (OSError, ConnectionError, TimeoutError, RuntimeError, ValueError, TypeError) as exc:
            self._connected = False
            self._log_fn(f"[IIFL] connect() failed: {_classify_iifl_error(exc)} - {exc}")
            return False

    def disconnect(self) -> None:
        if self._session is not None:
            try:
                self._session.close()
            except (OSError, RuntimeError):
                pass
        self._session = None
        self._token = None
        self._connected = False
        self._log_fn("[IIFL] Disconnected")

    # ── Rate limiting & retries ──────────────────────────────────────────────

    def _rate_limit(self) -> None:
        if not self._enable_rate_limit:
            return
        elapsed = time.time() - self._last_request_time
        if elapsed < self._min_request_interval:
            time.sleep(self._min_request_interval - elapsed)
        self._last_request_time = time.time()

    def _make_request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        authenticated: bool = True,
    ) -> Any:
        """Execute an XTS REST call. Unwraps the {"type": "success", "result": ...}
        envelope; raises RuntimeError (with the broker's own "description") on
        {"type": "error", ...} or after exhausting retries.
        """
        if self._session is None:
            self._session = requests.Session()
        url = f"{self._root_url}{path}"
        headers = {"Content-Type": "application/json"}
        if authenticated:
            if not self._token:
                raise RuntimeError("IIFL adapter is not connected - call connect() first")
            headers["Authorization"] = self._token

        last_exc: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                self._rate_limit()
                response = self._session.request(
                    method, url, json=json_body, params=params, headers=headers, timeout=10,
                )
                if response.status_code == 401:
                    raise RuntimeError(f"401 Unauthorized: {response.text[:200]}")
                if response.status_code == 429:
                    raise RuntimeError(f"429 Rate limited: {response.text[:200]}")
                body = response.json()
                if body.get("type") == "error":
                    raise RuntimeError(
                        f"{body.get('code', 'error')}: {body.get('description', body)}"
                    )
                if response.status_code >= 400:
                    raise RuntimeError(f"{response.status_code} error: {response.text[:200]}")
                return body.get("result")
            except Exception as exc:  # noqa: BLE001 - classify below, then re-raise/retry
                last_exc = exc
                category = _classify_iifl_error(exc)
                if category == "TOKEN_EXPIRED":
                    break
                if attempt < self._max_retries - 1:
                    backoff = (2.0 ** attempt) * 0.5
                    self._log_fn(
                        f"[IIFL] Retry {attempt + 1}/{self._max_retries} "
                        f"after {category} - backing off {backoff:.1f}s"
                    )
                    time.sleep(backoff)
        raise RuntimeError(
            f"IIFL API call failed after {self._max_retries} retries: "
            f"{_classify_iifl_error(last_exc)} - {last_exc}"
        ) from last_exc

    # ── BrokerPort interface ─────────────────────────────────────────────────

    def place_order(self, order: Order) -> str:
        if not self._connected:
            raise RuntimeError("IIFL adapter is not connected - call connect() first") from None

        instrument_id = getattr(order, "exchange_instrument_id", None)
        if instrument_id is None:
            raise RuntimeError(
                "IIFL place_order requires order.exchange_instrument_id to be "
                "pre-resolved by the caller - see module docstring, this "
                "adapter does not implement symbol->instrument-ID lookup"
            )

        direction = str(getattr(order, "direction", "BUY")).upper()
        order_type_map = {"MARKET": "Market", "LIMIT": "LIMIT", "SL": "StopLimit", "SL-M": "StopMarket"}
        xts_order_type = order_type_map.get(
            str(getattr(order, "order_type", "MARKET")).upper(), "Market"
        )

        try:
            result = self._make_request(
                "POST",
                "/interactive/orders",
                json_body={
                    "exchangeSegment": getattr(order, "exchange_segment", "NSEFO"),
                    "exchangeInstrumentID": int(instrument_id),
                    "productType": getattr(order, "product", "MIS"),
                    "orderType": xts_order_type,
                    "orderSide": "BUY" if direction == "BUY" else "SELL",
                    "timeInForce": "DAY",
                    "disclosedQuantity": 0,
                    "orderQuantity": int(getattr(order, "quantity", 1)),
                    "limitPrice": float(getattr(order, "price", 0.0) or 0.0),
                    "stopPrice": float(getattr(order, "trigger_price", 0.0) or 0.0),
                    "orderUniqueIdentifier": str(getattr(order, "order_id", "") or ""),
                },
            )
            order_id = str((result or {}).get("AppOrderID", ""))
            if not order_id:
                raise RuntimeError(f"place_order returned no AppOrderID: {result}")
            return order_id
        except RuntimeError:
            raise
        except (OSError, ConnectionError, TimeoutError, ValueError, TypeError) as exc:
            raise RuntimeError(
                f"place_order failed: {_classify_iifl_error(exc)} - {exc}"
            ) from exc

    def cancel_order(self, order_id: str) -> bool:
        if not self._connected:
            return False
        try:
            self._make_request("DELETE", "/interactive/orders", params={"appOrderID": order_id})
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
            body: dict[str, Any] = {"appOrderID": order_id}
            if quantity is not None:
                body["modifiedOrderQuantity"] = quantity
            if price is not None:
                body["modifiedLimitPrice"] = price
                body["modifiedOrderType"] = "LIMIT"
            if trigger_price is not None:
                body["modifiedStopPrice"] = trigger_price
            self._make_request("PUT", "/interactive/orders", json_body=body)
            return True
        except (OSError, ConnectionError, TimeoutError, RuntimeError, ValueError, TypeError):
            return False

    def _find_order(self, order_id: str) -> dict[str, Any] | None:
        result = self._make_request("GET", "/interactive/orders")
        rows = result if isinstance(result, list) else []
        for row in rows:
            if str(row.get("AppOrderID", "")) == str(order_id):
                return row
        return None

    def get_order_status(self, order_id: str) -> str:
        if not self._connected:
            return "ERROR"
        try:
            row = self._find_order(order_id)
            return str(row.get("OrderStatus", "UNKNOWN")) if row else "UNKNOWN"
        except (OSError, ConnectionError, TimeoutError, RuntimeError, ValueError, TypeError, KeyError):
            return "ERROR"

    def get_fill_price(self, order_id: str) -> float | None:
        """Average fill price for an IIFL order - see KiteBrokerAdapter's
        equivalent method for why every broker adapter must implement this
        itself rather than relying on a generic wrapper default."""
        if not self._connected:
            return None
        try:
            row = self._find_order(order_id)
            if row is None:
                return None
            return float(row.get("AveragePrice") or 0) or None
        except (OSError, ConnectionError, TimeoutError, RuntimeError, ValueError, TypeError, KeyError):
            return None

    def get_filled_quantity(self, order_id: str) -> int | None:
        if not self._connected:
            return None
        try:
            row = self._find_order(order_id)
            if row is None:
                return None
            return int(row.get("FilledQuantity") or 0)
        except (OSError, ConnectionError, TimeoutError, RuntimeError, ValueError, TypeError, KeyError):
            return None

    def get_positions(self) -> list[Position]:
        if not self._connected:
            return []
        try:
            result = self._make_request(
                "GET", "/interactive/portfolio/positions", params={"dayOrNet": "NetWise"},
            )
            rows = result.get("positionList", result) if isinstance(result, dict) else result
            positions: list[Position] = []
            if not isinstance(rows, list):
                return []
            for net in rows:
                qty = int(net.get("Quantity", 0) or 0)
                if qty == 0:
                    continue
                positions.append(
                    Position(
                        symbol=str(net.get("TradingSymbol", net.get("ExchangeInstrumentID", ""))),
                        quantity=qty,
                        average_price=float(net.get("AveragePrice", 0.0) or 0.0),
                        market_value=float(qty) * float(net.get("LastTradedPrice", 0.0) or 0.0),
                        unrealized_pnl=float(net.get("UnrealizedMTM", 0.0) or 0.0),
                        realized_pnl=float(net.get("RealizedMTM", 0.0) or 0.0),
                        timestamp=None,
                    )
                )
            return positions
        except (OSError, ConnectionError, TimeoutError, RuntimeError, ValueError, TypeError, KeyError):
            return []

    def get_quote(self, symbol: str) -> Quote:
        """Not implemented - XTS market data (LTP/quote) lives in the
        separate Market Data API, not the Interactive API this adapter
        implements, and wasn't part of the docs verified here. Do not
        fabricate a URL; the core bot's signal pipeline uses yfinance for
        quotes regardless."""
        raise NotImplementedError(
            "IIFLBrokerAdapter.get_quote: XTS Market Data API not yet "
            "verified against real docs - see module docstring"
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
            "IIFLBrokerAdapter.get_historical_data: XTS Market Data API not "
            "yet verified against real docs - see module docstring"
        )

    def health_check(self) -> dict[str, Any]:
        if not self._connected:
            return {"status": "unhealthy", "connected": False, "error": "Adapter not connected"}
        try:
            start = time.time()
            self._make_request("GET", "/interactive/orders")
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
                "error": _classify_iifl_error(exc),
                "detail": str(exc),
            }


# ── Factory functions ─────────────────────────────────────────────────────────

def create_iifl_adapter(
    *,
    root_url: str,
    app_key: str,
    secret_key: str,
    source: str = "WEBAPI",
    log_fn: Callable[[str], None] = _log.info,
    enable_rate_limit: bool = True,
    max_retries: int = 3,
) -> IIFLBrokerAdapter:
    """Factory: build a fully-connected IIFLBrokerAdapter from raw credentials.

    ``root_url`` has no safe default - see module docstring. Get it from
    IIFL directly; do not assume Symphony's public demo host is IIFL's
    real production endpoint.
    """
    ctx = _IIFLContext(
        root_url=root_url,
        app_key=app_key,
        secret_key=secret_key,
        source=source,
        log_fn=log_fn,
        enable_rate_limit=enable_rate_limit,
        max_retries=max_retries,
    )
    return IIFLBrokerAdapter(ctx)


def create_iifl_adapter_from_context(context: Any) -> IIFLBrokerAdapter:
    """Factory: build an IIFLBrokerAdapter from ``BrokerRuntimeContext``,
    mirroring ``create_kite_adapter_from_context``/``create_mstock_adapter_from_context``.
    """
    cfg = context.cfg
    log_fn = context.log_fn

    bc = cfg.get("BROKER_CONFIG") or {}
    root_url = str(bc.get("root_url") or cfg.get("IIFL_ROOT_URL") or "").strip()
    app_key = str(bc.get("api_key") or cfg.get("IIFL_APP_KEY") or "").strip()
    secret_key = str(bc.get("secret") or cfg.get("IIFL_SECRET_KEY") or "").strip()

    if not root_url:
        raise ValueError(
            "IIFL_ROOT_URL not found in BROKER_CONFIG.root_url or top-level "
            "config - IIFL is white-labelled XTS with no public default URL, "
            "get it from IIFL directly"
        )
    if not app_key:
        raise ValueError("IIFL_APP_KEY not found in BROKER_CONFIG.api_key or top-level config")
    if not secret_key:
        raise ValueError("IIFL_SECRET_KEY not found in BROKER_CONFIG.secret or top-level config")

    return create_iifl_adapter(
        root_url=root_url,
        app_key=app_key,
        secret_key=secret_key,
        log_fn=log_fn,
        enable_rate_limit=bool(cfg.get("enable_rate_limit", True)),
        max_retries=int(cfg.get("max_retries", 3)),
    )
