"""Tests for infrastructure/adapters/brokers/icicidirect/adapter.py.

Mirrors the structure of the other broker adapter test files: error
classifier, checksum header construction, factory-from-context credential
extraction, and adapter behavior against a mocked HTTP session.
"""

from __future__ import annotations

import hashlib
import json
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("requests")

from infrastructure.adapters.brokers.icicidirect.adapter import (
    ICICIDirectBrokerAdapter,
    _classify_icicidirect_error,
    create_icicidirect_adapter,
    create_icicidirect_adapter_from_context,
)

# ==============================================================================
# Error classifier
# ==============================================================================


class TestClassifyICICIDirectError:
    def test_token_expired(self):
        assert _classify_icicidirect_error(Exception("401 Unauthorized")) == "TOKEN_EXPIRED"

    def test_checksum_error_classified_as_token_expired(self):
        assert _classify_icicidirect_error(Exception("Invalid checksum")) == "TOKEN_EXPIRED"

    def test_timeout(self):
        assert _classify_icicidirect_error(Exception("timed out")) == "TIMEOUT"

    def test_rate_limited(self):
        assert _classify_icicidirect_error(Exception("429 rate limit")) == "RATE_LIMITED"

    def test_unknown(self):
        assert _classify_icicidirect_error(Exception("something odd")) == "UNKNOWN"


# ==============================================================================
# create_icicidirect_adapter_from_context - credential extraction
# ==============================================================================


class TestCreateICICIDirectAdapterFromContext:
    def test_broker_config_priority(self):
        ctx = MagicMock()
        ctx.cfg = {
            "BROKER_CONFIG": {"api_key": "cfg_key", "secret": "cfg_secret", "access_token": "cfg_session"},
        }
        ctx.log_fn = print
        adapter = create_icicidirect_adapter_from_context(ctx)
        assert adapter._app_key == "cfg_key"
        assert adapter._secret_key == "cfg_secret"
        assert adapter._session_token == "cfg_session"

    def test_missing_app_key_raises(self):
        ctx = MagicMock()
        ctx.cfg = {"ICICIDIRECT_SECRET_KEY": "s", "ICICIDIRECT_SESSION_TOKEN": "t"}
        ctx.log_fn = print
        with pytest.raises(ValueError, match="ICICIDIRECT_APP_KEY"):
            create_icicidirect_adapter_from_context(ctx)

    def test_missing_secret_key_raises(self):
        ctx = MagicMock()
        ctx.cfg = {"ICICIDIRECT_APP_KEY": "k", "ICICIDIRECT_SESSION_TOKEN": "t"}
        ctx.log_fn = print
        with pytest.raises(ValueError, match="ICICIDIRECT_SECRET_KEY"):
            create_icicidirect_adapter_from_context(ctx)

    def test_missing_session_token_raises(self):
        ctx = MagicMock()
        ctx.cfg = {"ICICIDIRECT_APP_KEY": "k", "ICICIDIRECT_SECRET_KEY": "s"}
        ctx.log_fn = print
        with pytest.raises(ValueError, match="ICICIDIRECT_SESSION_TOKEN"):
            create_icicidirect_adapter_from_context(ctx)


# ==============================================================================
# Checksum header construction
# ==============================================================================


class TestChecksumHeaders:
    def test_checksum_matches_documented_algorithm(self):
        """Regression: checksum must be SHA256(timestamp + json_payload + secret_key),
        per the official Breeze docs - not guessed differently."""
        adapter = create_icicidirect_adapter(
            app_key="test_app_key", secret_key="test_secret", session_token="test_session", log_fn=print,
        )
        body = {"stock_code": "ITC"}
        headers = adapter._checksum_headers(body)

        timestamp = headers["X-Timestamp"]
        payload = json.dumps(body, separators=(",", ":"))
        expected_checksum = hashlib.sha256(f"{timestamp}{payload}test_secret".encode()).hexdigest()

        assert headers["X-Checksum"] == f"token {expected_checksum}"
        assert headers["X-AppKey"] == "test_app_key"
        assert headers["X-SessionToken"] == "test_session"


# ==============================================================================
# ICICIDirectBrokerAdapter with a mocked HTTP session
# ==============================================================================


