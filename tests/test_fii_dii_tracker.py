"""Tests for core/fii_dii_tracker.py - Institutional Flow Tracker.

Covers:
- FIIDIIData dataclass defaults
- FIIDIITracker init, cache load/save
- get_latest() with cache hit, stale cache, remote fetch
- score_adjustment() logic for CALL/PUT
- start_background_refresh() thread
- stop(), get_eod_summary()
"""
from __future__ import annotations

import json
import time
from unittest.mock import MagicMock, patch


from core.fii_dii_tracker import FIIDIIData, FIIDIITracker


class TestFIIDIIData:
    """FIIDIIData dataclass."""

    def test_defaults(self):
        data = FIIDIIData(date="2026-01-15", fii_net=1500.0, dii_net=-800.0, fetched_at=1000.0)
        assert data.date == "2026-01-15"
        assert data.fii_net == 1500.0
        assert data.dii_net == -800.0
        assert data.fetched_at == 1000.0


class TestFIIDIITrackerInit:
    """FIIDIITracker construction and cache loading."""

    @patch("core.fii_dii_tracker._CACHE_FILE")
    def test_init_with_cache_hit(self, mock_cache_file):
        mock_cache_file.parent.mkdir = MagicMock()
        mock_cache_file.is_file.return_value = True
        mock_cache_file.read_text.return_value = json.dumps({
            "date": "2026-01-15",
            "fii_net": 1500.0,
            "dii_net": -800.0,
            "fetched_at": 1000.0,
        })
        tracker = FIIDIITracker(cfg={"fii_dii_enabled": True})
        assert tracker._data is not None
        assert tracker._data.fii_net == 1500.0
        assert tracker._last_fetch == 1000.0

    @patch("core.fii_dii_tracker._CACHE_FILE")
    def test_init_with_cache_miss(self, mock_cache_file):
        mock_cache_file.parent.mkdir = MagicMock()
        mock_cache_file.is_file.return_value = False
        tracker = FIIDIITracker(cfg={"fii_dii_enabled": True})
        assert tracker._data is None

    @patch("core.fii_dii_tracker._CACHE_FILE")
    def test_init_with_corrupt_cache(self, mock_cache_file):
        mock_cache_file.parent.mkdir = MagicMock()
        mock_cache_file.is_file.return_value = True
        mock_cache_file.read_text.return_value = "not json"
        tracker = FIIDIITracker(cfg={"fii_dii_enabled": True})
        assert tracker._data is None  # Graceful degradation


class TestGetLatest:
    """get_latest() tests."""

    @patch("core.fii_dii_tracker._CACHE_FILE")
    def test_disabled_returns_none(self, mock_cache_file):
        mock_cache_file.parent.mkdir = MagicMock()
        tracker = FIIDIITracker(cfg={"fii_dii_enabled": False})
        assert tracker.get_latest() is None

    @patch("core.fii_dii_tracker._CACHE_FILE")
    def test_cache_hit(self, mock_cache_file):
        mock_cache_file.parent.mkdir = MagicMock()
        mock_cache_file.is_file.return_value = False
        tracker = FIIDIITracker(cfg={"fii_dii_enabled": True, "fii_cache_hours": 24.0})
        data = FIIDIIData(date="2026-01-15", fii_net=1500.0, dii_net=-800.0, fetched_at=time.time())
        tracker._data = data
        tracker._last_fetch = time.time()
        latest = tracker.get_latest()
        assert latest is data

    @patch("core.fii_dii_tracker._CACHE_FILE")
    @patch.object(FIIDIITracker, "_fetch_remote")
    def test_stale_cache_fetches_remote(self, mock_fetch, mock_cache_file):
        mock_cache_file.parent.mkdir = MagicMock()
        mock_fetch.return_value = FIIDIIData(
            date="2026-01-16", fii_net=2000.0, dii_net=-1000.0, fetched_at=time.time()
        )
        tracker = FIIDIITracker(cfg={"fii_dii_enabled": True, "fii_cache_hours": 0.001})
        with patch.object(tracker, "_last_fetch", 0.0):  # force stale
            latest = tracker.get_latest()
            assert latest is not None
            assert latest.fii_net == 2000.0

    @patch("core.fii_dii_tracker._CACHE_FILE")
    @patch.object(FIIDIITracker, "_fetch_remote")
    def test_stale_cache_remote_fails_returns_stale(self, mock_fetch, mock_cache_file):
        mock_cache_file.parent.mkdir = MagicMock()
        mock_fetch.return_value = None
        stale_data = FIIDIIData(date="2026-01-15", fii_net=1500.0, dii_net=-800.0, fetched_at=0)
        tracker = FIIDIITracker(cfg={"fii_dii_enabled": True, "fii_cache_hours": 0.001})
        tracker._data = stale_data
        tracker._last_fetch = 0.0
        latest = tracker.get_latest()
        assert latest is stale_data  # Returns stale cache


