from __future__ import annotations

import importlib
import importlib.util
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.ports.broker import BrokerPort


def _flatten_effective_broker_config(cfg: dict[str, Any]) -> dict[str, Any]:
    """BROKER_CONFIG merged with top-level KITE/ANGEL keys (legacy single-bucket view)."""
    data = dict(cfg.get("BROKER_CONFIG") or {})
    if not str(data.get("api_key") or "").strip():
        data["api_key"] = str(cfg.get("KITE_API_KEY") or cfg.get("ANGEL_API_KEY") or "").strip()
    if not str(data.get("access_token") or "").strip():
        data["access_token"] = str(cfg.get("KITE_ACCESS_TOKEN") or "").strip()
    if not str(data.get("user_id") or "").strip():
        data["user_id"] = str(cfg.get("KITE_USER_ID") or "").strip()
    if not str(data.get("password") or "").strip():
        data["password"] = str(cfg.get("KITE_PASSWORD") or cfg.get("ANGEL_PASSWORD") or "").strip()
    if not str(data.get("totp_key") or "").strip():
        data["totp_key"] = str(cfg.get("KITE_TOTP_KEY") or cfg.get("ANGEL_TOTP_KEY") or "").strip()
    if not str(data.get("refresh_token") or "").strip():
        data["refresh_token"] = str(cfg.get("ANGEL_REFRESH_TOKEN") or "").strip()
    if not str(data.get("client_id") or "").strip():
        data["client_id"] = str(cfg.get("ANGEL_CLIENT_ID") or "").strip()
    return data


def broker_connection_secrets(cfg: dict[str, Any], driver: str) -> dict[str, Any]:
    """Merge ``BROKER_CONFIG`` with driver-specific top-level keys (``KITE_*`` / ``ANGEL_*``).

    Used by core Kite/Angel adapters and by app validate_config so credentials can live
    in ``BROKER_CONFIG`` JSON or legacy flat keys without drift.
    """
    d = str(driver or "").upper()
    bc = dict(cfg.get("BROKER_CONFIG") or {})
    if d == "KITE":
        if not str(bc.get("api_key") or "").strip():
            bc["api_key"] = str(cfg.get("KITE_API_KEY") or "").strip()
        if not str(bc.get("access_token") or "").strip():
            bc["access_token"] = str(cfg.get("KITE_ACCESS_TOKEN") or "").strip()
        return bc
    if d == "ANGEL":
        if not str(bc.get("api_key") or "").strip():
            bc["api_key"] = str(cfg.get("ANGEL_API_KEY") or "").strip()
        if not str(bc.get("client_id") or "").strip():
            bc["client_id"] = str(cfg.get("ANGEL_CLIENT_ID") or "").strip()
        if not str(bc.get("password") or "").strip():
            bc["password"] = str(cfg.get("ANGEL_PASSWORD") or "").strip()
        if not str(bc.get("totp_key") or "").strip():
            bc["totp_key"] = str(cfg.get("ANGEL_TOTP_KEY") or "").strip()
        if not str(bc.get("refresh_token") or "").strip():
            bc["refresh_token"] = str(cfg.get("ANGEL_REFRESH_TOKEN") or "").strip()
        return bc
    return _flatten_effective_broker_config(cfg)


