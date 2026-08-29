"""Tests for core/positions/bridge.py — Position type converter.

Tests the conversion from trader position types to domain model types
for portfolio aggregation across asset classes.
"""

from __future__ import annotations

from typing import Any

from core.positions.bridge import (
    _current_price,
    _parse_expiry,
    commodity_trade_to_domain,
    currency_trade_to_domain,
    equity_trade_to_domain,
    futures_trade_to_domain,
    wire_trader_positions_to_aggregator,
)

# ── Mock trader position helpers ──────────────────────────────────────────────


class MockTradePos:
    """Simulates a CommodityTradePosition / CurrencyTradePosition / FuturesPosition."""

    def __init__(
        self,
        symbol: str,
        direction: str,
        qty: int,
        entry_price: float,
        current_price: float | None = None,
        margin_used: float = 1000.0,
        expiry: str = "2026-09-26",
    ) -> None:
        self.symbol = symbol
        self.direction = direction
        self.qty = qty
        self.entry_price = entry_price
        self.current_price = current_price or entry_price
        self.margin_used = margin_used
        self.expiry = expiry


def make_mock_trade_pos(**kw: Any) -> Any:
    """Convenience factory for a mock position with defaults."""
    defaults = dict(symbol="GOLD", direction="BUY", qty=10, entry_price=100.0, current_price=105.0, margin_used=1000.0, expiry="2026-09-26")
    defaults.update(kw)
    return MockTradePos(**defaults)


# ── Helpers ────────────────────────────────────────────────────────────────────


class TestCurrentPrice:
    """Tests for the _current_price helper."""

    def test_has_current_price(self) -> None:
        pos = MockTradePos(symbol="X", direction="BUY", qty=1, entry_price=100.0, current_price=105.0)
        assert _current_price(pos) == 105.0

    def test_no_current_price_falls_to_entry(self) -> None:
        pos = MockTradePos(symbol="X", direction="BUY", qty=1, entry_price=100.0)
        # Remove current_price attribute
        del pos.current_price  # type: ignore[attr-defined]
        assert _current_price(pos) == 100.0

    def test_zero_current_price_falls_to_entry(self) -> None:
        pos = MockTradePos(symbol="X", direction="BUY", qty=1, entry_price=100.0, current_price=0.0)
        assert _current_price(pos) == 100.0

    def test_negative_current_price(self) -> None:
        pos = MockTradePos(symbol="X", direction="BUY", qty=1, entry_price=100.0, current_price=-5.0)
        assert _current_price(pos) == -5.0


class TestParseExpiry:
    """Tests for the _parse_expiry helper."""

    def test_valid_iso_date(self) -> None:
        d = _parse_expiry("2026-09-26")
        assert d.year == 2026
        assert d.month == 9
        assert d.day == 26

    def test_empty_string_falls_back(self) -> None:
        d = _parse_expiry("")
        assert d.year >= 2026

    def test_invalid_string_falls_back(self) -> None:
        from datetime import date
        d = _parse_expiry("not-a-date")
        assert d <= date.today()

    def test_partial_date(self) -> None:
        # Partial dates like "2026-10" work in Python 3.11+ (returns 2026-10-10)
        # but raise ValueError in Python 3.10 (falls back to today).
        # Only verify the year is reasonable.
        d = _parse_expiry("2026-10")
        assert d.year >= 2026


# ── Commodity bridge ──────────────────────────────────────────────────────────


