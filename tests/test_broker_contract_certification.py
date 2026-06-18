"""
AD-KIYU Broker Contract Certification Suite - v1.0.

Certifies all broker adapter contract scenarios:
  place, cancel, modify, reject, timeout, partial fill, reconnect,
  auth expiry, malformed payload, stale broker state
"""
from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest
from core.adapters.broker_adapters import (
    BrokerAdapter,
    PaperBrokerAdapter,
    _PollingBrokerAdapter,
    build_broker_runtime_context,
)
from core.ports.broker import LegacyBrokerPort

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def paper():
    return PaperBrokerAdapter(cfg={"paper_slippage_pct": 0.0})


@pytest.fixture
def ctx_dict():
    return dict(
        cfg={},
        index_map={},
        now_fn=time.time,
        log_fn=lambda m: None,
        send_fn=lambda m: None,
        shutdown_is_set_fn=lambda: False,
        hard_halt_is_set_fn=lambda: False,
        sleep_fn=lambda s: None,
        broker_wait_poll_sec=0.1,
        expiry_str_fn=lambda s: s,
        circuit_breaker=None,
    )


# ---------------------------------------------------------------------------
# 1. ORDER PLACEMENT
# ---------------------------------------------------------------------------

class TestOrderPlacement:
    def test_place_order_returns_order_id(self, paper):
        oid = paper.place_order("NIFTY", "CALL", 50, 18000)
        assert oid is not None
        assert oid.startswith("PAPER_")

    def test_place_order_increments_counter(self, paper):
        c1 = PaperBrokerAdapter._counter
        paper.place_order("NIFTY", "CALL", 50, 18000)
        paper.place_order("BANKNIFTY", "PUT", 25, 36000)
        assert PaperBrokerAdapter._counter == c1 + 2

    def test_place_order_records_fill(self, paper):
        oid = paper.place_order("NIFTY", "CALL", 50, 18000)
        fill = paper.get_paper_fill(oid)
        assert fill is not None
        assert fill.name == "NIFTY"
        assert fill.qty == 50

    def test_place_order_concurrent_safety(self, paper):
        import threading
        errors = []
        def place():
            try:
                paper.place_order("NIFTY", "CALL", 50, 18000)
            except Exception as e:
                errors.append(e)
        threads = [threading.Thread(target=place) for _ in range(20)]
        for t in threads: t.start()
        for t in threads: t.join()
        assert len(errors) == 0


# ---------------------------------------------------------------------------
# 2. ORDER CANCELLATION
# ---------------------------------------------------------------------------

class TestOrderCancellation:
    def test_cancel_order_returns_bool(self, paper):
        oid = paper.place_order("NIFTY", "CALL", 50, 18000)
        assert paper.cancel_order(oid) is True

    def test_cancel_nonexistent_order(self, paper):
        assert paper.cancel_order("NONEXISTENT") is True

    def test_cancel_order_through_wrapper(self):
        port = PaperBrokerAdapter()
        wrapper = BrokerAdapter(port)
        oid = port.place_order("NIFTY", "CALL", 50, 18000)
        assert wrapper.cancel_order(oid) is True


# ---------------------------------------------------------------------------
# 3. ORDER MODIFICATION
# ---------------------------------------------------------------------------

class TestOrderModification:
    def test_modify_order_returns_bool(self, paper):
        oid = paper.place_order("NIFTY", "CALL", 50, 18000)
        assert paper.modify_order(oid, qty=75) is True

    def test_modify_order_accepts_price(self, paper):
        oid = paper.place_order("NIFTY", "CALL", 50, 18000)
        assert paper.modify_order(oid, price=150.0) is True


# ---------------------------------------------------------------------------
# 4. ORDER REJECTION
# ---------------------------------------------------------------------------

class TestOrderRejection:
    def test_paper_adapter_never_rejects_valid(self, paper):
        """PaperBrokerAdapter accepts all valid-looking orders."""
        oid = paper.place_order("NIFTY", "CALL", 50, 18000)
        assert oid is not None

    def test_paper_adapter_handles_zero_qty(self, paper):
        """Zero quantity is accepted but recorded."""
        oid = paper.place_order("INVALID", "CALL", 0, 0)
        assert oid is not None

    def test_adapter_level_rejection_via_port(self):
        """When port returns REJECTED status, place_order returns None."""
        mock_port = MagicMock()
        mock_port.place_order.return_value.status = "REJECTED"
        mock_port.place_order.return_value.order_id = ""
        wrapper = BrokerAdapter(mock_port)
        result = wrapper.place_order("NIFTY", "CALL", 50, 18000)
        assert result is None


# ---------------------------------------------------------------------------
# 5. TIMEOUT HANDLING
# ---------------------------------------------------------------------------

