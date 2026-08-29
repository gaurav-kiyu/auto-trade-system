"""Tests for core.strategy.multi_asset_dispatcher."""

from __future__ import annotations

import pytest
from core.strategy.multi_asset_dispatcher import (
    AssetClass,
    AssetClassDetector,
    MultiAssetStrategyDispatcher,
    RoutingResult,
    get_dispatcher,
)


class TestAssetClassDetector:
    """Tests for asset class detection heuristics."""

    def test_detect_index_options(self):
        for sym in ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX"):
            assert AssetClassDetector.detect(sym) == AssetClass.INDEX_OPTIONS

    def test_detect_etf(self):
        assert AssetClassDetector.detect("NIFTYBEES") == AssetClass.ETF
        assert AssetClassDetector.detect("BANKBEES") == AssetClass.ETF
        assert AssetClassDetector.detect("GOLDBEES") == AssetClass.ETF
        assert AssetClassDetector.detect("SOMETHINGETF") == AssetClass.ETF

    def test_detect_equity_ticker(self):
        assert AssetClassDetector.detect("RELIANCE") == AssetClass.EQUITY
        assert AssetClassDetector.detect("TCS") == AssetClass.EQUITY
        assert AssetClassDetector.detect("HDFCBANK") == AssetClass.EQUITY

    def test_detect_reit(self):
        assert AssetClassDetector.detect("EMBASSYREIT") == AssetClass.REIT
        assert AssetClassDetector.detect("MINDSPACEREIT") == AssetClass.REIT

    def test_detect_invit(self):
        assert AssetClassDetector.detect("IRBINVIT") == AssetClass.INVIT
        assert AssetClassDetector.detect("POWERGRID_INVIT") == AssetClass.INVIT

    def test_detect_futures_prefix(self):
        assert AssetClassDetector.detect("FUT:NIFTY") == AssetClass.FUTURES

    def test_detect_commodity(self):
        assert AssetClassDetector.detect("COM:GOLD") == AssetClass.COMMODITY
        assert AssetClassDetector.detect("GOLD") == AssetClass.COMMODITY
        assert AssetClassDetector.detect("SILVER") == AssetClass.COMMODITY
        assert AssetClassDetector.detect("CRUDEOIL") == AssetClass.COMMODITY

    def test_detect_currency(self):
        assert AssetClassDetector.detect("CUR:USDINR") == AssetClass.CURRENCY
        assert AssetClassDetector.detect("USDINR") == AssetClass.CURRENCY
        assert AssetClassDetector.detect("EURINR") == AssetClass.CURRENCY

    def test_detect_unknown(self):
        assert AssetClassDetector.detect("random_symbol_123") == AssetClass.UNKNOWN
        assert AssetClassDetector.detect("") == AssetClass.UNKNOWN

    def test_detect_with_asset_map_index(self):
        asset_map = {"MYSPECIAL": "EQUITY", "MYFUND": "MUTUAL_FUND"}
        assert AssetClassDetector.detect("MYSPECIAL", asset_map) == AssetClass.EQUITY
        assert AssetClassDetector.detect("MYFUND", asset_map) == AssetClass.MUTUAL_FUND


