"""Tests for core/time_provider.py - Authoritative time source.

Covers:
- TimeProvider.now() returns IST timezone-aware datetime
- TimeProvider.today() returns correct date in IST
- TimeProvider.format_ts() standardized timestamp formatting
- TimeProvider.set_now_fn() overriding for deterministic testing
- IST constant is UTC+5:30
- Naive datetime override produces IST-aware output
- Singleton time_provider instance
"""

from __future__ import annotations

import datetime

from core.time_provider import IST, TimeProvider, time_provider


# ── IST Constant Tests ────────────────────────────────────────────────────────


class TestIST:
    def test_offset_is_5_30(self):
        assert IST.utcoffset(None) == datetime.timedelta(hours=5, minutes=30)

    def test_name(self):
        assert IST.tzname(None) in ("IST", "UTC+05:30")


# ── TimeProvider.now() Tests ──────────────────────────────────────────────────


class TestNow:
    def test_returns_datetime(self):
        now = TimeProvider.now()
        assert isinstance(now, datetime.datetime)

    def test_is_timezone_aware(self):
        now = TimeProvider.now()
        assert now.tzinfo is not None
        assert now.tzinfo is IST or now.utcoffset() is not None

    def test_is_in_ist(self):
        now = TimeProvider.now()
        offset = now.utcoffset()
        assert offset == datetime.timedelta(hours=5, minutes=30)

    def test_naive_datetime_override(self):
        """When _now_fn returns a naive datetime, now() should add IST tzinfo."""
        fixed_dt = datetime.datetime(2026, 6, 20, 10, 0, 0)  # Naive
        TimeProvider.set_now_fn(lambda: fixed_dt)
        try:
            result = TimeProvider.now()
            assert result.tzinfo is IST
            assert result.hour == 10
            assert result.minute == 0
        finally:
            TimeProvider.set_now_fn(datetime.datetime.now)

    def test_aware_datetime_override(self):
        """When _now_fn returns an aware datetime, now() should convert to IST."""
        utc_dt = datetime.datetime(2026, 6, 20, 4, 30, 0, tzinfo=datetime.timezone.utc)
        TimeProvider.set_now_fn(lambda: utc_dt)
        try:
            result = TimeProvider.now()
            # UTC 04:30 = IST 10:00
            assert result.hour == 10
            assert result.minute == 0
        finally:
            TimeProvider.set_now_fn(datetime.datetime.now)

    def test_set_now_fn_restores_default(self):
        """After resetting _now_fn, now() should return current time."""
        TimeProvider.set_now_fn(datetime.datetime.now)
        now = TimeProvider.now()
        assert isinstance(now, datetime.datetime)
        assert now.tzinfo is not None


# ── TimeProvider.today() Tests ────────────────────────────────────────────────


class TestToday:
    def test_returns_date(self):
        today = TimeProvider.today()
        assert isinstance(today, datetime.date)

    def test_matches_now_date(self):
        """Today should return the same date component as now()."""
        now = TimeProvider.now()
        today = TimeProvider.today()
        assert today == now.date()

    def test_override_affects_today(self):
        """Setting _now_fn should affect today()."""
        fixed_dt = datetime.datetime(2026, 1, 15, 10, 0, 0)
        TimeProvider.set_now_fn(lambda: fixed_dt)
        try:
            result = TimeProvider.today()
            assert result == datetime.date(2026, 1, 15)
        finally:
            TimeProvider.set_now_fn(datetime.datetime.now)


# ── TimeProvider.format_ts() Tests ────────────────────────────────────────────


class TestFormatTs:
    def test_returns_string(self):
        ts = TimeProvider.format_ts()
        assert isinstance(ts, str)

    def test_default_format(self):
        """Default format should be '%Y-%m-%d %H:%M:%S'."""
        TimeProvider.set_now_fn(lambda: datetime.datetime(2026, 6, 20, 10, 30, 45))
        try:
            result = TimeProvider.format_ts()
            assert result == "2026-06-20 10:30:45"
        finally:
            TimeProvider.set_now_fn(datetime.datetime.now)

    def test_custom_format(self):
        """Custom format string should be respected."""
        TimeProvider.set_now_fn(lambda: datetime.datetime(2026, 6, 20, 10, 30, 45))
        try:
            result = TimeProvider.format_ts("%Y%m%d")
            assert result == "20260620"
        finally:
            TimeProvider.set_now_fn(datetime.datetime.now)

    def test_ist_affects_format(self):
        """Time zone should affect the formatted output."""
        # 2026-06-20 23:30 UTC = 2026-06-21 05:00 IST
        utc_dt = datetime.datetime(2026, 6, 20, 23, 30, 0, tzinfo=datetime.timezone.utc)
        TimeProvider.set_now_fn(lambda: utc_dt)
        try:
            result = TimeProvider.format_ts("%Y-%m-%d")
            # In IST this should be the next day
            assert result == "2026-06-21"
        finally:
            TimeProvider.set_now_fn(datetime.datetime.now)


# ── Singleton Tests ───────────────────────────────────────────────────────────


class TestTimeProviderSingleton:
    def test_is_instance(self):
        assert isinstance(time_provider, TimeProvider)

    def test_now_works(self):
        now = time_provider.now()
        assert isinstance(now, datetime.datetime)
        assert now.tzinfo is not None

    def test_today_works(self):
        today = time_provider.today()
        assert isinstance(today, datetime.date)