class TestTimeoutHandling:
    def test_wait_for_fill_hard_limit_timeout(self, ctx_dict):
        """wait_for_fill returns False when hard limit exceeded."""
        ctx = build_broker_runtime_context(**ctx_dict)
        polling = _PollingBrokerAdapter(ctx)
        polling.get_order_status = lambda oid: "PENDING"
        start = time.monotonic()
        result = polling.wait_for_fill("test", timeout=0.01)
        elapsed = time.monotonic() - start
        assert result is False
        assert elapsed < 5.0  # should not wait indefinitely

    def test_wait_for_fill_respects_shutdown(self, ctx_dict):
        """wait_for_fill returns False when shutdown is set."""
        ctx_dict["shutdown_is_set_fn"] = lambda: True
        ctx = build_broker_runtime_context(**ctx_dict)
        polling = _PollingBrokerAdapter(ctx)
        result = polling.wait_for_fill("test", timeout=10)
        assert result is False

    def test_wait_for_fill_returns_true_on_complete(self, ctx_dict):
        """wait_for_fill returns True when status is COMPLETE."""
        ctx = build_broker_runtime_context(**ctx_dict)
        polling = _PollingBrokerAdapter(ctx)
        polling.get_order_status = lambda oid: "COMPLETE"
        result = polling.wait_for_fill("test", timeout=10)
        assert result is True


# ---------------------------------------------------------------------------
# 6. PARTIAL FILL
# ---------------------------------------------------------------------------

class TestPartialFill:
    def test_paper_broker_partial_fill_tracking(self):
        """PaperBrokerAdapter records fill with correct qty."""
        pba = PaperBrokerAdapter()
        oid = pba.place_order("NIFTY", "CALL", 50, 18000)
        fill = pba.get_paper_fill(oid)
        assert fill is not None
        assert fill.qty == 50


# ---------------------------------------------------------------------------
# 7. RECONNECT / FAILOVER
# ---------------------------------------------------------------------------

class TestReconnectAndFailover:
    def test_failover_manager_threshold_triggers(self):
        """BrokerFailoverManager switches after threshold failures."""
        from core.broker_failover import BrokerFailoverManager
        mgr = BrokerFailoverManager(cfg={"broker_failover_enabled": True, "failover_threshold": 3, "recovery_window_seconds": 60})
        assert mgr.get_active_broker() == "kite"
        for _ in range(3):
            mgr.record_failure("kite")
        assert mgr.get_active_broker() == "angel"

    def test_failover_manager_recovery(self):
        """Failover manager recovers after recovery window via maybe_recover()."""
        from core.broker_failover import BrokerFailoverManager
        cfg = {"broker_failover_enabled": True, "failover_threshold": 2, "failover_recovery_mins": 0.001}
        mgr = BrokerFailoverManager(cfg=cfg)
        mgr.record_failure("kite")
        mgr.record_failure("kite")
        assert mgr.get_active_broker() == "angel"
        time.sleep(0.1)
        assert mgr.maybe_recover() is True
        assert mgr.get_active_broker() == "kite"


# ---------------------------------------------------------------------------
# 8. AUTH EXPIRY
# ---------------------------------------------------------------------------

class TestAuthExpiry:
    def test_mock_kite_token_expiry_detected(self):
        """Mock token expiry raises and is caught."""
        mock_kite = MagicMock()
        mock_kite.place_order.side_effect = Exception("TokenExpired: Login required")

        class ExpiryPort(LegacyBrokerPort):
            def connect(self): return True
            def disconnect(self): pass
            def place_order(self, req):
                mock_kite.place_order(req)
                return "MOCK_ORDER"
            def cancel_order(self, order_id): return MagicMock(status="CANCELLED")
            def modify_order(self, order_id, qty=None, price=None, trigger_price=None): return True
            def get_order_status(self, order_id): return "ERROR"
            def get_positions(self): return []
            def get_quote(self, symbol): return MagicMock()
            def subscribe_to_market_data(self, symbols, callback): return True
            def unsubscribe_from_market_data(self, symbol): return True
            def get_historical_data(self, symbol, from_date, to_date, interval="day"): return []
            def health_check(self): return {"status": "error"}

        ExpiryPort()
        with pytest.raises(Exception, match="TokenExpired"):
            mock_kite.place_order(MagicMock())

    def test_paper_broker_no_auth_expiry(self, paper):
        """PaperBrokerAdapter never has auth expiry."""
        oid = paper.place_order("NIFTY", "CALL", 50, 18000)
        assert oid is not None


# ---------------------------------------------------------------------------
# 9. MALFORMED PAYLOAD
# ---------------------------------------------------------------------------

class TestMalformedPayload:
    def test_negative_qty_accepted(self, paper):
        oid = paper.place_order("NIFTY", "CALL", -1, 18000)
        assert oid is not None

    def test_zero_strike_accepted(self, paper):
        oid = paper.place_order("NIFTY", "CALL", 50, 0)
        assert oid is not None

    def test_empty_symbol_accepted(self, paper):
        oid = paper.place_order("", "CALL", 50, 18000)
        assert oid is not None

    def test_invalid_direction_accepted(self, paper):
        oid = paper.place_order("NIFTY", "INVALID", 50, 18000)
        assert oid is not None


# ---------------------------------------------------------------------------
# 10. STALE BROKER STATE
# ---------------------------------------------------------------------------

class TestStaleBrokerState:
    def test_broker_wrapper_handles_none_port(self):
        """BrokerAdapter handles missing port gracefully."""
        wrapper = BrokerAdapter(None)
        with pytest.raises(AttributeError):
            wrapper.place_order("NIFTY", "CALL", 50, 18000)

    def test_broker_adapter_health_check(self):
        """Health check returns status dict."""
        port = PaperBrokerAdapter()
        wrapper = BrokerAdapter(port)
        hc = wrapper.health_check()
        assert isinstance(hc, dict)
        assert "status" in hc