class TestMultiAssetStrategyDispatcher:
    """Tests for the multi-asset routing dispatcher."""

    def test_initialization(self):
        d = MultiAssetStrategyDispatcher()
        assert d.get_status()["registered_engines"] == {}
        assert d.get_status()["total_routes"] == 0

    def test_register_engine(self):
        d = MultiAssetStrategyDispatcher()
        d.register_engine(AssetClass.EQUITY, lambda symbol, signal, **kw: RoutingResult(
            handled=True, engine="eq_test", asset_class="EQUITY", action="ENTER"
        ), engine_name="eq_test")
        status = d.get_status()
        assert "EQUITY" in status["registered_engines"]
        assert status["registered_engines"]["EQUITY"]["name"] == "eq_test"

    def test_detect_asset_class_method(self):
        d = MultiAssetStrategyDispatcher()
        assert d.detect_asset_class("RELIANCE") == "EQUITY"
        assert d.detect_asset_class("NIFTY") == "INDEX_OPTIONS"
        assert d.detect_asset_class("GOLDBEES") == "ETF"

    def test_route_to_registered_engine(self):
        d = MultiAssetStrategyDispatcher()
        results = []
        def handler(symbol, signal, direction="", score=0, **kw):
            results.append((symbol, direction, score))
            return RoutingResult(handled=True, engine="eq_test", asset_class="EQUITY",
                                action="ENTER", message=f"Handled {symbol}")
        d.register_engine(AssetClass.EQUITY, handler, engine_name="eq_test")
        result = d.route("RELIANCE", direction="BUY", score=75)
        assert result.handled is True
        assert result.engine == "eq_test"
        assert result.action == "ENTER"
        assert len(results) == 1
        assert results[0] == ("RELIANCE", "BUY", 75)

    def test_route_no_engine(self):
        d = MultiAssetStrategyDispatcher()
        result = d.route("xyz_not_a_ticker_12345")
        assert result.handled is False
        assert result.asset_class == "UNKNOWN"
        assert "No engine registered" in result.message

    def test_route_engine_error(self):
        d = MultiAssetStrategyDispatcher()
        def failing_handler(symbol, signal, **kw):
            raise ValueError("Simulated failure")
        d.register_engine(AssetClass.EQUITY, failing_handler, engine_name="fail_engine")
        result = d.route("RELIANCE")
        assert result.handled is False
        assert result.action == "ERROR"
        assert "Simulated failure" in result.error

    def test_fallback_to_futures_handler(self):
        d = MultiAssetStrategyDispatcher()
        futures_handler_called = []
        def futures_handler(symbol, signal, **kw):
            futures_handler_called.append(symbol)
            return RoutingResult(handled=True, engine="futures", asset_class="FUTURES", action="ENTER")
        d.register_engine(AssetClass.FUTURES, futures_handler, engine_name="futures_trader")
        result = d.route("GOLD")
        assert result.handled is True
        assert len(futures_handler_called) == 1

    def test_routing_log(self):
        d = MultiAssetStrategyDispatcher()
        def handler(symbol, signal, **kw):
            return RoutingResult(handled=True, engine="test", asset_class="EQUITY", action="ENTER")
        d.register_engine(AssetClass.EQUITY, handler, engine_name="test")
        d.route("TCS")
        d.route("RELIANCE")
        log = d.get_routing_log()
        assert len(log) == 2
        assert log[0]["symbol"] == "RELIANCE"
        assert log[1]["symbol"] == "TCS"

    def test_singleton_factory(self):
        d1 = get_dispatcher()
        d2 = get_dispatcher()
        assert d1 is d2

    def test_get_routing_log_limit(self):
        d = MultiAssetStrategyDispatcher()
        def handler(symbol, signal, **kw):
            return RoutingResult(handled=True, engine="test", asset_class="EQUITY", action="ENTER")
        d.register_engine(AssetClass.EQUITY, handler, engine_name="test")
        for sym in ("A", "B", "C", "D", "E"):
            d.route(sym)
        log = d.get_routing_log(limit=2)
        assert len(log) == 2

    def test_route_with_signal_dict(self):
        d = MultiAssetStrategyDispatcher()
        captured = []
        def handler(symbol, signal, **kw):
            captured.append(signal)
            return RoutingResult(handled=True, engine="test", asset_class="EQUITY", action="ENTER")
        d.register_engine(AssetClass.EQUITY, handler, engine_name="test")
        d.route("TCS", signal={"direction": "SELL", "score": 60, "reason": "test"})
        assert len(captured) == 1
        assert captured[0]["direction"] == "SELL"
        assert captured[0]["score"] == 60

    def test_route_index_options_signal(self):
        d = MultiAssetStrategyDispatcher()
        captured = []
        def handler(symbol, signal, direction="", score=0, **kw):
            captured.append((symbol, direction, score))
            return RoutingResult(handled=True, engine="index_trader", asset_class="INDEX_OPTIONS",
                                action="ENTER", message=f"Handled {symbol}")
        d.register_engine(AssetClass.INDEX_OPTIONS, handler, engine_name="index_trader")
        result = d.route("NIFTY", direction="CALL", score=80)
        assert result.handled is True
        assert result.engine == "index_trader"
        assert result.action == "ENTER"
        assert len(captured) == 1
        assert captured[0] == ("NIFTY", "CALL", 80)

    def test_route_index_options_with_signal_dict(self):
        d = MultiAssetStrategyDispatcher()
        captured = []
        def handler(symbol, signal, **kw):
            captured.append(signal)
            return RoutingResult(handled=True, engine="index_trader", asset_class="INDEX_OPTIONS", action="ENTER")
        d.register_engine(AssetClass.INDEX_OPTIONS, handler, engine_name="index_trader")
        d.route("BANKNIFTY", signal={"direction": "PUT", "score": 75, "price": 52000})
        assert len(captured) == 1
        assert captured[0]["direction"] == "PUT"
        assert captured[0]["score"] == 75

    def test_route_index_options_via_evaluate_and_route(self):
        from unittest.mock import MagicMock, patch
        d = MultiAssetStrategyDispatcher()
        captured = []
        def handler(symbol, signal, **kw):
            captured.append((symbol, signal.get("direction", ""), signal.get("score", 0)))
            return RoutingResult(handled=True, engine="index_trader",
                                asset_class="INDEX_OPTIONS", action="ENTER")
        d.register_engine(AssetClass.INDEX_OPTIONS, handler, engine_name="index_trader")

        mock_result = MagicMock()
        mock_result.is_actionable.return_value = True
        mock_result.to_dict.return_value = {"direction": "CALL", "score": 80, "price": 24000}
        mock_result.score = 80

        mock_evaluator = MagicMock()
        mock_evaluator.evaluate.return_value = mock_result

        with patch.object(d, "_get_signal_evaluator", return_value=mock_evaluator):
            result = d.evaluate_and_route("NIFTY")

        assert result.handled is True
        assert result.action == "ENTER"
        assert len(captured) == 1
        assert captured[0] == ("NIFTY", "CALL", 80)

    def test_route_max_log_eviction(self):
        """When routing log exceeds max, oldest entries are evicted."""
        d = MultiAssetStrategyDispatcher()
        d._max_log = 3
        def handler(symbol, signal, **kw):
            return RoutingResult(handled=True, engine="test", asset_class="EQUITY", action="ENTER")
        d.register_engine(AssetClass.EQUITY, handler, engine_name="test")
        for sym in ("A", "B", "C", "D"):
            d.route(sym)
        log = d.get_routing_log()
        assert len(log) == 3
        # "A" should have been evicted; oldest remaining is "B"
        assert log[-1]["symbol"] == "B"


