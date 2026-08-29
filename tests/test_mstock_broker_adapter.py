"""Tests for infrastructure/adapters/brokers/mstock/adapter.py.

Mirrors the structure of tests/test_kite_broker_adapter.py: error
classifier, factory-from-context credential extraction, and adapter
behavior against a mocked HTTP session (no real network calls, no
dependency on a live mStock account).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("requests")

from infrastructure.adapters.brokers.mstock.adapter import (
    MStockBrokerAdapter,
    _classify_mstock_error,
    create_mstock_adapter,
    create_mstock_adapter_from_context,
)

# ==============================================================================
# Error classifier (stateless)
# ==============================================================================


class TestClassifyMStockError:
    def test_token_expired(self):
        assert _classify_mstock_error(Exception("401 Unauthorized: bad token")) == "TOKEN_EXPIRED"

    def test_timeout(self):
        assert _classify_mstock_error(Exception("request timed out")) == "TIMEOUT"

    def test_rate_limited(self):
        assert _classify_mstock_error(Exception("429 Rate limited")) == "RATE_LIMITED"

    def test_rejected(self):
        assert _classify_mstock_error(Exception("Order rejected by exchange")) == "ORDER_REJECTED"

    def test_margin_insufficient(self):
        assert _classify_mstock_error(Exception("Insufficient margin")) == "MARGIN_INSUFFICIENT"

    def test_unknown(self):
        assert _classify_mstock_error(Exception("something odd")) == "UNKNOWN"


# ==============================================================================
# create_mstock_adapter_from_context - credential extraction
# ==============================================================================


class TestCreateMStockAdapterFromContext:
    def test_broker_config_priority(self):
        ctx = MagicMock()
        ctx.cfg = {
            "BROKER_CONFIG": {"api_key": "cfg_key", "access_token": "cfg_token"},
            "MSTOCK_API_KEY": "top_key",
            "MSTOCK_ACCESS_TOKEN": "top_token",
        }
        ctx.log_fn = print
        adapter = create_mstock_adapter_from_context(ctx)
        assert adapter._api_key == "cfg_key"
        assert adapter._access_token == "cfg_token"

    def test_top_level_fallback(self):
        ctx = MagicMock()
        ctx.cfg = {"MSTOCK_API_KEY": "top_key", "MSTOCK_ACCESS_TOKEN": "top_token"}
        ctx.log_fn = print
        adapter = create_mstock_adapter_from_context(ctx)
        assert adapter._api_key == "top_key"
        assert adapter._access_token == "top_token"

    def test_missing_api_key_raises_value_error(self):
        ctx = MagicMock()
        ctx.cfg = {}
        ctx.log_fn = print
        with pytest.raises(ValueError, match="MSTOCK_API_KEY"):
            create_mstock_adapter_from_context(ctx)

    def test_missing_access_token_raises_value_error(self):
        ctx = MagicMock()
        ctx.cfg = {"MSTOCK_API_KEY": "key_present"}
        ctx.log_fn = print
        with pytest.raises(ValueError, match="MSTOCK_ACCESS_TOKEN"):
            create_mstock_adapter_from_context(ctx)


# ==============================================================================
# MStockBrokerAdapter with a mocked HTTP session
# ==============================================================================


def _mock_response(status_code=200, json_data=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.text = str(json_data or {})
    return resp


@pytest.fixture()
def adapter() -> MStockBrokerAdapter:
    return create_mstock_adapter(api_key="test_key", access_token="test_token", log_fn=print)


class TestConnection:
    def test_connect_success(self, adapter: MStockBrokerAdapter):
        with patch("requests.Session") as mock_session_cls:
            mock_session = mock_session_cls.return_value
            mock_session.request.return_value = _mock_response(200, {"status": "success", "data": []})
            assert adapter.connect() is True
            assert adapter._connected is True

    def test_connect_failure(self, adapter: MStockBrokerAdapter):
        with patch("requests.Session") as mock_session_cls:
            mock_session = mock_session_cls.return_value
            mock_session.request.return_value = _mock_response(401, {"status": "error"})
            assert adapter.connect() is False
            assert adapter._connected is False

    def test_disconnect(self, adapter: MStockBrokerAdapter):
        with patch("requests.Session") as mock_session_cls:
            mock_session_cls.return_value.request.return_value = _mock_response(200, {"data": []})
            adapter.connect()
        adapter.disconnect()
        assert adapter._connected is False
        assert adapter._session is None


class TestOrderLifecycle:
    def _connected_adapter(self, adapter: MStockBrokerAdapter, mock_session):
        mock_session.request.return_value = _mock_response(200, {"status": "success", "data": []})
        adapter._session = mock_session
        adapter._connected = True
        return adapter

    def test_place_order_success(self, adapter: MStockBrokerAdapter):
        mock_session = MagicMock()
        mock_session.request.return_value = _mock_response(
            200, {"status": "success", "data": {"order_id": "1131241001100"}},
        )
        adapter._session = mock_session
        adapter._connected = True

        order = MagicMock(symbol="NIFTY26JULFUT", direction="BUY", quantity=50,
                           order_type="MARKET", price=0.0, trigger_price=0.0)
        order_id = adapter.place_order(order)
        assert order_id == "1131241001100"

    def test_place_order_raises_when_not_connected(self, adapter: MStockBrokerAdapter):
        order = MagicMock(symbol="NIFTY26JULFUT", direction="BUY", quantity=50)
        with pytest.raises(RuntimeError, match="not connected"):
            adapter.place_order(order)

    def test_place_order_no_order_id_raises(self, adapter: MStockBrokerAdapter):
        mock_session = MagicMock()
        mock_session.request.return_value = _mock_response(200, {"status": "success", "data": {}})
        adapter._session = mock_session
        adapter._connected = True
        order = MagicMock(symbol="NIFTY26JULFUT", direction="BUY", quantity=50)
        with pytest.raises(RuntimeError, match="no order_id"):
            adapter.place_order(order)

    def test_cancel_order_success(self, adapter: MStockBrokerAdapter):
        mock_session = MagicMock()
        mock_session.request.return_value = _mock_response(200, {"status": "success", "data": {"order_id": "1"}})
        adapter._session = mock_session
        adapter._connected = True
        assert adapter.cancel_order("1") is True

    def test_cancel_order_fails_when_not_connected(self, adapter: MStockBrokerAdapter):
        assert adapter.cancel_order("1") is False

    def test_modify_order_success(self, adapter: MStockBrokerAdapter):
        mock_session = MagicMock()
        mock_session.request.return_value = _mock_response(200, {"status": "success", "data": {"order_id": "1"}})
        adapter._session = mock_session
        adapter._connected = True
        assert adapter.modify_order("1", quantity=100, price=150.0) is True


class TestOrderQueries:
    """Covers get_order_status/get_fill_price/get_filled_quantity - the
    exact fields that were missing entirely on the Kite side and caused
    the zero-P&L bug fixed earlier this session."""

    ORDER_BOOK = {
        "status": "success",
        "data": [
            {"order_id": "1131241001100", "status": "COMPLETE", "average_price": 125.5, "filled_quantity": 75},
            {"order_id": "1131241001200", "status": "PENDING", "average_price": 0, "filled_quantity": 0},
        ],
    }

    def _adapter_with_order_book(self, adapter: MStockBrokerAdapter):
        mock_session = MagicMock()
        mock_session.request.return_value = _mock_response(200, self.ORDER_BOOK)
        adapter._session = mock_session
        adapter._connected = True
        return adapter

    def test_get_order_status(self, adapter: MStockBrokerAdapter):
        adapter = self._adapter_with_order_book(adapter)
        assert adapter.get_order_status("1131241001100") == "COMPLETE"
        assert adapter.get_order_status("1131241001200") == "PENDING"
        assert adapter.get_order_status("UNKNOWN") == "UNKNOWN"

    def test_get_fill_price_returns_real_average_price(self, adapter: MStockBrokerAdapter):
        adapter = self._adapter_with_order_book(adapter)
        assert adapter.get_fill_price("1131241001100") == 125.5

    def test_get_fill_price_none_when_zero_or_unfilled(self, adapter: MStockBrokerAdapter):
        adapter = self._adapter_with_order_book(adapter)
        assert adapter.get_fill_price("1131241001200") is None
        assert adapter.get_fill_price("UNKNOWN") is None

    def test_get_fill_price_none_when_not_connected(self, adapter: MStockBrokerAdapter):
        assert adapter.get_fill_price("1131241001100") is None

    def test_get_filled_quantity_returns_real_quantity(self, adapter: MStockBrokerAdapter):
        adapter = self._adapter_with_order_book(adapter)
        assert adapter.get_filled_quantity("1131241001100") == 75

    def test_get_filled_quantity_zero_when_unfilled(self, adapter: MStockBrokerAdapter):
        adapter = self._adapter_with_order_book(adapter)
        assert adapter.get_filled_quantity("1131241001200") == 0


class TestPositions:
    def test_get_positions(self, adapter: MStockBrokerAdapter):
        mock_session = MagicMock()
        mock_session.request.return_value = _mock_response(200, {
            "status": "success",
            "data": [
                {"tradingsymbol": "NIFTY26JULFUT", "quantity": 50, "average_price": 24000.0,
                 "last_price": 24100.0, "pnl": 5000.0},
                {"tradingsymbol": "CLOSED", "quantity": 0, "average_price": 100.0, "last_price": 100.0, "pnl": 0.0},
            ],
        })
        adapter._session = mock_session
        adapter._connected = True
        positions = adapter.get_positions()
        assert len(positions) == 1  # zero-quantity rows are filtered out
        assert positions[0].symbol == "NIFTY26JULFUT"
        assert positions[0].unrealized_pnl == 5000.0

    def test_get_positions_empty_when_not_connected(self, adapter: MStockBrokerAdapter):
        assert adapter.get_positions() == []


class TestUnverifiedEndpoints:
    """get_quote/get_historical_data must fail loudly, not fabricate data -
    mStock's quote/historical endpoints weren't part of the docs verified
    for this adapter (see module docstring)."""

    def test_get_quote_not_implemented(self, adapter: MStockBrokerAdapter):
        with pytest.raises(NotImplementedError):
            adapter.get_quote("NIFTY")

    def test_get_historical_data_not_implemented(self, adapter: MStockBrokerAdapter):
        import datetime
        with pytest.raises(NotImplementedError):
            adapter.get_historical_data("NIFTY", datetime.datetime.now(), datetime.datetime.now())

    def test_subscribe_returns_false(self, adapter: MStockBrokerAdapter):
        assert adapter.subscribe_to_market_data(["NIFTY"], lambda q: None) is False


class TestHealthCheck:
    def test_health_check_unhealthy_when_not_connected(self, adapter: MStockBrokerAdapter):
        result = adapter.health_check()
        assert result["status"] == "unhealthy"
        assert result["connected"] is False

    def test_health_check_healthy(self, adapter: MStockBrokerAdapter):
        mock_session = MagicMock()
        mock_session.request.return_value = _mock_response(200, {"status": "success", "data": []})
        adapter._session = mock_session
        adapter._connected = True
        result = adapter.health_check()
        assert result["status"] == "healthy"
        assert result["connected"] is True
