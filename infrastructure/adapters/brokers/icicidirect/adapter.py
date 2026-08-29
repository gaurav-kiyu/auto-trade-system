"""
ICICI Direct Broker Adapter - Breeze API implementation of ``LegacyBrokerPort``.

Built from ICICI Securities' official Breeze API REST docs (verified
2026-08-21, https://api.icicidirect.com/breezeapi/documents/index.html):
order placement/cancel/modify/detail and portfolio positions pages.
First-party product with a fixed base URL (like Kite/mStock/Groww/Upstox/Dhan).

Architecture invariant
-----------------------
ALL broker API calls MUST go through a ``BrokerPort`` implementation.
Never call the Breeze REST API directly from core modules.

Verified endpoints (do not add endpoints below without re-checking the
docs first - do not guess a URL and ship it as if verified):
    POST   https://api.icicidirect.com/breezeapi/api/v1/order - place order
    PUT    https://api.icicidirect.com/breezeapi/api/v1/order - modify order
    DELETE https://api.icicidirect.com/breezeapi/api/v1/order - cancel order
    GET    https://api.icicidirect.com/breezeapi/api/v1/order - order detail (status, average_price, pending_quantity)
    GET    https://api.icicidirect.com/breezeapi/api/v1/portfoliopositions - net positions

Authentication (confirmed real - a genuinely different scheme from every
other adapter in this codebase, all of which use a plain Bearer token or
static header pair):
    X-AppKey:      <app key>
    X-SessionToken: <session token, obtained via a browser login flow -
                    same "get this externally" convention as Kite's/
                    Upstox's OAuth access_token>
    X-Timestamp:   ISO8601 UTC, must be within 60s of server time
    X-Checksum:    "token " + SHA256(timestamp + json_payload + secret_key)
    Content-Type:  application/json

IMPORTANT REAL CONSTRAINT: Breeze's ``order_type`` field only accepts
"limit"/"stoploss" — **market orders are not supported by this API at
all** (confirmed from the docs' enumerated values and from ICICI's own
FAQ). ``place_order()`` below raises a clear error for a MARKET order
request rather than silently substituting a different order type, since
that would change execution semantics without the caller asking for it.

NOT verified against real docs (left unimplemented rather than guessed):
live quote/LTP and historical-data endpoints. Symbol resolution uses
``stock_code``/``exchange_code`` (plain strings, confirmed from the docs
example) rather than a numeric instrument ID, so - unlike IIFL/Upstox/
Dhan - no separate instrument-lookup step is required here.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from collections.abc import Callable
from datetime import datetime, timezone
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

_BASE_URL = "https://api.icicidirect.com/breezeapi/api/v1"


class _ICICIDirectContext:
    """Minimal context needed by the ICICI Direct adapter."""

    __slots__ = ("app_key", "secret_key", "session_token", "log_fn", "enable_rate_limit", "max_retries")

    def __init__(
        self,
        app_key: str,
        secret_key: str,
        session_token: str,
        log_fn: Callable[[str], None],
        enable_rate_limit: bool = True,
        max_retries: int = 3,
    ) -> None:
        self.app_key = app_key
        self.secret_key = secret_key
        self.session_token = session_token
        self.log_fn = log_fn
        self.enable_rate_limit = enable_rate_limit
        self.max_retries = max_retries


def _classify_icicidirect_error(exc: Exception) -> str:
    msg = str(exc).lower()
    if "401" in msg or "token" in msg or "auth" in msg or "checksum" in msg:
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


class ICICIDirectBrokerAdapter(LegacyBrokerPort):
    """ICICI Direct (Breeze API) broker adapter.

    Breeze does not support market orders (see module docstring) -
    ``place_order()`` raises ``RuntimeError`` for ``order.order_type ==
    "MARKET"`` rather than silently converting it to a limit order at some
    guessed price, since that would change the trade's risk profile
    without the caller having asked for it.
    """

    def __init__(self, ctx: _ICICIDirectContext) -> None:
        if not REQUESTS_AVAILABLE:
            raise ImportError(
                "requests library is not available. Install it with: pip install requests"
            )

        self._app_key = ctx.app_key
        self._secret_key = ctx.secret_key
        self._session_token = ctx.session_token
        self._log_fn = ctx.log_fn
        self._enable_rate_limit = ctx.enable_rate_limit
        self._max_retries = ctx.max_retries

        self._session: Any = None
        self._connected = False

        self._last_request_time: float = 0.0
        self._min_request_interval: float = 0.15  # 10 orders/sec combined limit, stay well under

    # ── Connection management ────────────────────────────────────────────────

    def _checksum_headers(self, json_body: dict[str, Any] | None) -> dict[str, str]:
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
            f"{datetime.now(timezone.utc).microsecond // 1000:03d}Z"
        payload = json.dumps(json_body or {}, separators=(",", ":"))
        raw = f"{timestamp}{payload}{self._secret_key}"
        checksum = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        return {
            "Content-Type": "application/json",
            "X-Checksum": f"token {checksum}",
            "X-Timestamp": timestamp,
            "X-AppKey": self._app_key,
            "X-SessionToken": self._session_token,
        }

    def connect(self) -> bool:
        """Verify credentials by calling the positions endpoint."""
        try:
            self._session = requests.Session()
            self._make_request("GET", "/portfoliopositions", json_body={})
            self._connected = True
            self._log_fn("[ICICIDIRECT] Connected - positions endpoint reachable")
            return True
        except (OSError, ConnectionError, TimeoutError, RuntimeError, ValueError, TypeError) as exc:
            self._connected = False
            self._log_fn(f"[ICICIDIRECT] connect() failed: {_classify_icicidirect_error(exc)} - {exc}")
            return False

    def disconnect(self) -> None:
        if self._session is not None:
            try:
                self._session.close()
            except (OSError, RuntimeError):
                pass
        self._session = None
        self._connected = False
        self._log_fn("[ICICIDIRECT] Disconnected")

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
                # Checksum is timestamp-bound (60s window) - compute fresh per attempt.
                headers = self._checksum_headers(json_body)
                response = self._session.request(
                    method, url, json=json_body, headers=headers, timeout=10,
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
                category = _classify_icicidirect_error(exc)
                if category == "TOKEN_EXPIRED":
                    break
                if attempt < self._max_retries - 1:
                    backoff = (2.0 ** attempt) * 0.5
                    self._log_fn(
                        f"[ICICIDIRECT] Retry {attempt + 1}/{self._max_retries} "
                        f"after {category} - backing off {backoff:.1f}s"
                    )
                    time.sleep(backoff)
        raise RuntimeError(
            f"ICICI Direct API call failed after {self._max_retries} retries: "
            f"{_classify_icicidirect_error(last_exc)} - {last_exc}"
        ) from last_exc

    # ── BrokerPort interface ─────────────────────────────────────────────────

    def place_order(self, order: Order) -> str:
        if not self._connected:
            raise RuntimeError("ICICI Direct adapter is not connected - call connect() first") from None

        requested_type = str(getattr(order, "order_type", "MARKET")).upper()
        if requested_type == "MARKET":
            raise RuntimeError(
                "Breeze API does not support market orders (order_type must "
                "be 'limit' or 'stoploss') - the caller must supply a real "
                "limit price, this adapter will not guess one"
            )
        breeze_order_type = "stoploss" if requested_type in ("SL", "SL-M") else "limit"

        direction = str(getattr(order, "direction", "BUY")).upper()
        try:
            result = self._make_request(
                "POST", "/order",
                json_body={
                    "stock_code": getattr(order, "symbol", ""),
                    "exchange_code": getattr(order, "exchange", "NSE"),
                    "product": getattr(order, "product", "options"),
                    "action": "buy" if direction == "BUY" else "sell",
                    "order_type": breeze_order_type,
                    "quantity": str(int(getattr(order, "quantity", 1))),
                    "price": str(float(getattr(order, "price", 0.0) or 0.0)),
                    "validity": "day",
                    "stoploss": str(float(getattr(order, "trigger_price", 0.0) or 0.0)),
                },
            )
            order_id = str((result or {}).get("Success", {}).get("order_id", "") or (result or {}).get("order_id", ""))
            if not order_id:
                raise RuntimeError(f"place_order returned no order_id: {result}")
            return order_id
        except RuntimeError:
            raise
        except (OSError, ConnectionError, TimeoutError, ValueError, TypeError) as exc:
            raise RuntimeError(
                f"place_order failed: {_classify_icicidirect_error(exc)} - {exc}"
            ) from exc

    def cancel_order(self, order_id: str) -> bool:
        if not self._connected:
            return False
        try:
            self._make_request("DELETE", "/order", json_body={"order_id": order_id, "exchange_code": "NSE"})
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
            body: dict[str, Any] = {"order_id": order_id, "exchange_code": "NSE"}
            if quantity is not None:
                body["quantity"] = str(quantity)
            if price is not None:
                body["price"] = str(price)
                body["order_type"] = "limit"
            if trigger_price is not None:
                body["stoploss"] = str(trigger_price)
            self._make_request("PUT", "/order", json_body=body)
            return True
        except (OSError, ConnectionError, TimeoutError, RuntimeError, ValueError, TypeError):
            return False

    def _order_detail(self, order_id: str) -> dict[str, Any] | None:
        result = self._make_request(
            "GET", "/order", json_body={"order_id": order_id, "exchange_code": "NSE"},
        )
        row = (result or {}).get("Success") or result
        return row if isinstance(row, dict) else None

    def get_order_status(self, order_id: str) -> str:
        if not self._connected:
            return "ERROR"
        try:
            row = self._order_detail(order_id)
            return str(row.get("status", "UNKNOWN")) if row else "UNKNOWN"
        except (OSError, ConnectionError, TimeoutError, RuntimeError, ValueError, TypeError, KeyError):
            return "ERROR"

    def get_fill_price(self, order_id: str) -> float | None:
        """Average fill price for an ICICI Direct order - see
        KiteBrokerAdapter's equivalent method for why every broker adapter
        must implement this itself rather than relying on a generic
        wrapper default. Breeze's average_price is a string field."""
        if not self._connected:
            return None
        try:
            row = self._order_detail(order_id)
            if row is None:
                return None
            return float(row.get("average_price") or 0) or None
        except (OSError, ConnectionError, TimeoutError, RuntimeError, ValueError, TypeError, KeyError):
            return None

    def get_filled_quantity(self, order_id: str) -> int | None:
        """Breeze doesn't return filled_quantity directly - derived as
        quantity - pending_quantity, both string fields per the docs."""
        if not self._connected:
            return None
        try:
            row = self._order_detail(order_id)
            if row is None:
                return None
            total = int(float(row.get("quantity") or 0))
            pending = int(float(row.get("pending_quantity") or 0))
            return max(0, total - pending)
        except (OSError, ConnectionError, TimeoutError, RuntimeError, ValueError, TypeError, KeyError):
            return None

    def get_positions(self) -> list[Position]:
        if not self._connected:
            return []
        try:
            result = self._make_request("GET", "/portfoliopositions", json_body={})
            rows = (result or {}).get("Success", result) or []
            positions: list[Position] = []
            if not isinstance(rows, list):
                return []
            for net in rows:
                qty = int(float(net.get("quantity") or 0))
                if qty == 0:
                    continue
                avg_price = float(net.get("average_price") or 0.0)
                ltp = float(net.get("ltp") or 0.0)
                positions.append(
                    Position(
                        symbol=str(net.get("stock_code", "")),
                        quantity=qty,
                        average_price=avg_price,
                        market_value=float(qty) * ltp,
                        unrealized_pnl=float(net.get("pnl") or 0.0),
                        realized_pnl=0.0,
                        timestamp=None,
                    )
                )
            return positions
        except (OSError, ConnectionError, TimeoutError, RuntimeError, ValueError, TypeError, KeyError):
            return []

    def get_quote(self, symbol: str) -> Quote:
        """Not implemented - Breeze's live-quote endpoint wasn't part of
        the docs pages verified for this adapter. Do not fabricate a URL;
        the core bot's signal pipeline uses yfinance for quotes regardless."""
        raise NotImplementedError(
            "ICICIDirectBrokerAdapter.get_quote: Breeze quote endpoint not "
            "yet verified against real docs - see module docstring"
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
            "ICICIDirectBrokerAdapter.get_historical_data: Breeze historical-data "
            "endpoint not yet verified against real docs - see module docstring"
        )

    def health_check(self) -> dict[str, Any]:
        if not self._connected:
            return {"status": "unhealthy", "connected": False, "error": "Adapter not connected"}
        try:
            start = time.time()
            self._make_request("GET", "/portfoliopositions", json_body={})
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
                "error": _classify_icicidirect_error(exc),
                "detail": str(exc),
            }


