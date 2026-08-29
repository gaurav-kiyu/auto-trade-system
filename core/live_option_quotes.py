"""Live option quote feed (config key live_option_quotes_enabled, opt-in,
default OFF).

Fetches a REAL bid/ask/OI/volume quote for the option contract a signal
actually intends to trade, instead of leaving liquidity_guard.py permanently
failing open and strike_selector.py's chosen strike unpriced. Built on top
of two existing, real building blocks:

- core.exchange_calendar_engine.get_calendar_engine() for the real expiry
  date (weekly vs monthly).
- infrastructure.adapters.brokers.kite.adapter.KiteBrokerAdapter.get_quote()
  for the actual bid/ask/last/volume/oi (now exchange-aware - see that
  module's per-exchange instrument cache fix).

IMPORTANT - the NFO tradingsymbol format built here (build_option_symbol())
follows Zerodha's publicly documented convention (monthly:
"{SYMBOL}{YY}{MMM}{STRIKE}{CE/PE}", weekly: "{SYMBOL}{YY}{M}{DD}{STRIKE}
{CE/PE}" with a single-letter month code), but has NOT been validated
against a live Kite account/instruments dump in this session - NSE's own
option-chain contract conventions (which indices still have monthly
contracts, weekly expiry weekday per index) have changed over time via NSE
circulars. Treat the first few real fetches as a validation pass: compare
the resolved symbol/quote against your Kite account's own option chain
before trusting this for real position decisions.
"""
from __future__ import annotations

import datetime
import logging
from typing import Any

from core.datetime_ist import now_ist

_log = logging.getLogger(__name__)

_MONTH_ABBR = {
    1: "JAN", 2: "FEB", 3: "MAR", 4: "APR", 5: "MAY", 6: "JUN",
    7: "JUL", 8: "AUG", 9: "SEP", 10: "OCT", 11: "NOV", 12: "DEC",
}
# Kite's single-character weekly-expiry month code: 1-9 for Jan-Sep, then O/N/D.
_WEEKLY_MONTH_CODE = {
    1: "1", 2: "2", 3: "3", 4: "4", 5: "5", 6: "6", 7: "7", 8: "8", 9: "9",
    10: "O", 11: "N", 12: "D",
}


def build_option_symbol(
    index_name: str,
    expiry_date: datetime.date,
    strike: int,
    option_type: str,
    is_weekly: bool,
) -> str:
    """Build a Kite NFO tradingsymbol for an index option contract.

    Args:
        index_name: e.g. "NIFTY", "BANKNIFTY".
        expiry_date: The contract's real expiry date.
        strike: Strike price (integer - Kite tradingsymbols carry no decimals).
        option_type: "CE" or "PE" (also accepts "CALL"/"PUT").
        is_weekly: True for a weekly (non-monthly) expiry contract.

    """
    opt = "CE" if str(option_type).upper() in ("CE", "CALL") else "PE"
    yy = expiry_date.strftime("%y")
    if is_weekly:
        month_code = _WEEKLY_MONTH_CODE[expiry_date.month]
        return f"{index_name.upper()}{yy}{month_code}{expiry_date.day:02d}{int(strike)}{opt}"
    month_abbr = _MONTH_ABBR[expiry_date.month]
    return f"{index_name.upper()}{yy}{month_abbr}{int(strike)}{opt}"


def fetch_live_option_quote(
    broker_adapter: Any,
    index_name: str,
    strike: int,
    option_type: str,
    cfg: dict[str, Any] | None = None,
    expiry_date: datetime.date | None = None,
    is_weekly: bool | None = None,
) -> dict[str, Any] | None:
    """Fetch a real bid/ask/last/volume/oi quote for an index option leg.

    Args:
        expiry_date, is_weekly: Both optional. When either is omitted, the
            real expiry (and whether it's weekly vs monthly) is resolved via
            core.exchange_calendar_engine.get_calendar_engine() - pass both
            explicitly only if a caller already knows the exact contract
            (e.g. re-querying a position's own stored expiry).

    Returns a plain dict (bid/ask/last/volume/oi/symbol) suitable for
    merging straight into a signal dict, or None on any failure (fail-open
    - callers must keep working exactly as before when this returns None).
    """
    if broker_adapter is None or not hasattr(broker_adapter, "get_quote"):
        return None
    try:
        if expiry_date is None or is_weekly is None:
            from core.exchange_calendar_engine import get_calendar_engine
            record = get_calendar_engine(cfg).get_next_expiry(index_name)
            if record is None:
                return None
            expiry_date = record.expiry_date
            is_weekly = record.is_weekly
        symbol = build_option_symbol(index_name, expiry_date, strike, option_type, is_weekly)
        try:
            quote = broker_adapter.get_quote(symbol, exchange="NFO")
        except TypeError:
            # Adapter's get_quote() doesn't accept an exchange kwarg at all
            # (a non-Kite, non-exchange-aware adapter) - fail open rather
            # than risk retrying without it and getting back a quote for
            # the wrong instrument.
            return None
        # A wrapped PaperBrokerAdapter (today's real default - see
        # core/adapters/broker_adapters.py::BrokerAdapter.get_quote()) has no
        # get_quote() on the port it wraps and raises AttributeError, caught
        # by the outer except below - fail open.
        return {
            "symbol": symbol,
            "bid": float(getattr(quote, "bid", 0.0) or 0.0),
            "ask": float(getattr(quote, "ask", 0.0) or 0.0),
            "last": float(getattr(quote, "last", 0.0) or 0.0),
            "volume": int(getattr(quote, "volume", 0) or 0),
            "oi": int(getattr(quote, "oi", 0) or 0),
            "fetched_at": now_ist().isoformat(),
        }
    except (ValueError, TypeError, KeyError, AttributeError, IndexError, OSError, RuntimeError) as exc:
        _log.debug("Live option quote fetch failed for %s %s %s: %s", index_name, strike, option_type, exc)
        return None


__all__ = ["build_option_symbol", "fetch_live_option_quote"]