# ...existing code...
class BrokerAdapter:
    """
    COMPATIBILITY LAYER: This class is now a wrapper around the new BrokerPort architecture.
    It exists solely to prevent breaking the legacy index_trader.py.
    """
    def __init__(self, port: Any):
        self._port = port

    def place_order(self, name, direction, qty, strike) -> str | None:
        # Convert legacy call to structured OrderRequest if the underlying port
        # expects the newer port interface.
        if isinstance(self._port, PaperBrokerAdapter):
            return self._port.place_order(name, direction, qty, strike)

        from core.adapters.base_adapter import OrderRequest
        request = OrderRequest(
            symbol=f"{name}_{strike}_{'CE' if direction == 'CALL' else 'PE'}",
            qty=qty,
            price=0.0,
            order_type="MARKET",
            direction="BUY" if direction == "CALL" else "SELL",
            product="MIS",
            variety="REGULAR"
        )
        response = self._port.place_order(request)
        return response.order_id if response.status != "REJECTED" else None

    def exit_order(self, name, direction, qty, strike) -> str | None:
        if isinstance(self._port, PaperBrokerAdapter):
            return self._port.exit_order(name, direction, qty, strike)

        from core.adapters.base_adapter import OrderRequest
        request = OrderRequest(
            symbol=f"{name}_{strike}_{'CE' if direction == 'CALL' else 'PE'}",
            qty=qty,
            price=0.0,
            order_type="MARKET",
            direction="SELL" if direction == "CALL" else "BUY",
            product="MIS",
            variety="REGULAR"
        )
        response = self._port.place_order(request)
        return response.order_id if response.status != "REJECTED" else None

    def cancel_order(self, order_id) -> bool:
        response = self._port.cancel_order(order_id)
        return response.status == "CANCELLED"

    def get_fill_price(self, order_id) -> float | None:
        # The new port returns OrderResult; we might need a separate method for fills
        # For now, we simulate the legacy return
        return 0.0 

    def get_filled_quantity(self, order_id) -> int | None:
        return 0

    def get_order_status(self, order_id) -> str:
        response = self._port.get_order_status(order_id)
        return response.status

    def wait_for_fill(self, order_id, timeout=10) -> bool:
        # Legacy polling logic moved to the port or a service
        return True

    def health_check(self) -> dict:
        return {"status": "healthy", "adapter": self._port.__class__.__name__}
# ...existing code...


@dataclass(frozen=True)
class BrokerRuntimeContext:
    cfg: dict[str, Any]
    index_map: dict[str, Any]
    now_fn: Callable[[], Any]
    log_fn: Callable[[str], None]
    send_fn: Callable[[str], None]
    shutdown_is_set_fn: Callable[[], bool]
    hard_halt_is_set_fn: Callable[[], bool]
    sleep_fn: Callable[[float], None]
    broker_wait_poll_sec: float
    expiry_str_fn: Callable[[str], str]


def build_broker_runtime_context(
    *,
    cfg: dict[str, Any],
    index_map: dict[str, Any],
    now_fn: Callable[[], Any],
    log_fn: Callable[[str], None],
    send_fn: Callable[[str], None],
    shutdown_is_set_fn: Callable[[], bool],
    hard_halt_is_set_fn: Callable[[], bool],
    sleep_fn: Callable[[float], None],
    broker_wait_poll_sec: float,
    expiry_str_fn: Callable[[str], str],
) -> BrokerRuntimeContext:
    """Build the context object passed to :func:`create_broker_adapter` (shared by index and stock bots)."""
    return BrokerRuntimeContext(
        cfg=dict(cfg),
        index_map=index_map,
        now_fn=now_fn,
        log_fn=log_fn,
        send_fn=send_fn,
        shutdown_is_set_fn=shutdown_is_set_fn,
        hard_halt_is_set_fn=hard_halt_is_set_fn,
        sleep_fn=sleep_fn,
        broker_wait_poll_sec=broker_wait_poll_sec,
        expiry_str_fn=expiry_str_fn,
    )


@dataclass
class PaperFill:
    """Single paper-trade fill record — stored per order_id for analytics."""
    order_id: str
    name: str
    direction: str
    strike: int
    qty: int
    mid_price: float
    fill_price: float
    slippage_amt: float
    oi: int
    volume: int
    liquidity_skipped: bool
    is_entry: bool


