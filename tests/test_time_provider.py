"""Tests for core.time_provider — NTP clock sync and TimeProvider."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch


from core.time_provider import (
    IST,
    NTPClockSync,
    NTPStatus,
    TimeProvider,
    check_ntp_drift,
    get_ntp_sync,
    time_provider,
)


class TestNTPStatus:
    """NTPStatus dataclass tests."""

    def test_defaults(self):
        status = NTPStatus()
        assert status.ntp_time == 0.0
        assert status.system_time == 0.0
        assert status.drift_seconds == 0.0
        assert status.drift_acceptable is True
        assert status.server_reachable is True
        assert status.error == ""

    def test_to_dict(self):
        status = NTPStatus(
            ntp_time=1000.0,
            system_time=1002.5,
            drift_seconds=2.5,
            drift_acceptable=False,
            server_reachable=True,
            error="",
        )
        d = status.to_dict()
        assert d["ntp_time"] == 1000.0
        assert d["system_time"] == 1002.5
        assert d["drift_seconds"] == 2.5
        assert d["drift_acceptable"] is False
        assert d["server_reachable"] is True

    def test_to_dict_error(self):
        status = NTPStatus(error="ntplib not installed", server_reachable=False)
        d = status.to_dict()
        assert d["server_reachable"] is False
        assert "ntplib not installed" in d["error"]


class TestNTPClockSync:
    """NTPClockSync tests."""

    def test_init_defaults(self):
        sync = NTPClockSync()
        assert sync.MAX_DRIFT_SECONDS == 2.0
        assert sync.TIMEOUT == 5
        assert len(sync._servers) == 3
        assert sync._servers == ["pool.ntp.org", "time.google.com", "time.windows.com"]

    def test_init_with_config(self):
        cfg = {
            "ntp_servers": ["time.apple.com"],
            "ntp_timeout": 3,
            "ntp_max_drift": 1.0,
        }
        sync = NTPClockSync(cfg)
        assert sync._servers == ["time.apple.com"]
        assert sync._timeout == 3.0
        assert sync._max_drift == 1.0

    def test_init_empty_config(self):
        sync = NTPClockSync({})
        assert sync._servers == NTPClockSync.DEFAULT_SERVERS
        assert sync._timeout == NTPClockSync.TIMEOUT
        assert sync._max_drift == NTPClockSync.MAX_DRIFT_SECONDS

    def test_check_sync_import_error(self):
        """Should handle missing ntplib gracefully."""
        sync = NTPClockSync()
        with patch.dict("sys.modules", {"ntplib": None}):
            # Force ImportError by removing ntplib
            import sys
            original = sys.modules.pop("ntplib", None)
            try:
                status = sync.check_sync()
                assert status.server_reachable is False
                assert "ntplib not installed" in status.error
            finally:
                if original is not None:
                    sys.modules["ntplib"] = original

    def test_check_sync_network_error(self):
        """Should handle network errors gracefully."""
        sync = NTPClockSync({"ntp_servers": ["nonexistent.example.com"], "ntp_timeout": 1})

        status = sync.check_sync("nonexistent.example.com")
        assert status.server_reachable is False

    def test_last_status_initially_none(self):
        sync = NTPClockSync()
        assert sync.last_status is None

    def test_drift_ok_when_no_check(self):
        sync = NTPClockSync()
        assert sync.drift_ok is False

    def test_avg_drift_no_data(self):
        sync = NTPClockSync()
        assert sync.avg_drift == 0.0

    def test_get_stats_no_checks(self):
        sync = NTPClockSync()
        stats = sync.get_stats()
        assert stats["drift_ok"] is False
        assert stats["avg_drift_seconds"] == 0.0
        assert stats["n_checks"] == 0
        assert stats["last_status"] is None

    def test_get_stats_after_check(self):
        """Should reflect after a failed check (network error)."""
        sync = NTPClockSync({"ntp_servers": ["127.0.0.1"], "ntp_timeout": 1})
        sync.check_sync("127.0.0.1")
        stats = sync.get_stats()
        assert stats["n_checks"] <= 1  # May not have recorded if server unreachable
        assert "servers" in stats

    def test_concurrent_safety(self):
        """Multiple threads accessing NTPClockSync should not crash."""
        sync = NTPClockSync()
        import threading

        errors = []

        def _access():
            try:
                sync.check_sync()
                sync.drift_ok
                sync.avg_drift
                sync.get_stats()
                sync.last_status
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=_access) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert len(errors) == 0


class TestTimeProvider:
    """TimeProvider tests."""

    def test_now_returns_ist(self):
        now = TimeProvider.now()
        assert now.tzinfo is not None
        assert now.tzinfo == IST

    def test_now_timezone_offset(self):
        now = TimeProvider.now()
        offset = now.utcoffset()
        assert offset is not None
        assert offset.total_seconds() == 5.5 * 3600  # UTC + 5:30

    def test_today_returns_date(self):
        today = TimeProvider.today()
        assert hasattr(today, "year")
        assert hasattr(today, "month")
        assert hasattr(today, "day")

    def test_today_matches_now(self):
        today = TimeProvider.today()
        now = TimeProvider.now()
        assert today.year == now.year
        assert today.month == now.month
        assert today.day == now.day

    def test_format_ts_default(self):
        ts = TimeProvider.format_ts()
        assert isinstance(ts, str)
        assert len(ts) == 19  # "YYYY-MM-DD HH:MM:SS"

    def test_format_ts_custom(self):
        ts = TimeProvider.format_ts("%H:%M")
        assert len(ts) == 5

    def test_set_now_fn(self):
        """Custom now function for deterministic testing."""
        fixed = datetime(2026, 6, 20, 10, 30, 0, tzinfo=IST)
        TimeProvider.set_now_fn(lambda: fixed)
        try:
            now = TimeProvider.now()
            assert now == fixed
            assert now.hour == 10
            assert now.minute == 30
        finally:
            TimeProvider.set_now_fn(datetime.now)

    def test_set_now_fn_naive_input(self):
        """Naive datetime gets IST timezone assigned."""
        fixed = datetime(2026, 6, 20, 10, 30, 0)  # no tzinfo
        TimeProvider.set_now_fn(lambda: fixed)
        try:
            now = TimeProvider.now()
            assert now.tzinfo == IST
            assert now.hour == 10
        finally:
            TimeProvider.set_now_fn(datetime.now)

    def test_check_drift(self):
        """check_drift should return NTPStatus (possibly error)."""
        status = TimeProvider.check_drift()
        assert isinstance(status, NTPStatus)
        # May or may not be reachable depending on network
        assert isinstance(status.server_reachable, bool)

    def test_singleton_instance(self):
        assert time_provider is not None
        assert time_provider.now() is not None


class TestSingleton:
    """Singleton accessor tests."""

    def test_get_ntp_sync_singleton(self):
        s1 = get_ntp_sync()
        s2 = get_ntp_sync()
        assert s1 is s2

    def test_initialization_with_config(self):
        """Config should be applied on construction (test via constructor, not singleton)."""
        from core.time_provider import NTPClockSync
        sync = NTPClockSync({"ntp_max_drift": 5.0, "ntp_timeout": 3})
        assert sync._max_drift == 5.0
        assert sync._timeout == 3.0


class TestCheckNTPDrift:
    """check_ntp_drift convenience function tests."""

    def test_returns_status(self):
        status = check_ntp_drift()
        assert isinstance(status, NTPStatus)
