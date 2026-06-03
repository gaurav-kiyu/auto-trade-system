"""
NSE Event Calendar — High-Volatility Event Day Filter (Phase 7D).

Blocks or reduces position sizing on known high-volatility event days such as
Union Budget, RBI Monetary Policy, FOMC announcements, and custom user dates.

v2.45 Item 15 adds Corporate Action Calendar support: dividend ex-dates,
stock splits, and bonus issues for BANKNIFTY constituent stocks.

Config keys (all optional — safe defaults built in)
---------------------------------------------------
  event_calendar_enabled : bool  default true
  event_dates            : list  default []

  Each entry in event_dates:
    {
      "date":          "2026-02-01",     # ISO date string YYYY-MM-DD
      "type":          "BUDGET",         # BUDGET | RBI | FOMC | RESULT | CUSTOM
      "name":          "Union Budget",   # Human-readable label
      "block_entries": true,             # hard-block new entries (default false)
      "size_mult":     0.5               # position size multiplier 0-1 (default 1.0)
    }

  event_day_block_entries : bool  default false  (global fallback — overridden per event)
  event_day_size_mult     : float default 1.0    (global fallback — overridden per event)

  # Corporate Action Calendar (v2.45)
  corp_action_calendar_enabled : bool   default false
  corp_action_symbols          : list   default []   (e.g. ["HDFCBANK", "ICICIBANK"])
  corp_action_data             : list   default []   (static list of corporate actions)

  Each entry in corp_action_data:
    {
      "symbol": "HDFCBANK",
      "date":   "2026-05-15",
      "type":   "DIVIDEND",          # DIVIDEND | SPLIT | BONUS
      "factor": 1.0                  # split ratio or dividend per share
    }
"""
from __future__ import annotations

import datetime
import logging
import threading
from typing import Any

_log = logging.getLogger(__name__)


# ── Event record ──────────────────────────────────────────────────────────────

class EventRecord:
    __slots__ = ("date", "event_type", "name", "block_entries", "size_mult")

    def __init__(
        self,
        date: datetime.date,
        event_type: str,
        name: str,
        block_entries: bool,
        size_mult: float,
    ) -> None:
        self.date = date
        self.event_type = event_type
        self.name = name
        self.block_entries = block_entries
        self.size_mult = size_mult

    def __repr__(self) -> str:
        return f"EventRecord({self.date} {self.event_type!r} {self.name!r} block={self.block_entries} mult={self.size_mult})"


# ── Internal helpers ──────────────────────────────────────────────────────────

def _parse_event_dates(
    event_list: list[dict[str, Any]],
    global_block: bool,
    global_mult: float,
) -> dict[datetime.date, EventRecord]:
    records: dict[datetime.date, EventRecord] = {}
    for item in (event_list or []):
        try:
            d = datetime.date.fromisoformat(str(item.get("date", "")))
            records[d] = EventRecord(
                date=d,
                event_type=str(item.get("type", "CUSTOM")).upper(),
                name=str(item.get("name", "Event")),
                block_entries=bool(item.get("block_entries", global_block)),
                size_mult=float(item.get("size_mult", global_mult)),
            )
        except (ValueError, TypeError, KeyError) as exc:
            _log.debug("[EVENT_CAL] Skipping invalid event entry %r: %s", item, exc)
    return records


def _build_index(cfg: dict[str, Any]) -> dict[datetime.date, EventRecord]:
    return _parse_event_dates(
        event_list=list(cfg.get("event_dates") or []),
        global_block=bool(cfg.get("event_day_block_entries", False)),
        global_mult=float(cfg.get("event_day_size_mult", 1.0)),
    )


# ── Public API ────────────────────────────────────────────────────────────────

def get_event(
    date: datetime.date,
    cfg: dict[str, Any] | None = None,
) -> EventRecord | None:
    """
    Return the EventRecord for `date` if it is a configured event day, else None.

    Args:
        date : The trading date to check (usually today).
        cfg  : Bot config dict containing the ``event_dates`` list.
    """
    c = cfg or {}
    if not c.get("event_calendar_enabled", True):
        return None
    index = _build_index(c)
    return index.get(date)