def _mock_response(status_code=200, body=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = body if body is not None else {}
    resp.text = str(body or {})
    return resp


@pytest.fixture()
def adapter() -> ICICIDirectBrokerAdapter:
    return create_icicidirect_adapter(
        app_key="test_app_key", secret_key="test_secret", session_token="test_session", log_fn=print,
    )


class TestConnection:
    def test_connect_success(self, adapter: ICICIDirectBrokerAdapter):
        with patch("requests.Session") as mock_session_cls:
            mock_session_cls.return_value.request.return_value = _mock_response(200, {"Success": []})
            assert adapter.connect() is True
            assert adapter._connected is True

    def test_connect_failure(self, adapter: ICICIDirectBrokerAdapter):
        with patch("requests.Session") as mock_session_cls:
            mock_session_cls.return_value.request.return_value = _mock_response(401, {})
            assert adapter.connect() is False


class TestOrderLifecycle:
    def test_place_order_rejects_market_orders(self, adapter: ICICIDirectBrokerAdapter):
        """Regression: Breeze API genuinely does not support market orders -
        this must fail loudly, not silently substitute a limit order."""
        adapter._connected = True
        order = MagicMock(symbol="ITC", direction="BUY", quantity=1,
                           order_type="MARKET", price=0.0, trigger_price=0.0)
        with pytest.raises(RuntimeError, match="market orders"):
            adapter.place_order(order)

    def test_place_order_success_with_limit(self, adapter: ICICIDirectBrokerAdapter):
        mock_session = MagicMock()
        mock_session.request.return_value = _mock_response(
            200, {"Success": {"order_id": "20250205N300001234"}},
        )
        adapter._session = mock_session
        adapter._connected = True

        order = MagicMock(symbol="ITC", direction="BUY", quantity=1,
                           order_type="LIMIT", price=263.15, trigger_price=0.0,
                           exchange="NSE", product="options")
        order_id = adapter.place_order(order)
        assert order_id == "20250205N300001234"

    def test_place_order_raises_when_not_connected(self, adapter: ICICIDirectBrokerAdapter):
        order = MagicMock(order_type="LIMIT")
        with pytest.raises(RuntimeError, match="not connected"):
            adapter.place_order(order)

    def test_cancel_order_success(self, adapter: ICICIDirectBrokerAdapter):
        mock_session = MagicMock()
        mock_session.request.return_value = _mock_response(200, {"Success": {"order_id": "1"}})
        adapter._session = mock_session
        adapter._connected = True
        assert adapter.cancel_order("1") is True

    def test_cancel_order_fails_when_not_connected(self, adapter: ICICIDirectBrokerAdapter):
        assert adapter.cancel_order("1") is False

    def test_modify_order_success(self, adapter: ICICIDirectBrokerAdapter):
        mock_session = MagicMock()
        mock_session.request.return_value = _mock_response(200, {"Success": {"order_id": "1"}})
        adapter._session = mock_session
        adapter._connected = True
        assert adapter.modify_order("1", quantity=2, price=270.0) is True


class TestOrderQueries:
    ORDER_DETAIL = {
        "Success": {
            "order_id": "20250205N300001234", "status": "Executed",
            "average_price": "263.15", "quantity": "10", "pending_quantity": "0",
        },
    }

    def _adapter_with_order(self, adapter: ICICIDirectBrokerAdapter):
        mock_session = MagicMock()
        mock_session.request.return_value = _mock_response(200, self.ORDER_DETAIL)
        adapter._session = mock_session
        adapter._connected = True
        return adapter

    def test_get_order_status(self, adapter: ICICIDirectBrokerAdapter):
        adapter = self._adapter_with_order(adapter)
        assert adapter.get_order_status("20250205N300001234") == "Executed"

    def test_get_fill_price(self, adapter: ICICIDirectBrokerAdapter):
        adapter = self._adapter_with_order(adapter)
        assert adapter.get_fill_price("20250205N300001234") == 263.15

    def test_get_fill_price_none_when_not_connected(self, adapter: ICICIDirectBrokerAdapter):
        assert adapter.get_fill_price("20250205N300001234") is None

    def test_get_filled_quantity_derived_from_quantity_minus_pending(self, adapter: ICICIDirectBrokerAdapter):
        adapter = self._adapter_with_order(adapter)
        assert adapter.get_filled_quantity("20250205N300001234") == 10

    def test_get_filled_quantity_partial_fill(self, adapter: ICICIDirectBrokerAdapter):
        mock_session = MagicMock()
        mock_session.request.return_value = _mock_response(200, {
            "Success": {"order_id": "1", "status": "Partially Executed",
                        "average_price": "263.15", "quantity": "10", "pending_quantity": "4"},
        })
        adapter._session = mock_session
        adapter._connected = True
        assert adapter.get_filled_quantity("1") == 6


class TestPositions:
    def test_get_positions(self, adapter: ICICIDirectBrokerAdapter):
        mock_session = MagicMock()
        mock_session.request.return_value = _mock_response(200, {"Success": [
            {"stock_code": "ITC", "quantity": "10", "average_price": "260.0", "ltp": "265.0", "pnl": "50.0"},
            {"stock_code": "CLOSED", "quantity": "0", "average_price": "100.0", "ltp": "100.0", "pnl": "0.0"},
        ]})
        adapter._session = mock_session
        adapter._connected = True
        positions = adapter.get_positions()
        assert len(positions) == 1
        assert positions[0].symbol == "ITC"
        assert positions[0].unrealized_pnl == 50.0

    def test_get_positions_empty_when_not_connected(self, adapter: ICICIDirectBrokerAdapter):
        assert adapter.get_positions() == []


class TestUnverifiedEndpoints:
    def test_get_quote_not_implemented(self, adapter: ICICIDirectBrokerAdapter):
        with pytest.raises(NotImplementedError):
            adapter.get_quote("ITC")

    def test_get_historical_data_not_implemented(self, adapter: ICICIDirectBrokerAdapter):
        import datetime
        with pytest.raises(NotImplementedError):
            adapter.get_historical_data("ITC", datetime.datetime.now(), datetime.datetime.now())

    def test_subscribe_returns_false(self, adapter: ICICIDirectBrokerAdapter):
        assert adapter.subscribe_to_market_data(["ITC"], lambda q: None) is False


class TestHealthCheck:
    def test_health_check_unhealthy_when_not_connected(self, adapter: ICICIDirectBrokerAdapter):
        result = adapter.health_check()
        assert result["status"] == "unhealthy"

    def test_health_check_healthy(self, adapter: ICICIDirectBrokerAdapter):
        mock_session = MagicMock()
        mock_session.request.return_value = _mock_response(200, {"Success": []})
        adapter._session = mock_session
        adapter._connected = True
        result = adapter.health_check()
        assert result["status"] == "healthy"
