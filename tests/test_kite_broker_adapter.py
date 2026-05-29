"""
Tests for the KiteBrokerAdapter (Zerodha Kite Connect).

Because ``kiteconnect`` is typically not installed in CI / dev environments,
the tests that construct ``KiteBrokerAdapter`` verify that an ``ImportError``
is raised when the library is absent, while the stateless helper functions
are tested unconditionally.
"""

from __future__ import annotations

import time
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from infrastructure.adapters.brokers.kite.adapter import (
    KiteBrokerAdapter,
    _KiteContext,
    _classify_kite_error,
    create_kite_adapter,
    create_kite_adapter_from_context,
)


# ==============================================================================
# Error classifier (stateless – no KiteConnect dependency)
# ==============================================================================


class TestClassifyKiteError:
    """Verify the error classifier maps Kite exceptions to readable strings."""

    def test_token_expired(self):
        err = Exception("Token expired or invalid token")
        assert _classify_kite_error(err) == "TOKEN_EXPIRED"

    def test_timeout(self):
        err = Exception("Connection timed out after 5 seconds")
        assert _classify_kite_error(err) == "TIMEOUT"

    def test_rate_limited(self):
        err = Exception("Rate limit exceeded: 200 requests per minute")
        assert _classify_kite_error(err) == "RATE_LIMITED"

    def test_order_rejected(self):
        err = Exception("Order rejected: insufficient margin")
        assert _classify_kite_error(err) == "ORDER_REJECTED"

    def test_margin_insufficient(self):
        err = Exception("Insufficient margin for this order")
        assert _classify_kite_error(err) == "MARGIN_INSUFFICIENT"

    def test_generic_error(self):
        err = Exception("Something completely unexpected happened")
        assert _classify_kite_error(err) == "UNKNOWN"

    def test_auth_in_message(self):
        err = Exception("Authentication failed: invalid API key")
        assert _classify_kite_error(err) == "TOKEN_EXPIRED"

    def test_network_timeout(self):
        err = Exception("timed out connecting to api.kite.trade")
        assert _classify_kite_error(err) == "TIMEOUT"

    def test_rate_limit_exact(self):
        err = Exception("limit exceeded for API call")
        assert _classify_kite_error(err) == "RATE_LIMITED"

    def test_empty_message(self):
        err = Exception("")
        assert _classify_kite_error(err) == "UNKNOWN"

    def test_non_standard_exception(self):
        err = ValueError("token not found in response")
        assert _classify_kite_error(err) == "TOKEN_EXPIRED"


# ==============================================================================
# KiteBrokerAdapter constructor (KiteConnect absent)
# ==============================================================================


class TestKiteBrokerAdapterConstructor:
    """When ``kiteconnect`` is not installed, construction must fail with
    ``ImportError``."""

    def test_raises_import_error_when_kite_unavailable(self):
        ctx = _KiteContext(api_key="test", access_token="test", log_fn=print)
        with pytest.raises(ImportError, match="KiteConnect library"):
            KiteBrokerAdapter(ctx)

    def test_raises_import_error_create_kite_adapter(self):
        with pytest.raises(ImportError, match="KiteConnect library"):
            create_kite_adapter(api_key="x", access_token="y")

    def test_raises_import_error_from_context(self):
        ctx = MagicMock()
        ctx.cfg = {"KITE_API_KEY": "x", "KITE_ACCESS_TOKEN": "y"}
        ctx.log_fn = print
        with pytest.raises(ImportError, match="KiteConnect library"):
            create_kite_adapter_from_context(ctx)


# ==============================================================================
# Factory helpers (no KiteConnect needed)
# ==============================================================================