def event_entry_allowed(
    date: datetime.date,
    cfg: dict[str, Any] | None = None,
) -> tuple[bool, str]:
    """
    Return (allowed, reason).  allowed=False means hard-block new entries.

    Args:
        date : The trading date to check.
        cfg  : Bot config dict.

    Returns:
        (True,  "")      — no event today, or event allows entries.
        (False, reason)  — event today with block_entries=True.
    """
    ev = get_event(date, cfg)
    if ev is None:
        return True, ""
    if ev.block_entries:
        reason = f"{ev.event_type} day ({ev.name}) — entries blocked"
        _log.info("[EVENT_CAL] %s", reason)
        return False, reason
    return True, ""


def event_size_multiplier(
    date: datetime.date,
    cfg: dict[str, Any] | None = None,
) -> float:
    """
    Return the position size multiplier for `date`.

    Returns 1.0 (no adjustment) when no event is configured.
    Returns the event's size_mult (e.g. 0.5 for half-size) on event days.

    Args:
        date : The trading date.
        cfg  : Bot config dict.
    """
    ev = get_event(date, cfg)
    if ev is None:
        return 1.0
    mult = round(max(0.0, min(1.0, ev.size_mult)), 4)
    if mult < 1.0:
        _log.info(
            "[EVENT_CAL] %s day (%s) — position size × %.2f",
            ev.event_type, ev.name, mult,
        )
    return mult


