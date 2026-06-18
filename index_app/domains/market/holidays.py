"""NSE Holiday fetching — dynamic API fetch with hardcoded fallback.

Extracted from ``index_trader.py`` ``_fetch_nse_holidays_dynamic()``.
"""

from __future__ import annotations

import logging
from typing import Any

import requests

from core.datetime_ist import now_ist

_log = logging.getLogger(__name__)

# Hardcoded fallback for 2026 NSE trading holidays in case API fetch fails
_NSE_HOLIDAYS_FALLBACK: set[str] = {
    "2026-01-26",  # Republic Day
    "2026-03-27",  # Good Friday
    "2026-04-14",  # Dr. Ambedkar Jayanti
    "2026-05-01",  # Maharashtra Day
    "2026-08-17",  # Parsi New Year
    "2026-10-02",  # Mahatma Gandhi Jayanti
    "2026-10-09",  # Dussehra
    "2026-10-28",  # Diwali - Laxmi Pujan
    "2026-10-29",  # Diwali - Balipratipada (observed)
    "2026-11-16",  # Guru Nanak Jayanti
    "2026-12-25",  # Christmas
}


def fetch_nse_holidays(
    nse_session: requests.Session | None = None,
    existing_holidays: set[str] | None = None,
    existing_years: set[str] | None = None,
    fetch_meta: dict[str, Any] | None = None,
) -> tuple[set[str], set[str], dict[str, Any]]:
    """Fetch NSE trading holidays from the NSE holiday-master API.

    Falls back to hardcoded 2026 holidays if the API is unreachable or returns
    a non-JSON response.

    Args:
        nse_session: A ``requests.Session`` with NSE headers.
            If ``None``, a default session is created.
        existing_holidays: Existing set of holiday dates to extend.
            If ``None``, a new set is created and prepopulated with the fallback.
        existing_years: Existing set of years for which holidays exist.
            If ``None``, a new set is created.
        fetch_meta: Existing metadata dict. If ``None``, a new dict is created.

    Returns:
        ``(holidays, holiday_years, fetch_meta)`` where:
        - ``holidays``: set of ISO-format date strings (e.g. "2026-01-26")
        - ``holiday_years``: set of year strings (e.g. "2026")
        - ``fetch_meta``: dict with keys ``count``, ``fallback``, ``note``
    """
    if existing_holidays is None:
        existing_holidays = set(_NSE_HOLIDAYS_FALLBACK)
    if existing_years is None:
        existing_years = {d[:4] for d in _NSE_HOLIDAYS_FALLBACK}
    if fetch_meta is None:
        fetch_meta = {"count": len(existing_holidays), "fallback": True, "note": "initialised"}

    if nse_session is None:
        nse_session = requests.Session()
        nse_session.headers.update({
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json, text/plain, */*",
        })

    try:
        resp = nse_session.get(
            "https://www.nseindia.com/api/holiday-master?type=trading",
            timeout=15,
        )
        if resp.status_code != 200:
            raise ValueError(f"Non-200 response: {resp.status_code}")

        try:
            data = resp.json()
            holidays = set()
            # Handle "holidays" key (live API format) and "Special" key (fixture format)
            holiday_lists = list(data.get("holidays", [])) + list(data.get("Special", []))
            for item in holiday_lists:
                date = str(item.get("date", item.get("tradingDate", ""))).strip()
                if not date:
                    continue
                # Convert from Indian format "31-Dec-2026" to ISO "2026-12-31"
                if "-" in date:
                    parts = date.split("-")
                    if len(parts) == 3:
                        day, month_abbr, year = parts
                        month_map = {
                            "Jan": "01", "Feb": "02", "Mar": "03", "Apr": "04",
                            "May": "05", "Jun": "06", "Jul": "07", "Aug": "08",
                            "Sep": "09", "Oct": "10", "Nov": "11", "Dec": "12",
                        }
                        month = month_map.get(month_abbr, "01")
                        iso_date = f"{year}-{month}-{day}"
                        holidays.add(iso_date)
                else:
                    holidays.add(date)

            existing_holidays.update(holidays)
            existing_years.update({d[:4] for d in holidays})
            fetch_meta["fallback"] = False
            fetch_meta["note"] = "ok"
        except (ValueError, TypeError, KeyError, AttributeError, IndexError, OSError, AssertionError) as _parse_err:
            _log.warning("NSE holiday API returned non-JSON response: %s", _parse_err)
            fetch_meta["fallback"] = True
            fetch_meta["note"] = "non-json"
            _apply_fallback(existing_holidays, existing_years, fetch_meta)
    except (ValueError, TypeError, KeyError, AttributeError, IndexError, OSError):
        fetch_meta["fallback"] = True
        fetch_meta["note"] = "fetch-failed"
        _apply_fallback(existing_holidays, existing_years, fetch_meta)

    fetch_meta["count"] = len(existing_holidays)
    _warn_missing_year(existing_years, fetch_meta)
    return existing_holidays, existing_years, fetch_meta


def _apply_fallback(
    existing_holidays: set[str],
    existing_years: set[str],
    fetch_meta: dict[str, Any],
) -> None:
    """Apply hardcoded fallback holidays when API fetch fails."""
    if not existing_holidays:
        existing_holidays.update(_NSE_HOLIDAYS_FALLBACK)
        existing_years.update({d[:4] for d in _NSE_HOLIDAYS_FALLBACK})
        fetch_meta["fallback_applied"] = True
        _log.info("Applied hardcoded fallback holidays (%d dates)", len(_NSE_HOLIDAYS_FALLBACK))


def _warn_missing_year(
    holiday_years: set[str],
    fetch_meta: dict[str, Any],
) -> None:
    """Log a warning if the current year is missing from holiday data."""
    current_year = str(now_ist().year)
    if current_year not in holiday_years and not fetch_meta.get("_year_warning_logged"):
        _log.warning(
            "NSE holidays for %s not found. "
            "Holiday detection may not work. Years available: %s",
            current_year,
            sorted(holiday_years),
        )
        fetch_meta["_year_warning_logged"] = True
