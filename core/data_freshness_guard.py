"""
Data Freshness Guard - validates market data freshness before trading.

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

import logging
import time
from dataclasses import dataclass
from typing import Any

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class FreshnessResult:
    passed: bool
    stalest_bar_sec: float = 0.0
    stalest_bar_name: str = ""
    reject_reason: str = ""


def check_data_freshness(
    frames: dict[str, Any] | None = None,
    vix_ts: float | None = None,
    cfg: dict[str, Any] | None = None,
) -> FreshnessResult:
    """Check that all market data frames are recent enough for trading.

    The freshness guard is ALWAYS active regardless of config setting.
    If data_freshness_guard_enabled=false is set, a WARNING is logged and
    the guard still enforces freshness checks. This is a safety invariant.

    Args:
        frames: Dict of {timeframe_name: DataFrame} with a DatetimeIndex or
                'timestamp' column. DatetimeIndex is preferred (no code change
                needed for yfinance/BrokerAdapter DataFrames).
        vix_ts: Unix timestamp of the last VIX data point.
        cfg: Config dict.

    Returns:
        FreshnessResult with passed=True if all data is fresh.
    """
    c = cfg or {}
    if not c.get("data_freshness_guard_enabled", True):
        _log.warning(
            "data_freshness_guard_enabled=false is IGNORED - freshness guard "
            "is always active for safety. Set it to true in config to suppress this warning."
        )

    max_ages = {
        "1m":  int(c.get("data_freshness_max_age_1m_sec",  90)),
        "5m":  int(c.get("data_freshness_max_age_5m_sec",  300)),
        "15m": int(c.get("data_freshness_max_age_15m_sec", 600)),
    }

    if not frames:
        return FreshnessResult(False, reject_reason="no market data frames available")

    now = time.time()
    stalest_bar_sec = 0.0
    stalest_bar_name = ""
    for name, df in frames.items():
        max_age = max_ages.get(name, 120)
        if df is None or df.empty:
            return FreshnessResult(False, reject_reason=f"{name} bar is empty")

        # Support both DatetimeIndex (yfinance/BrokerAdapter) and 'timestamp' column
        try:
            last_ts = float(df.index[-1].timestamp())
        except (KeyError, IndexError, TypeError, AttributeError):
            try:
                last_ts = float(df["timestamp"].iloc[-1])
            except (KeyError, IndexError, TypeError):
                return FreshnessResult(False, reject_reason=f"{name} bar has no timestamp")

        age = now - last_ts
        if age > max_age:
            return FreshnessResult(
                False,
                stalest_bar_sec=age,
                stalest_bar_name=name,
                reject_reason=f"{name} bar age {age:.0f}s exceeds {max_age}s limit",
            )
        if age > stalest_bar_sec:
            stalest_bar_sec = age
            stalest_bar_name = name

    if vix_ts is not None:
        vix_max_age = int(c.get("data_freshness_vix_max_age_sec", 300))
        vix_age = now - vix_ts
        if vix_age > vix_max_age:
            return FreshnessResult(
                False,
                stalest_bar_sec=vix_age,
                stalest_bar_name="VIX",
                reject_reason=f"VIX age {vix_age:.0f}s exceeds {vix_max_age}s limit",
            )

    return FreshnessResult(True, stalest_bar_sec=stalest_bar_sec, stalest_bar_name=stalest_bar_name)