class TestIndexOptionsHandler:
    """Tests for the _make_index_options_handler edge cases."""

    def test_handler_advisory_mode_no_controller(self):
        from core.strategy.multi_asset_dispatcher import _make_index_options_handler
        d = MultiAssetStrategyDispatcher()
        handler = _make_index_options_handler()
        d.register_engine(AssetClass.INDEX_OPTIONS, handler, engine_name="index_trader")
        result = d.route("NIFTY", direction="CALL", score=80)
        assert result.handled is True
        assert result.engine == "index_trader"
        assert result.asset_class == "INDEX_OPTIONS"
        assert result.action == "ENTER"
        assert "Signal accepted" in result.message

    def test_handler_with_price_from_signal_dict(self):
        from core.strategy.multi_asset_dispatcher import _make_index_options_handler
        handler = _make_index_options_handler()
        result = handler(
            "NIFTY", signal={"direction": "PUT", "score": 75, "price": 24100},
        )
        assert result.handled is True
        assert result.message == "Signal accepted for NIFTY PUT score=75"

    def test_handler_with_banknifty_signal(self):
        from core.strategy.multi_asset_dispatcher import _make_index_options_handler
        d = MultiAssetStrategyDispatcher()
        handler = _make_index_options_handler()
        d.register_engine(AssetClass.INDEX_OPTIONS, handler, engine_name="index_trader")
        for sym in ("BANKNIFTY", "FINNIFTY"):
            result = d.route(sym, direction="PUT", score=65, signal={"price": 50000})
            assert result.handled is True
            assert result.engine == "index_trader"

    def test_get_dispatcher_with_all_engines_smoke(self):
        from core.strategy.multi_asset_dispatcher import get_dispatcher_with_all_engines
        d = get_dispatcher_with_all_engines(config={"webhook_enabled": False})
        assert d is not None
        status = d.get_status()
        assert "registered_engines" in status
        assert "INDEX_OPTIONS" in status["registered_engines"]