class PaperBrokerAdapter(BrokerAdapter):
    """
    Simulates paper trading with realistic mid-price fills, configurable slippage,
    and optional OI/volume liquidity filter.

    All constructor args default to None for backward compatibility:
        PaperBrokerAdapter()  ← unchanged behaviour (no fill price, no OI check)

    Enhanced mode (wire callbacks via constructor or configure_paper_simulation()):
        price_getter(name, direction, strike) -> float | None   — option mid-price
        oi_getter(name, direction, strike) -> (oi, volume) | None

    Config keys (read from cfg dict — all optional):
        paper_slippage_pct   : float  default 0.5  (% of mid applied as slippage)
        min_oi_threshold     : int    default 500  (minimum open interest)
        min_volume_threshold : int    default 100  (minimum traded volume)
    """

    _counter: int = 0  # class-level counter — guarantees unique IDs within a process

    def __init__(
        self,
        *,
        price_getter: Callable[[str, str, int], float | None] | None = None,
        oi_getter: Callable[[str, str, int], tuple[int, int] | None] | None = None,
        cfg: dict[str, Any] | None = None,
    ) -> None:
        self._price_getter = price_getter
        self._oi_getter = oi_getter
        self._cfg: dict[str, Any] = dict(cfg) if cfg else {}
        self._fills: dict[str, PaperFill] = {}

    def configure_paper_simulation(
        self,
        *,
        price_getter: Callable[[str, str, int], float | None] | None = None,
        oi_getter: Callable[[str, str, int], tuple[int, int] | None] | None = None,
        cfg: dict[str, Any] | None = None,
    ) -> None:
        """Wire live-data callbacks post-construction (e.g. from _make_broker())."""
        if price_getter is not None:
            self._price_getter = price_getter
        if oi_getter is not None:
            self._oi_getter = oi_getter
        if cfg is not None:
            self._cfg = dict(cfg)

    # ── Config helpers ────────────────────────────────────────────────────────

    def _slippage_pct(self) -> float:
        return float(self._cfg.get("paper_slippage_pct", 0.5))

    def _min_oi(self) -> int:
        return int(self._cfg.get("min_oi_threshold", 500))

    def _min_vol(self) -> int:
        return int(self._cfg.get("min_volume_threshold", 100))

    # ── Internal simulation helpers ───────────────────────────────────────────

    def _check_liquidity(self, name: str, direction: str, strike: int) -> tuple[bool, int, int]:
        """Returns (ok, oi, volume). ok=True means liquid enough (or no oi_getter)."""
        if self._oi_getter is None:
            return True, 0, 0
        try:
            result = self._oi_getter(name, direction, strike)
            if result is None:
                return True, 0, 0
            oi, volume = int(result[0]), int(result[1])
            ok = oi >= self._min_oi() and volume >= self._min_vol()
            return ok, oi, volume
        except Exception:
            return True, 0, 0

    def _fill_price(self, name: str, direction: str, strike: int, is_entry: bool) -> tuple[float, float]:
        """Returns (fill_price, mid_price). Applies slippage to mid."""
        if self._price_getter is None:
            return 0.0, 0.0
        try:
            mid = self._price_getter(name, direction, strike)
            if mid is None or mid <= 0:
                return 0.0, 0.0
            pct = self._slippage_pct() / 100.0
            fill = mid * (1.0 + pct) if is_entry else mid * (1.0 - pct)
            return round(fill, 2), round(mid, 2)
        except Exception:
            return 0.0, 0.0

    def _record_fill(
        self, order_id: str, name: str, direction: str,
        strike: int, qty: int, is_entry: bool,
    ) -> PaperFill:
        ok, oi, volume = self._check_liquidity(name, direction, strike)
        fill_price, mid_price = self._fill_price(name, direction, strike, is_entry)
        slippage_amt = round(fill_price - mid_price, 2) if mid_price > 0 else 0.0
        rec = PaperFill(
            order_id=order_id,
            name=name,
            direction=direction,
            strike=int(strike),
            qty=int(qty),
            mid_price=mid_price,
            fill_price=fill_price,
            slippage_amt=slippage_amt,
            oi=oi,
            volume=volume,
            liquidity_skipped=not ok,
            is_entry=is_entry,
        )
        self._fills[order_id] = rec
        return rec

    # ── BrokerAdapter interface ───────────────────────────────────────────────

    def place_order(self, name, direction, qty, strike) -> str:
        PaperBrokerAdapter._counter += 1
        oid = f"PAPER_{int(time.time() * 1000)}_{PaperBrokerAdapter._counter}"
        self._record_fill(oid, name, direction, int(strike), int(qty), is_entry=True)
        return oid

    def exit_order(self, name, direction, qty, strike) -> str:
        PaperBrokerAdapter._counter += 1
        oid = f"PAPER_EXIT_{int(time.time() * 1000)}_{PaperBrokerAdapter._counter}"
        self._record_fill(oid, name, direction, int(strike), int(qty), is_entry=False)
        return oid

    def get_order_status(self, _) -> str:
        return "COMPLETE"

    def get_fill_price(self, order_id) -> float | None:
        rec = self._fills.get(order_id)
        return rec.fill_price if (rec and rec.fill_price > 0) else None

    def get_filled_quantity(self, order_id) -> int | None:
        rec = self._fills.get(order_id)
        if rec is None:
            return None
        return 0 if rec.liquidity_skipped else rec.qty

    def wait_for_fill(self, _, timeout=10) -> bool:
        return True

    # ── Analytics helpers ─────────────────────────────────────────────────────

    def get_paper_fill(self, order_id: str) -> PaperFill | None:
        """Return the PaperFill record for a specific order."""
        return self._fills.get(order_id)

    def paper_fill_stats(self) -> dict[str, Any]:
        """Summary stats for EOD reporting."""
        fills = list(self._fills.values())
        if not fills:
            return {"fills": 0, "avg_slippage_pct": 0.0, "liquidity_skipped": 0}
        slippages = [
            f.slippage_amt / f.mid_price * 100
            for f in fills if f.mid_price > 0
        ]
        skipped = sum(1 for f in fills if f.liquidity_skipped)
        return {
            "fills": len(fills),
            "avg_slippage_pct": round(sum(slippages) / len(slippages), 4) if slippages else 0.0,
            "liquidity_skipped": skipped,
        }


