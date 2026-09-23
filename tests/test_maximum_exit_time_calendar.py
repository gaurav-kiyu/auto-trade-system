"""Tests for Maximum Exit Time Canonical Rules and Calendar Calculations.

Verifies:
- Intraday & Options: Same-day 15:15 IST (during market hours), rolled to next trading day if weekend or post-15:15.
- Commodities (MCX): +3 trading sessions at 23:30 IST (skipping weekends and statutory holidays).
- Currencies (CDS): +2 trading sessions at 17:00 IST (skipping weekends).
- Equities (Positional): +5 trading sessions at 15:30 IST (skipping weekends).
- Tests across:
  1. Normal trading day (Tuesday)
  2. Friday session (before and after close)
  3. Weekend signal (Saturday/Sunday)
  4. Statutory holiday (Gandhi Jayanti 02-Oct-2026)
  5. Weekly Expiry day (Thursday)
  6. Signal near market close (15:10 vs 15:20 IST)
"""

import pytest
from core.notifications.rich_signal_formatter import RichSignalFormatter


def test_normal_day_intraday_options():
    """Normal Tuesday 10:22 IST signal -> Same-day 15:15 IST."""
    info = RichSignalFormatter.get_holding_horizon_info(
        category="INDEX_OPTIONS",
        timestamp_str="2026-09-22 10:22:48",
    )
    assert info["is_intraday"] is True
    assert info["valid_from"] == "22 Sep 2026, 10:22:48 IST"
    assert info["valid_until"] == "22 Sep 2026, 15:15 IST"
    assert info["holding_period"] == "Intraday — same-day exit"


def test_signal_near_market_close_before_cutoff():
    """Signal at 15:10 IST (before 15:15 auto square-off cutoff) -> Same-day 15:15 IST."""
    info = RichSignalFormatter.get_holding_horizon_info(
        category="INDEX_OPTIONS",
        timestamp_str="2026-09-22 15:10:00",
    )
    assert info["valid_until"] == "22 Sep 2026, 15:15 IST"


def test_signal_near_market_close_after_cutoff():
    """Signal at 15:20 IST (after 15:15 auto square-off) -> Rolls to next trading day (Wednesday) 15:15 IST."""
    info = RichSignalFormatter.get_holding_horizon_info(
        category="INDEX_OPTIONS",
        timestamp_str="2026-09-22 15:20:00",
    )
    assert info["valid_until"] == "23 Sep 2026, 15:15 IST"


def test_friday_session_and_weekend_rollover():
    """Friday post-cutoff signal (16:00 IST) and weekend signals roll to Monday."""
    # Friday post-cutoff
    info_fri = RichSignalFormatter.get_holding_horizon_info(
        category="INDEX_OPTIONS",
        timestamp_str="2026-09-25 16:00:00",  # 25 Sep 2026 is Friday
    )
    assert info_fri["valid_until"] == "28 Sep 2026, 15:15 IST"  # 28 Sep 2026 is Monday

    # Saturday signal
    info_sat = RichSignalFormatter.get_holding_horizon_info(
        category="INDEX_OPTIONS",
        timestamp_str="2026-09-26 11:00:00",  # Saturday
    )
    assert info_sat["valid_until"] == "28 Sep 2026, 15:15 IST"  # Monday


def test_statutory_holiday_rollover():
    """Signal before Gandhi Jayanti (02-Oct-2026 Friday holiday) skips Friday and weekend."""
    # 01-Oct-2026 (Thursday) after cutoff:
    # Next trading day skips 02-Oct (Holiday) and 03/04-Oct (Weekend) -> Monday 05-Oct-2026!
    info = RichSignalFormatter.get_holding_horizon_info(
        category="INDEX_OPTIONS",
        timestamp_str="2026-10-01 16:30:00",
    )
    assert info["valid_until"] == "05 Oct 2026, 15:15 IST"


def test_commodities_mcx_3_trading_sessions():
    """MCX Commodity swing adds 3 trading days and sets 23:30 IST exit."""
    # Wednesday 23-Sep-2026 -> +3 trading days (Thu 24, Fri 25, Mon 28 Sep)
    info = RichSignalFormatter.get_holding_horizon_info(
        category="COMMODITIES",
        timestamp_str="2026-09-23 10:00:00",
    )
    assert info["is_intraday"] is False
    assert info["valid_until"] == "28 Sep 2026, 23:30 IST"


def test_currencies_cds_2_trading_sessions():
    """Currency derivatives add 2 trading days and set 17:00 IST exit."""
    # Friday 25-Sep-2026 -> +2 trading days (Mon 28, Tue 29 Sep)
    info = RichSignalFormatter.get_holding_horizon_info(
        category="CURRENCIES",
        timestamp_str="2026-09-25 10:00:00",
    )
    assert info["valid_until"] == "29 Sep 2026, 17:00 IST"


def test_equities_positional_5_trading_sessions():
    """Equities add 5 trading days and set 15:30 IST exit."""
    # Monday 21-Sep-2026 -> +5 trading days (Tue 22, Wed 23, Thu 24, Fri 25, Mon 28 Sep)
    info = RichSignalFormatter.get_holding_horizon_info(
        category="NSE_EQUITY",
        timestamp_str="2026-09-21 10:00:00",
    )
    assert info["valid_until"] == "28 Sep 2026, 15:30 IST"


def test_expiry_day_intraday_options():
    """Thursday Weekly Expiry generated at 11:00 IST expires at 15:15 IST same day."""
    # 24-Sep-2026 is Thursday (Nifty weekly expiry)
    info = RichSignalFormatter.get_holding_horizon_info(
        category="WEEKLY_EXPIRY_SPECIAL",
        timestamp_str="2026-09-24 11:00:00",
    )
    assert info["valid_until"] == "24 Sep 2026, 15:15 IST"