class TestWebhookRouting:
    """Tests for the _route_signal_via_dispatcher webhook helper."""
    pytest.importorskip("fastapi")

    def test_routes_signal_via_mocked_dispatcher(self):
        from unittest.mock import MagicMock, patch

        with patch("core.di_container.get_container") as mock_get_container:
            mock_container = MagicMock()
            mock_dispatcher = MagicMock()
            mock_dispatcher.route.return_value = MagicMock(
                asset_class="INDEX_OPTIONS", action="ENTER",
                engine="index_trader", message="Signal accepted for NIFTY CALL score=80",
            )
            mock_container.try_resolve.return_value = mock_dispatcher
            mock_get_container.return_value = mock_container

            from core.enterprise_dashboard.routes.webhooks import _route_signal_via_dispatcher
            result = _route_signal_via_dispatcher(
                {"symbol": "NIFTY", "direction": "CALL", "score": 80, "price": 24000},
                None,
            )

        assert result["status"] == "routed"
        assert result["symbol"] == "NIFTY"
        assert result["action"] == "ENTER"
        assert result["engine"] == "index_trader"
        mock_dispatcher.route.assert_called_once()

    def test_skipped_for_missing_symbol(self):
        from core.enterprise_dashboard.routes.webhooks import _route_signal_via_dispatcher
        result = _route_signal_via_dispatcher({}, None)
        assert result["status"] == "skipped"
        assert result["reason"] == "no_symbol"

    def test_fallback_to_queued_when_dispatcher_unregistered(self):
        from unittest.mock import MagicMock, patch

        with patch("core.di_container.get_container") as mock_get_container:
            mock_container = MagicMock()
            mock_container.try_resolve.return_value = None
            mock_get_container.return_value = mock_container

            from core.enterprise_dashboard.routes.webhooks import _route_signal_via_dispatcher
            result = _route_signal_via_dispatcher(
                {"symbol": "RELIANCE", "direction": "BUY", "score": 70},
                None,
            )

        assert result["status"] == "queued"
        assert "ts" in result


class TestRoutingResult:
    """Tests for the RoutingResult dataclass."""

    def test_default_values(self):
        r = RoutingResult(handled=True)
        assert r.handled is True
        assert r.engine == ""
        assert r.asset_class == ""
        assert r.action == "SKIP"
        assert r.message == ""

    def test_error_result(self):
        r = RoutingResult(handled=False, action="ERROR", error="Connection failed")
        assert r.handled is False
        assert r.error == "Connection failed"

    def test_full_result(self):
        r = RoutingResult(
            handled=True, engine="futures_trader", asset_class="FUTURES",
            action="ENTER", message="Entered NIFTY futures",
        )
        assert r.handled is True
        assert r.engine == "futures_trader"
        assert r.message == "Entered NIFTY futures"


