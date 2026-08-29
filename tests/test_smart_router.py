"""Tests for the Multi-Broker Smart Router."""

from __future__ import annotations

from unittest.mock import MagicMock

from core.execution.smart_router import (
    BrokerScore,
    RouterConfig,
    RouteResult,
    SmartRouter,
)


class TestRouterConfig:
    def test_defaults(self):
        """RouterConfig should have sensible defaults."""
        cfg = RouterConfig()
        assert cfg.strategy == "lowest_fee"
        assert cfg.preferred_broker == ""
        assert cfg.min_fill_rate == 0.5
        assert cfg.blacklisted_brokers == set()


class TestBrokerScore:
    def test_score_dataclass(self):
        """BrokerScore should store all fields correctly."""
        score = BrokerScore(
            broker="KITE", score=0.85, fee_score=0.9,
            health_score=1.0, latency_score=0.8,
            execution_score=0.7, is_available=True,
        )
        assert score.broker == "KITE"
        assert score.score == 0.85
        assert score.is_available is True

    def test_low_score_for_unavailable(self):
        """Unavailable broker should have health_score=0."""
        score = BrokerScore(
            broker="ANGEL", score=0.3, fee_score=0.5,
            health_score=0.0, latency_score=0.5,
            execution_score=0.5, is_available=False,
        )
        assert score.is_available is False
        assert score.health_score == 0.0


class TestRouteResult:
    def test_success_result(self):
        """Successful route should have order_id and no error."""
        result = RouteResult(success=True, broker="KITE", order_id="ORD123", fee_charged=20.0, latency_ms=150.0)
        assert result.success is True
        assert result.broker == "KITE"
        assert result.order_id == "ORD123"
        assert result.fee_charged == 20.0

    def test_failure_result(self):
        """Failed route should have error message."""
        result = RouteResult(success=False, broker="ANGEL", order_id="", error="Not connected")
        assert result.success is False
        assert result.error == "Not connected"


