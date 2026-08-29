"""
Groww Broker Adapter - Groww Trading API implementation of ``LegacyBrokerPort``.

Built from Groww's official first-party REST API docs (verified
2026-08-21, https://groww.in/trade-api/docs/curl/): Orders and Portfolio
pages. Unlike IIFL (white-labelled XTS), Groww's API is Groww's own
first-party product with a single fixed base URL, so - like Kite and
mStock - that URL is safely hardcoded here.

Architecture invariant
-----------------------
ALL broker API calls MUST go through a ``BrokerPort`` implementation.
Never call the Groww REST API directly from core modules.

Verified endpoints (do not add endpoints below without re-checking the
docs first - do not guess a URL and ship it as if verified):
    POST /v1/order/create           - place order
    POST /v1/order/modify           - modify order
    POST /v1/order/cancel           - cancel order
    GET  /v1/order/detail/{id}      - order detail (status, average_fill_price, filled_quantity)
    GET  /v1/positions/user         - all positions

Authentication: this adapter accepts an already-obtained ``access_token``
(same convention as Kite/mStock) - Groww's dashboard supports generating a
long-lived Access Token directly. Groww also offers a TOTP-based exchange
flow (``GrowwAPI.get_access_token(api_key, totp)`` in their official
Python SDK) for automated token refresh, but that SDK-internal endpoint
wasn't part of the docs pages verified for this adapter - implement it
separately (or install Groww's official SDK for that specific step) rather
than guessing the REST call here.

NOT verified against real docs (left unimplemented rather than guessed):
live quote/LTP and historical-data endpoints - Groww's docs reference a
"Live data API" and "Historical Data API" as separate products from the
Orders/Portfolio pages actually checked here.
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

_BASE_URL = "https://api.groww.in/v1"


class _GrowwContext:
    """Minimal context needed by the Groww adapter."""

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


def _classify_groww_error(exc: Exception) -> str:
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


class GrowwBrokerAdapter(LegacyBrokerPort):
    """Groww broker adapter - first-party REST API.

    The constructor accepts an already-obtained ``access_token`` (same
    convention as Kite/mStock) - see module docstring for how to get one
    and the TOTP-refresh gap.
    """

    def __init__(self, ctx: _GrowwContext) -> None:
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
        self._min_request_interval: float = 0.1

    # ── Connection management ────────────────────────────────────────────────

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._access_token}",
            "X-API-VERSION": "1.0",
        }

    def connect(self) -> bool:
        """Verify credentials by calling the positions endpoint (Groww's
        docs pages checked here don't show a dedicated lightweight
        'profile' verification call)."""
        try:
            self._session = requests.Session()
            self._make_request("GET", "/positions/user")
            self._connected = True
            self._log_fn("[GROWW] Connected - positions endpoint reachable")
            return True
        except (OSError, ConnectionError, TimeoutError, RuntimeError, ValueError, TypeError) as exc:
            self._connected = False
            self._log_fn(f"[GROWW] connect() failed: {_classify_groww_error(exc)} - {exc}")
            return False

    def disconnect(self) -> None:
        if self._session is not None:
            try:
                self._session.close()
            except (OSError, RuntimeError):
                pass
        self._session = None
        self._connected = False
        self._log_fn("[GROWW] Disconnected")

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
        params: dict[str, Any] | None = None,
    ) -> Any:
        if self._session is None:
            self._session = requests.Session()
        url = f"{_BASE_URL}{path}"
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
                if response.status_code >= 400:
                    raise RuntimeError(f"{response.status_code} error: {response.text[:200]}")
                return response.json()
            except Exception as exc:  # noqa: BLE001 - classify below, then re-raise/retry
                last_exc = exc
                category = _classify_groww_error(exc)
                if category == "TOKEN_EXPIRED":
                    break
                if attempt < self._max_retries - 1:
                    backoff = (2.0 ** attempt) * 0.5
                    self._log_fn(
                        f"[GROWW] Retry {attempt + 1}/{self._max_retries} "
                        f"after {category} - backing off {backoff:.1f}s"
                    )
                    time.sleep(backoff)
        raise RuntimeError(
            f"Groww API call failed after {self._max_retries} retries: "
            f"{_classify_groww_error(last_exc)} - {last_exc}"
        ) from last_exc

    # ── BrokerPort interface ─────────────────────────────────────────────────

    def place_order(self, order: Order) -> str:
        if not self._connected:
            raise RuntimeError("Groww adapter is not connected - call connect() first") from None

        direction = str(getattr(order, "direction", "BUY")).upper()
        order_type = str(getattr(order, "order_type", "MARKET")).upper()
        if order_type not in ("MARKET", "LIMIT", "SL", "SL-M"):
            order_type = "MARKET"

        try:
            result = self._make_request(
                "POST",
                "/order/create",
                json_body={
                    "trading_symbol": getattr(order, "symbol", ""),
                    "quantity": int(getattr(order, "quantity", 1)),
                    "validity": "DAY",
                    "exchange": getattr(order, "exchange", "NSE"),
                    "segment": getattr(order, "segment", "FNO"),
                    "product": getattr(order, "product", "MIS"),
                    "order_type": order_type,
                    "transaction_type": "BUY" if direction == "BUY" else "SELL",
                    "price": float(getattr(order, "price", 0.0) or 0.0),
                    "trigger_price": float(getattr(order, "trigger_price", 0.0) or 0.0),
                    "order_reference_id": str(getattr(order, "order_id", "") or ""),
                },
            )
            order_id = str((result or {}).get("groww_order_id", ""))
            if not order_id:
                raise RuntimeError(f"place_order returned no groww_order_id: {result}")
            return order_id
        except RuntimeError:
            raise
        except (OSError, ConnectionError, TimeoutError, ValueError, TypeError) as exc:
            raise RuntimeError(
                f"place_order failed: {_classify_groww_error(exc)} - {exc}"
            ) from exc

    def cancel_order(self, order_id: str) -> bool:
        if not self._connected:
            return False
        try:
            self._make_request(
                "POST", "/order/cancel",
                json_body={"groww_order_id": order_id, "segment": "FNO"},
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
        if not self._connected:
            return False
        try:
            body: dict[str, Any] = {"groww_order_id": order_id, "segment": "FNO", "order_type": "LIMIT"}
            if quantity is not None:
                body["quantity"] = quantity
            if price is not None:
                body["price"] = price
            if trigger_price is not None:
                body["trigger_price"] = trigger_price
            self._make_request("POST", "/order/modify", json_body=body)
            return True
        except (OSError, ConnectionError, TimeoutError, RuntimeError, ValueError, TypeError):
            return False

    def get_order_status(self, order_id: str) -> str:
        if not self._connected:
            return "ERROR"
        try:
            result = self._make_request("GET", f"/order/detail/{order_id}", params={"segment": "FNO"})
            return str((result or {}).get("order_status", "UNKNOWN"))
        except (OSError, ConnectionError, TimeoutError, RuntimeError, ValueError, TypeError, KeyError):
            return "ERROR"

    def get_fill_price(self, order_id: str) -> float | None:
        """Average fill price for a Groww order - see KiteBrokerAdapter's
        equivalent method for why every broker adapter must implement this
        itself rather than relying on a generic wrapper default."""
        if not self._connected:
            return None
        try:
            result = self._make_request("GET", f"/order/detail/{order_id}", params={"segment": "FNO"})
            return float((result or {}).get("average_fill_price") or 0) or None
        except (OSError, ConnectionError, TimeoutError, RuntimeError, ValueError, TypeError, KeyError):
            return None

    def get_filled_quantity(self, order_id: str) -> int | None:
        if not self._connected:
            return None
        try:
            result = self._make_request("GET", f"/order/detail/{order_id}", params={"segment": "FNO"})
            return int((result or {}).get("filled_quantity") or 0)
        except (OSError, ConnectionError, TimeoutError, RuntimeError, ValueError, TypeError, KeyError):
            return None

    def get_positions(self) -> list[Position]:
        if not self._connected:
            return []
        try:
            result = self._make_request("GET", "/positions/user")
            rows = (result or {}).get("positions", result) or []
            positions: list[Position] = []
            if not isinstance(rows, list):
                return []
            for net in rows:
                qty = int(net.get("quantity", 0) or 0)
                if qty == 0:
                    continue
                positions.append(
                    Position(
                        symbol=str(net.get("trading_symbol", "")),
                        quantity=qty,
                        average_price=float(net.get("net_price", 0.0) or 0.0),
                        # No live LTP field on this endpoint (see module
                        # docstring - quote API not verified) - market_value
                        # is therefore based on net_price, not a live price.
                        market_value=float(qty) * float(net.get("net_price", 0.0) or 0.0),
                        unrealized_pnl=0.0,
                        realized_pnl=float(net.get("realised_pnl", 0.0) or 0.0),
                        timestamp=None,
                    )
                )
            return positions
        except (OSError, ConnectionError, TimeoutError, RuntimeError, ValueError, TypeError, KeyError):
            return []

    def get_quote(self, symbol: str) -> Quote:
        """Not implemented - Groww's Live Data API is a separate product
        from the Orders/Portfolio docs verified for this adapter. Do not
        fabricate a URL; the core bot's signal pipeline uses yfinance for
        quotes regardless."""
        raise NotImplementedError(
            "GrowwBrokerAdapter.get_quote: Groww Live Data API not yet "
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
            "GrowwBrokerAdapter.get_historical_data: Groww Historical Data "
            "API not yet verified against real docs - see module docstring"
        )

    def health_check(self) -> dict[str, Any]:
        if not self._connected:
            return {"status": "unhealthy", "connected": False, "error": "Adapter not connected"}
        try:
            start = time.time()
            self._make_request("GET", "/positions/user")
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
                "error": _classify_groww_error(exc),
                "detail": str(exc),
            }


# ── Factory functions ─────────────────────────────────────────────────────────

def create_groww_adapter(
    *,
    access_token: str,
    log_fn: Callable[[str], None] = _log.info,
    enable_rate_limit: bool = True,
    max_retries: int = 3,
) -> GrowwBrokerAdapter:
    """Factory: build a fully-connected GrowwBrokerAdapter from a raw access token."""
    ctx = _GrowwContext(
        access_token=access_token,
        log_fn=log_fn,
        enable_rate_limit=enable_rate_limit,
        max_retries=max_retries,
    )
    return GrowwBrokerAdapter(ctx)


def create_groww_adapter_from_context(context: Any) -> GrowwBrokerAdapter:
    """Factory: build a GrowwBrokerAdapter from ``BrokerRuntimeContext``,
    mirroring ``create_kite_adapter_from_context``/``create_mstock_adapter_from_context``.
    """
    cfg = context.cfg
    log_fn = context.log_fn

    bc = cfg.get("BROKER_CONFIG") or {}
    access_token = str(bc.get("access_token") or cfg.get("GROWW_ACCESS_TOKEN") or "").strip()

    if not access_token:
        raise ValueError("GROWW_ACCESS_TOKEN not found in BROKER_CONFIG.access_token or top-level config")

    return create_groww_adapter(
        access_token=access_token,
        log_fn=log_fn,
        enable_rate_limit=bool(cfg.get("enable_rate_limit", True)),
        max_retries=int(cfg.get("max_retries", 3)),
    )
