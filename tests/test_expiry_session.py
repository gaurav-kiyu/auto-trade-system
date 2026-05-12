"""Tests for expiry day session functions in core/session_classifier.py (v2.44 Item 4)."""
import pytest
from datetime import datetime, date
from unittest.mock import patch
from core.session_classifier import (
    ExpirySession,
    ExpirySessionName,
    is_expiry_day,
    get_expiry_session,
)

CFG = {
    "expiry_day_mode": "CAUTIOUS",
    "expiry_morning_end": "11:00",
    "expiry_morning_lot_mult": 0.6,
    "expiry_morning_sl_pct": 0.82,
    "expiry_midday_lot_mult": 0.5,
    "expiry_caution_start": "12:30",
    "expiry_block_start": "13:30",
    "EXPIRY_CUTOFF_HOUR": 13,
    "EXPIRY_CUTOFF_MIN": 30,
}

# Known expiry dates:
# NIFTY/BANKNIFTY: Thursday (weekday=3)
# FINNIFTY: Tuesday (weekday=1)

THURSDAY = date(2024, 1, 4)   # Thursday
TUESDAY  = date(2024, 1, 2)   # Tuesday
MONDAY   = date(2024, 1, 1)   # Monday
FRIDAY   = date(2024, 1, 5)   # Friday


# ── is_expiry_day ─────────────────────────────────────────────────────────────

def test_nifty_expiry_on_thursday():
    assert is_expiry_day("NIFTY", CFG, check_date=THURSDAY) is True


def test_banknifty_expiry_on_thursday():
    assert is_expiry_day("BANKNIFTY", CFG, check_date=THURSDAY) is True


def test_finnifty_expiry_on_tuesday():
    assert is_expiry_day("FINNIFTY", CFG, check_date=TUESDAY) is True


def test_nifty_not_expiry_on_tuesday():
    assert is_expiry_day("NIFTY", CFG, check_date=TUESDAY) is False


def test_finnifty_not_expiry_on_thursday():
    assert is_expiry_day("FINNIFTY", CFG, check_date=THURSDAY) is False


def test_nifty_not_expiry_on_monday():
    assert is_expiry_day("NIFTY", CFG, check_date=MONDAY) is False


def test_banknifty_not_expiry_on_friday():
    assert is_expiry_day("BANKNIFTY", CFG, check_date=FRIDAY) is False


def test_unknown_index_defaults_to_thursday():
    # Unknown index defaults to weekday 3 (Thursday) — so True on Thursday
    assert is_expiry_day("SENSEX", CFG, check_date=THURSDAY) is True
    # And False on non-Thursday
    assert is_expiry_day("SENSEX", CFG, check_date=MONDAY) is False


# ── get_expiry_session ────────────────────────────────────────────────────────

def _dt(h, m, check_date=THURSDAY):
    return datetime(check_date.year, check_date.month, check_date.day, h, m)


def test_returns_none_on_non_expiry_day():
    t = _dt(10, 0, MONDAY)
    result = get_expiry_session("NIFTY", t, CFG, check_date=MONDAY)
    assert result is None


def test_expiry_morning_session():
    t = _dt(9, 30)
    s = get_expiry_session("NIFTY", t, CFG, check_date=THURSDAY)
    assert s is not None
    assert s.name == ExpirySessionName.EXPIRY_MORNING


def test_expiry_morning_lot_mult():
    t = _dt(10, 45)
    s = get_expiry_session("NIFTY", t, CFG, check_date=THURSDAY)
    assert s.lot_multiplier == pytest.approx(0.6)


def test_expiry_morning_sl_override():
    t = _dt(10, 0)
    s = get_expiry_session("NIFTY", t, CFG, check_date=THURSDAY)
    assert s.sl_pct_override == pytest.approx(0.82)


def test_expiry_midday_session():
    t = _dt(11, 30)
    s = get_expiry_session("NIFTY", t, CFG, check_date=THURSDAY)
    assert s is not None
    assert s.name == ExpirySessionName.EXPIRY_MIDDAY


def test_expiry_midday_lot_mult():
    t = _dt(12, 0)
    s = get_expiry_session("NIFTY", t, CFG, check_date=THURSDAY)
    assert s.lot_multiplier == pytest.approx(0.5)


def test_expiry_caution_session():
    t = _dt(12, 45)
    s = get_expiry_session("NIFTY", t, CFG, check_date=THURSDAY)
    assert s is not None
    assert s.name == ExpirySessionName.EXPIRY_CAUTION


def test_expiry_caution_no_auto_execute():
    t = _dt(13, 0)
    s = get_expiry_session("NIFTY", t, CFG, check_date=THURSDAY)
    assert s.auto_execute_allowed is False


def test_expiry_blocked_session():
    t = _dt(13, 45)
    s = get_expiry_session("NIFTY", t, CFG, check_date=THURSDAY)
    assert s is not None
    assert s.name == ExpirySessionName.EXPIRY_BLOCKED


def test_expiry_blocked_no_auto_execute():
    t = _dt(14, 30)
    s = get_expiry_session("NIFTY", t, CFG, check_date=THURSDAY)
    assert s.auto_execute_allowed is False


def test_finnifty_session_on_tuesday():
    t = _dt(10, 0, TUESDAY)
    s = get_expiry_session("FINNIFTY", t, CFG, check_date=TUESDAY)
    assert s is not None
    assert s.name == ExpirySessionName.EXPIRY_MORNING


# ── ExpirySession dataclass ───────────────────────────────────────────────────

def test_expiry_session_has_all_fields():
    t = _dt(10, 0)
    s = get_expiry_session("NIFTY", t, CFG, check_date=THURSDAY)
    assert hasattr(s, "name")
    assert hasattr(s, "lot_multiplier")
    assert hasattr(s, "sl_pct_override")
    assert hasattr(s, "score_adj")
    assert hasattr(s, "auto_execute_allowed")
    assert hasattr(s, "reason")


def test_expiry_session_reason_is_string():
    t = _dt(10, 0)
    s = get_expiry_session("NIFTY", t, CFG, check_date=THURSDAY)
    assert isinstance(s.reason, str)
    assert len(s.reason) > 0
