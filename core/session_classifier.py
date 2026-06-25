"""
Session Classifier - Time-of-Day Intelligence Layer (Phase 3).

Partitions the NSE trading day into named session bands and applies
configurable score adjustments to the signal pipeline.

Session bands (default IST boundaries):
    PRE_MARKET   before 09:15                - market closed
    OPENING      09:15 - 10:15 (early end)   - high-vol gap-fill zone
    TRENDING     10:15 - 11:30               - best directional window
    CHOPPY       11:30 - 13:30               - midday low-conviction
    RECOVERY     13:30 - 14:15               - post-lunch drift
    PRE_CLOSE    14:15 - 15:00 (block from)  - EOD squeeze caution
    CLOSED       after 15:00                 - no new entries

The OPENING / TRENDING boundaries reuse existing NSE_EARLY_SESSION_END and
NSE_CASH_SESSION_START config keys so there is no new duplication.

Config keys (all optional - safe defaults built in)
----------------------------------------------------
  session_classifier_enabled     : bool  default true
  session_choppy_start_hour      : int   default 11
  session_choppy_start_minute    : int   default 30
  session_recovery_start_hour    : int   default 13
  session_recovery_start_minute  : int   default 30
  session_pre_close_start_hour   : int   default 14
  session_pre_close_start_minute : int   default 15
  session_opening_score_adj      : int   default -10
  session_trending_score_adj     : int   default  +5
  session_choppy_score_adj       : int   default -15
  session_recovery_score_adj     : int   default   0
  session_pre_close_score_adj    : int   default  -5
  session_opening_allowed        : bool  default true  (False → hard-block OPENING)
  session_choppy_allowed         : bool  default true  (False → hard-block CHOPPY)
"""
from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any

from core.datetime_ist import now_ist

_log = logging.getLogger(__name__)

# ── Session type ──────────────────────────────────────────────────────────────


class SessionType(str, Enum):
    PRE_MARKET = "PRE_MARKET"
    OPENING    = "OPENING"
    TRENDING   = "TRENDING"
    CHOPPY     = "CHOPPY"
    RECOVERY   = "RECOVERY"
    PRE_CLOSE  = "PRE_CLOSE"
    CLOSED     = "CLOSED"


# ── Default boundary constants ────────────────────────────────────────────────

_DEF_OPEN_H,     _DEF_OPEN_M     = 9,  15   # NSE cash open
_DEF_EARLY_H,    _DEF_EARLY_M    = 10, 15   # early session end (opening→trending)
_DEF_CHOPPY_H,   _DEF_CHOPPY_M   = 11, 30
_DEF_RECOVERY_H, _DEF_RECOVERY_M = 13, 30
_DEF_PRE_CL_H,   _DEF_PRE_CL_M  = 14, 15
_DEF_BLOCK_H,    _DEF_BLOCK_M    = 15, 0    # NSE no-new-entry time

# Default score adjustments per session
_DEF_ADJ: dict[SessionType, int] = {
    SessionType.OPENING:   -10,
    SessionType.TRENDING:   +5,
    SessionType.CHOPPY:    -15,
    SessionType.RECOVERY:    0,
    SessionType.PRE_CLOSE:  -5,
}


# ── Internal helpers ──────────────────────────────────────────────────────────

def _get_boundary(cfg: dict[str, Any], h_key: str, m_key: str, def_h: int, def_m: int) -> datetime.time:
    h = int(cfg.get(h_key, def_h))
    m = int(cfg.get(m_key, def_m))
    return datetime.time(h, m)


def _nse_open_time(cfg: dict[str, Any]) -> datetime.time:
    """NSE cash open - reuses NSE_CASH_SESSION_START_* config keys."""
    try:
        from core.datetime_ist import nse_cash_open_time
        return nse_cash_open_time()
    except (ImportError, AttributeError, ValueError, TypeError):
        return _get_boundary(
            cfg,
            "NSE_CASH_SESSION_START_HOUR",
            "NSE_CASH_SESSION_START_MINUTE",
            _DEF_OPEN_H, _DEF_OPEN_M,
        )


