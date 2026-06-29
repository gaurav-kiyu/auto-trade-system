"""
Comprehensive tests for core.ports.broker.broker_port.

Covers all dataclasses, enums, and the abstract broker port interface.
Uses a concrete test adapter to verify the contract is implementable.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, fields
from datetime import datetime
from typing import Any

import pytest
from core.ports.broker.broker_port import (
    BrokerAuthStatus,
    BrokerCapability,
    BrokerCredentials,
    BrokerOrderRequest,
    BrokerPort,
    Exchange,
    Holding,
    Margin,
    OrderResult,
    OrderStatus,
    OrderType,
    OrderVariety,
    Position,
    PositionDirection,
    ProductType,
    Trade,
)

# ── Enum Tests ────────────────────────────────────────────────────────────────


class TestEnums:
    def test_broker_auth_status_values(self) -> None:
        assert BrokerAuthStatus.CONNECTED.value == "CONNECTED"
        assert BrokerAuthStatus.DISCONNECTED.value == "DISCONNECTED"
        assert BrokerAuthStatus.TOKEN_EXPIRED.value == "TOKEN_EXPIRED"
        assert BrokerAuthStatus.ERROR.value == "ERROR"

    def test_order_type_values(self) -> None:
        assert OrderType.MARKET.value == "MARKET"
        assert OrderType.LIMIT.value == "LIMIT"
        assert OrderType.SL.value == "SL"
        assert OrderType.SL_M.value == "SL_M"

    def test_order_variety_values(self) -> None:
        assert OrderVariety.REGULAR.value == "REGULAR"
        assert OrderVariety.CO.value == "CO"
        assert OrderVariety.BO.value == "BO"
        assert OrderVariety.AMO.value == "AMO"
        assert OrderVariety.ICEBERG.value == "ICEBERG"

    def test_product_type_values(self) -> None:
        assert ProductType.MIS.value == "MIS"
        assert ProductType.NRML.value == "NRML"
        assert ProductType.CNC.value == "CNC"

    def test_order_status_values(self) -> None:
        assert OrderStatus.PENDING.value == "PENDING"
        assert OrderStatus.SUBMITTED.value == "SUBMITTED"
        assert OrderStatus.PARTIALLY_FILLED.value == "PARTIALLY_FILLED"
        assert OrderStatus.FILLED.value == "FILLED"
        assert OrderStatus.CANCELLED.value == "CANCELLED"
        assert OrderStatus.REJECTED.value == "REJECTED"
        assert OrderStatus.EXPIRED.value == "EXPIRED"
        assert OrderStatus.TRIGGER_PENDING.value == "TRIGGER_PENDING"
        assert OrderStatus.OPEN.value == "OPEN"
        assert OrderStatus.UNKNOWN.value == "UNKNOWN"

    def test_position_direction_values(self) -> None:
        assert PositionDirection.LONG.value == "LONG"
        assert PositionDirection.SHORT.value == "SHORT"

    def test_exchange_values(self) -> None:
        assert Exchange.NSE.value == "NSE"
        assert Exchange.BSE.value == "BSE"
        assert Exchange.NFO.value == "NFO"
        assert Exchange.BFO.value == "BFO"
        assert Exchange.MCX.value == "MCX"
        assert Exchange.CDS.value == "CDS"

    def test_all_enums_distinct(self) -> None:
        """Verify no accidental value collisions across enums."""
        all_values = [
            e.value for e in BrokerAuthStatus
        ] + [
            e.value for e in OrderType
        ] + [
            e.value for e in OrderVariety
        ] + [
            e.value for e in ProductType
        ] + [
            e.value for e in OrderStatus
        ] + [
            e.value for e in PositionDirection
        ] + [
            e.value for e in Exchange
        ]
        assert len(all_values) == len(set(all_values)), "Enum values must be distinct"


# ── Dataclass Tests ───────────────────────────────────────────────────────────


class TestBrokerCredentials:
    def test_defaults(self) -> None:
        creds = BrokerCredentials(broker_name="test")
        assert creds.broker_name == "test"
        assert creds.api_key == ""
        assert creds.api_secret == ""
        assert creds.access_token == ""
        assert creds.user_id == ""
        assert creds.additional_params == {}

    def test_full_init(self) -> None:
        creds = BrokerCredentials(
            broker_name="zerodha",
            api_key="key123",
            api_secret="secret456",
            access_token="token789",
            user_id="user001",
            totp_key="totp123",
            additional_params={"timeout": 10},
        )
        assert creds.broker_name == "zerodha"
        assert creds.additional_params["timeout"] == 10

    def test_immutable_fields(self) -> None:
        """BrokerCredentials should define all expected fields."""
        field_names = {f.name for f in fields(BrokerCredentials)}
        expected = {"broker_name", "api_key", "api_secret", "access_token",
                     "refresh_token", "user_id", "totp_key", "additional_params"}
        assert field_names >= expected, f"Missing fields: {expected - field_names}"


class TestBrokerOrderRequest:
    def test_defaults(self) -> None:
        req = BrokerOrderRequest(
            symbol="NIFTY",
            exchange=Exchange.NFO,
            transaction_type="BUY",
            quantity=75,
            order_type=OrderType.MARKET,
        )
        assert req.product == ProductType.MIS
        assert req.variety == OrderVariety.REGULAR
        assert req.price is None

    def test_full_init(self) -> None:
        req = BrokerOrderRequest(
            symbol="BANKNIFTY",
            exchange=Exchange.NFO,
            transaction_type="SELL",
            quantity=30,
            order_type=OrderType.LIMIT,
            product=ProductType.NRML,
            variety=OrderVariety.BO,
            price=45000.0,
            trigger_price=44900.0,
            validity="IOC",
            tag="strategy_1",
            idempotency_key="uuid-123",
            strategy_id="strat_a",
            user_order_id="my_order_1",
            additional_fields={"iceberg_qty": 10},
        )
        assert req.price == 45000.0
        assert req.idempotency_key == "uuid-123"
        assert req.additional_fields["iceberg_qty"] == 10


class TestOrderResult:
    def test_minimal(self) -> None:
        result = OrderResult(broker_order_id="order1", status=OrderStatus.SUBMITTED)
        assert result.broker_order_id == "order1"
        assert result.status == OrderStatus.SUBMITTED

    def test_full(self) -> None:
        dt = datetime(2025, 1, 15, 10, 30)
        result = OrderResult(
            broker_order_id="order1",
            status=OrderStatus.FILLED,
            filled_quantity=75,
            pending_quantity=0,
            average_price=18500.0,
            total_amount=75 * 18500.0,
            placed_at=dt,
            filled_at=dt,
            exchange_order_id="exch_001",
            reject_reason="",
            metadata={"slippage": 0.5},
        )
        assert result.average_price == 18500.0
        assert result.metadata["slippage"] == 0.5

    def test_rejected(self) -> None:
        result = OrderResult(
            broker_order_id="order2",
            status=OrderStatus.REJECTED,
            reject_reason="Insufficient margin",
        )
        assert result.reject_reason == "Insufficient margin"


class TestPosition:
    def test_minimal(self) -> None:
        pos = Position(
            symbol="NIFTY",
            exchange=Exchange.NFO,
            direction=PositionDirection.LONG,
            quantity=75,
            average_price=18500.0,
            last_price=18600.0,
            pnl=7500.0,
        )
        assert pos.pnl == 7500.0

    def test_all_fields(self) -> None:
        pos = Position(
            symbol="BANKNIFTY",
            exchange=Exchange.NFO,
            direction=PositionDirection.SHORT,
            quantity=30,
            average_price=45000.0,
            last_price=44800.0,
            pnl=6000.0,
            realised_pnl=2000.0,
            unrealised_pnl=4000.0,
            buy_quantity=30,
            sell_quantity=30,
            buy_average=45000.0,
            sell_average=44800.0,
            product=ProductType.MIS,
            multiplier=1.0,
            trade_value=1350000.0,
            lot_size=15,
            metadata={"source": "manual"},
        )
        assert pos.multiplier == 1.0
        assert pos.lot_size == 15


class TestHolding:
    def test_minimal(self) -> None:
        h = Holding(symbol="RELIANCE", exchange=Exchange.NSE, quantity=10,
                     average_price=2500.0, last_price=2600.0, pnl=1000.0)
        assert h.metadata == {}
        assert h.product == ProductType.NRML


class TestTrade:
    def test_minimal(self) -> None:
        t = Trade(
            trade_id="trade1",
            order_id="order1",
            symbol="NIFTY",
            exchange=Exchange.NFO,
            transaction_type="BUY",
            quantity=75,
            price=18500.0,
            amount=75 * 18500.0,
            trade_time=datetime.now(),
        )
        assert t.brokerage == 0.0


class TestMargin:
    def test_defaults(self) -> None:
        m = Margin()
        assert m.total_margin == 0.0
        assert m.used_margin == 0.0
        assert m.available_margin == 0.0

    def test_full(self) -> None:
        m = Margin(
            total_margin=500000.0,
            used_margin=200000.0,
            available_margin=300000.0,
            cash=500000.0,
            exposure=200000.0,
            additional={"futures_margin": 100000.0},
        )
        assert m.cash == 500000.0
        assert m.additional["futures_margin"] == 100000.0


class TestBrokerCapability:
    def test_minimal(self) -> None:
        cap = BrokerCapability(name="order_place", description="Place orders")
        assert cap.version == "1.0"

    def test_full(self) -> None:
        cap = BrokerCapability(name="websocket", description="Real-time data", version="2.0")
        assert cap.version == "2.0"


# ── BrokerPort Interface Contract Tests ───────────────────────────────────────


class _TestBrokerAdapter(BrokerPort):
    """Concrete test adapter implementing all abstract methods."""

    def __init__(self) -> None:
        self._authenticated = False
        self._orders: dict[str, OrderResult] = {}
        self._positions: list[Position] = []
        self._trades: list[Trade] = []

    @property
    def broker_name(self) -> str:
        return "test_broker"

    @property
    def capabilities(self) -> list[BrokerCapability]:
        return [BrokerCapability("order_place", "Test orders")]

    def authenticate(self, credentials: BrokerCredentials) -> BrokerAuthStatus:
        self._authenticated = True
        return BrokerAuthStatus.CONNECTED

    def is_authenticated(self) -> bool:
        return self._authenticated

    def refresh_token(self, force: bool = False) -> bool:
        return True

    def logout(self) -> bool:
        self._authenticated = False
        return True

    def place_order(self, order: BrokerOrderRequest) -> OrderResult:
        result = OrderResult(broker_order_id="test_001", status=OrderStatus.SUBMITTED)
        self._orders["test_001"] = result
        return result

    def modify_order(
        self,
        broker_order_id: str,
        *,
        quantity: int | None = None,
        price: float | None = None,
        trigger_price: float | None = None,
        order_type: OrderType | None = None,
        validity: str | None = None,
    ) -> OrderResult:
        return OrderResult(broker_order_id=broker_order_id, status=OrderStatus.FILLED)

    def cancel_order(self, broker_order_id: str) -> OrderResult:
        return OrderResult(broker_order_id=broker_order_id, status=OrderStatus.CANCELLED)

    def get_order_status(self, broker_order_id: str) -> OrderResult:
        return self._orders.get(broker_order_id, OrderResult(
            broker_order_id=broker_order_id, status=OrderStatus.UNKNOWN))

    def get_order_history(self, **kwargs: Any) -> list[OrderResult]:
        return list(self._orders.values())

    def get_positions(self) -> list[Position]:
        return self._positions

    def get_position(self, symbol: str) -> Position | None:
        for p in self._positions:
            if p.symbol == symbol:
                return p
        return None

    def get_holdings(self) -> list[Holding]:
        return []

    def get_trades(self, **kwargs: Any) -> list[Trade]:
        return self._trades

    def get_margin(self) -> Margin:
        return Margin(total_margin=500000.0, available_margin=500000.0)

    def get_balance(self) -> dict[str, float]:
        return {"cash": 1000000.0, "available": 800000.0, "used": 200000.0}

    def get_ltp(self, symbol: str, exchange: Exchange) -> float:
        return 18500.0

    def get_quote(self, symbol: str, exchange: Exchange) -> dict[str, Any]:
        return {"symbol": symbol, "ltp": 18500.0, "volume": 100000}

    def get_option_chain(
        self,
        symbol: str,
        expiry: str | None = None,
        strike: float | None = None,
        option_type: str | None = None,
    ) -> list[dict[str, Any]]:
        return [{"symbol": symbol, "strike": 18500, "type": "CE"}]

    def get_historical_data(
        self,
        symbol: str,
        exchange: Exchange,
        interval: str,
        from_date: datetime,
        to_date: datetime,
    ) -> list[dict[str, Any]]:
        return [{"date": from_date.isoformat(), "open": 18400, "close": 18500}]

    def subscribe_market_data(
        self,
        symbols: list[str],
        exchange: Exchange,
        callback: Callable[[dict[str, Any]], None],
    ) -> bool:
        return True

    def unsubscribe_market_data(
        self,
        symbols: list[str],
        exchange: Exchange,
    ) -> bool:
        return True

    def health_check(self) -> dict[str, Any]:
        return {"status": "healthy", "latency_ms": 15, "auth_status": "connected"}

    def ping(self) -> bool:
        return True

    def handle_error(self, error: Exception, context: dict[str, Any] = None) -> None:
        pass

    def is_rate_limited(self) -> bool:
        return False


class TestBrokerPortContract:
    """Verify the abstract interface contract is properly implementable."""

    @pytest.fixture
    def adapter(self) -> _TestBrokerAdapter:
        return _TestBrokerAdapter()

    def test_broker_name(self, adapter: _TestBrokerAdapter) -> None:
        assert adapter.broker_name == "test_broker"

    def test_capabilities(self, adapter: _TestBrokerAdapter) -> None:
        caps = adapter.capabilities
        assert len(caps) >= 1
        assert isinstance(caps[0], BrokerCapability)

    def test_auth_lifecycle(self, adapter: _TestBrokerAdapter) -> None:
        assert not adapter.is_authenticated()
        creds = BrokerCredentials(broker_name="test")
        status = adapter.authenticate(creds)
        assert status == BrokerAuthStatus.CONNECTED
        assert adapter.is_authenticated()

    def test_logout(self, adapter: _TestBrokerAdapter) -> None:
        creds = BrokerCredentials(broker_name="test")
        adapter.authenticate(creds)
        assert adapter.logout()
        assert not adapter.is_authenticated()

    def test_token_refresh(self, adapter: _TestBrokerAdapter) -> None:
        assert adapter.refresh_token()
        assert adapter.refresh_token(force=True)

    def test_place_and_get_order(self, adapter: _TestBrokerAdapter) -> None:
        req = BrokerOrderRequest(
            symbol="NIFTY",
            exchange=Exchange.NFO,
            transaction_type="BUY",
            quantity=75,
            order_type=OrderType.MARKET,
        )
        result = adapter.place_order(req)
        assert result.status == OrderStatus.SUBMITTED

        status = adapter.get_order_status(result.broker_order_id)
        assert status.broker_order_id == "test_001"

    def test_modify_order(self, adapter: _TestBrokerAdapter) -> None:
        result = adapter.modify_order("test_001", quantity=100)
        assert result.status == OrderStatus.FILLED

    def test_cancel_order(self, adapter: _TestBrokerAdapter) -> None:
        result = adapter.cancel_order("test_001")
        assert result.status == OrderStatus.CANCELLED

    def test_order_history(self, adapter: _TestBrokerAdapter) -> None:
        history = adapter.get_order_history()
        assert isinstance(history, list)

    def test_positions_lifecycle(self, adapter: _TestBrokerAdapter) -> None:
        positions = adapter.get_positions()
        assert positions == []

        position = adapter.get_position("NIFTY")
        assert position is None

    def test_holdings(self, adapter: _TestBrokerAdapter) -> None:
        holdings = adapter.get_holdings()
        assert holdings == []

    def test_trades(self, adapter: _TestBrokerAdapter) -> None:
        trades = adapter.get_trades()
        assert isinstance(trades, list)

    def test_margin(self, adapter: _TestBrokerAdapter) -> None:
        margin = adapter.get_margin()
        assert isinstance(margin, Margin)
        assert margin.total_margin > 0

    def test_balance(self, adapter: _TestBrokerAdapter) -> None:
        balance = adapter.get_balance()
        assert "cash" in balance
        assert "available" in balance
        assert "used" in balance

    def test_market_data(self, adapter: _TestBrokerAdapter) -> None:
        ltp = adapter.get_ltp("NIFTY", Exchange.NFO)
        assert ltp > 0

        quote = adapter.get_quote("NIFTY", Exchange.NFO)
        assert quote["symbol"] == "NIFTY"

    def test_option_chain(self, adapter: _TestBrokerAdapter) -> None:
        chain = adapter.get_option_chain("NIFTY")
        assert len(chain) >= 1
        assert chain[0]["type"] == "CE"

    def test_historical_data(self, adapter: _TestBrokerAdapter) -> None:
        from datetime import datetime
        data = adapter.get_historical_data(
            "NIFTY", Exchange.NFO, "1d",
            datetime(2025, 1, 1), datetime(2025, 1, 31),
        )
        assert len(data) >= 1

    def test_websocket_subscription(self, adapter: _TestBrokerAdapter) -> None:
        def callback(data: dict[str, Any]) -> None:
            pass

        assert adapter.subscribe_market_data(["NIFTY"], Exchange.NFO, callback)
        assert adapter.unsubscribe_market_data(["NIFTY"], Exchange.NFO)

    def test_health_check(self, adapter: _TestBrokerAdapter) -> None:
        health = adapter.health_check()
        assert health["status"] == "healthy"

    def test_ping(self, adapter: _TestBrokerAdapter) -> None:
        assert adapter.ping()

    def test_error_handling(self, adapter: _TestBrokerAdapter) -> None:
        # handle_error should not raise
        adapter.handle_error(ValueError("test"), {"operation": "test"})

    def test_rate_limiting(self, adapter: _TestBrokerAdapter) -> None:
        assert not adapter.is_rate_limited()


# ── Edge Case Tests ───────────────────────────────────────────────────────────


class TestEdgeCases:
    def test_broker_order_request_validation(self) -> None:
        """Verify the request dataclass works with all OrderType values."""
        for ot in OrderType:
            req = BrokerOrderRequest(
                symbol="TEST",
                exchange=Exchange.NSE,
                transaction_type="BUY",
                quantity=1,
                order_type=ot,
            )
            assert req.order_type == ot

    def test_broker_credentials_serializable(self) -> None:
        """Verify credentials can be round-tripped through dataclass asdict()."""
        creds = BrokerCredentials(
            broker_name="test",
            api_key="key",
            additional_params={"nested": {"a": 1}},
        )
        d = asdict(creds)
        restored = BrokerCredentials(**d)
        assert restored.broker_name == "test"
        assert restored.additional_params["nested"]["a"] == 1

    def test_order_status_count(self) -> None:
        """Verify all 10 order status values are defined."""
        assert len(list(OrderStatus)) == 10, (
            f"Expected 10 OrderStatus values, got {len(list(OrderStatus))}"
        )

    def test_exchange_count(self) -> None:
        """Verify all 6 exchange values are defined."""
        assert len(list(Exchange)) == 6, (
            f"Expected 6 Exchange values, got {len(list(Exchange))}"
        )


class TestEdgeCaseFilters:
    """Edge-case tests for filter parameters on query methods."""

    @pytest.fixture
    def adapter(self) -> _TestBrokerAdapter:
        return _TestBrokerAdapter()

    def test_get_order_history_with_symbol_filter(self, adapter: _TestBrokerAdapter) -> None:
        """get_order_history with symbol filter should be accepted."""
        req = BrokerOrderRequest(
            symbol="NIFTY", exchange=Exchange.NFO,
            transaction_type="BUY", quantity=75, order_type=OrderType.MARKET,
        )
        adapter.place_order(req)
        # Symbol filter is accepted even if test adapter ignores it
        history = adapter.get_order_history(symbol="NIFTY")
        assert isinstance(history, list)
        assert len(history) == 1

    def test_get_order_history_with_date_filter(self, adapter: _TestBrokerAdapter) -> None:
        """get_order_history with date range should not raise."""
        from datetime import datetime
        history = adapter.get_order_history(
            from_date=datetime(2025, 1, 1),
            to_date=datetime(2025, 1, 31),
            max_results=10,
        )
        assert isinstance(history, list)

    def test_get_trades_with_date_range(self, adapter: _TestBrokerAdapter) -> None:
        """get_trades with from/to date filters should not raise."""
        from datetime import datetime
        trades = adapter.get_trades(
            from_date=datetime(2025, 1, 1),
            to_date=datetime(2025, 1, 31),
            max_results=100,
        )
        assert isinstance(trades, list)

    def test_get_trades_with_no_filters(self, adapter: _TestBrokerAdapter) -> None:
        """get_trades with no filters returns all trades."""
        trades = adapter.get_trades()
        assert isinstance(trades, list)

    def test_historical_data_one_minute_interval(self, adapter: _TestBrokerAdapter) -> None:
        """get_historical_data with '1m' interval."""
        from datetime import datetime
        data = adapter.get_historical_data(
            "NIFTY", Exchange.NFO, "1m",
            datetime(2025, 1, 1), datetime(2025, 1, 2),
        )
        assert isinstance(data, list)

    def test_historical_data_fifteen_minute_interval(self, adapter: _TestBrokerAdapter) -> None:
        """get_historical_data with '15m' interval."""
        from datetime import datetime
        data = adapter.get_historical_data(
            "BANKNIFTY", Exchange.NFO, "15m",
            datetime(2025, 1, 1), datetime(2025, 1, 7),
        )
        assert isinstance(data, list)

    def test_historical_data_daily_interval(self, adapter: _TestBrokerAdapter) -> None:
        """get_historical_data with '1d' interval."""
        from datetime import datetime
        data = adapter.get_historical_data(
            "FINNIFTY", Exchange.NFO, "1d",
            datetime(2025, 1, 1), datetime(2025, 1, 31),
        )
        assert isinstance(data, list)

    def test_option_chain_with_expiry_filter(self, adapter: _TestBrokerAdapter) -> None:
        """get_option_chain with expiry filter."""
        chain = adapter.get_option_chain("NIFTY", expiry="2025-01-30")
        assert isinstance(chain, list)

    def test_option_chain_with_strike_filter(self, adapter: _TestBrokerAdapter) -> None:
        """get_option_chain with strike and type filter."""
        chain = adapter.get_option_chain("NIFTY", strike=18500.0, option_type="PE")
        assert isinstance(chain, list)


class TestConcurrencySafety:
    """Verify the test adapter handles concurrent access without crashes."""

    def test_concurrent_place_and_query_orders(self) -> None:
        """Concurrent order placement and querying should not raise."""
        import threading

        adapter = _TestBrokerAdapter()
        errors: list[Exception] = []

        def place_orders() -> None:
            for i in range(10):
                try:
                    req = BrokerOrderRequest(
                        symbol=f"NIFTY{i}", exchange=Exchange.NFO,
                        transaction_type="BUY", quantity=75, order_type=OrderType.MARKET,
                    )
                    adapter.place_order(req)
                except Exception as e:
                    errors.append(e)

        def query_orders() -> None:
            for _ in range(10):
                try:
                    adapter.get_order_history()
                    adapter.get_order_status("test_001")
                except Exception as e:
                    errors.append(e)

        threads = [
            threading.Thread(target=place_orders),
            threading.Thread(target=query_orders),
            threading.Thread(target=place_orders),
            threading.Thread(target=query_orders),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert len(errors) == 0, f"Concurrency errors: {errors}"

    def test_concurrent_position_and_trade_queries(self) -> None:
        """Concurrent position/trade/margin queries should not raise."""
        import threading

        adapter = _TestBrokerAdapter()
        errors: list[Exception] = []

        def query_all() -> None:
            for _ in range(5):
                try:
                    adapter.get_positions()
                    adapter.get_position("NIFTY")
                    adapter.get_trades()
                    adapter.get_margin()
                    adapter.get_balance()
                    adapter.health_check()
                    adapter.ping()
                    adapter.is_rate_limited()
                except Exception as e:
                    errors.append(e)

        threads = [threading.Thread(target=query_all) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert len(errors) == 0, f"Concurrency errors: {errors}"