class TestCreateKiteAdapterFromContext:
    """Test credential extraction logic in ``create_kite_adapter_from_context``
    without requiring KiteConnect."""

    def test_broker_config_priority(self):
        """BROKER_CONFIG keys take priority over top-level KITE_* keys."""
        ctx = MagicMock()
        ctx.cfg = {
            "BROKER_CONFIG": {
                "api_key": "from_broker_config",
                "access_token": "token_bc",
            },
            "KITE_API_KEY": "from_top_level",
            "KITE_ACCESS_TOKEN": "token_top",
        }
        ctx.log_fn = print
        with pytest.raises(ImportError):
            # We expect ImportError because KiteConnect is not installed,
            # but the credentials should be correctly extracted first.
            try:
                create_kite_adapter_from_context(ctx)
            except ImportError:
                raise
            except ValueError as exc:
                pytest.fail(f"Unexpected ValueError: {exc}")

    def test_top_level_fallback(self):
        """When BROKER_CONFIG is absent, fall back to KITE_API_KEY /
        KITE_ACCESS_TOKEN top-level keys."""
        ctx = MagicMock()
        ctx.cfg = {
            "KITE_API_KEY": "top_key",
            "KITE_ACCESS_TOKEN": "top_token",
        }
        ctx.log_fn = print
        with pytest.raises(ImportError):
            create_kite_adapter_from_context(ctx)

    def test_missing_api_key_raises_value_error(self):
        """Missing KITE_API_KEY must raise ValueError before reaching adapter."""
        ctx = MagicMock()
        ctx.cfg = {}
        ctx.log_fn = print
        with pytest.raises(ValueError, match="KITE_API_KEY"):
            create_kite_adapter_from_context(ctx)

    def test_missing_access_token_raises_value_error(self):
        """Missing KITE_ACCESS_TOKEN must raise ValueError before reaching adapter."""
        ctx = MagicMock()
        ctx.cfg = {"KITE_API_KEY": "key_present"}
        ctx.log_fn = print
        with pytest.raises(ValueError, match="KITE_ACCESS_TOKEN"):
            create_kite_adapter_from_context(ctx)


# ==============================================================================
# KiteBrokerAdapter with mocked KiteConnect
# ==============================================================================


class MockKiteConnect:
    """Minimal mock of the KiteConnect SDK for adapter tests."""

    TRANSACTION_TYPE_BUY = "BUY"
    TRANSACTION_TYPE_SELL = "SELL"
    ORDER_TYPE_MARKET = "MARKET"
    ORDER_TYPE_LIMIT = "LIMIT"
    ORDER_TYPE_SL = "SL"
    ORDER_TYPE_SL_M = "SL-M"
    VARIETY_REGULAR = "REGULAR"
    EXCHANGE_NSE = "NSE"
    EXCHANGE_NFO = "NFO"
    PRODUCT_MIS = "MIS"
    PRODUCT_NRML = "NRML"
    VALIDITY_DAY = "DAY"
    INTERVAL_MINUTE = "minute"
    INTERVAL_3MINUTE = "3minute"
    INTERVAL_5MINUTE = "5minute"
    INTERVAL_15MINUTE = "15minute"
    INTERVAL_30MINUTE = "30minute"
    INTERVAL_60MINUTE = "60minute"
    INTERVAL_DAY = "day"

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self.access_token: str = ""

    def set_access_token(self, token: str) -> None:
        self.access_token = token

    def profile(self) -> dict:
        return {"user_id": "TEST123", "user_name": "Test User"}

    def instruments(self, exchange: str) -> list[dict]:
        return [
            {"tradingsymbol": "NIFTY", "exchange": "NSE", "instrument_token": 12345},
            {"tradingsymbol": "BANKNIFTY", "exchange": "NSE", "instrument_token": 67890},
        ]

    def place_order(self, **kwargs: object) -> str:
        return "ORDER123"

    def cancel_order(self, **kwargs: object) -> dict:
        return {"order_id": kwargs.get("order_id", "")}

    def modify_order(self, **kwargs: object) -> dict:
        return {"order_id": kwargs.get("order_id", "")}

    def orders(self) -> list[dict]:
        return [
            {"order_id": "ORDER123", "status": "COMPLETE", "tradingsymbol": "NIFTY"},
            {"order_id": "ORDER456", "status": "PENDING", "tradingsymbol": "BANKNIFTY"},
        ]

    def positions(self) -> dict:
        return {
            "net": [
                {
                    "tradingsymbol": "NIFTY",
                    "quantity": 75,
                    "average_price": 18500.0,
                    "last_price": 18600.0,
                    "pnl": 7500.0,
                    "exchange_update_time": int(time.time() * 1000),
                },
            ],
            "day": [],
        }

    def quote(self, tokens: list[int]) -> dict:
        return {
            "12345": {
                "bid": 18595.0,
                "ask": 18605.0,
                "last_price": 18600.0,
                "volume": 100000,
            },
        }

    def historical_data(
        self,
        instrument_token: int,
        from_date: datetime,
        to_date: datetime,
        interval: str,
    ) -> list[dict]:
        return [
            {"date": "2024-01-01", "open": 18500, "high": 18600, "low": 18400, "close": 18550, "volume": 50000},
        ]