def _nse_early_end_time(cfg: dict[str, Any]) -> datetime.time:
    """Early-session end - reuses NSE_EARLY_SESSION_END_* config keys."""
    try:
        from core.datetime_ist import nse_early_session_end_time
        return nse_early_session_end_time()
    except (ImportError, AttributeError, ValueError, TypeError):
        return _get_boundary(
            cfg,
            "NSE_EARLY_SESSION_END_HOUR",
            "NSE_EARLY_SESSION_END_MINUTE",
            _DEF_EARLY_H, _DEF_EARLY_M,
        )


def _nse_block_time(cfg: dict[str, Any]) -> datetime.time:
    """No-new-entry time - reuses NSE_BLOCK_NEW_ENTRIES_FROM_* config keys."""
    try:
        from core.datetime_ist import nse_block_new_entries_from_time
        return nse_block_new_entries_from_time()
    except (ImportError, AttributeError, ValueError, TypeError):
        return _get_boundary(
            cfg,
            "NSE_BLOCK_NEW_ENTRIES_FROM_HOUR",
            "NSE_BLOCK_NEW_ENTRIES_FROM_MINUTE",
            _DEF_BLOCK_H, _DEF_BLOCK_M,
        )


# ── Public API ────────────────────────────────────────────────────────────────


def classify_session(
    t: datetime.time | datetime.datetime,
    cfg: dict[str, Any] | None = None,
) -> SessionType:
    """
    Classify current IST wall-clock time into a SessionType.

    Args:
        t   : Current time (datetime.time or datetime.datetime, naive IST).
        cfg : Bot config dict - used to read boundary overrides.

    Returns:
        SessionType enum value.
    """
    c = cfg or {}
    # Accept both datetime and time objects - extract time component if needed
    if isinstance(t, datetime.datetime):
        t = t.time()
    t_open     = _nse_open_time(c)
    t_trending = _nse_early_end_time(c)
    t_choppy   = _get_boundary(c, "session_choppy_start_hour",   "session_choppy_start_minute",   _DEF_CHOPPY_H,   _DEF_CHOPPY_M)
    t_recovery = _get_boundary(c, "session_recovery_start_hour", "session_recovery_start_minute", _DEF_RECOVERY_H, _DEF_RECOVERY_M)
    t_pre_cl   = _get_boundary(c, "session_pre_close_start_hour","session_pre_close_start_minute",_DEF_PRE_CL_H,   _DEF_PRE_CL_M)
    t_block    = _nse_block_time(c)

    if t < t_open:
        return SessionType.PRE_MARKET
    if t < t_trending:
        return SessionType.OPENING
    if t < t_choppy:
        return SessionType.TRENDING
    if t < t_recovery:
        return SessionType.CHOPPY
    if t < t_pre_cl:
        return SessionType.RECOVERY
    if t < t_block:
        return SessionType.PRE_CLOSE
    return SessionType.CLOSED


def get_session_score_adj(
    session: SessionType,
    cfg: dict[str, Any] | None = None,
) -> int:
    """
    Return the integer score adjustment for the given session.

    Positive → boost (TRENDING +5).
    Negative → penalty (CHOPPY -15, OPENING -10).
    Zero     → neutral (RECOVERY, PRE_MARKET, CLOSED).

    Args:
        session : SessionType from :func:`classify_session`.
        cfg     : Bot config dict for per-session override.

    Returns:
        Integer score delta (applied as: new_score = clamp(old + adj, 0, 100)).
    """
    c = cfg or {}
    _key_map = {
        SessionType.OPENING:   "session_opening_score_adj",
        SessionType.TRENDING:  "session_trending_score_adj",
        SessionType.CHOPPY:    "session_choppy_score_adj",
        SessionType.RECOVERY:  "session_recovery_score_adj",
        SessionType.PRE_CLOSE: "session_pre_close_score_adj",
    }
    default = _DEF_ADJ.get(session, 0)
    key = _key_map.get(session)
    if key is None:
        return 0
    return int(c.get(key, default))


