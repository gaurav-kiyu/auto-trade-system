"""Tests for corporate action calendar extension in core/event_calendar.py (v2.45 Item 15)."""
import datetime
import pytest
from core.event_calendar import (
    CorporateAction, fetch_corporate_actions, is_corp_action_day,
)


def _cfg(**kw):
    base = {
        "corp_action_calendar_enabled": True,
        "corp_action_data": [
            {"symbol": "HDFCBANK", "date": "2026-05-15", "type": "DIVIDEND", "factor": 2.0},
            {"symbol": "ICICIBANK", "date": "2026-06-01", "type": "SPLIT",    "factor": 2.0},
            {"symbol": "AXISBANK",  "date": "2026-04-30", "type": "BONUS",    "factor": 1.0},
        ],
    }
    base.update(kw)
    return base


# ── fetch_corporate_actions ───────────────────────────────────────────────────

def test_disabled_returns_empty():
    result = fetch_corporate_actions({"corp_action_calendar_enabled": False})
    assert result == []


def test_no_data_returns_empty():
    result = fetch_corporate_actions({"corp_action_calendar_enabled": True, "corp_action_data": []})
    assert result == []


def test_returns_list_of_corp_actions():
    result = fetch_corporate_actions(_cfg())
    assert all(isinstance(r, CorporateAction) for r in result)


def test_count_matches_data():
    result = fetch_corporate_actions(_cfg())
    assert len(result) == 3


def test_sorted_by_date():
    result = fetch_corporate_actions(_cfg())
    dates = [r.date for r in result]
    assert dates == sorted(dates)


def test_symbol_uppercased():
    cfg = {"corp_action_calendar_enabled": True,
           "corp_action_data": [{"symbol": "hdfcbank", "date": "2026-05-01",
                                  "type": "DIVIDEND", "factor": 1.0}]}
    result = fetch_corporate_actions(cfg)
    assert result[0].symbol == "HDFCBANK"


def test_bad_entry_skipped():
    cfg = {"corp_action_calendar_enabled": True,
           "corp_action_data": [{"symbol": "X", "date": "NOT-A-DATE",
                                  "type": "DIVIDEND", "factor": 1.0}]}
    result = fetch_corporate_actions(cfg)
    assert result == []


# ── is_corp_action_day ────────────────────────────────────────────────────────

def test_action_found_on_date():
    ok, desc = is_corp_action_day(
        "HDFCBANK",
        check_date=datetime.date(2026, 5, 15),
        cfg=_cfg(),
    )
    assert ok is True
    assert "HDFCBANK" in desc


def test_no_action_on_different_date():
    ok, _ = is_corp_action_day(
        "HDFCBANK",
        check_date=datetime.date(2026, 5, 16),
        cfg=_cfg(),
    )
    assert ok is False


def test_no_action_for_unlisted_symbol():
    ok, _ = is_corp_action_day(
        "RELIANCE",
        check_date=datetime.date(2026, 5, 15),
        cfg=_cfg(),
    )
    assert ok is False


def test_disabled_always_false():
    ok, _ = is_corp_action_day(
        "HDFCBANK",
        check_date=datetime.date(2026, 5, 15),
        cfg={"corp_action_calendar_enabled": False},
    )
    assert ok is False
