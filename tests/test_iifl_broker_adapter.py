"""Tests for infrastructure/adapters/brokers/iifl/adapter.py.

Mirrors tests/test_mstock_broker_adapter.py's structure: error classifier,
factory-from-context credential extraction (including the required,
no-default root_url), and adapter behavior against a mocked HTTP session.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("requests")

from infrastructure.adapters.brokers.iifl.adapter import (
    IIFLBrokerAdapter,
    _classify_iifl_error,
    _IIFLContext,
    create_iifl_adapter,
    create_iifl_adapter_from_context,
)

# ==============================================================================
# Error classifier
# ==============================================================================


class TestClassifyIIFLError:
    def test_token_expired(self):
        assert _classify_iifl_error(Exception("401 Unauthorized session expired")) == "TOKEN_EXPIRED"

    def test_timeout(self):
        assert _classify_iifl_error(Exception("request timed out")) == "TIMEOUT"

    def test_rate_limited(self):
        assert _classify_iifl_error(Exception("429 Rate limited")) == "RATE_LIMITED"

    def test_unknown(self):
        assert _classify_iifl_error(Exception("something odd")) == "UNKNOWN"


# ==============================================================================
# create_iifl_adapter_from_context - credential extraction
# ==============================================================================


class TestCreateIIFLAdapterFromContext:
    def test_broker_config_priority(self):
        ctx = MagicMock()
        ctx.cfg = {
            "BROKER_CONFIG": {
                "root_url": "https://real-iifl-host.example.com",
                "api_key": "cfg_key",
                "secret": "cfg_secret",
            },
        }
        ctx.log_fn = print
        adapter = create_iifl_adapter_from_context(ctx)
        assert adapter._root_url == "https://real-iifl-host.example.com"
        assert adapter._app_key == "cfg_key"

    def test_missing_root_url_raises_value_error(self):
        """root_url has no safe default - XTS is white-labelled per broker,
        there is no publicly-verifiable single IIFL endpoint to fall back to."""
        ctx = MagicMock()
        ctx.cfg = {"IIFL_APP_KEY": "key", "IIFL_SECRET_KEY": "secret"}
        ctx.log_fn = print
        with pytest.raises(ValueError, match="IIFL_ROOT_URL"):
            create_iifl_adapter_from_context(ctx)

    def test_missing_app_key_raises_value_error(self):
        ctx = MagicMock()
        ctx.cfg = {"IIFL_ROOT_URL": "https://x.example.com"}
        ctx.log_fn = print
        with pytest.raises(ValueError, match="IIFL_APP_KEY"):
            create_iifl_adapter_from_context(ctx)

    def test_missing_secret_key_raises_value_error(self):
        ctx = MagicMock()
        ctx.cfg = {"IIFL_ROOT_URL": "https://x.example.com", "IIFL_APP_KEY": "key"}
        ctx.log_fn = print
        with pytest.raises(ValueError, match="IIFL_SECRET_KEY"):
            create_iifl_adapter_from_context(ctx)


class TestConstructorRequiresRootURL:
    def test_empty_root_url_raises(self):
        ctx = _IIFLContext(root_url="", app_key="k", secret_key="s", log_fn=print)
        with pytest.raises(ValueError, match="root_url"):
            IIFLBrokerAdapter(ctx)


# ==============================================================================
# IIFLBrokerAdapter with a mocked HTTP session
# ==============================================================================


def _mock_response(status_code=200, body=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = body or {}
    resp.text = str(body or {})
    return resp


def _envelope(result):
    return {"type": "success", "code": "s-ok", "description": "ok", "result": result}


@pytest.fixture()
def adapter() -> IIFLBrokerAdapter:
    return create_iifl_adapter(
        root_url="https://real-iifl-host.example.com",
        app_key="test_key",
        secret_key="test_secret",
        log_fn=print,
    )


class TestConnection:
    def test_connect_success(self, adapter: IIFLBrokerAdapter):
        with patch("requests.Session") as mock_session_cls:
            mock_session_cls.return_value.request.return_value = _mock_response(
                200, _envelope({"token": "abc123"}),
            )
            assert adapter.connect() is True
            assert adapter._connected is True
            assert adapter._token == "abc123"

    def test_connect_failure_error_envelope(self, adapter: IIFLBrokerAdapter):
        with patch("requests.Session") as mock_session_cls:
            mock_session_cls.return_value.request.return_value = _mock_response(
                200, {"type": "error", "code": "e-auth", "description": "bad creds"},
            )
            assert adapter.connect() is False
            assert adapter._connected is False

    def test_disconnect(self, adapter: IIFLBrokerAdapter):
        with patch("requests.Session") as mock_session_cls:
            mock_session_cls.return_value.request.return_value = _mock_response(
                200, _envelope({"token": "abc123"}),
            )
            adapter.connect()
        adapter.disconnect()
        assert adapter._connected is False
        assert adapter._token is None


class TestOrderLifecycle:
    def test_place_order_requires_resolved_instrument_id(self, adapter: IIFLBrokerAdapter):
        adapter._connected = True
        adapter._token = "abc"
        order = MagicMock(spec=["symbol", "direction", "quantity", "order_type", "price", "trigger_price"])
        order.symbol, order.direction, order.quantity = "NIFTY26JULFUT", "BUY", 50
        order.order_type, order.price, order.trigger_price = "MARKET", 0.0, 0.0
        with pytest.raises(RuntimeError, match="exchange_instrument_id"):
            adapter.place_order(order)

    def test_place_order_success(self, adapter: IIFLBrokerAdapter):
        mock_session = MagicMock()
        mock_session.request.return_value = _mock_response(200, _envelope({"AppOrderID": 2190766863}))
        adapter._session = mock_session
        adapter._connected = True
        adapter._token = "abc"

        order = MagicMock(symbol="NIFTY26JULFUT", direction="BUY", quantity=50,
                           order_type="MARKET", price=0.0, trigger_price=0.0,
                           exchange_instrument_id=12345)
        order_id = adapter.place_order(order)
        assert order_id == "2190766863"

    def test_place_order_raises_when_not_connected(self, adapter: IIFLBrokerAdapter):
        order = MagicMock(exchange_instrument_id=12345)
        with pytest.raises(RuntimeError, match="not connected"):
            adapter.place_order(order)

    def test_cancel_order_success(self, adapter: IIFLBrokerAdapter):
        mock_session = MagicMock()
        mock_session.request.return_value = _mock_response(200, _envelope({}))
        adapter._session = mock_session
        adapter._connected = True
        adapter._token = "abc"
        assert adapter.cancel_order("2190766863") is True

    def test_cancel_order_fails_when_not_connected(self, adapter: IIFLBrokerAdapter):
        assert adapter.cancel_order("1") is False

    def test_modify_order_success(self, adapter: IIFLBrokerAdapter):
        mock_session = MagicMock()
        mock_session.request.return_value = _mock_response(200, _envelope({}))
        adapter._session = mock_session
        adapter._connected = True
        adapter._token = "abc"
        assert adapter.modify_order("2190766863", quantity=100, price=150.0) is True


class TestOrderQueries:
    ORDER_BOOK = [
        {"AppOrderID": 2190766863, "OrderStatus": "Filled", "AveragePrice": 125.5, "FilledQuantity": 75},
        {"AppOrderID": 2190766999, "OrderStatus": "Open", "AveragePrice": 0, "FilledQuantity": 0},
    ]

    def _adapter_with_order_book(self, adapter: IIFLBrokerAdapter):
        mock_session = MagicMock()
        mock_session.request.return_value = _mock_response(200, _envelope(self.ORDER_BOOK))
        adapter._session = mock_session
        adapter._connected = True
        adapter._token = "abc"
        return adapter

    def test_get_order_status(self, adapter: IIFLBrokerAdapter):
        adapter = self._adapter_with_order_book(adapter)
        assert adapter.get_order_status("2190766863") == "Filled"
        assert adapter.get_order_status("2190766999") == "Open"
        assert adapter.get_order_status("unknown") == "UNKNOWN"

    def test_get_fill_price(self, adapter: IIFLBrokerAdapter):
        adapter = self._adapter_with_order_book(adapter)
        assert adapter.get_fill_price("2190766863") == 125.5
        assert adapter.get_fill_price("2190766999") is None

    def test_get_fill_price_none_when_not_connected(self, adapter: IIFLBrokerAdapter):
        assert adapter.get_fill_price("2190766863") is None

    def test_get_filled_quantity(self, adapter: IIFLBrokerAdapter):
        adapter = self._adapter_with_order_book(adapter)
        assert adapter.get_filled_quantity("2190766863") == 75
        assert adapter.get_filled_quantity("2190766999") == 0


class TestPositions:
    def test_get_positions(self, adapter: IIFLBrokerAdapter):
        mock_session = MagicMock()
        mock_session.request.return_value = _mock_response(200, _envelope({
            "positionList": [
                {"TradingSymbol": "NIFTY26JULFUT", "Quantity": 50, "AveragePrice": 24000.0,
                 "LastTradedPrice": 24100.0, "UnrealizedMTM": 5000.0, "RealizedMTM": 0.0},
                {"TradingSymbol": "CLOSED", "Quantity": 0, "AveragePrice": 100.0,
                 "LastTradedPrice": 100.0, "UnrealizedMTM": 0.0, "RealizedMTM": 0.0},
            ],
        }))
        adapter._session = mock_session
        adapter._connected = True
        adapter._token = "abc"
        positions = adapter.get_positions()
        assert len(positions) == 1
        assert positions[0].symbol == "NIFTY26JULFUT"
        assert positions[0].unrealized_pnl == 5000.0

    def test_get_positions_empty_when_not_connected(self, adapter: IIFLBrokerAdapter):
        assert adapter.get_positions() == []


class TestUnverifiedEndpoints:
    def test_get_quote_not_implemented(self, adapter: IIFLBrokerAdapter):
        with pytest.raises(NotImplementedError):
            adapter.get_quote("NIFTY")

    def test_get_historical_data_not_implemented(self, adapter: IIFLBrokerAdapter):
        import datetime
        with pytest.raises(NotImplementedError):
            adapter.get_historical_data("NIFTY", datetime.datetime.now(), datetime.datetime.now())

    def test_subscribe_returns_false(self, adapter: IIFLBrokerAdapter):
        assert adapter.subscribe_to_market_data(["NIFTY"], lambda q: None) is False


class TestHealthCheck:
    def test_health_check_unhealthy_when_not_connected(self, adapter: IIFLBrokerAdapter):
        result = adapter.health_check()
        assert result["status"] == "unhealthy"

    def test_health_check_healthy(self, adapter: IIFLBrokerAdapter):
        mock_session = MagicMock()
        mock_session.request.return_value = _mock_response(200, _envelope([]))
        adapter._session = mock_session
        adapter._connected = True
        adapter._token = "abc"
        result = adapter.health_check()
        assert result["status"] == "healthy"
