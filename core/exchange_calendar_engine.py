"""
Exchange Calendar Engine (Master Prompt Phase 19).

Unified class wrapping the existing event_calendar.py function-based API with:
  - NSE trading holiday calendar (live via NSE API + config)
  - Special session detection (Muhurat trading, half-days)
  - Market status (OPEN / PRE_MARKET / POST_MARKET / NON_TRADING / HALF_DAY / MUHURAT)
  - Expiry calendar tracking for NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY
  - Corporate actions, IPO calendar, SEBI circulars
  - Trading hours query (adjusted for special sessions)

Usage:
    from core.exchange_calendar_engine import ExchangeCalendarEngine

    engine = ExchangeCalendarEngine(cfg)
    status = engine.get_market_status()
    print(status)

    # Check if muhurat trading today
    if engine.is_muhurat_trading():
        hours = engine.get_trading_hours()
        print(f"Muhurat session: {hours['open']} - {hours['close']}")

    # Expiry calendar
    expiries = engine.get_expiry_calendar(year=2026)
    for name, dates in expiries.items():
        print(f"{name}: next expiry {dates[0]}")
"""

from __future__ import annotations

import datetime
import logging
import threading
from dataclasses import dataclass
from enum import Enum
from typing import Any

from core.datetime_ist import now_ist, is_saturday_allowed

_log = logging.getLogger(__name__)


# ── Enhanced Market Status ───────────────────────────────────────────────────


class ExtendedMarketStatus(str, Enum):
    """Extended market status with special session support.

    Extends the basic MarketStatus from event_calendar.py to include
    HALF_DAY and MUHURAT for special NSE trading sessions.
    """
    OPEN        = "OPEN"          # 09:15-15:30 on a normal trading day
    PRE_MARKET  = "PRE_MARKET"    # before 09:15 on a trading day
    POST_MARKET = "POST_MARKET"   # after 15:30 on a trading day
    NON_TRADING = "NON_TRADING"   # weekend or holiday
    HALF_DAY    = "HALF_DAY"      # truncated session (e.g. 09:15-12:30)
    MUHURAT     = "MUHURAT"       # Diwali muhurat trading (typically evening session)


@dataclass(frozen=True)
class TradingHours:
    """Trading hours for a given date.

    Attributes:
        date: The trading date.
        is_trading_day: Whether this is a trading day.
        session_type: Type of session (REGULAR, HALF_DAY, MUHURAT, CLOSED).
        open_time: Market open time (IST).
        close_time: Market close time (IST).
        description: Human-readable description.
    """
    date: datetime.date
    is_trading_day: bool
    session_type: str = "REGULAR"
    open_time: datetime.time | None = None
    close_time: datetime.time | None = None
    description: str = ""


@dataclass(frozen=True)
class ExpiryRecord:
    """An expiry date for an index derivative.

    Attributes:
        index_name: Index name (NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY).
        expiry_date: The expiry date.
        is_weekly: Whether this is a weekly expiry (vs monthly).
        trading_week: ISO week number.
    """
    index_name: str
    expiry_date: datetime.date
    is_weekly: bool = True
    trading_week: int = 0

    @property
    def days_to_expiry(self) -> int:
        """Number of days from today until expiry."""
        return (self.expiry_date - now_ist().date()).days


# ── Known NSE special session dates (hard-coded for known years) ────────────
# These are announced by NSE via circulars. The list should be updated annually.
# Format: {year: [(date, type, description), ...]}

_NSE_SPECIAL_SESSIONS: dict[int, list[tuple[str, str, str]]] = {
    2025: [
        ("2025-10-21", "MUHURAT", "Diwali Muhurat Trading 2025 (18:15-19:15)"),
    ],
    2026: [],  # Will be populated when NSE announces 2026 dates
}

# Known half-day sessions (market closes early, typically 09:15-12:30)
_NSE_HALF_DAYS: dict[int, list[tuple[str, str]]] = {
    2025: [
        ("2025-03-14", "Holi Half Day"),
        ("2025-10-21", "Diwali Half Day"),
    ],
    2026: [],  # Will be populated when NSE announces 2026 dates
}

# Expiry day mapping (derived from NSE weekly expiry schedule)
_WEEKLY_EXPIRY_MAP: dict[str, int] = {
    "NIFTY": 3,        # Thursday
    "BANKNIFTY": 2,    # Wednesday
    "FINNIFTY": 1,     # Tuesday
    "MIDCPNIFTY": 0,   # Monday
    "SENSEX": 4,       # Friday
}

_MONTHLY_EXPIRY_DEFAULT: int = 3  # Last Thursday (default for most indices)


