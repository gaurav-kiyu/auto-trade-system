"""Tests for core.live_option_quotes - live option bid/ask/OI/volume fetch.

Covers:
- build_option_symbol(): monthly and weekly Kite NFO tradingsymbol format
- fetch_live_option_quote(): real-effect + fail-open paths
"""
from __future__ import annotations

import datetime
from unittest.mock import MagicMock, patch

from core.live_option_quotes import build_option_symbol, fetch_live_option_quote


class TestBuildOptionSymbol:
    def test_monthly_call_symbol(self):
        symbol = build_option_symbol("NIFTY", datetime.date(2024, 12, 26), 23500, "CE", is_weekly=False)
        assert symbol == "NIFTY24DEC23500CE"

    def test_monthly_put_symbol(self):
        symbol = build_option_symbol("NIFTY", datetime.date(2024, 12, 26), 23500, "PE", is_weekly=False)
        assert symbol == "NIFTY24DEC23500PE"

    def test_weekly_symbol_uses_single_letter_month_code(self):
        # Dec 5 2024, weekly expiry -> month code "D", day "05"
        symbol = build_option_symbol("NIFTY", datetime.date(2024, 12, 5), 23500, "CE", is_weekly=True)
        assert symbol == "NIFTY24D0523500CE"

    def test_weekly_symbol_single_digit_month(self):
        # March (month 3) weekly -> month code "3"
        symbol = build_option_symbol("BANKNIFTY", datetime.date(2024, 3, 7), 48000, "PE", is_weekly=True)
        assert symbol == "BANKNIFTY2430748000PE"

    def test_accepts_call_put_aliases(self):
        assert build_option_symbol("NIFTY", datetime.date(2024, 12, 26), 23500, "CALL", is_weekly=False) == "NIFTY24DEC23500CE"
        assert build_option_symbol("NIFTY", datetime.date(2024, 12, 26), 23500, "PUT", is_weekly=False) == "NIFTY24DEC23500PE"

    def test_strike_has_no_decimal_point(self):
        symbol = build_option_symbol("NIFTY", datetime.date(2024, 12, 26), 23500, "CE", is_weekly=False)
        assert "." not in symbol


class TestFetchLiveOptionQuote:
    def test_none_broker_adapter_returns_none(self):
        assert fetch_live_option_quote(None, "NIFTY", 23500, "CE") is None

    def test_adapter_without_get_quote_returns_none(self):
        assert fetch_live_option_quote(object(), "NIFTY", 23500, "CE") is None

    def test_real_effect_with_explicit_expiry(self):
        mock_broker = MagicMock()
        mock_quote = MagicMock(bid=150.5, ask=151.0, last=150.75, volume=12000, oi=450000)
        mock_broker.get_quote.return_value = mock_quote
        result = fetch_live_option_quote(
            mock_broker, "NIFTY", 23500, "CE",
            expiry_date=datetime.date(2024, 12, 26), is_weekly=False,
        )
        assert result is not None
        assert result["symbol"] == "NIFTY24DEC23500CE"
        assert result["bid"] == 150.5
        assert result["ask"] == 151.0
        assert result["oi"] == 450000
        mock_broker.get_quote.assert_called_once_with("NIFTY24DEC23500CE", exchange="NFO")

    def test_adapter_rejecting_exchange_kwarg_fails_open(self):
        mock_broker = MagicMock()
        mock_broker.get_quote.side_effect = TypeError("get_quote() got an unexpected keyword argument 'exchange'")
        result = fetch_live_option_quote(
            mock_broker, "NIFTY", 23500, "CE",
            expiry_date=datetime.date(2024, 12, 26), is_weekly=False,
        )
        assert result is None

    def test_broker_exception_fails_open(self):
        mock_broker = MagicMock()
        mock_broker.get_quote.side_effect = RuntimeError("Cannot resolve instrument token")
        result = fetch_live_option_quote(
            mock_broker, "NIFTY", 23500, "CE",
            expiry_date=datetime.date(2024, 12, 26), is_weekly=False,
        )
        assert result is None

    def test_uses_calendar_engine_when_expiry_omitted(self):
        mock_broker = MagicMock()
        mock_quote = MagicMock(bid=100.0, ask=101.0, last=100.5, volume=5000, oi=10000)
        mock_broker.get_quote.return_value = mock_quote
        mock_record = MagicMock(expiry_date=datetime.date(2024, 12, 26), is_weekly=False)
        with patch("core.exchange_calendar_engine.get_calendar_engine") as mock_get_engine:
            mock_get_engine.return_value.get_next_expiry.return_value = mock_record
            result = fetch_live_option_quote(mock_broker, "NIFTY", 23500, "CE")
        assert result is not None
        assert result["symbol"] == "NIFTY24DEC23500CE"

    def test_calendar_engine_returning_none_fails_open(self):
        mock_broker = MagicMock()
        with patch("core.exchange_calendar_engine.get_calendar_engine") as mock_get_engine:
            mock_get_engine.return_value.get_next_expiry.return_value = None
            result = fetch_live_option_quote(mock_broker, "NIFTY", 23500, "CE")
        assert result is None
