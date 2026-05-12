"""Tests for core.data_freshness_guard — stale data rejection."""
from __future__ import annotations

import time

import pandas as pd

from core.data_freshness_guard import check_data_freshness


def _make_frame(age_sec: float, name: str = "5m", n_rows: int = 5) -> pd.DataFrame:
    now = time.time()
    ts = [now - (n_rows - i) * 10 for i in range(n_rows)]
    ts[-1] = now - age_sec  # last row has the target age
    return pd.DataFrame({"timestamp": ts, "close": [100.0] * n_rows})


class TestDataFreshnessGuard:
    def test_all_fresh_passes(self) -> None:
        frames = {"5m": _make_frame(10)}
        result = check_data_freshness(frames, cfg={"data_freshness_guard_enabled": True})
        assert result.passed

    def test_stale_1m_bar_fails(self) -> None:
        frames = {"1m": _make_frame(200)}  # 200s > 90s max
        result = check_data_freshness(frames, cfg={"data_freshness_guard_enabled": True})
        assert not result.passed
        assert "1m" in result.reject_reason

    def test_stale_5m_bar_fails(self) -> None:
        frames = {"5m": _make_frame(400)}  # 400s > 300s max
        result = check_data_freshness(frames, cfg={"data_freshness_guard_enabled": True})
        assert not result.passed

    def test_no_frames_fails(self) -> None:
        result = check_data_freshness(None, cfg={"data_freshness_guard_enabled": True})
        assert not result.passed

    def test_empty_frame_fails(self) -> None:
        frames = {"5m": pd.DataFrame()}
        result = check_data_freshness(frames, cfg={"data_freshness_guard_enabled": True})
        assert not result.passed

    def test_disabled_guard_always_passes(self) -> None:
        result = check_data_freshness(None, cfg={"data_freshness_guard_enabled": False})
        assert result.passed

    def test_vix_stale_fails(self) -> None:
        frames = {"5m": _make_frame(10)}
        result = check_data_freshness(frames, vix_ts=time.time() - 600, cfg={"data_freshness_guard_enabled": True})
        assert not result.passed
        assert "VIX" in result.reject_reason

    def test_vix_fresh_passes(self) -> None:
        frames = {"5m": _make_frame(10)}
        result = check_data_freshness(frames, vix_ts=time.time() - 30, cfg={"data_freshness_guard_enabled": True})
        assert result.passed

    def test_mixed_freshness_passes_with_fresh_data(self) -> None:
        frames = {"1m": _make_frame(30), "5m": _make_frame(60), "15m": _make_frame(120)}
        result = check_data_freshness(frames, cfg={"data_freshness_guard_enabled": True})
        assert result.passed
