"""
IST DateTime Service - Provides IST timezone-aware datetime functions.
Eliminates datetime.now() usage throughout the codebase.
"""

from __future__ import annotations

import datetime
from typing import Optional, Tuple


# IST offset (UTC+5:30)
IST_OFFSET = datetime.timedelta(hours=5, minutes=30)

# Default NSE session times (IST) - these would normally come from config
_NSE_OPEN: Tuple[int, int] = (9, 15)      # 09:15
_NSE_CLOSE: Tuple[int, int] = (15, 20)    # 15:20
_NSE_CONTINUOUS_OPEN: Tuple[int, int] = (9, 20)  # 09:20
_NSE_SCHEDULE_CLOSED: Tuple[int, int] = (15, 30) # 15:30
_NSE_BLOCK_ENTRIES_FROM: Tuple[int, int] = (15, 0) # 15:00
_NSE_POST_OPEN_NO_TRADE_MINS: int = 10
_NSE_EARLY_SESSION_END: Tuple[int, int] = (10, 15) # 10:15


def now_ist() -> datetime.datetime:
    """
    Get current time in IST (Indian Standard Time) as naive datetime.

    Returns:
        Current IST time as naive datetime object (no timezone info)
    """
    return datetime.datetime.utcnow() + IST_OFFSET


def configure_nse_cash_session(
    open_hm: Tuple[int, int],
    close_hm: Tuple[int, int],
    *,
    continuous_open_hm: Optional[Tuple[int, int]] = None,
    schedule_closed_hm: Optional[Tuple[int, int]] = None,
    block_new_entries_from_hm: Optional[Tuple[int, int]] = None,
    post_open_no_trade_mins: Optional[int] = None,
    early_session_end_hm: Optional[Tuple[int, int]] = None,
) -> None:
    """
    Configure NSE session times from configuration.

    Args:
        open_hm: (hour, minute) for market open
        close_hm: (hour, minute) for market close
        continuous_open_hm: (hour, minute) for continuous trading window start
        schedule_closed_hm: (hour, minute) for scheduled close
        block_new_entries_from_hm: (hour, minute) to block new entries
        post_open_no_trade_mins: minutes after open when no trading allowed
        early_session_end_hm: (hour, minute) for early session end
    """
    global _NSE_OPEN, _NSE_CLOSE, _NSE_CONTINUOUS_OPEN, _NSE_SCHEDULE_CLOSED
    global _NSE_BLOCK_ENTRIES_FROM, _NSE_POST_OPEN_NO_TRADE_MINS, _NSE_EARLY_SESSION_END

    _NSE_OPEN = open_hm
    _NSE_CLOSE = close_hm
    if continuous_open_hm is not None:
        _NSE_CONTINUOUS_OPEN = continuous_open_hm
    if schedule_closed_hm is not None:
        _NSE_SCHEDULE_CLOSED = schedule_closed_hm
    if block_new_entries_from_hm is not None:
        _NSE_BLOCK_ENTRIES_FROM = block_new_entries_from_hm
    if post_open_no_trade_mins is not None:
        _NSE_POST_OPEN_NO_TRADE_MINS = post_open_no_trade_mins
    if early_session_end_hm is not None:
        _NSE_EARLY_SESSION_END = early_session_end_hm


def _hm_to_time(hm: Tuple[int, int]) -> datetime.time:
    """Convert (hour, minute) tuple to datetime.time object."""
    return datetime.time(hm[0], hm[1])


def nse_cash_open_time() -> datetime.time:
    """Get NSE cash market open time."""
    return _hm_to_time(_NSE_OPEN)


def nse_cash_close_time() -> datetime.time:
    """Get NSE cash market close time."""
    return _hm_to_time(_NSE_CLOSE)


def nse_continuous_trade_start_time() -> datetime.time:
    """Get NSE continuous trading window start time."""
    return _hm_to_time(_NSE_CONTINUOUS_OPEN)


def nse_schedule_closed_time() -> datetime.time:
    """Get NSE scheduled close time."""
    return _hm_to_time(_NSE_SCHEDULE_CLOSED)


def nse_block_new_entries_from_time() -> datetime.time:
    """Get time from which new entries are blocked."""
    return _hm_to_time(_NSE_BLOCK_ENTRIES_FROM)


def nse_early_session_end_time() -> datetime.time:
    """Get NSE early session end time."""
    return _hm_to_time(_NSE_EARLY_SESSION_END)