# ── Factory functions ─────────────────────────────────────────────────────────

def create_icicidirect_adapter(
    *,
    app_key: str,
    secret_key: str,
    session_token: str,
    log_fn: Callable[[str], None] = _log.info,
    enable_rate_limit: bool = True,
    max_retries: int = 3,
) -> ICICIDirectBrokerAdapter:
    """Factory: build a fully-connected ICICIDirectBrokerAdapter from raw credentials."""
    ctx = _ICICIDirectContext(
        app_key=app_key,
        secret_key=secret_key,
        session_token=session_token,
        log_fn=log_fn,
        enable_rate_limit=enable_rate_limit,
        max_retries=max_retries,
    )
    return ICICIDirectBrokerAdapter(ctx)


def create_icicidirect_adapter_from_context(context: Any) -> ICICIDirectBrokerAdapter:
    """Factory: build an ICICIDirectBrokerAdapter from ``BrokerRuntimeContext``,
    mirroring ``create_kite_adapter_from_context``/``create_mstock_adapter_from_context``.
    """
    cfg = context.cfg
    log_fn = context.log_fn

    bc = cfg.get("BROKER_CONFIG") or {}
    app_key = str(bc.get("api_key") or cfg.get("ICICIDIRECT_APP_KEY") or "").strip()
    secret_key = str(bc.get("secret") or cfg.get("ICICIDIRECT_SECRET_KEY") or "").strip()
    session_token = str(bc.get("access_token") or cfg.get("ICICIDIRECT_SESSION_TOKEN") or "").strip()

    if not app_key:
        raise ValueError("ICICIDIRECT_APP_KEY not found in BROKER_CONFIG.api_key or top-level config")
    if not secret_key:
        raise ValueError("ICICIDIRECT_SECRET_KEY not found in BROKER_CONFIG.secret or top-level config")
    if not session_token:
        raise ValueError("ICICIDIRECT_SESSION_TOKEN not found in BROKER_CONFIG.access_token or top-level config")

    return create_icicidirect_adapter(
        app_key=app_key,
        secret_key=secret_key,
        session_token=session_token,
        log_fn=log_fn,
        enable_rate_limit=bool(cfg.get("enable_rate_limit", True)),
        max_retries=int(cfg.get("max_retries", 3)),
    )
