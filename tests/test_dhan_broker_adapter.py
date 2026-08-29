"""Tests for infrastructure/adapters/brokers/dhan/adapter.py.

Mirrors the structure of the other broker adapter test files: error
classifier, factory-from-context credential extraction, and adapter
behavior against a mocked HTTP session.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("requests")

from infrastructure.adapters.brokers.dhan.adapter import (
    DhanBrokerAdapter,
    _classify_dhan_error,
    create_dhan_adapter,
    create_dhan_adapter_from_context,
)

# ==============================================================================
# Error classifier
# ==============================================================================


class TestClassifyDhanError:
    def test_token_expired(self):
        assert _classify_dhan_error(Exception("401 Unauthorized")) == "TOKEN_EXPIRED"

    def test_timeout(self):
        assert _classify_dhan_error(Exception("timed out")) == "TIMEOUT"

    def test_rate_limited(self):
        assert _classify_dhan_error(Exception("429 rate limit exceeded")) == "RATE_LIMITED"

    def test_unknown(self):
        assert _classify_dhan_error(Exception("something odd")) == "UNKNOWN"


# ==============================================================================
# create_dhan_adapter_from_context - credential extraction
# ==============================================================================


class TestCreateDhanAdapterFromContext:
    def test_broker_config_priority(self):
        ctx = MagicMock()
        ctx.cfg = {
            "BROKER_CONFIG": {"user_id": "cfg_client", "access_token": "cfg_token"},
            "DHAN_CLIENT_ID": "top_client",
            "DHAN_ACCESS_TOKEN": "top_token",
        }
        ctx.log_fn = print
        adapter = create_dhan_adapter_from_context(ctx)
        assert adapter._client_id == "cfg_client"
        assert adapter._access_token == "cfg_token"

    def test_top_level_fallback(self):
        ctx = MagicMock()
        ctx.cfg = {"DHAN_CLIENT_ID": "top_client", "DHAN_ACCESS_TOKEN": "top_token"}
        ctx.log_fn = print
        adapter = create_dhan_adapter_from_context(ctx)
        assert adapter._client_id == "top_client"
        assert adapter._access_token == "top_token"

    def test_missing_client_id_raises_value_error(self):
        ctx = MagicMock()
        ctx.cfg = {"DHAN_ACCESS_TOKEN": "token"}
        ctx.log_fn = print
        with pytest.raises(ValueError, match="DHAN_CLIENT_ID"):
            create_dhan_adapter_from_context(ctx)

    def test_missing_access_token_raises_value_error(self):
        ctx = MagicMock()
        ctx.cfg = {"DHAN_CLIENT_ID": "client"}
        ctx.log_fn = print
        with pytest.raises(ValueError, match="DHAN_ACCESS_TOKEN"):
            create_dhan_adapter_from_context(ctx)


# ==============================================================================
# DhanBrokerAdapter with a mocked HTTP session
# ==============================================================================


def _mock_response(status_code=200, body=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = body if body is not None else {}
    resp.text = str(body or {})
    return resp


@pytest.fixture()
def adapter() -> DhanBrokerAdapter:
    return create_dhan_adapter(client_id="test_client", access_token="test_token", log_fn=print)


class TestConnection:
    def test_connect_success(self, adapter: DhanBrokerAdapter):
        with patch("requests.Session") as mock_session_cls:
            mock_session_cls.return_value.request.return_value = _mock_response(200, [])
            assert adapter.connect() is True
            assert adapter._connected is True

    def test_connect_failure(self, adapter: DhanBrokerAdapter):
        with patch("requests.Session") as mock_session_cls:
            mock_session_cls.return_value.request.return_value = _mock_response(401, {})
            assert adapter.connect() is False

    def test_headers_use_dhan_specific_scheme(self, adapter: DhanBrokerAdapter):
        """Regression: Dhan uses access-token/client-id headers, not Bearer -
        different from every other adapter in this codebase."""
        headers = adapter._headers()
        assert headers["access-token"] == "test_token"
        assert headers["client-id"] == "test_client"
        assert "Authorization" not in headers


class TestOrderLifecycle:
    def test_place_order_requires_resolved_security_id(self, adapter: DhanBrokerAdapter):
        adapter._connected = True
        order = MagicMock(spec=["symbol", "direction", "quantity", "order_type", "price", "trigger_price"])
        order.symbol, order.direction, order.quantity = "NIFTY26JULFUT", "BUY", 50
        order.order_type, order.price, order.trigger_price = "MARKET", 0.0, 0.0
        with pytest.raises(RuntimeError, match="security_id"):
            adapter.place_order(order)

    def test_place_order_success(self, adapter: DhanBrokerAdapter):
        mock_session = MagicMock()
        mock_session.request.return_value = _mock_response(200, {"orderId": "112111182198", "orderStatus": "TRANSIT"})
        adapter._session = mock_session
        adapter._connected = True

        order = MagicMock(symbol="NIFTY26JULFUT", direction="BUY", quantity=50,
                           order_type="MARKET", price=0.0, trigger_price=0.0,
                           security_id="12345")
        order_id = adapter.place_order(order)
        assert order_id == "112111182198"

    def test_place_order_raises_when_not_connected(self, adapter: DhanBrokerAdapter):
        order = MagicMock(security_id="12345")
        with pytest.raises(RuntimeError, match="not connected"):
            adapter.place_order(order)

    def test_cancel_order_success(self, adapter: DhanBrokerAdapter):
        mock_session = MagicMock()
        mock_session.request.return_value = _mock_response(200, {"orderId": "1", "orderStatus": "CANCELLED"})
        adapter._session = mock_session
        adapter._connected = True
        assert adapter.cancel_order("1") is True

    def test_cancel_order_fails_when_not_connected(self, adapter: DhanBrokerAdapter):
        assert adapter.cancel_order("1") is False

    def test_modify_order_success(self, adapter: DhanBrokerAdapter):
        mock_session = MagicMock()
        mock_session.request.return_value = _mock_response(200, {"orderId": "1", "orderStatus": "PENDING"})
        adapter._session = mock_session
        adapter._connected = True
        assert adapter.modify_order("1", quantity=100, price=150.0) is True


class TestOrderQueries:
    def test_get_order_status(self, adapter: DhanBrokerAdapter):
        mock_session = MagicMock()
        mock_session.request.return_value = _mock_response(200, {"orderId": "112111182198", "orderStatus": "TRADED"})
        adapter._session = mock_session
        adapter._connected = True
        assert adapter.get_order_status("112111182198") == "TRADED"

    def test_get_fill_price_from_trade_book(self, adapter: DhanBrokerAdapter):
        mock_session = MagicMock()
        mock_session.request.return_value = _mock_response(
            200, [{"tradedPrice": 125.5, "tradedQuantity": 75}],
        )
        adapter._session = mock_session
        adapter._connected = True
        assert adapter.get_fill_price("112111182198") == 125.5

    def test_get_fill_price_averages_multiple_fills(self, adapter: DhanBrokerAdapter):
        mock_session = MagicMock()
        mock_session.request.return_value = _mock_response(
            200, [{"tradedPrice": 100.0, "tradedQuantity": 50}, {"tradedPrice": 110.0, "tradedQuantity": 50}],
        )
        adapter._session = mock_session
        adapter._connected = True
        assert adapter.get_fill_price("112111182198") == pytest.approx(105.0)

    def test_get_fill_price_none_when_no_trades(self, adapter: DhanBrokerAdapter):
        mock_session = MagicMock()
        mock_session.request.return_value = _mock_response(200, [])
        adapter._session = mock_session
        adapter._connected = True
        assert adapter.get_fill_price("112111182198") is None

    def test_get_fill_price_none_when_not_connected(self, adapter: DhanBrokerAdapter):
        assert adapter.get_fill_price("112111182198") is None

    def test_get_filled_quantity_from_trade_book(self, adapter: DhanBrokerAdapter):
        mock_session = MagicMock()
        mock_session.request.return_value = _mock_response(
            200, [{"tradedPrice": 125.5, "tradedQuantity": 75}],
        )
        adapter._session = mock_session
        adapter._connected = True
        assert adapter.get_filled_quantity("112111182198") == 75


class TestPositions:
    def test_get_positions(self, adapter: DhanBrokerAdapter):
        mock_session = MagicMock()
        mock_session.request.return_value = _mock_response(200, [
            {"tradingSymbol": "NIFTY26JULFUT", "netQty": 50, "costPrice": 24000.0,
             "lastTradedPrice": 24100.0, "unrealizedProfit": 5000.0, "realizedProfit": 0.0},
            {"tradingSymbol": "CLOSED", "netQty": 0, "costPrice": 100.0,
             "lastTradedPrice": 100.0, "unrealizedProfit": 0.0, "realizedProfit": 500.0},
        ])
        adapter._session = mock_session
        adapter._connected = True
        positions = adapter.get_positions()
        assert len(positions) == 1
        assert positions[0].symbol == "NIFTY26JULFUT"
        assert positions[0].unrealized_pnl == 5000.0

    def test_get_positions_empty_when_not_connected(self, adapter: DhanBrokerAdapter):
        assert adapter.get_positions() == []


class TestUnverifiedEndpoints:
    def test_get_quote_not_implemented(self, adapter: DhanBrokerAdapter):
        with pytest.raises(NotImplementedError):
            adapter.get_quote("NIFTY")

    def test_get_historical_data_not_implemented(self, adapter: DhanBrokerAdapter):
        import datetime
        with pytest.raises(NotImplementedError):
            adapter.get_historical_data("NIFTY", datetime.datetime.now(), datetime.datetime.now())

    def test_subscribe_returns_false(self, adapter: DhanBrokerAdapter):
        assert adapter.subscribe_to_market_data(["NIFTY"], lambda q: None) is False


class TestHealthCheck:
    def test_health_check_unhealthy_when_not_connected(self, adapter: DhanBrokerAdapter):
        result = adapter.health_check()
        assert result["status"] == "unhealthy"

    def test_health_check_healthy(self, adapter: DhanBrokerAdapter):
        mock_session = MagicMock()
        mock_session.request.return_value = _mock_response(200, [])
        adapter._session = mock_session
        adapter._connected = True
        result = adapter.health_check()
        assert result["status"] == "healthy"