class _PollingBrokerAdapter(BrokerAdapter):
    def __init__(self, context: BrokerRuntimeContext) -> None:
        self._context = context

    def wait_for_fill(self, order_id, timeout=10) -> bool:
        start = time.monotonic()
        hard_limit = max(timeout * 3, 30)
        while time.monotonic() - start < hard_limit:
            if self._context.shutdown_is_set_fn() or self._context.hard_halt_is_set_fn():
                return False
            status = self.get_order_status(order_id)
            if status in ("COMPLETE", "FILLED", "TRIGGER PENDING"):
                return True
            if status in ("CANCELLED", "REJECTED"):
                return False
            if time.monotonic() - start > timeout:
                self._context.log_fn(f"[BROKER] wait_for_fill timeout {timeout}s for {order_id} status={status}")
                return False
            self._context.sleep_fn(self._context.broker_wait_poll_sec)
        self._context.log_fn(f"[BROKER] wait_for_fill hard limit {hard_limit}s exceeded for {order_id}")
        return False


class KiteBrokerAdapter(_PollingBrokerAdapter):
    _rate_limit_lock = threading.Lock()
    _last_api_call = 0.0
    _min_interval_ms = 500  # Minimum 500ms between API calls

    def __init__(self, context: BrokerRuntimeContext) -> None:
        super().__init__(context)
        self._kite = None
        self._connected = False
        self._token_date = None
        self._kite_lock = threading.Lock()
        self._connect()

    def _rate_limit_wait(self) -> None:
        """Enforce rate limiting to prevent API ban."""
        with self._rate_limit_lock:
            now = time.time()
            elapsed_ms = (now - self._last_api_call) * 1000
            if elapsed_ms < self._min_interval_ms:
                sleep_ms = (self._min_interval_ms - elapsed_ms) / 1000.0
                time.sleep(sleep_ms)
            self._last_api_call = time.time()

    def _connect(self):
        try:
            from kiteconnect import KiteConnect  # type: ignore

            sec = broker_connection_secrets(self._context.cfg, "KITE")
            k = KiteConnect(api_key=str(sec.get("api_key") or ""))
            k.set_access_token(str(sec.get("access_token") or ""))
            profile = k.profile()
            with self._kite_lock:
                self._kite = k
                self._connected = True
                self._token_date = self._context.now_fn().date()
            label = str(self._context.cfg.get("BROKER_NAME") or "").strip() or "Kite"
            self._context.log_fn(f"[KITE] Connected ({label}): {profile.get('user_name', '?')}")
        except Exception as exc:
            self._context.log_fn(f"[KITE] Connect failed: {exc}")

    def _ensure_token_fresh(self) -> bool:
        with self._kite_lock:
            today = self._context.now_fn().date()
            token_date = self._token_date
            connected = self._connected
        if token_date == today:
            return connected
        self._context.send_fn(
            f"Broker token expired (set {token_date}, today {today}). Refresh the token in config and restart."
        )
        with self._kite_lock:
            self._connected = False
        return False

    def _symbol(self, name: str, direction: str, strike: int) -> str:
        suffix = "CE" if direction == "CALL" else "PE"
        expiry_str = self._context.expiry_str_fn(name)
        nse_sym = self._context.index_map.get(name, {}).get("nse")
        if not nse_sym:
            raise ValueError(f"Unknown index '{name}' in index_map — cannot build option symbol")
        return f"{nse_sym}{expiry_str}{strike}{suffix}"

    def _kite_order(self, name, direction, qty, strike, txn_type):
        if not self._ensure_token_fresh():
            return None
        with self._kite_lock:
            kite = self._kite
        if not kite:
            return None
        try:
            oid = kite.place_order(
                variety=kite.VARIETY_REGULAR,
                exchange=kite.EXCHANGE_NFO,
                tradingsymbol=self._symbol(name, direction, strike),
                transaction_type=txn_type,
                quantity=qty,
                product=kite.PRODUCT_MIS,
                order_type=kite.ORDER_TYPE_MARKET,
            )
            self._context.log_fn(f"[KITE] {txn_type} order: {oid}")
            return str(oid)
        except Exception as exc:
            self._context.send_fn(f"Order failed: {exc}")
            return None

    def place_order(self, name, direction, qty, strike):
        from kiteconnect import KiteConnect  # type: ignore

        self._rate_limit_wait()  # Rate limiting to prevent API ban
        return self._kite_order(name, direction, qty, strike, KiteConnect.TRANSACTION_TYPE_BUY)

    def exit_order(self, name, direction, qty, strike):
        from kiteconnect import KiteConnect  # type: ignore

        self._rate_limit_wait()  # Rate limiting to prevent API ban
        return self._kite_order(name, direction, qty, strike, KiteConnect.TRANSACTION_TYPE_SELL)

    def _order_record(self, order_id):
        with self._kite_lock:
            connected = self._connected
            kite = self._kite
        if not connected or not kite or not order_id:
            return None
        try:
            for row in kite.orders():
                if str(row.get("order_id", "")) == str(order_id):
                    return row
        except Exception as exc:
            self._context.log_fn(f"[KITE] orders() {exc}")
        return None

    def get_order_status(self, order_id) -> str:
        row = self._order_record(order_id)
        return str((row or {}).get("status") or "UNKNOWN")

    def cancel_order(self, order_id) -> bool:
        with self._kite_lock:
            connected = self._connected
            kite = self._kite
        if not connected or not kite or not order_id:
            return False
        try:
            kite.cancel_order(variety=kite.VARIETY_REGULAR, order_id=order_id)
            return True
        except Exception as exc:
            self._context.log_fn(f"[KITE CANCEL] {exc}")
            return False

    def get_fill_price(self, order_id) -> float | None:
        row = self._order_record(order_id)
        if not row:
            return None
        try:
            price = float(row.get("average_price") or 0)
            return price if price > 0 else None
        except Exception:
            return None

    def get_filled_quantity(self, order_id) -> int | None:
        row = self._order_record(order_id)
        if not row:
            return None
        try:
            return int(float(row.get("filled_quantity") or 0))
        except Exception:
            return None