@pytest.fixture
def mock_kite_module():
    """Patch ``kiteconnect`` so the adapter can be instantiated.

    **Important:** Cleans up ``sys.modules`` entries on teardown so that
    tests which rely on ``KiteExceptions is None`` (i.e. ``kiteconnect``
    absent) are not polluted by leaked mock objects.
    """
    import sys
    original_modules = {
        k: v for k, v in sys.modules.items()
        if k.startswith("kiteconnect")
    }
    with patch.dict("sys.modules", {
        "kiteconnect": MagicMock(),
        "kiteconnect.exceptions": MagicMock(),
    }):
        # Wire up the mock KiteConnect class
        sys.modules["kiteconnect"].KiteConnect = MockKiteConnect
        sys.modules["kiteconnect.exceptions"].TokenException = Exception
        sys.modules["kiteconnect.exceptions"].OrderException = Exception
        sys.modules["kiteconnect.exceptions"].NetworkException = Exception
        sys.modules["kiteconnect.exceptions"].InputException = Exception
        sys.modules["kiteconnect.exceptions"].DataException = Exception
        sys.modules["kiteconnect.exceptions"].PermissionException = Exception
        yield
        # Cleanup: remove mock entries so adapter module-level code
        # re-evaluates ``KiteExceptions is None`` on next import.
        for key in list(sys.modules.keys()):
            if key.startswith("kiteconnect"):
                del sys.modules[key]
        # Restore any pre-existing kiteconnect entries
        sys.modules.update(original_modules)