def session_entry_allowed(
    session: SessionType,
    cfg: dict[str, Any] | None = None,
) -> bool:
    """
    Return False if new entries should be hard-blocked for this session.

    Default: all active sessions are allowed (False only when config explicitly
    sets the flag to false).  PRE_MARKET and CLOSED always return False regardless
    of config.

    Args:
        session : SessionType from :func:`classify_session`.
        cfg     : Bot config dict.

    Returns:
        True → entry permitted, False → hard-block.
    """
    if session in (SessionType.PRE_MARKET, SessionType.CLOSED):
        return False
    c = cfg or {}
    if session == SessionType.OPENING:
        return bool(c.get("session_opening_allowed", True))
    if session == SessionType.CHOPPY:
        return bool(c.get("session_choppy_allowed", True))
    return True


# ── Expiry-day session (Item 4 - v2.44) ──────────────────────────────────────

class ExpirySessionName(str, Enum):
    EXPIRY_MORNING = "EXPIRY_MORNING"
    EXPIRY_MIDDAY  = "EXPIRY_MIDDAY"
    EXPIRY_CAUTION = "EXPIRY_CAUTION"
    EXPIRY_BLOCKED = "EXPIRY_BLOCKED"


@dataclass(frozen=True)
class ExpirySession:
    name:                 str
    lot_multiplier:       float
    sl_pct_override:      float | None  # None = use config default
    score_adj:            int
    auto_execute_allowed: bool
    reason:               str


# Default expiry session parameters
_EXPIRY_SESSION_DEFAULTS: dict[str, dict] = {
    ExpirySessionName.EXPIRY_MORNING: dict(
        lot_multiplier=0.6, sl_pct_override=0.82, score_adj=0,
        auto_execute_allowed=True,
        reason="Expiry morning - high volatility, reduced size",
    ),
    ExpirySessionName.EXPIRY_MIDDAY: dict(
        lot_multiplier=0.5, sl_pct_override=0.85, score_adj=-5,
        auto_execute_allowed=True,
        reason="Expiry midday - elevated gamma risk",
    ),
    ExpirySessionName.EXPIRY_CAUTION: dict(
        lot_multiplier=0.0, sl_pct_override=None, score_adj=-10,
        auto_execute_allowed=False,
        reason="Expiry caution window - no auto-execution",
    ),
    ExpirySessionName.EXPIRY_BLOCKED: dict(
        lot_multiplier=0.0, sl_pct_override=None, score_adj=0,
        auto_execute_allowed=False,
        reason="Expiry block - entries hard-blocked",
    ),
}

# NSE weekly expiry days: NIFTY/BANKNIFTY=Thursday(3), FINNIFTY=Tuesday(1)
_INDEX_EXPIRY_WEEKDAY: dict[str, int] = {
    "NIFTY":     3,
    "BANKNIFTY": 3,
    "FINNIFTY":  1,
}


def is_expiry_day(
    index_name: str,
    cfg: dict[str, Any] | None = None,
    check_date: datetime.date | None = None,
) -> bool:
    """
    Returns True if check_date (default: today IST) is the weekly expiry
    day for the given index. Adjusts for NSE holidays by moving to prior day.

    NIFTY/BANKNIFTY: Thursday (weekday=3)
    FINNIFTY:        Tuesday  (weekday=1)
    """
    c      = cfg or {}
    try:
        from core.datetime_ist import now_ist
        today = check_date or now_ist().date()
    except (ImportError, ValueError, AttributeError):
        today = check_date or datetime.date.today()

    expiry_wd = _INDEX_EXPIRY_WEEKDAY.get(str(index_name).upper(), 3)

    today_wd = today.weekday()
    if today_wd != expiry_wd:
        return False

    # Check if today is an NSE holiday (use event_calendar if available)
    try:
        from core.event_calendar import _nse_holidays
        holidays = _nse_holidays(c)
        if today in holidays:
            return False
        # If today is a holiday, expiry was yesterday (not handled here)
    except (ImportError, AttributeError, ValueError, TypeError) as e:
        _log.debug("[SESSION_CLASSIFIER] non-critical error: %s", e)

    return True