class TestHandlerFactories:
    """Tests for handler factory functions (_make_handler, _make_handler_for_equity, etc.)."""

    def test_make_handler_with_valid_trader(self):
        from unittest.mock import MagicMock

        from core.strategy.multi_asset_dispatcher import _make_handler
        mock_trader = MagicMock()
        mock_trader.enter_position.return_value = True
        handler = _make_handler(mock_trader, "test_engine", "FUTURES")
        result = handler("NIFTY", direction="BUY", score=75)
        assert result.handled is True
        assert result.engine == "test_engine"
        assert result.action == "ENTER"
        mock_trader.enter_position.assert_called_once()

    def test_make_handler_trader_fails(self):
        from unittest.mock import MagicMock

        from core.strategy.multi_asset_dispatcher import _make_handler
        mock_trader = MagicMock()
        mock_trader.enter_position.return_value = False
        handler = _make_handler(mock_trader, "test_engine", "COMMODITY")
        result = handler("GOLD", signal={"direction": "BUY", "score": 60})
        assert result.handled is False
        assert result.action == "SKIP"
        assert "Failed" in result.message

    def test_make_handler_for_equity_with_reason(self):
        from unittest.mock import MagicMock

        from core.strategy.multi_asset_dispatcher import _make_handler_for_equity
        mock_trader = MagicMock()
        mock_trader.enter_position.return_value = True
        handler = _make_handler_for_equity(mock_trader, "equity_test", "EQUITY")
        result = handler("RELIANCE", direction="BUY", score=70, reason="signal_alert")
        assert result.handled is True
        mock_trader.enter_position.assert_called_with("RELIANCE", "BUY", 70, reason="signal_alert")

    def test_make_index_options_handler_no_direction(self):
        from core.strategy.multi_asset_dispatcher import _make_index_options_handler
        handler = _make_index_options_handler()
        result = handler("NIFTY", signal={})
        assert result.handled is False
        assert result.action == "SKIP"
        assert "No direction" in result.message


class TestEvaluateAndRoute:
    """Tests for the evaluate_and_route method of MultiAssetStrategyDispatcher."""

    def test_evaluate_and_route_when_evaluator_unavailable(self):
        from unittest.mock import patch
        d = MultiAssetStrategyDispatcher()
        with patch.object(d, "_get_signal_evaluator", return_value=None):
            result = d.evaluate_and_route("RELIANCE")
        assert result.handled is False
        assert result.action == "ERROR"
        assert "SignalEvaluator unavailable" in result.message

    def test_evaluate_and_route_when_evaluator_returns_none(self):
        from unittest.mock import MagicMock, patch
        d = MultiAssetStrategyDispatcher()
        mock_evaluator = MagicMock()
        mock_evaluator.evaluate.return_value = None
        with patch.object(d, "_get_signal_evaluator", return_value=mock_evaluator):
            result = d.evaluate_and_route("RELIANCE")
        assert result.handled is False
        assert result.action == "SKIP"
        assert "No actionable signal" in result.message

    def test_evaluate_and_route_when_signal_below_threshold(self):
        from unittest.mock import MagicMock, patch
        d = MultiAssetStrategyDispatcher()
        mock_result = MagicMock()
        mock_result.is_actionable.return_value = False
        mock_result.score = 20
        mock_evaluator = MagicMock()
        mock_evaluator.evaluate.return_value = mock_result
        with patch.object(d, "_get_signal_evaluator", return_value=mock_evaluator):
            result = d.evaluate_and_route("RELIANCE", min_score=35)
        assert result.handled is False
        assert result.action == "SKIP"
        assert "below threshold" in result.message

    def test_evaluate_and_route_auto_detects_index_options(self):
        from unittest.mock import MagicMock, patch
        d = MultiAssetStrategyDispatcher()
        mock_result = MagicMock()
        mock_result.is_actionable.return_value = True
        mock_result.to_dict.return_value = {"direction": "CALL", "score": 80, "price": 24000}
        mock_result.score = 80
        mock_evaluator = MagicMock()
        mock_evaluator.evaluate.return_value = mock_result
        with patch.object(d, "_get_signal_evaluator", return_value=mock_evaluator):
            result = d.evaluate_and_route("NIFTY")
        assert "No engine registered" in result.message


