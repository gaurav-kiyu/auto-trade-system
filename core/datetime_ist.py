"""Naive IST wall clock shared by index and stock entry scripts (UTC+5:30, no tzinfo)."""

from __future__ import annotations

import datetime
from typing import Any

IST_OFFSET = datetime.timedelta(hours=5, minutes=30)

# NSE session clock (IST, naive). Overridden via configure_nse_cash_session from bot JSON.
_NSE_OPEN: tuple[int, int] = (9, 15)
_NSE_CLOSE: tuple[int, int] = (15, 20)
_NSE_CONTINUOUS_OPEN: tuple[int, int] = (9, 20)
_NSE_SCHEDULE_CLOSED: tuple[int, int] = (15, 30)
_NSE_BLOCK_ENTRIES_FROM: tuple[int, int] = (15, 0)
_NSE_POST_OPEN_NO_TRADE_MINS: int = 10
_NSE_EARLY_SESSION_END: tuple[int, int] = (10, 15)


def _hm_to_time(hm: tuple[int, int]) -> datetime.time:
    return datetime.time(int(hm[0]), int(hm[1]))


def configure_nse_cash_session(
    open_hm: tuple[int, int],
    close_hm: tuple[int, int],
    *,
    continuous_open_hm: tuple[int, int] | None = None,
    schedule_closed_hm: tuple[int, int] | None = None,
    block_new_entries_from_hm: tuple[int, int] | None = None,
    post_open_no_trade_minutes: int | None = None,
    early_session_end_hm: tuple[int, int] | None = None,
) -> None:
    """
    Set NSE cash hours for :func:`is_nse_cash_session` and related helpers.

    Optional keyword args tune ``market_status`` / entry gates so index and stock
    bots stay aligned without duplicating ``datetime.time(9,15)`` literals.
    """
    global _NSE_OPEN, _NSE_CLOSE, _NSE_CONTINUOUS_OPEN, _NSE_SCHEDULE_CLOSED
    global _NSE_BLOCK_ENTRIES_FROM, _NSE_POST_OPEN_NO_TRADE_MINS, _NSE_EARLY_SESSION_END
    _NSE_OPEN = (int(open_hm[0]), int(open_hm[1]))
    _NSE_CLOSE = (int(close_hm[0]), int(close_hm[1]))
    if continuous_open_hm is not None:
        _NSE_CONTINUOUS_OPEN = (int(continuous_open_hm[0]), int(continuous_open_hm[1]))
    if schedule_closed_hm is not None:
        _NSE_SCHEDULE_CLOSED = (int(schedule_closed_hm[0]), int(schedule_closed_hm[1]))
    if block_new_entries_from_hm is not None:
        _NSE_BLOCK_ENTRIES_FROM = (int(block_new_entries_from_hm[0]), int(block_new_entries_from_hm[1]))
    if post_open_no_trade_minutes is not None:
        _NSE_POST_OPEN_NO_TRADE_MINS = max(0, int(post_open_no_trade_minutes))
    if early_session_end_hm is not None:
        _NSE_EARLY_SESSION_END = (int(early_session_end_hm[0]), int(early_session_end_hm[1]))


def apply_nse_session_from_cfg(cfg: dict) -> None:
    """Apply all ``NSE_*`` clock keys from a merged bot config (startup / soft-reload)."""
    try:
        configure_nse_cash_session(
            (
                int(cfg.get("NSE_CASH_SESSION_START_HOUR", 9)),
                int(cfg.get("NSE_CASH_SESSION_START_MINUTE", 15)),
            ),
            (
                int(cfg.get("NSE_CASH_SESSION_END_HOUR", 15)),
                int(cfg.get("NSE_CASH_SESSION_END_MINUTE", 20)),
            ),
            continuous_open_hm=(
                int(cfg.get("NSE_CONTINUOUS_TRADE_START_HOUR", 9)),
                int(cfg.get("NSE_CONTINUOUS_TRADE_START_MINUTE", 20)),
            ),
            schedule_closed_hm=(
                int(cfg.get("NSE_MARKET_STATUS_CLOSED_HOUR", 15)),
                int(cfg.get("NSE_MARKET_STATUS_CLOSED_MINUTE", 30)),
            ),
            block_new_entries_from_hm=(
                int(cfg.get("NSE_BLOCK_NEW_ENTRIES_FROM_HOUR", 15)),
                int(cfg.get("NSE_BLOCK_NEW_ENTRIES_FROM_MINUTE", 0)),
            ),
            post_open_no_trade_minutes=int(cfg.get("NSE_POST_OPEN_NO_TRADE_MINUTES", 10)),
            early_session_end_hm=(
                int(cfg.get("NSE_EARLY_SESSION_END_HOUR", 10)),
                int(cfg.get("NSE_EARLY_SESSION_END_MINUTE", 15)),
            ),
        )
    except Exception:
        configure_nse_cash_session(
            (9, 15),
            (15, 20),
            continuous_open_hm=(9, 20),
            schedule_closed_hm=(15, 30),
            block_new_entries_from_hm=(15, 0),
            post_open_no_trade_minutes=10,
            early_session_end_hm=(10, 15),
        )