class ExchangeCalendarEngine:
    """Unified Exchange Calendar Engine.

    Wraps all calendar-related functionality from event_calendar.py and
    datetime_ist.py into a single class, adding special session detection
    and expiry calendar tracking.

    This is the single entry point for ALL calendar queries.
    """

    def __init__(self, cfg: dict[str, Any] | None = None):
        """Initialize the Exchange Calendar Engine.

        Args:
            cfg: Bot config dict (may contain event_dates, corp_action_data, etc.)
        """
        self._cfg = cfg or {}
        self._lock = threading.RLock()
        self._special_cache: dict[int, list[dict[str, Any]]] = {}

    # ── Market day / holiday checks ──────────────────────────────────────

    def is_market_day(self, check_date: datetime.date | None = None) -> bool:
        """Check if check_date is a trading day.

        Delegates to event_calendar.is_market_day() internally.

        Args:
            check_date: Date to check (default: today IST).

        Returns:
            True if the date is a trading day, False otherwise.
        """
        from core.event_calendar import is_market_day as _base_check
        return _base_check(self._cfg, check_date)

    def is_holiday(self, check_date: datetime.date | None = None) -> bool:
        """Inverse of is_market_day."""
        return not self.is_market_day(check_date)

    # ── Special session detection ────────────────────────────────────────

    def get_special_sessions(self, year: int | None = None) -> list[dict[str, Any]]:
        """Get all special NSE sessions for a given year.

        Includes muhurat trading, half-days, and any other special sessions.

        Args:
            year: Calendar year (default: current year IST).

        Returns:
            List of dicts with keys: date, type, name, description, open_time, close_time.
        """
        with self._lock:
            if year is None:
                year = now_ist().year

            if year in self._special_cache:
                return self._special_cache[year]

            sessions: list[dict[str, Any]] = []

            # Muhurat trading sessions
            muhurat_list = _NSE_SPECIAL_SESSIONS.get(year, [])
            for date_str, sess_type, desc in muhurat_list:
                try:
                    d = datetime.date.fromisoformat(date_str)
                    sessions.append({
                        "date": d,
                        "type": sess_type,
                        "name": desc.split("(")[0].strip(),
                        "description": desc,
                        "open_time": datetime.time(18, 15) if sess_type == "MUHURAT" else None,
                        "close_time": datetime.time(19, 15) if sess_type == "MUHURAT" else None,
                    })
                except (ValueError, TypeError):
                    continue

            # Half-day sessions
            half_day_list = _NSE_HALF_DAYS.get(year, [])
            for date_str, name in half_day_list:
                try:
                    d = datetime.date.fromisoformat(date_str)
                    # Check not already added as muhurat
                    if not any(s["date"] == d and s["type"] == "MUHURAT" for s in sessions):
                        sessions.append({
                            "date": d,
                            "type": "HALF_DAY",
                            "name": name,
                            "description": f"{name} - market closes at 12:30 IST",
                            "open_time": datetime.time(9, 15),
                            "close_time": datetime.time(12, 30),
                        })
                except (ValueError, TypeError):
                    continue

            # Also check event_dates from config for special types
            for ev in (self._cfg.get("event_dates") or []):
                try:
                    ev_type = str(ev.get("type", "")).upper()
                    if ev_type in ("MUHURAT", "HALF_DAY", "SPECIAL_SESSION"):
                        ev_date = datetime.date.fromisoformat(str(ev["date"]))
                        if not any(s["date"] == ev_date for s in sessions):
                            sessions.append({
                                "date": ev_date,
                                "type": ev_type,
                                "name": str(ev.get("name", ev_type)),
                                "description": str(ev.get("name", "Special session")),
                                "open_time": None,
                                "close_time": None,
                            })
                except (ValueError, TypeError, KeyError):
                    continue

            sessions.sort(key=lambda s: s["date"])
            self._special_cache[year] = sessions
            return sessions

    def is_muhurat_trading(self, check_date: datetime.date | None = None) -> bool:
        """Check if check_date is a Muhurat trading session (Diwali special).

        During Muhurat trading, the market opens at 18:15 and closes at 19:15 IST.
        Saturdays are automatically allowed for Muhurat sessions.

        Args:
            check_date: Date to check (default: today IST).

        Returns:
            True if this is a Muhurat trading day.
        """
        if check_date is None:
            check_date = now_ist().date()
        for session in self.get_special_sessions(check_date.year):
            if session["date"] == check_date and session["type"] == "MUHURAT":
                return True
        return False

    def is_half_day(self, check_date: datetime.date | None = None) -> bool:
        """Check if check_date is a half-day trading session.

        During half-days, the market closes at 12:30 IST instead of 15:30.

        Args:
            check_date: Date to check (default: today IST).

        Returns:
            True if this is a half-day trading session.
        """
        if check_date is None:
            check_date = now_ist().date()
        for session in self.get_special_sessions(check_date.year):
            if session["date"] == check_date and session["type"] == "HALF_DAY":
                return True
        return False

    def get_trading_hours(self, check_date: datetime.date | None = None) -> TradingHours:
        """Get the trading hours for a given date, adjusted for special sessions.

        Args:
            check_date: Date to check (default: today IST).

        Returns:
            TradingHours with session type, open/close times, and description.
        """
        if check_date is None:
            check_date = now_ist().date()

        # Check special sessions first
        for session in self.get_special_sessions(check_date.year):
            if session["date"] != check_date:
                continue
            if session["type"] == "MUHURAT":
                return TradingHours(
                    date=check_date,
                    is_trading_day=True,
                    session_type="MUHURAT",
                    open_time=session.get("open_time", datetime.time(18, 15)),
                    close_time=session.get("close_time", datetime.time(19, 15)),
                    description=session["description"],
                )
            if session["type"] == "HALF_DAY":
                return TradingHours(
                    date=check_date,
                    is_trading_day=True,
                    session_type="HALF_DAY",
                    open_time=datetime.time(9, 15),
                    close_time=datetime.time(12, 30),
                    description=session["description"],
                )
            return TradingHours(
                date=check_date,
                is_trading_day=True,
                session_type=session["type"],
                description=session.get("name", "Special session"),
            )

        # Regular trading day check
        if not self.is_market_day(check_date):
            return TradingHours(
                date=check_date,
                is_trading_day=False,
                session_type="CLOSED",
                description="Weekend or holiday",
            )

        return TradingHours(
            date=check_date,
            is_trading_day=True,
            session_type="REGULAR",
            open_time=datetime.time(9, 15),
            close_time=datetime.time(15, 30),
            description="Regular trading session",
        )

    # ── Market status ────────────────────────────────────────────────────

    def get_market_status(
        self,
        check_dt: datetime.datetime | None = None,
    ) -> ExtendedMarketStatus:
        """Get the current market status, considering special sessions.

        Args:
            check_dt: Datetime to check (default: now IST).

        Returns:
            ExtendedMarketStatus: MUHURAT / HALF_DAY / OPEN / PRE_MARKET /
                                  POST_MARKET / NON_TRADING
        """
        dt = check_dt or now_ist()
        today = dt.date()

        # Check special session types first
        for session in self.get_special_sessions(today.year):
            if session["date"] != today:
                continue
            if session["type"] == "MUHURAT":
                open_t = session.get("open_time", datetime.time(18, 15))
                close_t = session.get("close_time", datetime.time(19, 15))
                if open_t <= dt.time() <= close_t:
                    return ExtendedMarketStatus.MUHURAT
                return ExtendedMarketStatus.PRE_MARKET if dt.time() < open_t else ExtendedMarketStatus.POST_MARKET
            if session["type"] == "HALF_DAY":
                open_t = datetime.time(9, 15)
                close_t = datetime.time(12, 30)
                if open_t <= dt.time() <= close_t:
                    return ExtendedMarketStatus.HALF_DAY
                if dt.time() < open_t:
                    return ExtendedMarketStatus.PRE_MARKET
                return ExtendedMarketStatus.POST_MARKET

        # Fall back to base implementation
        from core.event_calendar import get_market_status as _base_status
        base = _base_status(self._cfg, dt)
        return ExtendedMarketStatus(base.value)

    # ── Expiry calendar ──────────────────────────────────────────────────

    def get_expiry_calendar(
        self,
        year: int | None = None,
        indices: list[str] | None = None,
    ) -> dict[str, list[ExpiryRecord]]:
        """Get the expiry calendar for derivative indices.

        Computes weekly and monthly expiry dates for the given year.

        Args:
            year: Year to compute (default: current year).
            indices: List of indices to include (default: all).

        Returns:
            Dict mapping index name -> sorted list of ExpiryRecord.
        """
        if year is None:
            year = now_ist().year
        if indices is None:
            indices = list(_WEEKLY_EXPIRY_MAP.keys())

        calendar: dict[str, list[ExpiryRecord]] = {}
        for idx in indices:
            weekday = _WEEKLY_EXPIRY_MAP.get(idx)
            if weekday is None:
                continue

            expiries: list[ExpiryRecord] = []
            current = datetime.date(year, 1, 1)

            # Advance to first occurrence of target weekday
            days_ahead = weekday - current.weekday()
            if days_ahead < 0:
                days_ahead += 7
            current += datetime.timedelta(days=days_ahead)

            # Collect weekly expiries
            while current.year == year:
                if self.is_market_day(current):
                    expiries.append(ExpiryRecord(
                        index_name=idx,
                        expiry_date=current,
                        is_weekly=True,
                        trading_week=current.isocalendar()[1],
                    ))
                current += datetime.timedelta(days=7)

            # Also compute monthly expiry (last trading day with that weekday in month)
            # Note: If NSE declares a holiday falling 3+ days before the last Thursday,
            # the monthly expiry may shift to a different weekly expiry. The 2-day buffer
            # below handles the common case of 1-day holiday shifts.
            monthly_expiries: list[ExpiryRecord] = []
            for month in range(1, 13):
                last_day = datetime.date(year, month + 1, 1) - datetime.timedelta(days=1) if month < 12 \
                    else datetime.date(year, 12, 31)
                # Walk backwards to find last occurrence of target weekday
                candidate = last_day
                while candidate.weekday() != weekday:
                    candidate -= datetime.timedelta(days=1)
                # Use the weekly expiry that falls on/near the last occurrence
                # 2-day buffer handles common 1-day holiday shifts
                for exp in expiries:
                    if exp.expiry_date.month == month and exp.expiry_date >= candidate - datetime.timedelta(days=2):
                        monthly_expiries.append(ExpiryRecord(
                            index_name=idx,
                            expiry_date=exp.expiry_date,
                            is_weekly=False,
                            trading_week=exp.trading_week,
                        ))
                        break

            calendar[idx] = expiries

        return calendar

    def get_next_expiry(
        self,
        index_name: str = "NIFTY",
        from_date: datetime.date | None = None,
    ) -> ExpiryRecord | None:
        """Get the next expiry date for a given index.

        Args:
            index_name: Index name (default: "NIFTY").
            from_date: Starting date (default: today IST).

        Returns:
            ExpiryRecord for the next expiry, or None if not found.
        """
        if from_date is None:
            from_date = now_ist().date()
        calendar = self.get_expiry_calendar(from_date.year, [index_name])
        expiries = calendar.get(index_name, [])
        for exp in expiries:
            if exp.expiry_date >= from_date:
                return exp
        return None

    def is_expiry_day(
        self,
        index_name: str = "NIFTY",
        check_date: datetime.date | None = None,
    ) -> bool:
        """Check if check_date is an expiry day for the given index.

        Args:
            index_name: Index name.
            check_date: Date to check (default: today IST).

        Returns:
            True if this is an expiry day.
        """
        if check_date is None:
            check_date = now_ist().date()
        next_exp = self.get_next_expiry(index_name, check_date)
        return next_exp is not None and next_exp.expiry_date == check_date

    # ── Delegated calendar functions ─────────────────────────────────────

    def get_event_calendar(self) -> dict[str, Any]:
        """Get the configured high-volatility event calendar.

        Returns:
            Dict with is_event_day, event_type, name, block_entries, size_mult.
        """
        from core.event_calendar import event_summary
        today = now_ist().date()
        return event_summary(today, self._cfg)

    def get_corporate_actions(self) -> list[Any]:
        """Get corporate action calendar from config.

        Returns:
            List of CorporateAction objects sorted by date.
        """
        from core.event_calendar import fetch_corporate_actions
        return fetch_corporate_actions(self._cfg)

    def get_ipo_calendar(self) -> list[Any]:
        """Get IPO/FPO/OFS/QIP calendar from config.

        Returns:
            List of IPOEvent objects sorted by date.
        """
        from core.event_calendar import fetch_ipo_events
        return fetch_ipo_events(self._cfg)

    def get_sebi_circulars(self) -> list[Any]:
        """Get SEBI circular calendar from config.

        Returns:
            List of SEBICircular objects sorted by date.
        """
        from core.event_calendar import fetch_sebi_circulars
        return fetch_sebi_circulars(self._cfg)

    # ── Sleep utilities ──────────────────────────────────────────────────

    def sleep_until_next_open(self, stop_event=None) -> None:
        """Sleep until the next market open.

        Respects special sessions (muhurat, half-days) for next open
        time calculation. Wakes every 60s to check for STOP_TRADING.

        Args:
            stop_event: Optional threading.Event to interrupt sleep.
        """
        from core.event_calendar import sleep_until
        from core.event_calendar import get_next_market_open

        next_open = get_next_market_open(self._cfg)
        sleep_until(next_open, stop_event)

    # ── Summary ──────────────────────────────────────────────────────────

    def summary(self) -> dict[str, Any]:
        """Get a comprehensive calendar summary dict.

        Returns:
            Dict with market status, events, special sessions, and upcoming calendar.
        """
        now = now_ist()
        today = now.date()
        year = now.year

        # Market status
        status = self.get_market_status(now)
        hours = self.get_trading_hours(today)

        # Special sessions
        specials = self.get_special_sessions(year)
        upcoming_specials = [s for s in specials if s["date"] >= today]

        # Expiry calendar
        expiries: dict[str, str] = {}
        for idx in _WEEKLY_EXPIRY_MAP:
            next_exp = self.get_next_expiry(idx, today)
            if next_exp:
                expiries[idx] = str(next_exp.expiry_date)

        # Events
        event = self.get_event_calendar()

        return {
            "timestamp": str(now),
            "market_status": status.value,
            "is_trading_day": self.is_market_day(today),
            "trading_hours": {
                "date": str(hours.date),
                "session_type": hours.session_type,
                "open": str(hours.open_time) if hours.open_time else None,
                "close": str(hours.close_time) if hours.close_time else None,
                "description": hours.description,
            },
            "special_sessions": {
                "total": len(specials),
                "upcoming": len(upcoming_specials),
                "upcoming_detail": [
                    {"date": str(s["date"]), "type": s["type"], "name": s["name"]}
                    for s in upcoming_specials[:10]
                ],
            },
            "event_day": {
                "is_event_day": event.get("is_event_day", False),
                "type": event.get("type"),
                "name": event.get("name"),
            },
            "next_expiries": expiries,
            "corporate_actions": len(self.get_corporate_actions()),
            "upcoming_ipos": len(self.get_ipo_calendar()),
            "sebi_circulars": len(self.get_sebi_circulars()),
            "saturday_trading_allowed": is_saturday_allowed(),
        }

    def print_summary(self) -> None:
        """Print a human-readable calendar summary."""
        data = self.summary()
        lines = [
            "=" * 60,
            "  EXCHANGE CALENDAR ENGINE SUMMARY",
            "=" * 60,
            f"  Time (IST):         {data['timestamp']}",
            f"  Market Status:      {data['market_status']}",
            f"  Trading Day:        {'YES' if data['is_trading_day'] else 'NO'}",
            f"  Session Type:       {data['trading_hours']['session_type']}",
            f"  Trading Hours:      {data['trading_hours']['open'] or 'N/A'} - {data['trading_hours']['close'] or 'N/A'}",
            f"  Saturday Trading:   {'ALLOWED' if data['saturday_trading_allowed'] else 'DISABLED'}",
        ]
        if data['event_day']['is_event_day']:
            lines.append(f"  Event Day:          {data['event_day']['type']} - {data['event_day']['name']}")
        lines.append("")
        lines.append("  Next Expiries:")
        for idx, date_str in data['next_expiries'].items():
            lines.append(f"    {idx:<15s} {date_str}")
        if data['special_sessions']['upcoming'] > 0:
            lines.append("")
            lines.append(f"  Upcoming Special Sessions ({data['special_sessions']['upcoming']}):")
            for s in data['special_sessions']['upcoming_detail']:
                lines.append(f"    {s['date']:<12s} {s['type']:<15s} {s['name']}")
        lines.append("")
        lines.append(f"  Corporate Actions:  {data['corporate_actions']} upcoming")
        lines.append(f"  IPOs:               {data['upcoming_ipos']} upcoming")
        lines.append(f"  SEBI Circulars:     {data['sebi_circulars']} upcoming")
        lines.append("=" * 60)
        print("\n".join(lines))


# ── Convenience API ───────────────────────────────────────────────────────────


# Module-level cache for singleton factory
_engine_cache: dict[int, ExchangeCalendarEngine] = {}
_engine_cache_lock = threading.Lock()

def get_calendar_engine(cfg: dict[str, Any] | None = None) -> ExchangeCalendarEngine:
    """Get a configured singleton ExchangeCalendarEngine instance.

    Uses the config dict identity as the cache key so the same caller
    always gets the same engine instance (lightweight singleton per caller).
    Pass a module-level/long-lived config dict for best cache behavior.

    Args:
        cfg: Bot config dict.

    Returns:
        ExchangeCalendarEngine instance.
    """
    if cfg is None:
        cfg = {}
    key = id(cfg)
    with _engine_cache_lock:
        if key not in _engine_cache:
            _engine_cache[key] = ExchangeCalendarEngine(cfg)
        return _engine_cache[key]


__all__ = [
    "ExchangeCalendarEngine",
    "ExtendedMarketStatus",
    "ExpiryRecord",
    "TradingHours",
    "get_calendar_engine",
]