class TestSmartRouter:
    def test_empty_routers(self):
        """Router with no brokers should return empty available list."""
        router = SmartRouter(routers={})
        assert router.available_brokers() == []
        assert router.select_broker() is None

    def test_single_paper_broker(self):
        """Router with single paper broker should always select it."""
        mock_adapter = MagicMock()
        mock_adapter.get_order_status.return_value = "COMPLETE"
        router = SmartRouter(routers={"PAPER": mock_adapter})
        available = router.available_brokers()
        assert "PAPER" in available
        assert router.select_broker() == "PAPER"

    def test_blacklisted_broker(self):
        """Blacklisted broker should not appear in available list."""
        mock_adapter = MagicMock()
        router = SmartRouter(
            routers={"KITE": mock_adapter, "ANGEL": mock_adapter},
            config={"blacklisted_brokers": {"ANGEL"}},
        )
        available = router.available_brokers()
        assert "KITE" in available
        assert "ANGEL" not in available

    def test_preferred_broker(self):
        """Preferred broker should be selected when available."""
        mock_adapter = MagicMock()
        mock_adapter.get_order_status.return_value = "COMPLETE"
        router = SmartRouter(
            routers={"KITE": mock_adapter, "ANGEL": mock_adapter},
            config={"preferred_broker": "KITE"},
        )
        assert router.select_broker() == "KITE"

    def test_lowest_fee_strategy(self):
        """Lowest-fee strategy should select cheaper broker."""
        mock_adapter = MagicMock()
        mock_adapter.get_order_status.return_value = "COMPLETE"
        router = SmartRouter(
            routers={"KITE": mock_adapter, "ANGEL": mock_adapter},
            config={"strategy": "lowest_fee", "fee_weights": {"KITE": 20.0, "ANGEL": 15.0}},
        )
        # ANGEL has lower fees (Rs15 vs Rs20)
        assert router.select_broker() == "ANGEL"

    def test_round_robin_strategy(self):
        """Round-robin should cycle through brokers."""
        mock_adapter = MagicMock()
        mock_adapter.get_order_status.return_value = "COMPLETE"
        router = SmartRouter(
            routers={"KITE": mock_adapter, "ANGEL": mock_adapter},
            config={"strategy": "round_robin"},
        )
        broker1 = router.select_broker()
        broker2 = router.select_broker()
        assert broker1 != broker2, "Round-robin should alternate"

    def test_weighted_strategy(self):
        """Weighted strategy should select highest-scored broker."""
        mock_adapter = MagicMock()
        mock_adapter.get_order_status.return_value = "COMPLETE"
        router = SmartRouter(
            routers={"KITE": mock_adapter, "ANGEL": mock_adapter},
            config={"strategy": "weighted"},
        )
        broker = router.select_broker()
        assert broker in ("KITE", "ANGEL")

    def test_route_order_success(self):
        """Successful route should return valid order_id."""
        mock_adapter = MagicMock()
        mock_adapter.place_order.return_value = "KITE_ORD_001"
        router = SmartRouter(routers={"KITE": mock_adapter})
        result = router.route_order("KITE", "NIFTY", "CALL", 1, 23600)
        assert result.success is True
        assert result.order_id == "KITE_ORD_001"
        assert result.broker == "KITE"

    def test_route_order_failure(self):
        """Failed route should return error."""
        mock_adapter = MagicMock()
        mock_adapter.place_order.side_effect = ConnectionError("Broker not reachable")
        router = SmartRouter(routers={"KITE": mock_adapter})
        result = router.route_order("KITE", "NIFTY", "CALL", 1, 23600)
        assert result.success is False
        assert "Broker not reachable" in result.error

    def test_route_to_best_auto_select(self):
        """route_to_best should auto-select broker and route."""
        mock_adapter = MagicMock()
        mock_adapter.place_order.return_value = "ORD_001"
        mock_adapter.get_order_status.return_value = "COMPLETE"
        router = SmartRouter(routers={"PAPER": mock_adapter})
        result = router.route_to_best("NIFTY", "CALL", 1, 23600)
        assert result.success is True
        assert result.broker == "PAPER"

    def test_route_to_best_no_broker(self):
        """route_to_best with no brokers should return error."""
        router = SmartRouter(routers={})
        result = router.route_to_best("NIFTY", "CALL", 1, 23600)
        assert result.success is False
        assert "No available broker" in result.error

    def test_health_check(self):
        """Health check should report broker status."""
        mock_adapter = MagicMock()
        mock_adapter.get_order_status.return_value = "COMPLETE"
        router = SmartRouter(routers={"KITE": mock_adapter})
        health = router.health_check()
        assert health["status"] == "healthy"
        assert health["total_brokers"] == 1
        assert health["available"] == 1
        assert "KITE" in health

    def test_health_check_degraded(self):
        """Health check should report degraded when no brokers available."""
        router = SmartRouter(routers={})
        health = router.health_check()
        assert health["status"] == "degraded"

    def test_record_fill(self):
        """Recorded fills should affect execution quality tracking."""
        mock_adapter = MagicMock()
        router = SmartRouter(routers={"KITE": mock_adapter})
        router.record_fill("KITE", True)
        router.record_fill("KITE", True)
        router.record_fill("KITE", False)
        fills = router._fill_rates.get("KITE", [])
        assert len(fills) == 3
        assert fills == [True, True, False]

    def test_score_broker_none_for_unknown(self):
        """Unknown broker should return None from score_broker."""
        mock_adapter = MagicMock()
        router = SmartRouter(routers={"KITE": mock_adapter})
        assert router.score_broker("UNKNOWN") is None

    def test_score_broker_blacklisted(self):
        """Blacklisted broker should return None from score_broker."""
        mock_adapter = MagicMock()
        router = SmartRouter(
            routers={"KITE": mock_adapter},
            config={"blacklisted_brokers": {"KITE"}},
        )
        assert router.score_broker("KITE") is None

    def test_route_order_unknown_broker(self):
        """Routing to unknown broker should return error."""
        mock_adapter = MagicMock()
        router = SmartRouter(routers={"KITE": mock_adapter})
        result = router.route_order("UNKNOWN", "NIFTY", "CALL", 1, 23600)
        assert result.success is False
        assert "not registered" in result.error
