"""
Tests for Phase 7D — NSE Event Calendar (core/event_calendar.py).

Covers:
  - get_event: returns None when disabled, None on non-event day, record on event day
  - event_entry_allowed: pass-through when no event; blocks when block_entries=True
  - event_size_multiplier: 1.0 on non-event day; per-event mult; clamped to [0,1]
  - event_summary: correct keys in both cases
  - _parse_event_dates: skips malformed entries gracefully
  - Global fallback defaults for block_entries and size_mult
"""
from __future__ import annotations

import datetime
import pytest

from core.event_calendar import (
    get_event,
    event_entry_allowed,
    event_size_multiplier,
    event_summary,
    EventRecord,
)

TODAY = datetime.date(2026, 2, 1)
NON_EVENT_DATE = datetime.date(2026, 3, 15)

BUDGET_EVENT = {
    "date": "2026-02-01",
    "type": "BUDGET",
    "name": "Union Budget",
    "block_entries": True,
    "size_mult": 0.5,
}

RBI_EVENT = {
    "date": "2026-04-10",
    "type": "RBI",
    "name": "RBI MPC",
    "block_entries": False,
    "size_mult": 0.75,
}

CFG_WITH_EVENTS = {
    "event_calendar_enabled": True,
    "event_dates": [BUDGET_EVENT, RBI_EVENT],
    "event_day_block_entries": False,
    "event_day_size_mult": 1.0,
}

CFG_DISABLED = {
    "event_calendar_enabled": False,
    "event_dates": [BUDGET_EVENT],
}


# ── get_event ──────────────────────────────────────────────────────────────────

class TestGetEvent:
    def test_returns_none_when_disabled(self):
        assert get_event(TODAY, CFG_DISABLED) is None

    def test_returns_none_on_non_event_day(self):
        assert get_event(NON_EVENT_DATE, CFG_WITH_EVENTS) is None

    def test_returns_record_on_event_day(self):
        rec = get_event(TODAY, CFG_WITH_EVENTS)
        assert rec is not None
        assert isinstance(rec, EventRecord)

    def test_record_has_correct_fields(self):
        rec = get_event(TODAY, CFG_WITH_EVENTS)
        assert rec.date == TODAY
        assert rec.event_type == "BUDGET"
        assert rec.name == "Union Budget"
        assert rec.block_entries is True
        assert rec.size_mult == 0.5

    def test_returns_none_with_empty_event_dates(self):
        cfg = {"event_calendar_enabled": True, "event_dates": []}
        assert get_event(TODAY, cfg) is None

    def test_returns_none_with_no_cfg(self):
        assert get_event(NON_EVENT_DATE, None) is None

    def test_second_event_day_works(self):
        rbi_date = datetime.date(2026, 4, 10)
        rec = get_event(rbi_date, CFG_WITH_EVENTS)
        assert rec is not None
        assert rec.event_type == "RBI"


# ── event_entry_allowed ────────────────────────────────────────────────────────

class TestEventEntryAllowed:
    def test_allowed_on_non_event_day(self):
        ok, reason = event_entry_allowed(NON_EVENT_DATE, CFG_WITH_EVENTS)
        assert ok is True
        assert reason == ""

    def test_blocked_when_block_entries_true(self):
        ok, reason = event_entry_allowed(TODAY, CFG_WITH_EVENTS)
        assert ok is False
        assert "BUDGET" in reason
        assert "Union Budget" in reason

    def test_allowed_when_block_entries_false(self):
        rbi_date = datetime.date(2026, 4, 10)
        ok, reason = event_entry_allowed(rbi_date, CFG_WITH_EVENTS)
        assert ok is True
        assert reason == ""

    def test_allowed_when_calendar_disabled(self):
        ok, _ = event_entry_allowed(TODAY, CFG_DISABLED)
        assert ok is True

    def test_allowed_with_no_cfg(self):
        ok, _ = event_entry_allowed(NON_EVENT_DATE, None)
        assert ok is True


