"""Tests for infrastructure/adapters/brokers/upstox/adapter.py.

Mirrors the structure of the mStock/Groww adapter tests: error classifier,
factory-from-context credential extraction, and adapter behavior against
a mocked HTTP session.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("requests")

from infrastructure.adapters.brokers.upstox.adapter import (
    UpstoxBrokerAdapter,
    _classify_upstox_error,
    create_upstox_adapter,
    create_upstox_adapter_from_context,
)

# ==============================================================================
# Error classifier
# ==============================================================================


class TestClassifyUpstoxError:
    def test_token_expired(self):
        assert _classify_upstox_error(Exception("401 Unauthorized")) == "TOKEN_EXPIRED"

    def test_timeout(self):
        assert _classify_upstox_error(Exception("timed out")) == "TIMEOUT"

    def test_rate_limited(self):
        assert _classify_upstox_error(Exception("429 too many requests, rate limit")) == "RATE_LIMITED"

    def test_unknown(self):
        assert _classify_upstox_error(Exception("something odd")) == "UNKNOWN"


# ==============================================================================
# create_upstox_adapter_from_context - credential extraction
# ==============================================================================


class TestCreateUpstoxAdapterFromContext:
    def test_broker_config_priority(self):
        ctx = MagicMock()
        ctx.cfg = {"BROKER_CONFIG": {"access_token": "cfg_token"}, "UPSTOX_ACCESS_TOKEN": "top_token"}
        ctx.log_fn = print
        adapter = create_upstox_adapter_from_context(ctx)
        assert adapter._access_token == "cfg_token"

    def test_top_level_fallback(self):
        ctx = MagicMock()
        ctx.cfg = {"UPSTOX_ACCESS_TOKEN": "top_token"}
        ctx.log_fn = print
        adapter = create_upstox_adapter_from_context(ctx)
        assert adapter._access_token == "top_token"

    def test_missing_access_token_raises_value_error(self):
        ctx = MagicMock()
        ctx.cfg = {}
        ctx.log_fn = print
        with pytest.raises(ValueError, match="UPSTOX_ACCESS_TOKEN"):
            create_upstox_adapter_from_context(ctx)


# ==============================================================================
# UpstoxBrokerAdapter with a mocked HTTP session
# ==============================================================================


def _mock_response(status_code=200, body=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = body or {}
    resp.text = str(body or {})
    return resp


@pytest.fixture()
def adapter() -> UpstoxBrokerAdapter:
    return create_upstox_adapter(access_token="test_token", log_fn=print)


class TestConnection:
    def test_connect_success(self, adapter: UpstoxBrokerAdapter):
        with patch("requests.Session") as mock_session_cls:
            mock_session_cls.return_value.request.return_value = _mock_response(200, {"status": "success", "data": []})
            assert adapter.connect() is True
            assert adapter._connected is True

    def test_connect_failure(self, adapter: UpstoxBrokerAdapter):
        with patch("requests.Session") as mock_session_cls:
            mock_session_cls.return_value.request.return_value = _mock_response(401, {})
            assert adapter.connect() is False


class TestOrderLifecycle:
    def test_place_order_requires_resolved_instrument_token(self, adapter: UpstoxBrokerAdapter):
        adapter._connected = True
        order = MagicMock(spec=["symbol", "direction", "quantity", "order_type", "price", "trigger_price"])
        order.symbol, order.direction, order.quantity = "NIFTY26JULFUT", "BUY", 50
        order.order_type, order.price, order.trigger_price = "MARKET", 0.0, 0.0
        with pytest.raises(RuntimeError, match="instrument_token"):
            adapter.place_order(order)

    def test_place_order_success(self, adapter: UpstoxBrokerAdapter):
        mock_session = MagicMock()
        mock_session.request.return_value = _mock_response(
            200, {"status": "success", "data": {"order_id": "1644490272000"}},
        )
        adapter._session = mock_session
        adapter._connected = True

        order = MagicMock(symbol="NIFTY26JULFUT", direction="BUY", quantity=50,
                           order_type="MARKET", price=0.0, trigger_price=0.0,
                           instrument_token="NSE_FO|12345")
        order_id = adapter.place_order(order)
        assert order_id == "1644490272000"

    def test_place_order_raises_when_not_connected(self, adapter: UpstoxBrokerAdapter):
        order = MagicMock(instrument_token="NSE_FO|12345")
        with pytest.raises(RuntimeError, match="not connected"):
            adapter.place_order(order)

    def test_cancel_order_success(self, adapter: UpstoxBrokerAdapter):
        mock_session = MagicMock()
        mock_session.request.return_value = _mock_response(200, {"status": "success", "data": {"order_id": "1"}})
        adapter._session = mock_session
        adapter._connected = True
        assert adapter.cancel_order("1") is True

    def test_cancel_order_fails_when_not_connected(self, adapter: UpstoxBrokerAdapter):
        assert adapter.cancel_order("1") is False

    def test_modify_order_success(self, adapter: UpstoxBrokerAdapter):
        mock_session = MagicMock()
        mock_session.request.return_value = _mock_response(200, {"status": "success", "data": {"order_id": "1"}})
        adapter._session = mock_session
        adapter._connected = True
        assert adapter.modify_order("1", quantity=100, price=150.0) is True


class TestOrderQueries:
    def _adapter_with_detail(self, adapter: UpstoxBrokerAdapter, data):
        mock_session = MagicMock()
        mock_session.request.return_value = _mock_response(200, {"status": "success", "data": data})
        adapter._session = mock_session
        adapter._connected = True
        return adapter

    def test_get_order_status(self, adapter: UpstoxBrokerAdapter):
        adapter = self._adapter_with_detail(
            adapter, {"status": "complete", "average_price": 570.95, "filled_quantity": 1, "pending_quantity": 0},
        )
        assert adapter.get_order_status("231019025562880") == "complete"

    def test_get_fill_price(self, adapter: UpstoxBrokerAdapter):
        adapter = self._adapter_with_detail(
            adapter, {"status": "complete", "average_price": 570.95, "filled_quantity": 1},
        )
        assert adapter.get_fill_price("231019025562880") == 570.95

    def test_get_fill_price_none_when_zero(self, adapter: UpstoxBrokerAdapter):
        adapter = self._adapter_with_detail(
            adapter, {"status": "open", "average_price": 0, "filled_quantity": 0},
        )
        assert adapter.get_fill_price("231019025562880") is None

    def test_get_fill_price_none_when_not_connected(self, adapter: UpstoxBrokerAdapter):
        assert adapter.get_fill_price("231019025562880") is None

    def test_get_filled_quantity(self, adapter: UpstoxBrokerAdapter):
        adapter = self._adapter_with_detail(
            adapter, {"status": "complete", "average_price": 570.95, "filled_quantity": 1},
        )
        assert adapter.get_filled_quantity("231019025562880") == 1


class TestPositions:
    def test_get_positions(self, adapter: UpstoxBrokerAdapter):
        mock_session = MagicMock()
        mock_session.request.return_value = _mock_response(200, {"status": "success", "data": [
            {"trading_symbol": "NIFTY26JULFUT", "quantity": 50, "average_price": 24000.0,
             "last_price": 24100.0, "pnl": 5000.0, "unrealised": 5000.0, "realised": 0.0},
            {"trading_symbol": "CLOSED", "quantity": 0, "average_price": 100.0,
             "last_price": 100.0, "pnl": 0.0, "unrealised": 0.0, "realised": 0.0},
        ]})
        adapter._session = mock_session
        adapter._connected = True
        positions = adapter.get_positions()
        assert len(positions) == 1
        assert positions[0].symbol == "NIFTY26JULFUT"
        assert positions[0].unrealized_pnl == 5000.0

    def test_get_positions_empty_when_not_connected(self, adapter: UpstoxBrokerAdapter):
        assert adapter.get_positions() == []


class TestUnverifiedEndpoints:
    def test_get_quote_not_implemented(self, adapter: UpstoxBrokerAdapter):
        with pytest.raises(NotImplementedError):
            adapter.get_quote("NIFTY")

    def test_get_historical_data_not_implemented(self, adapter: UpstoxBrokerAdapter):
        import datetime
        with pytest.raises(NotImplementedError):
            adapter.get_historical_data("NIFTY", datetime.datetime.now(), datetime.datetime.now())

    def test_subscribe_returns_false(self, adapter: UpstoxBrokerAdapter):
        assert adapter.subscribe_to_market_data(["NIFTY"], lambda q: None) is False


class TestHealthCheck:
    def test_health_check_unhealthy_when_not_connected(self, adapter: UpstoxBrokerAdapter):
        result = adapter.health_check()
        assert result["status"] == "unhealthy"

    def test_health_check_healthy(self, adapter: UpstoxBrokerAdapter):
        mock_session = MagicMock()
        mock_session.request.return_value = _mock_response(200, {"status": "success", "data": []})
        adapter._session = mock_session
        adapter._connected = True
        result = adapter.health_check()
        assert result["status"] == "healthy"