@pytest.mark.usefixtures("mock_kite_module")
class TestKiteBrokerAdapterMocked:
    """Test the adapter behaviour with a mocked KiteConnect SDK."""

    # Force re-import the adapter module to pick up the mock
    @pytest.fixture(autouse=True)
    def _reimport_adapter(self, mock_kite_module):
        import importlib
        from infrastructure.adapters.brokers import kite as kite_pkg
        importlib.reload(kite_pkg.adapter)
        self.module = kite_pkg.adapter

    def _make_adapter(self):
        ctx = self.module._KiteContext(
            api_key="test_key",
            access_token="test_token",
            log_fn=print,
        )
        return self.module.KiteBrokerAdapter(ctx)

    # ── Connection ───────────────────────────────────────────────────────

    def test_connect_success(self):
        adapter = self._make_adapter()
        assert adapter.connect() is True
        assert adapter._connected is True

    def test_connect_called_twice(self):
        adapter = self._make_adapter()
        assert adapter.connect() is True
        assert adapter.connect() is True  # second connect should succeed

    def test_disconnect(self):
        adapter = self._make_adapter()
        adapter.connect()
        adapter.disconnect()
        assert adapter._connected is False
        assert adapter._kite is None

    def test_health_check_healthy(self):
        adapter = self._make_adapter()
        adapter.connect()
        result = adapter.health_check()
        assert result["status"] == "healthy"
        assert result["connected"] is True

    def test_health_check_unhealthy_when_not_connected(self):
        adapter = self._make_adapter()
        result = adapter.health_check()
        assert result["status"] == "unhealthy"
        assert result["connected"] is False

    # ── Place order ──────────────────────────────────────────────────────

    def test_place_order_raises_when_not_connected(self):
        adapter = self._make_adapter()
        with pytest.raises(RuntimeError, match="not connected"):
            adapter.place_order(MagicMock(symbol="NIFTY"))

    def test_place_order_success(self):
        adapter = self._make_adapter()
        adapter.connect()
        order = MagicMock(symbol="NIFTY", direction="BUY", quantity=75,
                          order_type="MARKET", price=0.0, trigger_price=0.0,
                          product="MIS", exchange="NFO", tag="test")
        order_id = adapter.place_order(order)
        assert order_id == "ORDER123"

    # ── Cancel order ─────────────────────────────────────────────────────

    def test_cancel_order_success(self):
        adapter = self._make_adapter()
        adapter.connect()
        assert adapter.cancel_order("ORDER123") is True

    def test_cancel_order_fails_when_not_connected(self):
        adapter = self._make_adapter()
        assert adapter.cancel_order("ORDER123") is False

    # ── Modify order ─────────────────────────────────────────────────────

    def test_modify_order_success(self):
        adapter = self._make_adapter()
        adapter.connect()
        assert adapter.modify_order("ORDER123", quantity=100, price=18600.0) is True

    def test_modify_order_fails_when_not_connected(self):
        adapter = self._make_adapter()
        assert adapter.modify_order("ORDER123") is False

    # ── Get order status ─────────────────────────────────────────────────

    def test_get_order_status(self):
        adapter = self._make_adapter()
        adapter.connect()
        assert adapter.get_order_status("ORDER123") == "COMPLETE"
        assert adapter.get_order_status("ORDER456") == "PENDING"
        assert adapter.get_order_status("UNKNOWN_ID") == "UNKNOWN"

    def test_get_order_status_error_when_not_connected(self):
        adapter = self._make_adapter()
        assert adapter.get_order_status("ORDER123") == "ERROR"

    # ── Get positions ────────────────────────────────────────────────────

    def test_get_positions(self):
        adapter = self._make_adapter()
        adapter.connect()
        positions = adapter.get_positions()
        assert len(positions) == 1
        assert positions[0].symbol == "NIFTY"
        assert positions[0].quantity == 75
        assert positions[0].unrealized_pnl == 7500.0

    def test_get_positions_empty_when_not_connected(self):
        adapter = self._make_adapter()
        assert adapter.get_positions() == []

    # ── Get quote ────────────────────────────────────────────────────────

    def test_get_quote(self):
        adapter = self._make_adapter()
        adapter.connect()
        quote = adapter.get_quote("NIFTY")
        assert quote.symbol == "NIFTY"
        assert quote.bid == 18595.0
        assert quote.ask == 18605.0
        assert quote.last == 18600.0
        assert quote.volume == 100000

    def test_get_quote_raises_when_not_connected(self):
        adapter = self._make_adapter()
        with pytest.raises(RuntimeError, match="not connected"):
            adapter.get_quote("NIFTY")

    # ── Market data subscription ─────────────────────────────────────────

    def test_subscribe_not_implemented(self):
        adapter = self._make_adapter()
        assert adapter.subscribe_to_market_data(["NIFTY"], print) is False

    def test_unsubscribe_not_implemented(self):
        adapter = self._make_adapter()
        assert adapter.unsubscribe_from_market_data("NIFTY") is False

    # ── Historical data ──────────────────────────────────────────────────

    def test_get_historical_data(self):
        adapter = self._make_adapter()
        adapter.connect()
        data = adapter.get_historical_data(
            "NIFTY",
            datetime(2024, 1, 1),
            datetime(2024, 1, 31),
            interval="day",
        )
        assert len(data) == 1
        assert data[0]["symbol"] if "symbol" in data[0] else data[0]["close"] == 18550

    def test_get_historical_data_raises_when_not_connected(self):
        adapter = self._make_adapter()
        with pytest.raises(RuntimeError, match="not connected"):
            adapter.get_historical_data("NIFTY", datetime.now(), datetime.now())

    # ── Rate limiting ────────────────────────────────────────────────────

    def test_rate_limit_enforces_minimum_interval(self):
        adapter = self._make_adapter()
        adapter._enable_rate_limit = True
        adapter._min_request_interval = 0.05  # 50 ms
        start = time.time()
        adapter._rate_limit()
        adapter._rate_limit()
        elapsed = time.time() - start
        assert elapsed >= 0.05  # at least one wait cycle

    def test_rate_limit_disabled(self):
        adapter = self._make_adapter()
        adapter._enable_rate_limit = False
        start = time.time()
        for _ in range(10):
            adapter._rate_limit()
        elapsed = time.time() - start
        assert elapsed < 0.1  # very fast without rate limiting