# ── event_size_multiplier ──────────────────────────────────────────────────────

class TestEventSizeMultiplier:
    def test_returns_1_on_non_event_day(self):
        assert event_size_multiplier(NON_EVENT_DATE, CFG_WITH_EVENTS) == 1.0

    def test_returns_event_mult_on_event_day(self):
        mult = event_size_multiplier(TODAY, CFG_WITH_EVENTS)
        assert mult == 0.5

    def test_returns_1_when_calendar_disabled(self):
        assert event_size_multiplier(TODAY, CFG_DISABLED) == 1.0

    def test_mult_clamped_above_1(self):
        cfg = {
            "event_calendar_enabled": True,
            "event_dates": [{"date": str(TODAY), "type": "CUSTOM", "name": "X", "size_mult": 1.5}],
        }
        assert event_size_multiplier(TODAY, cfg) == 1.0

    def test_mult_clamped_below_0(self):
        cfg = {
            "event_calendar_enabled": True,
            "event_dates": [{"date": str(TODAY), "type": "CUSTOM", "name": "X", "size_mult": -0.3}],
        }
        assert event_size_multiplier(TODAY, cfg) == 0.0

    def test_rbi_event_mult(self):
        rbi_date = datetime.date(2026, 4, 10)
        mult = event_size_multiplier(rbi_date, CFG_WITH_EVENTS)
        assert mult == 0.75


# ── event_summary ──────────────────────────────────────────────────────────────

class TestEventSummary:
    def test_summary_non_event_day(self):
        s = event_summary(NON_EVENT_DATE, CFG_WITH_EVENTS)
        assert s["is_event_day"] is False
        assert "date" in s

    def test_summary_event_day_keys(self):
        s = event_summary(TODAY, CFG_WITH_EVENTS)
        for key in ("is_event_day", "date", "type", "name", "block_entries", "size_mult"):
            assert key in s, f"Missing key: {key}"

    def test_summary_event_day_values(self):
        s = event_summary(TODAY, CFG_WITH_EVENTS)
        assert s["is_event_day"] is True
        assert s["type"] == "BUDGET"
        assert s["block_entries"] is True
        assert s["size_mult"] == 0.5


# ── Malformed event entries ────────────────────────────────────────────────────

class TestMalformedEventEntries:
    def test_skips_invalid_date(self):
        cfg = {
            "event_calendar_enabled": True,
            "event_dates": [
                {"date": "not-a-date", "type": "CUSTOM", "name": "Bad"},
                BUDGET_EVENT,
            ],
        }
        rec = get_event(TODAY, cfg)
        assert rec is not None  # valid entry still processed

    def test_skips_missing_date_key(self):
        cfg = {
            "event_calendar_enabled": True,
            "event_dates": [{"type": "CUSTOM", "name": "No Date"}, BUDGET_EVENT],
        }
        rec = get_event(TODAY, cfg)
        assert rec is not None


# ── Global fallback defaults ───────────────────────────────────────────────────

class TestGlobalFallbackDefaults:
    def test_global_block_entries_applied_when_event_has_no_block_key(self):
        cfg = {
            "event_calendar_enabled": True,
            "event_day_block_entries": True,
            "event_day_size_mult": 0.6,
            "event_dates": [{"date": str(TODAY), "type": "CUSTOM", "name": "Evt"}],
        }
        rec = get_event(TODAY, cfg)
        assert rec.block_entries is True
        assert rec.size_mult == 0.6

    def test_per_event_overrides_global(self):
        cfg = {
            "event_calendar_enabled": True,
            "event_day_block_entries": True,
            "event_day_size_mult": 0.6,
            "event_dates": [BUDGET_EVENT],  # block_entries=True, size_mult=0.5
        }
        rec = get_event(TODAY, cfg)
        # Per-event block_entries and size_mult take precedence
        assert rec.block_entries is True
        assert rec.size_mult == 0.5