class TestCommodityTradeToDomain:
    """Tests for commodity_trade_to_domain."""

    def test_buy_position(self) -> None:
        pos = make_mock_trade_pos(symbol="GOLD", direction="BUY", qty=10, entry_price=100.0, current_price=105.0)
        result = commodity_trade_to_domain({"GOLD": pos})
        assert len(result) == 1
        cp = result[0]
        assert cp.quantity == 10  # positive for BUY
        assert cp.average_price == 100.0
        assert cp.current_price == 105.0
        assert cp.margin_used == 1000.0

    def test_sell_position(self) -> None:
        pos = make_mock_trade_pos(symbol="SILVER", direction="SELL", qty=5, entry_price=200.0, current_price=195.0)
        result = commodity_trade_to_domain({"SILVER": pos})
        assert len(result) == 1
        cp = result[0]
        assert cp.quantity == -5  # negative for SELL
        assert cp.average_price == 200.0
        assert cp.current_price == 195.0

    def test_unrealized_pnl_long_profit(self) -> None:
        pos = make_mock_trade_pos(symbol="GOLD", direction="BUY", qty=10, entry_price=100.0, current_price=110.0)
        cp = commodity_trade_to_domain({"GOLD": pos})[0]
        # (110 - 100) * 10 * 1 = 100
        assert cp.unrealized_pnl == 100.0

    def test_unrealized_pnl_long_loss(self) -> None:
        pos = make_mock_trade_pos(symbol="GOLD", direction="BUY", qty=5, entry_price=100.0, current_price=90.0)
        cp = commodity_trade_to_domain({"GOLD": pos})[0]
        # (90 - 100) * 5 * 1 = -50
        assert cp.unrealized_pnl == -50.0

    def test_unrealized_pnl_short_profit(self) -> None:
        """SELL position with price down → PnL positive (direction-aware bridge)."""
        pos = make_mock_trade_pos(symbol="SILVER", direction="SELL", qty=5, entry_price=200.0, current_price=180.0)
        cp = commodity_trade_to_domain({"SILVER": pos})[0]
        # (180 - 200) * 5 * -1 = 100 (short profit when price drops)
        assert cp.unrealized_pnl == 100.0

    def test_empty_dict(self) -> None:
        assert commodity_trade_to_domain({}) == []

    def test_multiple_positions(self) -> None:
        pos1 = make_mock_trade_pos(symbol="GOLD", direction="BUY", qty=10, entry_price=100.0)
        pos2 = make_mock_trade_pos(symbol="SILVER", direction="SELL", qty=5, entry_price=200.0)
        result = commodity_trade_to_domain({"GOLD": pos1, "SILVER": pos2})
        assert len(result) == 2


# ── Currency bridge ───────────────────────────────────────────────────────────


class TestCurrencyTradeToDomain:
    """Tests for currency_trade_to_domain."""

    def test_buy_usdinr(self) -> None:
        pos = make_mock_trade_pos(symbol="USDINR", direction="BUY", qty=1000, entry_price=83.50, current_price=83.75)
        result = currency_trade_to_domain({"USDINR": pos})
        assert len(result) == 1
        cp = result[0]
        assert cp.quantity == 1000
        assert cp.average_price == 83.50
        assert cp.current_price == 83.75

    def test_sell_eurinr(self) -> None:
        pos = make_mock_trade_pos(symbol="EURINR", direction="SELL", qty=500, entry_price=91.20, current_price=91.00)
        result = currency_trade_to_domain({"EURINR": pos})
        assert len(result) == 1
        assert result[0].quantity == -500

    def test_all_currency_pairs(self) -> None:
        pairs = ["USDINR", "EURINR", "GBPINR", "JPYINR"]
        positions = {p: make_mock_trade_pos(symbol=p, direction="BUY", qty=100) for p in pairs}
        result = currency_trade_to_domain(positions)
        assert len(result) == 4

    def test_unknown_pair_defaults(self) -> None:
        pos = make_mock_trade_pos(symbol="AUDINR", direction="BUY", qty=100, entry_price=55.0)
        result = currency_trade_to_domain({"AUDINR": pos})
        assert len(result) == 1

    def test_empty_dict(self) -> None:
        assert currency_trade_to_domain({}) == []


# ── Futures bridge ────────────────────────────────────────────────────────────


