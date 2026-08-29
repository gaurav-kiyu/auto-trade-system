"""Unit tests for core.datetime_ist."""

from __future__ import annotations

import datetime

from core.datetime_ist import (
    IST_OFFSET,
    apply_nse_session_from_cfg,
    configure_nse_cash_session,
    format_weekday_bias_str,
    is_nse_cash_session,
    is_nse_continuous_trading_window,
    is_nse_post_open_no_trade_zone,
    mins_until_nse_cash_close,
    now_ist,
    nse_close_safety_start_time,
)


def test_now_ist_naive_and_reasonable():
    t = now_ist()
    assert t.tzinfo is None
    utc = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    delta = abs((t - (utc + IST_OFFSET)).total_seconds())
    assert delta < 2.0


def test_format_weekday_bias_str():
    assert "Monday" in format_weekday_bias_str({"Monday": 0.9, "Friday": 1.0})
    assert "(invalid)" in format_weekday_bias_str(None)


def test_is_nse_cash_session_weekday_window():
    mon_10 = datetime.datetime(2026, 4, 13, 10, 0, 0)
    assert is_nse_cash_session(mon_10) is True
    mon_9 = datetime.datetime(2026, 4, 13, 9, 14, 0)
    assert is_nse_cash_session(mon_9) is False
    mon_1530 = datetime.datetime(2026, 4, 13, 15, 21, 0)
    assert is_nse_cash_session(mon_1530) is False


def test_is_nse_cash_session_weekend():
    sat = datetime.datetime(2026, 4, 18, 10, 0, 0)
    assert is_nse_cash_session(sat) is False


def test_configure_nse_cash_session_custom_bounds():
    try:
        configure_nse_cash_session((10, 0), (10, 30))
        mon = datetime.datetime(2026, 4, 13, 10, 15, 0)
        assert is_nse_cash_session(mon) is True
        mon_early = datetime.datetime(2026, 4, 13, 9, 45, 0)
        assert is_nse_cash_session(mon_early) is False
    finally:
        apply_nse_session_from_cfg({})


def test_is_nse_continuous_trading_window_default():
    t_ok = datetime.time(10, 0)
    assert is_nse_continuous_trading_window(t_ok) is True
    assert is_nse_continuous_trading_window(datetime.time(9, 19)) is False


def test_nse_close_safety_start_time():
    assert nse_close_safety_start_time(10) == datetime.time(15, 10)


def test_is_nse_post_open_no_trade_zone_default():
    assert is_nse_post_open_no_trade_zone(datetime.time(9, 20)) is True
    assert is_nse_post_open_no_trade_zone(datetime.time(9, 26)) is False


def test_apply_nse_session_from_cfg_minimal_dict():
    try:
        apply_nse_session_from_cfg(
            {
                "NSE_CASH_SESSION_START_HOUR": 10,
                "NSE_CASH_SESSION_START_MINUTE": 0,
                "NSE_CASH_SESSION_END_HOUR": 11,
                "NSE_CASH_SESSION_END_MINUTE": 0,
            }
        )
        assert is_nse_cash_session(datetime.datetime(2026, 4, 13, 10, 30, 0)) is True
        assert mins_until_nse_cash_close(datetime.datetime(2026, 4, 13, 10, 45, 0)) == 15.0
    finally:
        apply_nse_session_from_cfg({})