def event_summary(
    date: datetime.date,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a snapshot dict for logging and Telegram alerts."""
    ev = get_event(date, cfg)
    if ev is None:
        return {"is_event_day": False, "date": str(date)}
    return {
        "is_event_day":   True,
        "date":           str(ev.date),
        "type":           ev.event_type,
        "name":           ev.name,
        "block_entries":  ev.block_entries,
        "size_mult":      ev.size_mult,
    }


# ── Market day / holiday calendar (Item 5 — v2.44) ───────────────────────────

import time as _time
from enum import Enum


class MarketStatus(str, Enum):
    OPEN        = "OPEN"         # 09:15–15:30 on a trading day
    PRE_MARKET  = "PRE_MARKET"   # before 09:15 on a trading day
    POST_MARKET = "POST_MARKET"  # after 15:30 on a trading day
    NON_TRADING = "NON_TRADING"  # weekend or holiday


# NSE market open/close times (IST)
_NSE_OPEN  = datetime.time(9, 15)
_NSE_CLOSE = datetime.time(15, 30)

# NSE holiday API URL
_NSE_HOLIDAY_API  = "https://www.nseindia.com/api/holiday-master?type=trading"
# In-memory cache for live holidays
_LIVE_HOLIDAYS: set[datetime.date] | None = None
_LIVE_HOLIDAYS_TS: float = 0.0
_LIVE_HOLIDAYS_TTL: float = 3600.0  # 1 hour cache
_LIVE_HOLIDAYS_LOCK = threading.Lock()


def _fetch_nse_holidays() -> set[datetime.date]:
    """Fetch NSE trading holiday calendar from the NSE holiday-master API.

    Falls back to empty set if the API is unreachable.
    """
    try:
        import json
        import urllib.request
        req = urllib.request.Request(
            _NSE_HOLIDAY_API,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Accept": "application/json",
            }
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        holidays: set[datetime.date] = set()
        # NSE returns list of holiday objects with "tradingDate" field
        entries = data if isinstance(data, list) else data.get("holidays", data.get("data", []))
        for entry in entries:
            raw_date = entry.get("tradingDate") or entry.get("date", "")
            try:
                holidays.add(datetime.date.fromisoformat(str(raw_date)[:10]))
            except (ValueError, TypeError):
                continue
        if holidays:
            _log.info("[HOLIDAY] Fetched %d NSE trading holidays from API", len(holidays))
        return holidays
    except (ValueError, OSError, ConnectionError, ImportError) as exc:
        _log.warning("[HOLIDAY] Could not fetch from NSE API: %s — using config-based holidays", exc)
        return set()


def _get_live_holidays() -> set[datetime.date]:
    """Return cached live NSE holidays, refreshing from API if stale."""
    global _LIVE_HOLIDAYS, _LIVE_HOLIDAYS_TS
    now = _time.time()
    with _LIVE_HOLIDAYS_LOCK:
        if _LIVE_HOLIDAYS is None or (now - _LIVE_HOLIDAYS_TS) > _LIVE_HOLIDAYS_TTL:
            fetched = _fetch_nse_holidays()
            if fetched:
                _LIVE_HOLIDAYS = fetched
                _LIVE_HOLIDAYS_TS = now
            elif _LIVE_HOLIDAYS is None:
                _LIVE_HOLIDAYS = set()  # empty fallback if never fetched
        return set(_LIVE_HOLIDAYS)


def _nse_holidays(cfg: dict[str, Any]) -> set[datetime.date]:
    """Extract holiday dates from event_dates where block_entries=True,
    merged with live NSE API data."""
    # Config-based holidays from event_dates
    index = _build_index(cfg)
    holidays = {d for d, ev in index.items() if ev.block_entries}

    # Merge with live NSE API holidays
    live = _get_live_holidays()
    holidays.update(live)

    return holidays


def is_market_day(
    cfg: dict[str, Any] | None = None,
    check_date: datetime.date | None = None,
) -> bool:
    """
    Returns True if check_date (default: today IST) is a trading day.
    Checks: not Saturday, not Sunday, not in NSE holiday list (live + config).
    """
    c   = cfg or {}
    try:
        from core.datetime_ist import now_ist
        today = check_date or now_ist().date()
    except (ImportError, ValueError, TypeError):
        today = check_date or datetime.date.today()  # nosec — safe fallback when import fails

    if today.weekday() in (5, 6):   # Saturday=5, Sunday=6
        return False

    holidays = _nse_holidays(c)
    # Also support simple NSE_HOLIDAYS list of "YYYY-MM-DD" strings
    for raw in c.get("NSE_HOLIDAYS", []):
        try:
            holidays.add(datetime.date.fromisoformat(str(raw)))
        except (ValueError, TypeError) as _ex:
            logging.getLogger(__name__).debug(f"Invalid NSE_HOLIDAY entry: {raw} — {_ex}")
    return today not in holidays


def get_market_status(
    cfg: dict[str, Any] | None = None,
    check_dt: datetime.datetime | None = None,
) -> MarketStatus:
    """
    Returns MarketStatus for the given datetime (default: now IST).
    OPEN: 09:15–15:30 on a trading day
    PRE_MARKET: before 09:15 on a trading day
    POST_MARKET: after 15:30 on a trading day
    NON_TRADING: weekend or holiday
    """
    c = cfg or {}
    try:
        from core.datetime_ist import now_ist
        now = check_dt or now_ist()
    except (ImportError, ValueError, TypeError):
        now = check_dt or now_ist()

    today = now.date()
    current_time = now.time()

    if not is_market_day(c, today):
        return MarketStatus.NON_TRADING
    if current_time < _NSE_OPEN:
        return MarketStatus.PRE_MARKET
    if current_time <= _NSE_CLOSE:
        return MarketStatus.OPEN
    return MarketStatus.POST_MARKET


def is_pre_market(cfg: dict[str, Any] | None = None) -> bool:
    """True if today is a trading day and current time < 09:15 IST."""
    return get_market_status(cfg) == MarketStatus.PRE_MARKET


def get_next_market_open(
    cfg: dict[str, Any] | None = None,
    from_dt: datetime.datetime | None = None,
) -> datetime.datetime:
    """
    Returns next market open datetime (09:15 IST on next valid trading day).
    Scans forward from now, skipping weekends and holidays.
    """
    c = cfg or {}
    try:
        from core.datetime_ist import now_ist
        now = from_dt or now_ist()
    except (ImportError, ValueError, TypeError):
        now = from_dt or now_ist()

    candidate = now.date()
    # If today is trading day and open hasn't happened yet, return today's open
    if is_market_day(c, candidate) and now.time() < _NSE_OPEN:
        return datetime.datetime.combine(candidate, _NSE_OPEN)

    # Otherwise advance to the next trading day
    candidate += datetime.timedelta(days=1)
    for _ in range(14):  # safety cap
        if is_market_day(c, candidate):
            return datetime.datetime.combine(candidate, _NSE_OPEN)
        candidate += datetime.timedelta(days=1)

    # Fallback: 7 days from now at 09:15
    return datetime.datetime.combine(now.date() + datetime.timedelta(days=7), _NSE_OPEN)


def get_time_until_market_open(
    cfg: dict[str, Any] | None = None,
) -> datetime.timedelta:
    """Returns timedelta until next market open."""
    try:
        from core.datetime_ist import now_ist
        now = now_ist()
    except (ImportError, ValueError, TypeError):
        now = now_ist()
    next_open = get_next_market_open(cfg, now)
    return next_open - now


def sleep_until(target_dt: datetime.datetime, stop_event=None) -> None:
    """
    Sleeps until target_dt.
    Wakes every 60s to check for STOP_TRADING kill file or stop_event.
    """
    import os
    while True:
        try:
            from core.datetime_ist import now_ist
            now = now_ist()
        except (ImportError, ValueError, TypeError):
            now = now_ist()

        remaining = (target_dt - now).total_seconds()
        if remaining <= 0:
            return

        if os.path.exists("STOP_TRADING"):
            _log.info("[MARKET_CAL] STOP_TRADING detected during sleep — exiting")
            return

        if stop_event is not None:
            if stop_event.wait(min(60.0, remaining)):
                return
        else:
            _time.sleep(min(60.0, remaining))


# ── Corporate Action Calendar (v2.45 Item 15) ─────────────────────────────────

from dataclasses import dataclass as _dataclass


@_dataclass(frozen=True)
class CorporateAction:
    symbol:      str
    date:        datetime.date
    action_type: str    # "DIVIDEND", "SPLIT", "BONUS"
    factor:      float  # split ratio or dividend per share


def fetch_corporate_actions(
    cfg: dict[str, Any] | None = None,
) -> list[CorporateAction]:
    """
    Load corporate actions from config's corp_action_data list.

    Args:
        cfg: config dict (may contain corp_action_data list).

    Returns:
        List of CorporateAction sorted by date ascending.
    """
    c = cfg or {}
    if not c.get("corp_action_calendar_enabled", False):
        return []

    raw: list[dict] = c.get("corp_action_data", []) or []
    actions: list[CorporateAction] = []
    for entry in raw:
        try:
            date = datetime.date.fromisoformat(str(entry["date"]))
            actions.append(CorporateAction(
                symbol=str(entry.get("symbol", "")).upper(),
                date=date,
                action_type=str(entry.get("type", "UNKNOWN")).upper(),
                factor=float(entry.get("factor", 1.0)),
            ))
        except (ValueError, TypeError, KeyError) as exc:
            _log.debug("[CORP_ACTION] bad entry %s: %s", entry, exc)

    return sorted(actions, key=lambda a: a.date)


def is_corp_action_day(
    symbol:     str,
    check_date: datetime.date | None = None,
    cfg:        dict[str, Any] | None = None,
) -> tuple[bool, str]:
    """
    Check if a corporate action occurs on check_date for the given symbol.

    Args:
        symbol:     stock ticker (e.g. "HDFCBANK").
        check_date: date to check (default: today IST).
        cfg:        config dict.

    Returns:
        (True, description)  if action found on that date.
        (False, "")          otherwise.
    """
    c = cfg or {}
    if not c.get("corp_action_calendar_enabled", False):
        return False, ""

    if check_date is None:
        try:
            from core.datetime_ist import now_ist
            check_date = now_ist().date()
        except (ImportError, ValueError, TypeError):
            check_date = datetime.date.today()

    sym_upper = symbol.upper()
    for action in fetch_corporate_actions(c):
        if action.symbol == sym_upper and action.date == check_date:
            desc = f"{action.action_type} factor={action.factor} for {sym_upper}"
            return True, desc
    return False, ""