class AngelBrokerAdapter(_PollingBrokerAdapter):
    def __init__(self, context: BrokerRuntimeContext) -> None:
        super().__init__(context)
        self._client = None
        self._connected = False
        self._lock = threading.Lock()
        self._connect()

    def _connect(self):
        try:
            from SmartApi import SmartConnect  # type: ignore

            sec = broker_connection_secrets(self._context.cfg, "ANGEL")
            client = SmartConnect(api_key=str(sec.get("api_key") or ""))
            session = client.generateSession(
                str(sec.get("client_id") or ""),
                str(sec.get("password") or ""),
                str(sec.get("totp_key") or ""),
            )
            if isinstance(session, dict) and session.get("status") is False:
                raise RuntimeError(str(session.get("message") or "session failed"))
            refresh = str(sec.get("refresh_token") or "")
            if refresh:
                try:
                    client.generateToken(refresh)
                except Exception:
                    pass
            with self._lock:
                self._client = client
                self._connected = True
            label = str(self._context.cfg.get("BROKER_NAME") or "").strip() or "Angel"
            self._context.log_fn(f"[SMARTAPI] Connected ({label})")
        except Exception as exc:
            self._context.log_fn(f"[SMARTAPI] Connect failed: {exc}")

    def _symbol(self, name, direction, strike) -> str:
        suffix = "CE" if direction == "CALL" else "PE"
        expiry_str = self._context.expiry_str_fn(name)
        nse_sym = self._context.index_map.get(name, {}).get("nse")
        if not nse_sym:
            raise ValueError(f"Unknown index '{name}' in index_map — cannot build option symbol")
        return f"{nse_sym}{expiry_str}{strike}{suffix}"

    def _order(self, name, direction, qty, strike, txn_type):
        with self._lock:
            client = self._client
            connected = self._connected
        if not connected or not client:
            return None
        try:
            payload = {
                "variety": "NORMAL",
                "tradingsymbol": self._symbol(name, direction, strike),
                "symboltoken": "0",
                "transactiontype": txn_type,
                "exchange": "NFO",
                "ordertype": "MARKET",
                "producttype": "INTRADAY",
                "duration": "DAY",
                "price": "0",
                "squareoff": "0",
                "stoploss": "0",
                "quantity": str(int(qty)),
            }
            result = client.placeOrder(payload)
            if not result:
                return None
            # SmartApi returns {"status": True, "data": {"orderid": "XXXXXX"}, ...}
            # Extract the real order ID so status/fill lookups match orderBook rows.
            if isinstance(result, dict):
                oid = str(result.get("data", {}).get("orderid") or result.get("orderid") or "").strip()
                return oid if oid else str(result)
            return str(result)
        except Exception as exc:
            self._context.log_fn(f"[SMARTAPI ORDER] {exc}")
            return None

    def place_order(self, name, direction, qty, strike):
        return self._order(name, direction, qty, strike, "BUY")

    def exit_order(self, name, direction, qty, strike):
        return self._order(name, direction, qty, strike, "SELL")

    def _order_book_rows(self):
        with self._lock:
            client = self._client
            connected = self._connected
        if not connected or not client:
            return []
        try:
            book = client.orderBook() or {}
            return book.get("data") if isinstance(book, dict) else book
        except Exception as exc:
            self._context.log_fn(f"[SMARTAPI BOOK] {exc}")
            return []

    def get_order_status(self, order_id) -> str:
        for row in self._order_book_rows() or []:
            if str(row.get("orderid", "")) == str(order_id):
                status = str(row.get("orderstatus", "UNKNOWN")).upper()
                return "COMPLETE" if "COMPLETE" in status else ("REJECTED" if "REJECTED" in status else status)
        return "UNKNOWN"

    def get_fill_price(self, order_id) -> float | None:
        for row in self._order_book_rows() or []:
            if str(row.get("orderid", "")) == str(order_id):
                try:
                    return float(row.get("averageprice") or 0) or None
                except Exception:
                    return None
        return None

    def get_filled_quantity(self, order_id) -> int | None:
        for row in self._order_book_rows() or []:
            if str(row.get("orderid", "")) == str(order_id):
                try:
                    return int(float(row.get("filledshares") or row.get("filled_qty") or 0))
                except Exception:
                    return None
        return None

    def get_positions(self):
        with self._lock:
            client = self._client
            connected = self._connected
        if not connected or not client:
            return []
        try:
            data = client.position() or {}
            return data.get("data") if isinstance(data, dict) else data
        except Exception as exc:
            self._context.log_fn(f"[SMARTAPI POS] {exc}")
            return []


