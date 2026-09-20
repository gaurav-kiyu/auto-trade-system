"""Data Freshness Guard - validates market data freshness before trading.

Ensures trading decisions are based on current, not stale data.
Configurable via config keys:

    data_freshness_max_age_1m_sec   : int   default 90   (1m bar max age in sec)
    data_freshness_max_age_5m_sec   : int   default 300  (5m bar max age in sec)
    data_freshness_max_age_15m_sec  : int   default 600  (15m bar max age in sec)
    data_freshness_vix_max_age_sec  : int   default 300  (VIX data max age in sec)
    data_freshness_guard_enabled    : bool  default true

NOTE: Setting data_freshness_guard_enabled to false logs a WARNING and still
refuses to trade. The guard cannot be disabled via configuration - this is a
safety invariant enforced by code.
"""
from __future__ import annotations

import datetime
import logging
import time
from dataclasses import dataclass
from typing import Any

from core.datetime_ist import now_ist
from core.exchange_calendar_engine import ExchangeCalendarEngine, ExtendedMarketStatus

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class FreshnessResult:
    passed: bool
    stalest_bar_sec: float = 0.0
    stalest_bar_name: str = ""
    reject_reason: str = ""
    reject_code: str = ""


def _parse_bar_timestamp(val: Any) -> float | None:
    """Safely parse a bar timestamp from index or column to unix epoch seconds.

    Handles tz-naive (assumes IST Asia/Kolkata), tz-aware (converts to epoch),
    numeric epochs, and pandas/string timestamps.
    """
    if val is None:
        return None
    # Check for pandas NaT
    if hasattr(val, "value") and getattr(val, "value") == -9223372036854775808:
        return None
    try:
        # pd.Timestamp or datetime.datetime
        if hasattr(val, "timestamp") and callable(val.timestamp):
            # If tz-naive, localize to Asia/Kolkata (IST) to prevent 5.5-hour UTC interpretation skew
            if getattr(val, "tzinfo", None) is None:
                if hasattr(val, "tz_localize"):
                    val = val.tz_localize("Asia/Kolkata")
                else:
                    ist_tz = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
                    val = val.replace(tzinfo=ist_tz)
            ts = float(val.timestamp())
            if ts != ts:  # NaN check
                return None
            return ts
    except Exception:
        pass
    try:
        # Numeric epoch
        f_val = float(val)
        if f_val != f_val or f_val <= 0:
            return None
        # If timestamp is in milliseconds (e.g. > 1e11)
        if f_val > 1e11:
            f_val /= 1000.0
        return f_val
    except (ValueError, TypeError):
        pass
    try:
        # ISO / String timestamp
        import pandas as pd
        dt = pd.to_datetime(val, errors="coerce")
        if pd.isna(dt):
            return None
        if dt.tzinfo is None:
            dt = dt.tz_localize("Asia/Kolkata")
        return float(dt.timestamp())
    except Exception:
        return None


