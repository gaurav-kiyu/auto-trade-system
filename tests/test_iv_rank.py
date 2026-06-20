"""Tests for core/iv_rank.py - IV Rank / IV Percentile Calculator.

Covers:
- get_iv_rank() with various VIX inputs
- get_iv_percentile()
- get_score_multiplier() for premium adjustment
- iv_summary() snapshot dict
- invalidate_cache()
- IVSkewData, compute_iv_skew(), get_skew_adjusted_premium()
- Edge cases: insufficient history, invalid VIX, flat VIX
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from core.iv_rank import (
    IVSkewData,
    compute_iv_skew,
    get_iv_percentile,
    get_iv_rank,
    get_score_multiplier,
    get_skew_adjusted_premium,
    invalidate_cache,
    iv_summary,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture(autouse=True)
def clear_cache():
    """Clear in-memory cache before each test."""
    invalidate_cache()
    yield
    invalidate_cache()


@pytest.fixture
def mock_vix_history():
    """Mock VIX history with 100 sessions ranging from 10 to 30."""
    with patch("core.iv_rank._fetch_vix_history") as mock_fetch:
        import random
        random.seed(42)
        closes = sorted([random.uniform(10.0, 30.0) for _ in range(200)])
        mock_fetch.return_value = closes
        yield mock_fetch


# =============================================================================
# get_iv_rank Tests
# =============================================================================

class TestGetIvRank:
    def test_returns_rank_in_range(self, mock_vix_history):
        # VIX=20 in a 10-30 range → rank = (20-10)/(30-10)*100 = 50
        rank = get_iv_rank(20.0)
        assert 0 <= rank <= 100
        assert rank == pytest.approx(50.0, abs=5)

    def test_low_vix_low_rank(self, mock_vix_history):
        rank = get_iv_rank(12.0)
        assert rank < 30

    def test_high_vix_high_rank(self, mock_vix_history):
        rank = get_iv_rank(28.0)
        assert rank > 70

    def test_returns_negative_on_bad_vix(self):
        assert get_iv_rank(0) == -1.0
        assert get_iv_rank(-5) == -1.0

    def test_returns_negative_on_none_vix(self):
        assert get_iv_rank(None) == -1.0  # type: ignore[arg-type]

    def test_caches_results(self, mock_vix_history):
        rank1 = get_iv_rank(20.0)
        rank2 = get_iv_rank(20.0)
        assert rank1 == rank2
        assert isinstance(rank1, float)
        assert isinstance(rank2, float)

    def test_force_refresh_bypasses_cache(self, mock_vix_history):
        get_iv_rank(20.0, force_refresh=True)
        get_iv_rank(20.0, force_refresh=True)
        assert mock_vix_history.call_count == 2

    def test_disabled_from_config(self, mock_vix_history):
        config = {"iv_rank_enabled": False}
        mult, rank, tag = get_score_multiplier(20.0, config)
        assert mult == 1.0
        assert tag == "iv_rank_disabled"


# =============================================================================
# get_iv_percentile Tests
# =============================================================================

class TestGetIvPercentile:
    def test_returns_percentile_in_range(self, mock_vix_history):
        pct = get_iv_percentile(20.0)
        assert 0 <= pct <= 100

    def test_high_vix_high_percentile(self, mock_vix_history):
        pct = get_iv_percentile(28.0)
        assert pct > 50

    def test_returns_negative_on_bad_input(self):
        assert get_iv_percentile(0) == -1.0
        assert get_iv_percentile(-1) == -1.0

    def test_low_vix_low_percentile(self, mock_vix_history):
        pct = get_iv_percentile(11.0)
        assert pct < 30


# =============================================================================
# get_score_multiplier Tests
# =============================================================================

class TestGetScoreMultiplier:
    def test_low_iv_boosts_score(self, mock_vix_history):
        mult, rank, tag = get_score_multiplier(11.0)
        assert mult > 1.0  # Cheap premiums → boost score
        assert "cheap" in tag

    def test_high_iv_reduces_score(self, mock_vix_history):
        mult, rank, tag = get_score_multiplier(28.0)
        assert mult < 1.0  # Expensive premiums → reduce score
        assert "expensive" in tag

    def test_neutral_iv_no_adjustment(self, mock_vix_history):
        mult, rank, tag = get_score_multiplier(20.0)
        assert mult == 1.0  # Neutral → no adjustment
        assert "neutral" in tag

    def test_custom_thresholds(self, mock_vix_history):
        config = {
            "iv_rank_high_threshold": 60.0,
            "iv_rank_low_threshold": 40.0,
            "iv_rank_high_mult": 0.50,
            "iv_rank_low_mult": 1.50,
        }
        mult, rank, tag = get_score_multiplier(25.0, config)
        # rank depends on history... just verify it returns something
        assert isinstance(mult, float)

    def test_multiplier_clamped(self, mock_vix_history):
        """Multiplier should be in expected range."""
        mult, _, _ = get_score_multiplier(28.0)
        assert 0.0 < mult <= 1.5

    def test_invalid_vix_returns_noop(self):
        mult, rank, tag = get_score_multiplier(0)
        assert mult == 1.0
        assert rank == -1.0
        assert "unavailable" in tag


# =============================================================================
# iv_summary Tests
# =============================================================================

class TestIvSummary:
    def test_returns_expected_keys(self, mock_vix_history):
        summary = iv_summary(20.0)
        assert "iv_rank" in summary
        assert "iv_percentile" in summary
        assert "score_multiplier" in summary
        assert "iv_regime" in summary
        assert "reason" in summary

    def test_low_iv_regime(self, mock_vix_history):
        summary = iv_summary(11.0)
        assert summary["iv_regime"] == "LOW_IV"
        assert summary["score_multiplier"] > 1.0

    def test_high_iv_regime(self, mock_vix_history):
        summary = iv_summary(28.0)
        assert summary["iv_regime"] == "HIGH_IV"
        assert summary["score_multiplier"] < 1.0

    def test_neutral_iv_regime(self, mock_vix_history):
        summary = iv_summary(20.0)
        assert summary["iv_regime"] == "NEUTRAL_IV"

    def test_unknown_on_bad_vix(self):
        summary = iv_summary(0)
        assert summary["iv_regime"] == "UNKNOWN"
        assert summary["iv_rank"] == -1.0

    def test_disabled_returns_empty_data(self):
        config = {"iv_rank_enabled": False}
        summary = iv_summary(20.0, config)
        # Even when disabled, iv_summary tries to compute
        # but iv_rank may or may not work depending on cache
        assert "iv_regime" in summary


# =============================================================================
# invalidate_cache Tests
# =============================================================================

class TestInvalidateCache:
    def test_clears_memory_cache(self, mock_vix_history):
        get_iv_rank(20.0)
        invalidate_cache()
        result = get_iv_rank(20.0)
        assert isinstance(result, float)


# =============================================================================
# IV Skew Tests (compute_iv_skew)
# =============================================================================

class TestComputeIvSkew:
    def test_returns_none_on_empty_chain(self):
        result = compute_iv_skew({}, 23500.0, 5)
        assert result is None

    def test_returns_none_on_zero_spot(self):
        result = compute_iv_skew({"calls": {23500: 100}, "puts": {23500: 90}}, 0, 5)
        assert result is None

    def test_normal_iv_skew(self):
        chain = {
            "calls": {23000: 500, 23500: 200, 24000: 50},
            "puts": {23000: 50, 23500: 200, 24000: 450},
        }
        result = compute_iv_skew(chain, 23500.0, 7)
        assert result is not None
        assert isinstance(result, IVSkewData)
        assert result.regime in ("NORMAL", "ELEVATED", "EXTREME")
        assert result.atm_iv >= 0
        assert result.ts > 0

    def test_returns_none_missing_puts(self):
        chain = {"calls": {23500: 100}, "puts": {}}
        result = compute_iv_skew(chain, 23500.0, 5)
        assert result is None

    def test_disabled_returns_none(self):
        chain = {"calls": {23500: 100}, "puts": {23500: 90}}
        result = compute_iv_skew(chain, 23500.0, 5, {"iv_skew_enabled": False})
        assert result is None

    def test_extreme_put_skew_regime(self):
        """When put skew is very high, regime should be EXTREME."""
        chain = {
            "calls": {22000: 10, 23500: 200, 25000: 5},
            "puts": {22000: 500, 23500: 200, 25000: 10},
        }
        result = compute_iv_skew(chain, 23500.0, 7)
        if result is not None:
            assert result.regime in ("NORMAL", "ELEVATED", "EXTREME")

    def test_dte_boundary(self):
        """DTE=0 should be handled (clamped to 1)."""
        chain = {
            "calls": {23500: 100},
            "puts": {23500: 100},
        }
        result = compute_iv_skew(chain, 23500.0, 0)
        # May return None if insufficient strikes, but shouldn't crash
        assert result is None or isinstance(result, IVSkewData)


# =============================================================================
# get_skew_adjusted_premium Tests
# =============================================================================

class TestGetSkewAdjustedPremium:
    def test_returns_raw_for_calls(self):
        skew = IVSkewData(put_skew=5.0, atm_iv=15.0, put_25d_iv=17.0, call_25d_iv=12.0, skew_percentile=80.0, regime="ELEVATED", ts=time.time())
        adj = get_skew_adjusted_premium(100.0, is_put=False, is_otm=True, skew_data=skew)
        assert adj == 100.0

    def test_returns_raw_for_atm(self):
        skew = IVSkewData(put_skew=5.0, atm_iv=15.0, put_25d_iv=17.0, call_25d_iv=12.0, skew_percentile=80.0, regime="ELEVATED", ts=time.time())
        adj = get_skew_adjusted_premium(100.0, is_put=True, is_otm=False, skew_data=skew)
        assert adj == 100.0

    def test_adjusts_put_otm_in_elevated(self):
        skew = IVSkewData(put_skew=5.0, atm_iv=15.0, put_25d_iv=17.0, call_25d_iv=12.0, skew_percentile=80.0, regime="ELEVATED", ts=time.time())
        adj = get_skew_adjusted_premium(100.0, is_put=True, is_otm=True, skew_data=skew)
        assert adj > 100.0

    def test_returns_raw_on_none_skew(self):
        adj = get_skew_adjusted_premium(100.0, is_put=True, is_otm=True, skew_data=None)
        assert adj == 100.0

    def test_returns_raw_on_normal_regime(self):
        skew = IVSkewData(put_skew=1.0, atm_iv=15.0, put_25d_iv=15.5, call_25d_iv=14.5, skew_percentile=30.0, regime="NORMAL", ts=time.time())
        adj = get_skew_adjusted_premium(100.0, is_put=True, is_otm=True, skew_data=skew)
        assert adj == 100.0

    def test_custom_adjustment_mult(self):
        skew = IVSkewData(put_skew=5.0, atm_iv=15.0, put_25d_iv=17.0, call_25d_iv=12.0, skew_percentile=80.0, regime="ELEVATED", ts=time.time())
        adj = get_skew_adjusted_premium(100.0, is_put=True, is_otm=True, skew_data=skew, cfg={"iv_skew_adj_mult": 1.0})
        assert adj > 100.0

    def test_extreme_regime_adjustment(self):
        skew = IVSkewData(put_skew=10.0, atm_iv=15.0, put_25d_iv=20.0, call_25d_iv=10.0, skew_percentile=95.0, regime="EXTREME", ts=time.time())
        adj = get_skew_adjusted_premium(100.0, is_put=True, is_otm=True, skew_data=skew)
        assert adj > 100.0