def load_broker_factory_from_spec(spec: str) -> Callable[[BrokerRuntimeContext], BrokerAdapter] | None:
    """Load ``module.path:callable`` that takes ``BrokerRuntimeContext`` and returns a ``BrokerAdapter``."""
    raw = (spec or "").strip()
    if not raw or ":" not in raw:
        return None
    mod_name, _, attr = raw.partition(":")
    mod_name, attr = mod_name.strip(), attr.strip()
    if not mod_name or not attr:
        return None
    mod = sys.modules.get(mod_name)
    if mod is None:
        mod = sys.modules.get(mod_name.rsplit(".", 1)[-1])
    try:
        if mod is None:
            mod = importlib.import_module(mod_name)
    except Exception:
        mod = None
    if mod is None:
        short_name = mod_name.rsplit(".", 1)[-1]
        try:
            mod = importlib.import_module(short_name)
        except Exception:
            mod = None
    if mod is None:
        rel_module = Path(*mod_name.split("."))
        search_roots = [Path.cwd(), *[Path(p) for p in sys.path if p]]
        for root in search_roots:
            file_candidate = root / f"{rel_module}.py"
            init_candidate = root / rel_module / "__init__.py"
            target = file_candidate if file_candidate.is_file() else init_candidate if init_candidate.is_file() else None
            if target is None:
                continue
            try:
                loader_spec = importlib.util.spec_from_file_location(mod_name, target)
                if loader_spec is None or loader_spec.loader is None:
                    continue
                loaded = importlib.util.module_from_spec(loader_spec)
                sys.modules.setdefault(mod_name, loaded)
                loader_spec.loader.exec_module(loaded)
                mod = loaded
                break
            except Exception:
                sys.modules.pop(mod_name, None)
                continue
    if mod is None:
        return None
    fn = getattr(mod, attr, None)
    if not callable(fn):
        return None
    return fn  # type: ignore[return-value]