def apply_nse_session_from_cfg(config: dict) -> None:
    """
    Apply NSE session configuration from bot configuration.

    Expected config keys:
    - NSE_CASH_SESSION_START_HOUR, NSE_CASH_SESSION_START_MINUTE
    - NSE_CASH_SESSION_END_HOUR, NSE_CASH_SESSION_END_MINUTE
    - NSE_CONTINUOUS_TRADE_START_HOUR, NSE_CONTINUOUS_TRADE_START_MINUTE
    - NSE_MARKET_STATUS_CLOSED_HOUR, NSE_MARKET_STATUS_CLOSED_MINUTE
    - NSE_BLOCK_NEW_ENTRIES_FROM_HOUR, NSE_BLOCK_NEW_ENTRIES_FROM_MINUTE
    - NSE_POST_OPEN_NO_TRADE_MINUTES
    - NSE_EARLY_SESSION_END_HOUR, NSE_EARLY_SESSION_END_MINUTE
    """
    configure_nse_cash_session(
        open_hm=(
            config.get("NSE_CASH_SESSION_START_HOUR", 9),
            config.get("NSE_CASH_SESSION_START_MINUTE", 15)
        ),
        close_hm=(
            config.get("NSE_CASH_SESSION_END_HOUR", 15),
            config.get("NSE_CASH_SESSION_END_MINUTE", 20)
        ),
        continuous_open_hm=(
            config.get("NSE_CONTINUOUS_TRADE_START_HOUR", 9),
            config.get("NSE_CONTINUOUS_TRADE_START_MINUTE", 20)
        ),
        schedule_closed_hm=(
            config.get("NSE_MARKET_STATUS_CLOSED_HOUR", 15),
            config.get("NSE_MARKET_STATUS_CLOSED_MINUTE", 30)
        ),
        block_new_entries_from_hm=(
            config.get("NSE_BLOCK_NEW_ENTRIES_FROM_HOUR", 15),
            config.get("NSE_BLOCK_NEW_ENTRIES_FROM_MINUTE", 0)
        ),
        post_open_no_trade_mins=config.get("NSE_POST_OPEN_NO_TRADE_MINUTES", 10),
        early_session_end_hm=(
            config.get("NSE_EARLY_SESSION_END_HOUR", 10),
            config.get("NSE_EARLY_SESSION_END_MINUTE", 15)
        )
    )


def is_nse_continuous_trading_window() -> bool:
    """
    Check if current time is within NSE continuous trading window.

    Returns:
        True if within continuous trading window (09:20-15:20)
    """
    now = now_ist()
    current_time = now.time()

    start_time = nse_continuous_trade_start_time()
    end_time = nse_cash_close_time()

    return start_time <= current_time < end_time


def is_market_open() -> bool:
    """
    Check if market is currently open.

    Returns:
        True if market is open (09:15-15:20)
    """
    now = now_ist()
    current_time = now.time()

    # Check if it's a weekday
    if now.weekday() >= 5:  # Saturday=5, Sunday=6
        return False

    # Check if it's a holiday (simplified - would normally check holiday calendar)
    # For now, we'll just check time
    open_time = nse_cash_open_time()
    close_time = nse_cash_close_time()

    return open_time <= current_time < close_time


def mins_until_nse_cash_close(dt: Optional[datetime.datetime] = None) -> float:
    """
    Get minutes until NSE cash market close.

    Args:
        dt: Optional datetime to check (defaults to now)

    Returns:
        Minutes until market close (negative if market is closed)
    """
    if dt is None:
        dt = now_ist()

    close_time = datetime.datetime.combine(dt.date(), nse_cash_close_time())
    delta = close_time - dt
    return delta.total_seconds() / 60.0


def market_status() -> str:
    """
    Get current market status.

    Returns:
        One of: "PRE", "OPEN", "CLOSED", "WEEKEND", "HOLIDAY"
    """
    now = now_ist()

    # Check weekend
    if now.weekday() >= 5:
        return "WEEKEND"

    # Check time
    current_time = now.time()
    open_time = nse_cash_open_time()
    close_time = nse_cash_close_time()

    if current_time < open_time:
        return "PRE"
    elif current_time < close_time:
        return "OPEN"
    else:
        return "CLOSED"


def get_regime() -> str:
    """
    Get current market regime based on time of day.

    Returns:
        One of: "MORNING", "MIDDAY", "CLOSING"
    """
    now = now_ist()
    current_time = now.time()

    morning_end = datetime.time(10, 0)
    midday_end = datetime.time(14, 30)

    if current_time < morning_end:
        return "MORNING"
    elif current_time < midday_end:
        return "MIDDAY"
    else:
        return "CLOSING"


def time_risk_mult() -> float:
    """
    Get time-based risk multiplier.

    Returns:
        Risk multiplier based on time of day (higher risk in later hours)
    """
    now = now_ist()
    current_time = now.time()

    if current_time >= datetime.time(14, 0):  # 2:00 PM onwards
        return 0.50
    elif current_time >= datetime.time(13, 0):  # 1:00 PM onwards
        return 0.75
    else:
        return 1.0


def is_early_session() -> bool:
    """
    Check if currently in early session.

    Returns:
        True if in early session (09:15-10:15)
    """
    now = now_ist()
    current_time = now.time()

    start_time = nse_cash_open_time()
    end_time = nse_early_session_end_time()

    return start_time <= current_time < end_time


def format_weekday_bias_str(weekday_bias: dict) -> str:
    """
    Format weekday bias for logging/display.

    Args:
        weekday_bias: Dictionary mapping weekday names to bias multipliers

    Returns:
        Formatted string showing today's bias
    """
    if not weekday_bias:
        return ""

    today = now_ist().strftime("%A")
    bias = weekday_bias.get(today, 1.0)

    if bias == 1.0:
        return f"{today}: Neutral"
    elif bias > 1.0:
        return f"{today}: Bullish ({bias:.2f}x)"
    else:
        return f"{today}: Bearish ({bias:.2f}x)"