class TestRouteEdgeCases:
    """Tests for edge cases in the route() method."""

    def test_route_with_non_routing_result_response(self):
        d = MultiAssetStrategyDispatcher()
        def handler(symbol, signal, **kw):
            return {"custom": "dict", "status": "ok"}
        d.register_engine(AssetClass.EQUITY, handler, engine_name="test")
        result = d.route("TCS")
        assert result.handled is True
        assert result.action == "ENTER"

    def test_detect_asset_class_with_custom_asset_map(self):
        asset_map = {"MYSPECIAL": "BOND"}
        d = MultiAssetStrategyDispatcher(asset_map_index=asset_map)
        assert d.detect_asset_class("MYSPECIAL") == "BOND"

    def test_route_falls_back_to_futures_for_bond(self):
        asset_map = {"MYSPECIAL": "BOND"}
        d = MultiAssetStrategyDispatcher(asset_map_index=asset_map)
        def futures_handler(symbol, signal, **kw):
            return RoutingResult(handled=True, engine="futures", asset_class="BOND", action="ENTER")
        d.register_engine(AssetClass.FUTURES, futures_handler, engine_name="futures_trader")
        result = d.route("MYSPECIAL")
        assert result.handled is True
        assert result.engine == "futures"


class TestBrokerExecutorBuilder:
    """Tests for the _build_broker_executor_for_dispatcher function."""

    def test_paper_mode_default(self):
        """Default config produces paper-mode callbacks."""
        from core.strategy.multi_asset_dispatcher import _build_broker_executor_for_dispatcher
        entry, exit = _build_broker_executor_for_dispatcher({})
        assert callable(entry)
        assert callable(exit)
        result = entry("TEST", "BUY", 1, 100.0)
        assert result is False

    def test_import_error_fallback(self):
        """When build_broker_executor raises ImportError, no-op fallback is returned."""
        from unittest.mock import patch

        from core.strategy.multi_asset_dispatcher import _build_broker_executor_for_dispatcher

        with patch("index_app.domains.broker.factory.build_broker_executor", side_effect=ImportError("simulated")):
            entry, exit = _build_broker_executor_for_dispatcher({})
            assert callable(entry)
            assert callable(exit)
            assert entry("ANY", "BUY", 10, 200.0) is False
            # exit should not raise
            exit("ANY", 10, 200.0)

    def test_value_error_fallback(self):
        """When build_broker_executor raises ValueError, no-op fallback is returned."""
        from unittest.mock import patch

        from core.strategy.multi_asset_dispatcher import _build_broker_executor_for_dispatcher

        with patch("index_app.domains.broker.factory.build_broker_executor", side_effect=ValueError("bad config")):
            entry, exit = _build_broker_executor_for_dispatcher({})
            assert entry("ANY", "BUY", 10, 200.0) is False


class TestGetDispatcherWithAllEngines:
    """Tests for get_dispatcher_with_all_engines factory function."""

    def test_registers_index_options(self):
        """Always registers INDEX_OPTIONS engine."""
        from core.strategy.multi_asset_dispatcher import get_dispatcher_with_all_engines
        d = get_dispatcher_with_all_engines(config={})
        status = d.get_status()
        assert "INDEX_OPTIONS" in status["registered_engines"]
        assert status["registered_engines"]["INDEX_OPTIONS"]["name"] == "index_trader"

    def test_with_equity_config_registers_equity(self):
        """With EQUITY_MAP in config, EquityTrader gets registered."""
        from core.strategy.multi_asset_dispatcher import get_dispatcher_with_all_engines
        config = {
            "EQUITY_MAP": {"RELIANCE": {"yf": "RELIANCE.NS", "enabled": True}},
            "EQUITY_ENABLED": True,
        }
        d = get_dispatcher_with_all_engines(config=config)
        status = d.get_status()
        registered = list(status["registered_engines"].keys())
        assert "INDEX_OPTIONS" in registered
        assert "EQUITY" in registered