class TestFuturesTradeToDomain:
    """Tests for futures_trade_to_domain."""

    def test_buy_future(self) -> None:
        pos = make_mock_trade_pos(symbol="NIFTY", direction="BUY", qty=50, entry_price=24500.0, current_price=24600.0)
        result = futures_trade_to_domain({"NIFTY": pos})
        assert len(result) == 1
        fp = result[0]
        assert fp.quantity == 50
        assert fp.average_price == 24500.0
        assert fp.current_price == 24600.0

    def test_sell_future(self) -> None:
        pos = make_mock_trade_pos(symbol="BANKNIFTY", direction="SELL", qty=15, entry_price=51000.0, current_price=50800.0)
        result = futures_trade_to_domain({"BANKNIFTY": pos})
        assert len(result) == 1
        assert result[0].quantity == -15

    def test_empty_dict(self) -> None:
        assert futures_trade_to_domain({}) == []

    def test_multiple_futures(self) -> None:
        pos1 = make_mock_trade_pos(symbol="NIFTY", direction="BUY", qty=50, entry_price=24500.0)
        pos2 = make_mock_trade_pos(symbol="BANKNIFTY", direction="SELL", qty=15, entry_price=51000.0)
        result = futures_trade_to_domain({"NIFTY": pos1, "BANKNIFTY": pos2})
        assert len(result) == 2


# ── Wire positions ────────────────────────────────────────────────────────────


class TestWireTraderPositionsToAggregator:
    """Tests for wire_trader_positions_to_aggregator."""

    def test_all_traders_present(self) -> None:
        ct_pos = {"GOLD": make_mock_trade_pos(symbol="GOLD", direction="BUY", qty=10)}
        cct_pos = {"USDINR": make_mock_trade_pos(symbol="USDINR", direction="BUY", qty=1000)}
        ft_pos = {"NIFTY": make_mock_trade_pos(symbol="NIFTY", direction="BUY", qty=50)}
        et_pos = {
            "RELIANCE": {
                "direction": "BUY", "qty": 10, "entry_price": 2500.0,
                "entry_time": 1000.0, "score": 80, "asset_class": "EQUITY",
            },
        }

        class MockTrader:
            def __init__(self, positions: dict) -> None:
                self.positions = positions

        refs = {
            "commodity_trader": MockTrader(ct_pos),
            "currency_trader": MockTrader(cct_pos),
            "futures_trader": MockTrader(ft_pos),
            "equity_trader": MockTrader(et_pos),
        }

        result = wire_trader_positions_to_aggregator(refs)
        assert "commodity_positions" in result
        assert len(result["commodity_positions"]) == 1
        assert "currency_positions" in result
        assert len(result["currency_positions"]) == 1
        assert "fo_futures" in result
        assert len(result["fo_futures"]) == 1
        assert "equity_positions" in result
        assert len(result["equity_positions"]) == 1

    def test_no_traders(self) -> None:
        result = wire_trader_positions_to_aggregator({})
        assert result == {}

    def test_trader_without_positions(self) -> None:
        class TraderNoPos:
            pass

        refs = {"commodity_trader": TraderNoPos()}
        result = wire_trader_positions_to_aggregator(refs)
        assert result == {}

    def test_with_equity_trader(self) -> None:
        et_pos = {
            "RELIANCE": {
                "direction": "BUY", "qty": 10, "entry_price": 2500.0,
                "entry_time": 1000.0, "score": 80, "asset_class": "EQUITY",
            },
        }

        class MockTrader:
            def __init__(self, positions: dict) -> None:
                self.positions = positions

        refs = {
            "commodity_trader": MockTrader({}),
            "currency_trader": MockTrader({}),
            "futures_trader": MockTrader({}),
            "equity_trader": MockTrader(et_pos),
        }
        result = wire_trader_positions_to_aggregator(refs)
        assert "equity_positions" in result
        assert len(result["equity_positions"]) == 1
        assert result["equity_positions"][0].stock.symbol == "RELIANCE"

    def test_empty_positions(self) -> None:
        class MockTrader:
            def __init__(self) -> None:
                self.positions = {}

        refs = {
            "commodity_trader": MockTrader(),
            "currency_trader": MockTrader(),
            "futures_trader": MockTrader(),
            "equity_trader": MockTrader(),
        }
        result = wire_trader_positions_to_aggregator(refs)
        # Each trader with empty positions returns an empty list
        assert "commodity_positions" in result
        assert result["commodity_positions"] == []
        assert "equity_positions" in result
        assert result["equity_positions"] == []


# ── Equity bridge ────────────────────────────────────────────────────────────