# ...existing code...
def create_broker_adapter(
    *,
    driver: str,
    broker_api_enabled: bool,
    paper_mode: bool,
    manual_signals_only: bool,
    execution_mode: str = "MANUAL",
    context: BrokerRuntimeContext,
) -> BrokerAdapter:
    if manual_signals_only or execution_mode == "SIGNAL_ONLY":
        return PaperBrokerAdapter()
    if not (broker_api_enabled and not paper_mode):
        return PaperBrokerAdapter()

    cfg = context.cfg
    custom_spec = str(cfg.get("BROKER_CUSTOM_FACTORY") or "").strip()
    factory = load_broker_factory_from_spec(custom_spec) if custom_spec else None
    if factory is not None:
        try:
            port = factory(context)
            if not isinstance(port, BrokerPort):
                context.log_fn(f"[BROKER] BROKER_CUSTOM_FACTORY returned {type(port)!r}, not BrokerPort — using paper")
                return PaperBrokerAdapter()
            return BrokerAdapter(port)
        except Exception as exc:
            context.log_fn(f"[BROKER] BROKER_CUSTOM_FACTORY failed: {exc} — using paper adapter")
            return PaperBrokerAdapter()

    normalized = str(driver or "GENERIC").upper()
    if normalized == "KITE":
        from infrastructure.adapters.brokers.kite.adapter import KiteBrokerAdapter as KitePort
        return BrokerAdapter(KitePort(context))
    if normalized == "ANGEL":
        from infrastructure.adapters.brokers.angel.adapter import AngelBrokerAdapter as AngelPort
        return BrokerAdapter(AngelPort(context))
    if normalized not in ("GENERIC", "PAPER", "SIM", "CUSTOM"):
        context.log_fn(
            f"[BROKER] Unknown BROKER_DRIVER={normalized!r} (set BROKER_CUSTOM_FACTORY for a third-party broker) — paper adapter"
        )
    return BrokerAdapter(PaperBrokerAdapter())
# ...existing code...


def create_broker_adapter_with_runtime_context(
    *,
    cfg: dict[str, Any],
    index_map: dict[str, Any],
    driver: str,
    broker_api_enabled: bool,
    paper_mode: bool,
    manual_signals_only: bool,
    execution_mode: str = "MANUAL",
    now_fn: Callable[[], Any],
    log_fn: Callable[[str], None],
    send_fn: Callable[[str], None],
    shutdown_is_set_fn: Callable[[], bool],
    hard_halt_is_set_fn: Callable[[], bool],
    sleep_fn: Callable[[float], None],
    broker_wait_poll_sec: float,
    expiry_str_fn: Callable[[str], str],
) -> BrokerAdapter:
    """Combine :func:`build_broker_runtime_context` and :func:`create_broker_adapter` (shared by index + stock)."""
    context = build_broker_runtime_context(
        cfg=cfg,
        index_map=index_map,
        now_fn=now_fn,
        log_fn=log_fn,
        send_fn=send_fn,
        shutdown_is_set_fn=shutdown_is_set_fn,
        hard_halt_is_set_fn=hard_halt_is_set_fn,
        sleep_fn=sleep_fn,
        broker_wait_poll_sec=broker_wait_poll_sec,
        expiry_str_fn=expiry_str_fn,
    )
    return create_broker_adapter(
        driver=driver,
        broker_api_enabled=broker_api_enabled,
        paper_mode=paper_mode,
        manual_signals_only=manual_signals_only,
        execution_mode=execution_mode,
        context=context,
    )