def check_data_freshness(
    frames: dict[str, Any] | None = None,
    vix_ts: float | None = None,
    cfg: dict[str, Any] | None = None,
    current_time: float | datetime.datetime | None = None,
    calendar_engine: ExchangeCalendarEngine | None = None,
    session_aware: bool | None = None,
    allow_off_market: bool = True,
) -> FreshnessResult:
    """Check that all market data frames are recent enough for trading.

    The freshness guard is ALWAYS active regardless of config setting.
    If data_freshness_guard_enabled=false is set, a WARNING is logged and
    the guard still enforces freshness checks. This is a safety invariant.

    Args:
        frames: Dict of {timeframe_name: DataFrame} with a DatetimeIndex or
                'timestamp' column. Normalizes 'df1m'->'1m', 'df5m'->'5m', etc.
        vix_ts: Unix timestamp of the last VIX data point.
        cfg: Config dict.
        current_time: Optional explicit timestamp for testing/replay.
        calendar_engine: Optional ExchangeCalendarEngine for market session awareness.
        session_aware: Whether to apply session awareness (defaults to True if calendar_engine
                       or session_aware_freshness config is set, else False for base checks).
        allow_off_market: If True and session_aware is active, relaxes stale-age rejection
                          when the exchange is closed.

    Returns:
        FreshnessResult with passed=True if all data is fresh and structurally valid.
    """
    c = cfg or {}
    if not c.get("data_freshness_guard_enabled", True):
        _log.warning(
            "data_freshness_guard_enabled=false is IGNORED - freshness guard "
            "is always active for safety. Set it to true in config to suppress this warning.",
        )

    max_ages = {
        "1m":  int(c.get("data_freshness_max_age_1m_sec",  90)),
        "5m":  int(c.get("data_freshness_max_age_5m_sec",  300)),
        "15m": int(c.get("data_freshness_max_age_15m_sec", 600)),
    }

    if not frames:
        return FreshnessResult(
            False,
            reject_reason="no market data frames available",
            reject_code="INVALID_MARKET_DATA",
        )

    # Determine reference current time
    if current_time is None:
        now_epoch = time.time()
        now_dt = now_ist()
    elif isinstance(current_time, (int, float)):
        now_epoch = float(current_time)
        now_dt = datetime.datetime.fromtimestamp(now_epoch, tz=now_ist().tzinfo)
    elif isinstance(current_time, datetime.datetime):
        now_dt = current_time if current_time.tzinfo else current_time.replace(tzinfo=now_ist().tzinfo)
        now_epoch = now_dt.timestamp()
    else:
        now_epoch = time.time()
        now_dt = now_ist()

    # Session awareness check
    use_session_aware = session_aware
    if use_session_aware is None:
        use_session_aware = bool(calendar_engine is not None or c.get("session_aware_freshness", False))

    is_active_session = True
    if use_session_aware:
        engine = calendar_engine or ExchangeCalendarEngine(c)
        market_status = engine.get_market_status(now_dt)
        is_active_session = market_status in (
            ExtendedMarketStatus.OPEN,
            ExtendedMarketStatus.HALF_DAY,
            ExtendedMarketStatus.MUHURAT,
        )

    # Normalize timeframe keys: df1m -> 1m, df5m -> 5m, df15m -> 15m
    normalized_frames: dict[str, Any] = {}
    for k, v in frames.items():
        norm_k = k.lower().replace("df", "")
        normalized_frames[norm_k] = v

    # Sparse 1m fallback: If 1m is missing or empty, but 5m is present,
    # evaluate primary freshness on 5m.
    if ("1m" not in normalized_frames or normalized_frames["1m"] is None or getattr(normalized_frames["1m"], "empty", True)) and "5m" in normalized_frames:
        eval_frames = {k: v for k, v in normalized_frames.items() if k != "1m"}
    else:
        eval_frames = normalized_frames

    stalest_bar_sec = 0.0
    stalest_bar_name = ""

    for name, df in eval_frames.items():
        max_age = max_ages.get(name, 300)
        if df is None or getattr(df, "empty", True):
            return FreshnessResult(
                False,
                reject_reason=f"{name} bar is empty",
                reject_code="INVALID_MARKET_DATA",
            )

        # Extract timestamp: check timestamp column first, or DatetimeIndex
        last_val = None
        for col in ("timestamp", "Datetime", "Date", "datetime", "time"):
            if col in getattr(df, "columns", []):
                try:
                    last_val = df[col].iloc[-1]
                    break
                except Exception:
                    pass

        if last_val is None and hasattr(df, "index") and len(df.index) > 0:
            import pandas as pd
            if isinstance(df.index, pd.DatetimeIndex) or hasattr(df.index[-1], "timestamp"):
                last_val = df.index[-1]
            elif isinstance(df.index[-1], str) and len(df.index[-1]) >= 10:
                last_val = df.index[-1]

        last_ts = _parse_bar_timestamp(last_val)
        if last_ts is None:
            return FreshnessResult(
                False,
                reject_reason=f"{name} bar has no timestamp or timestamp is malformed",
                reject_code="INVALID_MARKET_DATA",
            )

        # Future timestamp check (allowing 60s clock skew)
        if last_ts > now_epoch + 60.0:
            return FreshnessResult(
                False,
                stalest_bar_sec=last_ts - now_epoch,
                stalest_bar_name=name,
                reject_reason=f"{name} bar timestamp is in the future ({last_ts - now_epoch:.0f}s ahead)",
                reject_code="INVALID_MARKET_DATA",
            )

        age = now_epoch - last_ts

        # Check staleness: if session_aware is active and exchange is closed, allow_off_market relaxes the age check
        if use_session_aware and not is_active_session and allow_off_market:
            pass  # Off-market reference allowed without age rejection
        elif age > max_age:
            return FreshnessResult(
                False,
                stalest_bar_sec=age,
                stalest_bar_name=name,
                reject_reason=f"{name} bar age {age:.0f}s exceeds {max_age}s limit",
                reject_code="STALE_MARKET_DATA",
            )

        if age > stalest_bar_sec:
            stalest_bar_sec = age
            stalest_bar_name = name

    if vix_ts is not None:
        vix_max_age = int(c.get("data_freshness_vix_max_age_sec", 300))
        vix_age = now_epoch - vix_ts
        if use_session_aware and not is_active_session and allow_off_market:
            pass
        elif vix_age > vix_max_age:
            return FreshnessResult(
                False,
                stalest_bar_sec=vix_age,
                stalest_bar_name="VIX",
                reject_reason=f"VIX age {vix_age:.0f}s exceeds {vix_max_age}s limit",
                reject_code="STALE_MARKET_DATA",
            )

    return FreshnessResult(
        True,
        stalest_bar_sec=stalest_bar_sec,
        stalest_bar_name=stalest_bar_name,
        reject_code="VALID",
    )


__all__ = [
    "FreshnessResult",
    "check_data_freshness",
]