class TestEquityTradeToDomain:
    """Tests for equity_trade_to_domain (dict-based position conversion)."""

    def test_buy_position(self) -> None:
        pos_dict = {
            "RELIANCE": {
                "direction": "BUY",
                "qty": 10,
                "entry_price": 2500.0,
                "entry_time": 1000.0,
                "score": 80,
                "reason": "signal",
                "peak_price": 2500.0,
                "asset_class": "EQUITY",
            }
        }
        result = equity_trade_to_domain(pos_dict)
        assert len(result) == 1
        ep = result[0]
        assert ep.quantity == 10  # positive for BUY
        assert ep.average_price == 2500.0
        assert ep.stock.symbol == "RELIANCE"

    def test_sell_position(self) -> None:
        pos_dict = {
            "TCS": {
                "direction": "SELL",
                "qty": 5,
                "entry_price": 3500.0,
                "entry_time": 1000.0,
                "score": 75,
                "reason": "bearish",
                "peak_price": 3500.0,
                "asset_class": "EQUITY",
            }
        }
        result = equity_trade_to_domain(pos_dict)
        assert len(result) == 1
        ep = result[0]
        assert ep.quantity == -5  # negative for SELL

    def test_unrealized_pnl_long_profit(self) -> None:
        pos_dict = {
            "HDFCBANK": {
                "direction": "BUY",
                "qty": 10,
                "entry_price": 1600.0,
                "entry_time": 1000.0,
                "score": 80,
                "asset_class": "EQUITY",
            }
        }
        ep = equity_trade_to_domain(pos_dict)[0]
        # current_price defaults to entry_price since not stored in dict
        # PnL = (entry - entry) * qty = 0
        assert ep.unrealized_pnl == 0.0

    def test_empty_dict(self) -> None:
        assert equity_trade_to_domain({}) == []

    def test_multiple_positions(self) -> None:
        pos_dict = {
            "RELIANCE": {
                "direction": "BUY", "qty": 10, "entry_price": 2500.0,
                "entry_time": 1000.0, "score": 80, "asset_class": "EQUITY",
            },
            "TCS": {
                "direction": "SELL", "qty": 5, "entry_price": 3500.0,
                "entry_time": 1000.0, "score": 75, "asset_class": "EQUITY",
            },
        }
        result = equity_trade_to_domain(pos_dict)
        assert len(result) == 2

    def test_zero_entry_price_skipped(self) -> None:
        pos_dict = {
            "BAD": {
                "direction": "BUY", "qty": 10, "entry_price": 0.0,
                "entry_time": 1000.0, "score": 80, "asset_class": "EQUITY",
            },
        }
        result = equity_trade_to_domain(pos_dict)
        assert len(result) == 0  # skipped due to zero entry_price


# ── Domain model validation (integration) ─────────────────────────────────────


class TestDomainModelValidation:
    """Verify bridge output passes domain model __post_init__ validation."""

    def test_commodity_position_passes_validation(self) -> None:
        pos = make_mock_trade_pos(symbol="GOLD", direction="BUY", qty=10, entry_price=100.0, current_price=105.0)
        result = commodity_trade_to_domain({"GOLD": pos})
        cp = result[0]
        # __post_init__ requires average_price > 0 and current_price > 0
        assert cp.average_price > 0
        assert cp.current_price > 0
        # Also verify contract has valid last_price (default 0 passes)
        assert cp.contract.last_price == 0.0

    def test_future_position_passes_validation(self) -> None:
        pos = make_mock_trade_pos(symbol="NIFTY", direction="BUY", qty=50, entry_price=24500.0, current_price=24600.0)
        result = futures_trade_to_domain({"NIFTY": pos})
        fp = result[0]
        assert fp.average_price > 0
        assert fp.current_price > 0

    def test_currency_position_passes_validation(self) -> None:
        pos = make_mock_trade_pos(symbol="USDINR", direction="BUY", qty=1000, entry_price=83.50, current_price=83.75)
        result = currency_trade_to_domain({"USDINR": pos})
        cp = result[0]
        assert cp.average_price > 0
        assert cp.current_price > 0