class TestScoreAdjustment:
    """score_adjustment() logic."""

    @patch("core.fii_dii_tracker._CACHE_FILE")
    def test_disabled_returns_zero(self, mock_cache_file):
        mock_cache_file.parent.mkdir = MagicMock()
        tracker = FIIDIITracker(cfg={"fii_dii_enabled": False})
        assert tracker.score_adjustment("CALL") == 0

    @patch("core.fii_dii_tracker._CACHE_FILE")
    def test_no_data_returns_zero(self, mock_cache_file):
        mock_cache_file.parent.mkdir = MagicMock()
        tracker = FIIDIITracker(cfg={"fii_dii_enabled": True})
        assert tracker.score_adjustment("CALL") == 0

    @patch("core.fii_dii_tracker._CACHE_FILE")
    def test_fii_buying_bonus_call(self, mock_cache_file):
        mock_cache_file.parent.mkdir = MagicMock()
        tracker = FIIDIITracker(cfg={"fii_dii_enabled": True, "fii_score_threshold": 1000, "fii_score_bonus": 5})
        tracker._data = FIIDIIData(date="T", fii_net=1500.0, dii_net=0, fetched_at=1)
        assert tracker.score_adjustment("CALL") == 5

    @patch("core.fii_dii_tracker._CACHE_FILE")
    def test_fii_buying_penalty_put(self, mock_cache_file):
        mock_cache_file.parent.mkdir = MagicMock()
        tracker = FIIDIITracker(cfg={"fii_dii_enabled": True, "fii_score_threshold": 1000, "fii_score_bonus": 5})
        tracker._data = FIIDIIData(date="T", fii_net=1500.0, dii_net=0, fetched_at=1)
        assert tracker.score_adjustment("PUT") == -5

    @patch("core.fii_dii_tracker._CACHE_FILE")
    def test_fii_selling_bonus_put(self, mock_cache_file):
        mock_cache_file.parent.mkdir = MagicMock()
        tracker = FIIDIITracker(cfg={"fii_dii_enabled": True, "fii_score_threshold": 1000, "fii_score_bonus": 5})
        tracker._data = FIIDIIData(date="T", fii_net=-1500.0, dii_net=0, fetched_at=1)
        assert tracker.score_adjustment("PUT") == 5

    @patch("core.fii_dii_tracker._CACHE_FILE")
    def test_fii_selling_penalty_call(self, mock_cache_file):
        mock_cache_file.parent.mkdir = MagicMock()
        tracker = FIIDIITracker(cfg={"fii_dii_enabled": True, "fii_score_threshold": 1000, "fii_score_bonus": 5})
        tracker._data = FIIDIIData(date="T", fii_net=-1500.0, dii_net=0, fetched_at=1)
        assert tracker.score_adjustment("CALL") == -5

    @patch("core.fii_dii_tracker._CACHE_FILE")
    def test_below_threshold_returns_zero(self, mock_cache_file):
        mock_cache_file.parent.mkdir = MagicMock()
        tracker = FIIDIITracker(cfg={"fii_dii_enabled": True, "fii_score_threshold": 2000.0, "fii_score_bonus": 5})
        tracker._data = FIIDIIData(date="T", fii_net=1500.0, dii_net=0, fetched_at=1)
        assert tracker.score_adjustment("CALL") == 0


class TestBackgroundRefresh:
    """start_background_refresh() and stop()."""

    @patch("core.fii_dii_tracker._CACHE_FILE")
    def test_disabled_does_not_start(self, mock_cache_file):
        mock_cache_file.parent.mkdir = MagicMock()
        tracker = FIIDIITracker(cfg={"fii_dii_enabled": False})
        tracker.start_background_refresh()
        assert tracker._bg_thread is None

    @patch("core.fii_dii_tracker._CACHE_FILE")
    def test_start_and_stop(self, mock_cache_file):
        mock_cache_file.parent.mkdir = MagicMock()
        tracker = FIIDIITracker(cfg={"fii_dii_enabled": True, "fii_cache_hours": 24})
        tracker._fetch_remote = MagicMock(return_value=None)
        tracker.start_background_refresh()
        assert tracker._bg_thread is not None
        assert tracker._bg_thread.daemon is True
        tracker.stop()
        assert tracker._stop_event.is_set()
        tracker._bg_thread.join(timeout=2)

    @patch("core.fii_dii_tracker._CACHE_FILE")
    def test_does_not_duplicate_thread(self, mock_cache_file):
        mock_cache_file.parent.mkdir = MagicMock()
        tracker = FIIDIITracker(cfg={"fii_dii_enabled": True})
        tracker._fetch_remote = MagicMock(return_value=None)
        tracker._bg_thread = MagicMock()
        tracker._bg_thread.is_alive.return_value = True
        tracker.start_background_refresh()  # Should not create a new thread
        assert tracker._bg_thread.is_alive.called


class TestEODSummary:
    """get_eod_summary()."""

    @patch("core.fii_dii_tracker._CACHE_FILE")
    def test_disabled_returns_empty(self, mock_cache_file):
        mock_cache_file.parent.mkdir = MagicMock()
        tracker = FIIDIITracker(cfg={"fii_dii_enabled": False})
        assert tracker.get_eod_summary() == ""

    @patch("core.fii_dii_tracker._CACHE_FILE")
    def test_no_data_summary(self, mock_cache_file):
        mock_cache_file.parent.mkdir = MagicMock()
        tracker = FIIDIITracker(cfg={"fii_dii_enabled": True})
        assert "data unavailable" in tracker.get_eod_summary()

    @patch("core.fii_dii_tracker._CACHE_FILE")
    def test_with_data_summary(self, mock_cache_file):
        mock_cache_file.parent.mkdir = MagicMock()
        tracker = FIIDIITracker(cfg={"fii_dii_enabled": True})
        tracker._data = FIIDIIData(date="T", fii_net=1500.0, dii_net=-800.0, fetched_at=1)
        summary = tracker.get_eod_summary()
        assert "FII" in summary
        assert "DII" in summary