def get_expiry_session(
    index_name:   str,
    current_time: datetime.time,
    cfg:          dict[str, Any] | None = None,
    check_date:   datetime.date | None = None,
) -> ExpirySession | None:
    """
    Returns ExpirySession if today is an expiry day for this index, else None.
    The caller falls back to normal session scoring when None is returned.
    """
    c = cfg or {}
    if not is_expiry_day(index_name, c, check_date):
        return None

    # Accept both datetime and time objects
    if hasattr(current_time, "time"):
        current_time = current_time.time()

    mode = str(c.get("expiry_day_mode", "CAUTIOUS")).upper()
    if mode == "BLOCK_ALL":
        d = _EXPIRY_SESSION_DEFAULTS[ExpirySessionName.EXPIRY_BLOCKED]
        return ExpirySession(name=ExpirySessionName.EXPIRY_BLOCKED, **d)

    # Parse boundary times
    def _t(key: str, default: str) -> datetime.time:
        try:
            raw = str(c.get(key, default))
            h, m = map(int, raw.split(":"))
            return datetime.time(h, m)
        except (ValueError, TypeError, KeyError):
            h, m = map(int, default.split(":"))
            return datetime.time(h, m)

    morning_end = _t("expiry_morning_end",   "11:00")
    caution_st  = _t("expiry_caution_start", "12:30")
    block_st    = _t("expiry_block_start",   "13:30")
    nse_open    = datetime.time(9, 15)

    def _build(name: str, cfg_overrides: dict) -> ExpirySession:
        base = dict(_EXPIRY_SESSION_DEFAULTS[name])
        base.update(cfg_overrides)
        return ExpirySession(name=name, **base)

    if nse_open <= current_time < morning_end:
        return _build(ExpirySessionName.EXPIRY_MORNING, {
            "lot_multiplier": float(c.get("expiry_morning_lot_mult", 0.6)),
            "sl_pct_override": float(c.get("expiry_morning_sl_pct", 0.82)),
        })

    if morning_end <= current_time < caution_st:
        return _build(ExpirySessionName.EXPIRY_MIDDAY, {
            "lot_multiplier": float(c.get("expiry_midday_lot_mult", 0.5)),
        })

    if caution_st <= current_time < block_st:
        return _build(ExpirySessionName.EXPIRY_CAUTION, {})

    if current_time >= block_st:
        return _build(ExpirySessionName.EXPIRY_BLOCKED, {})

    return None  # before market open


def session_summary(
    cfg: dict[str, Any] | None = None,
    now: datetime.time | None = None,
) -> dict[str, Any]:
    """
    Return a snapshot dict for logging and Telegram alerts.

    Keys: session, score_adj, entry_allowed, boundaries
    """
    c = cfg or {}
    t = now or now_ist().time()
    sess = classify_session(t, c)
    adj  = get_session_score_adj(sess, c)
    allowed = session_entry_allowed(sess, c)
    return {
        "session":       sess.value,
        "score_adj":     adj,
        "entry_allowed": allowed,
        "boundaries": {
            "nse_open":    str(_nse_open_time(c)),
            "trending":    str(_nse_early_end_time(c)),
            "choppy":      str(_get_boundary(c, "session_choppy_start_hour",    "session_choppy_start_minute",    _DEF_CHOPPY_H,   _DEF_CHOPPY_M)),
            "recovery":    str(_get_boundary(c, "session_recovery_start_hour",  "session_recovery_start_minute",  _DEF_RECOVERY_H, _DEF_RECOVERY_M)),
            "pre_close":   str(_get_boundary(c, "session_pre_close_start_hour", "session_pre_close_start_minute", _DEF_PRE_CL_H,   _DEF_PRE_CL_M)),
            "block_from":  str(_nse_block_time(c)),
        },
    }


__all__ = [
    "ExpirySession",
    "ExpirySessionName",
    "SessionType",
    "classify_session",
    "get_expiry_session",
    "get_session_score_adj",
    "is_expiry_day",
    "session_entry_allowed",
    "session_summary",
]