# ==============================================================================
# Edge cases
# ==============================================================================


class TestKiteBrokerAdapterEdgeCases:
    """Test edge cases and error handling paths."""

    @pytest.mark.usefixtures("mock_kite_module")
    def test_place_order_unknown_symbol(self):
        import importlib
        from infrastructure.adapters.brokers import kite as kite_pkg
        importlib.reload(kite_pkg.adapter)

        ctx = kite_pkg.adapter._KiteContext(
            api_key="key", access_token="token", log_fn=print
        )
        adapter = kite_pkg.adapter.KiteBrokerAdapter(ctx)
        adapter.connect()
        order = MagicMock(symbol="UNKNOWN_SYMBOL", direction="BUY", quantity=1,
                          order_type="MARKET", price=0.0, trigger_price=0.0,
                          product="MIS", exchange="NFO", tag="")
        with pytest.raises(RuntimeError, match="Cannot resolve instrument token"):
            adapter.place_order(order)

    @pytest.mark.usefixtures("mock_kite_module")
    def test_get_quote_unknown_symbol(self):
        import importlib
        from infrastructure.adapters.brokers import kite as kite_pkg
        importlib.reload(kite_pkg.adapter)

        ctx = kite_pkg.adapter._KiteContext(
            api_key="key", access_token="token", log_fn=print
        )
        adapter = kite_pkg.adapter.KiteBrokerAdapter(ctx)
        adapter.connect()
        with pytest.raises(RuntimeError, match="Cannot resolve instrument token"):
            adapter.get_quote("UNKNOWN_SYMBOL")

    def test_error_classifier_with_non_standard_exceptions(self):
        """Verify custom exception types are handled gracefully."""
        class CustomOrderError(Exception):
            pass

        err = CustomOrderError("order rejected: insufficient funds")
        assert "ORDER_REJECTED" in _classify_kite_error(err)

    @pytest.mark.usefixtures("mock_kite_module")
    def test_get_positions_skip_zero_quantity(self):
        import importlib
        from infrastructure.adapters.brokers import kite as kite_pkg
        importlib.reload(kite_pkg.adapter)
        with patch.object(MockKiteConnect, "positions", return_value={
            "net": [
                {"tradingsymbol": "NIFTY", "quantity": 0, "average_price": 0,
                 "last_price": 0, "pnl": 0, "exchange_update_time": 0},
                {"tradingsymbol": "BANKNIFTY", "quantity": 50, "average_price": 37000,
                 "last_price": 37100, "pnl": 5000, "exchange_update_time": int(time.time() * 1000)},
            ],
            "day": [],
        }):
            ctx = kite_pkg.adapter._KiteContext(
                api_key="key", access_token="token", log_fn=print
            )
            adapter = kite_pkg.adapter.KiteBrokerAdapter(ctx)
            adapter.connect()
            positions = adapter.get_positions()
            assert len(positions) == 1
            assert positions[0].symbol == "BANKNIFTY"