def nse_cash_open_time() -> datetime.time:
    return _hm_to_time(_NSE_OPEN)


def nse_cash_close_time() -> datetime.time:
    return _hm_to_time(_NSE_CLOSE)


def nse_continuous_open_time() -> datetime.time:
    return _hm_to_time(_NSE_CONTINUOUS_OPEN)


def nse_schedule_closed_time() -> datetime.time:
    return _hm_to_time(_NSE_SCHEDULE_CLOSED)


def nse_block_new_entries_from_time() -> datetime.time:
    return _hm_to_time(_NSE_BLOCK_ENTRIES_FROM)


def nse_early_session_end_time() -> datetime.time:
    return _hm_to_time(_NSE_EARLY_SESSION_END)


def now_ist() -> datetime.datetime:
    """Naive datetime in IST for logs and filenames — not a tzinfo-aware value."""
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) + IST_OFFSET


def is_nse_cash_session(now: datetime.datetime | None = None) -> bool:
    """
    True during NSE cash / index cash hours (Mon–Fri, IST), using bounds from
    :func:`configure_nse_cash_session` (defaults 09:15–15:20).
    """
    dt = now or now_ist()
    if dt.weekday() >= 5:
        return False
    t = dt.time()
    open_ = nse_cash_open_time()
    close = nse_cash_close_time()
    return open_ <= t <= close


def is_nse_continuous_trading_window(clock: datetime.time | None = None) -> bool:
    """True when time is within continuous cash session (default 09:20–15:20 IST)."""
    t = clock or now_ist().time()
    lo = nse_continuous_open_time()
    hi = nse_cash_close_time()
    return lo <= t <= hi


def is_nse_post_open_no_trade_zone(clock: datetime.time | None = None) -> bool:
    """True from cash open through open + configured post-open minutes (default 9:15–9:25)."""
    t = clock or now_ist().time()
    start = nse_cash_open_time()
    end_dt = datetime.datetime.combine(datetime.date(2000, 1, 1), start) + datetime.timedelta(
        minutes=_NSE_POST_OPEN_NO_TRADE_MINS
    )
    return start <= t <= end_dt.time()


def mins_until_nse_cash_close(now: datetime.datetime | None = None) -> float:
    """Minutes until configured cash close (same basis as legacy mins_until_eod)."""
    dt = now or now_ist()
    eod = dt.replace(
        hour=_NSE_CLOSE[0],
        minute=_NSE_CLOSE[1],
        second=0,
        microsecond=0,
    )
    return max(0.0, (eod - dt).total_seconds() / 60.0)


def nse_close_safety_start_time(safety_mins: int) -> datetime.time:
    """Earliest time of day at which the pre-close safety window is active (close − safety_mins)."""
    ch, cm = _NSE_CLOSE
    base = datetime.datetime(2000, 1, 1, ch, cm)
    t = base - datetime.timedelta(minutes=max(0, int(safety_mins)))
    return t.time()


def format_weekday_bias_str(weekday_bias: Any) -> str:
    """Human-readable WEEKDAY_BIAS for logs / Telegram."""
    if not isinstance(weekday_bias, dict):
        return "WEEKDAY_BIAS: (invalid)"
    return "WEEKDAY_BIAS: " + ", ".join(f"{k}={v}" for k, v in sorted(weekday_bias.items()))
