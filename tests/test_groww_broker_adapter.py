"""Tests for infrastructure/adapters/brokers/groww/adapter.py.

Mirrors tests/test_mstock_broker_adapter.py's structure: error classifier,
factory-from-context credential extraction, and adapter behavior against
a mocked HTTP session.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("requests")

from infrastructure.adapters.brokers.groww.adapter import (
    GrowwBrokerAdapter,
    _classify_groww_error,
    create_groww_adapter,
    create_groww_adapter_from_context,
)

# ==============================================================================
# Error classifier
# ==============================================================================


class TestClassifyGrowwError:
    def test_token_expired(self):
        assert _classify_groww_error(Exception("401 Unauthorized")) == "TOKEN_EXPIRED"

    def test_timeout(self):
        assert _classify_groww_error(Exception("request timed out")) == "TIMEOUT"

    def test_rate_limited(self):
        assert _classify_groww_error(Exception("429 Rate limited")) == "RATE_LIMITED"

    def test_unknown(self):
        assert _classify_groww_error(Exception("something odd")) == "UNKNOWN"


# ==============================================================================
# create_groww_adapter_from_context - credential extraction
# ==============================================================================


class TestCreateGrowwAdapterFromContext:
    def test_broker_config_priority(self):
        ctx = MagicMock()
        ctx.cfg = {
            "BROKER_CONFIG": {"access_token": "cfg_token"},
            "GROWW_ACCESS_TOKEN": "top_token",
        }
        ctx.log_fn = print
        adapter = create_groww_adapter_from_context(ctx)
        assert adapter._access_token == "cfg_token"

    def test_top_level_fallback(self):
        ctx = MagicMock()
        ctx.cfg = {"GROWW_ACCESS_TOKEN": "top_token"}
        ctx.log_fn = print
        adapter = create_groww_adapter_from_context(ctx)
        assert adapter._access_token == "top_token"

    def test_missing_access_token_raises_value_error(self):
        ctx = MagicMock()
        ctx.cfg = {}
        ctx.log_fn = print
        with pytest.raises(ValueError, match="GROWW_ACCESS_TOKEN"):
            create_groww_adapter_from_context(ctx)


# ==============================================================================
# GrowwBrokerAdapter with a mocked HTTP session
# ==============================================================================


def _mock_response(status_code=200, body=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = body or {}
    resp.text = str(body or {})
    return resp


@pytest.fixture()
def adapter() -> GrowwBrokerAdapter:
    return create_groww_adapter(access_token="test_token", log_fn=print)


class TestConnection:
    def test_connect_success(self, adapter: GrowwBrokerAdapter):
        with patch("requests.Session") as mock_session_cls:
            mock_session_cls.return_value.request.return_value = _mock_response(200, {"positions": []})
            assert adapter.connect() is True
            assert adapter._connected is True

    def test_connect_failure(self, adapter: GrowwBrokerAdapter):
        with patch("requests.Session") as mock_session_cls:
            mock_session_cls.return_value.request.return_value = _mock_response(401, {})
            assert adapter.connect() is False

    def test_disconnect(self, adapter: GrowwBrokerAdapter):
        with patch("requests.Session") as mock_session_cls:
            mock_session_cls.return_value.request.return_value = _mock_response(200, {"positions": []})
            adapter.connect()
        adapter.disconnect()
        assert adapter._connected is False
        assert adapter._session is None


class TestOrderLifecycle:
    def test_place_order_success(self, adapter: GrowwBrokerAdapter):
        mock_session = MagicMock()
        mock_session.request.return_value = _mock_response(
            200, {"groww_order_id": "GRW123456", "order_status": "NEW"},
        )
        adapter._session = mock_session
        adapter._connected = True

        order = MagicMock(symbol="NIFTY26JULFUT", direction="BUY", quantity=50,
                           order_type="MARKET", price=0.0, trigger_price=0.0)
        order_id = adapter.place_order(order)
        assert order_id == "GRW123456"

    def test_place_order_raises_when_not_connected(self, adapter: GrowwBrokerAdapter):
        order = MagicMock(symbol="NIFTY26JULFUT", direction="BUY", quantity=50)
        with pytest.raises(RuntimeError, match="not connected"):
            adapter.place_order(order)

    def test_place_order_no_order_id_raises(self, adapter: GrowwBrokerAdapter):
        mock_session = MagicMock()
        mock_session.request.return_value = _mock_response(200, {})
        adapter._session = mock_session
        adapter._connected = True
        order = MagicMock(symbol="NIFTY26JULFUT", direction="BUY", quantity=50)
        with pytest.raises(RuntimeError, match="no groww_order_id"):
            adapter.place_order(order)

    def test_cancel_order_success(self, adapter: GrowwBrokerAdapter):
        mock_session = MagicMock()
        mock_session.request.return_value = _mock_response(200, {"groww_order_id": "GRW123456", "order_status": "CANCELLED"})
        adapter._session = mock_session
        adapter._connected = True
        assert adapter.cancel_order("GRW123456") is True

    def test_cancel_order_fails_when_not_connected(self, adapter: GrowwBrokerAdapter):
        assert adapter.cancel_order("GRW123456") is False

    def test_modify_order_success(self, adapter: GrowwBrokerAdapter):
        mock_session = MagicMock()
        mock_session.request.return_value = _mock_response(200, {"groww_order_id": "GRW123456", "order_status": "MODIFIED"})
        adapter._session = mock_session
        adapter._connected = True
        assert adapter.modify_order("GRW123456", quantity=100, price=150.0) is True


class TestOrderQueries:
    def _adapter_with_order_detail(self, adapter: GrowwBrokerAdapter, detail):
        mock_session = MagicMock()
        mock_session.request.return_value = _mock_response(200, detail)
        adapter._session = mock_session
        adapter._connected = True
        return adapter

    def test_get_order_status(self, adapter: GrowwBrokerAdapter):
        adapter = self._adapter_with_order_detail(
            adapter, {"order_status": "EXECUTED", "average_fill_price": 125.5, "filled_quantity": 75},
        )
        assert adapter.get_order_status("GRW123456") == "EXECUTED"

    def test_get_fill_price(self, adapter: GrowwBrokerAdapter):
        adapter = self._adapter_with_order_detail(
            adapter, {"order_status": "EXECUTED", "average_fill_price": 125.5, "filled_quantity": 75},
        )
        assert adapter.get_fill_price("GRW123456") == 125.5

    def test_get_fill_price_none_when_zero(self, adapter: GrowwBrokerAdapter):
        adapter = self._adapter_with_order_detail(
            adapter, {"order_status": "NEW", "average_fill_price": 0, "filled_quantity": 0},
        )
        assert adapter.get_fill_price("GRW123456") is None

    def test_get_fill_price_none_when_not_connected(self, adapter: GrowwBrokerAdapter):
        assert adapter.get_fill_price("GRW123456") is None

    def test_get_filled_quantity(self, adapter: GrowwBrokerAdapter):
        adapter = self._adapter_with_order_detail(
            adapter, {"order_status": "EXECUTED", "average_fill_price": 125.5, "filled_quantity": 75},
        )
        assert adapter.get_filled_quantity("GRW123456") == 75


class TestPositions:
    def test_get_positions(self, adapter: GrowwBrokerAdapter):
        mock_session = MagicMock()
        mock_session.request.return_value = _mock_response(200, {
            "positions": [
                {"trading_symbol": "NIFTY26JULFUT", "quantity": 50, "net_price": 24000.0, "realised_pnl": 0.0},
                {"trading_symbol": "CLOSED", "quantity": 0, "net_price": 100.0, "realised_pnl": 500.0},
            ],
        })
        adapter._session = mock_session
        adapter._connected = True
        positions = adapter.get_positions()
        assert len(positions) == 1
        assert positions[0].symbol == "NIFTY26JULFUT"

    def test_get_positions_empty_when_not_connected(self, adapter: GrowwBrokerAdapter):
        assert adapter.get_positions() == []


class TestUnverifiedEndpoints:
    def test_get_quote_not_implemented(self, adapter: GrowwBrokerAdapter):
        with pytest.raises(NotImplementedError):
            adapter.get_quote("NIFTY")

    def test_get_historical_data_not_implemented(self, adapter: GrowwBrokerAdapter):
        import datetime
        with pytest.raises(NotImplementedError):
            adapter.get_historical_data("NIFTY", datetime.datetime.now(), datetime.datetime.now())

    def test_subscribe_returns_false(self, adapter: GrowwBrokerAdapter):
        assert adapter.subscribe_to_market_data(["NIFTY"], lambda q: None) is False


class TestHealthCheck:
    def test_health_check_unhealthy_when_not_connected(self, adapter: GrowwBrokerAdapter):
        result = adapter.health_check()
        assert result["status"] == "unhealthy"

    def test_health_check_healthy(self, adapter: GrowwBrokerAdapter):
        mock_session = MagicMock()
        mock_session.request.return_value = _mock_response(200, {"positions": []})
        adapter._session = mock_session
        adapter._connected = True
        result = adapter.health_check()
        assert result["status"] == "healthy"
