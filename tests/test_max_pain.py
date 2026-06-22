"""
Tests for core/max_pain.py - Max Pain Calculator.
"""

from __future__ import annotations

import json

import pytest

from core.max_pain import MaxPainResult, compute_max_pain, compute_pain_index


# Sample option chain for testing
_SAMPLE_CHAIN = {
    "calls": {
        24500: {"oi": 15000, "ltp": 850.0},
        24600: {"oi": 22000, "ltp": 780.0},
        24700: {"oi": 31000, "ltp": 700.0},
        24800: {"oi": 45000, "ltp": 620.0},
        24900: {"oi": 58000, "ltp": 540.0},
        25000: {"oi": 72000, "ltp": 460.0},
        25100: {"oi": 49000, "ltp": 380.0},
        25200: {"oi": 35000, "ltp": 300.0},
        25300: {"oi": 28000, "ltp": 220.0},
        25400: {"oi": 18000, "ltp": 150.0},
        25500: {"oi": 12000, "ltp": 90.0},
    },
    "puts": {
        24500: {"oi": 8000, "ltp": 120.0},
        24600: {"oi": 12000, "ltp": 150.0},
        24700: {"oi": 18000, "ltp": 190.0},
        24800: {"oi": 25000, "ltp": 240.0},
        24900: {"oi": 35000, "ltp": 300.0},
        25000: {"oi": 68000, "ltp": 380.0},
        25100: {"oi": 42000, "ltp": 460.0},
        25200: {"oi": 31000, "ltp": 540.0},
        25300: {"oi": 22000, "ltp": 620.0},
        25400: {"oi": 15000, "ltp": 700.0},
        25500: {"oi": 9000, "ltp": 780.0},
    },
}


class TestComputeMaxPain:
    """Tests for compute_max_pain core logic."""

    def test_basic_max_pain(self):
        """Max Pain should return a valid strike with pain index."""
        result = compute_max_pain(23363.35, option_chain=_SAMPLE_CHAIN)
        assert isinstance(result, MaxPainResult)
        assert result.max_pain_strike > 0
        assert result.pain_index >= 0
        assert result.total_oi > 0
        assert result.call_oi_total > 0
        assert result.put_oi_total > 0

    def test_max_pain_in_strike_range(self):
        """Max Pain should be within the range of available strikes."""
        result = compute_max_pain(23363.35, option_chain=_SAMPLE_CHAIN)
        strikes = sorted(_SAMPLE_CHAIN["calls"].keys())
        assert strikes[0] <= result.max_pain_strike <= strikes[-1]

    def test_pain_curve_reasonable(self):
        """Pain curve should have entries for all strikes."""
        result = compute_max_pain(23363.35, option_chain=_SAMPLE_CHAIN)
        assert len(result.pain_curve) > 0
        # All values should be positive
        assert all(v >= 0 for v in result.pain_curve.values())

    def test_put_call_ratio(self):
        """PCR should be correctly computed."""
        result = compute_max_pain(23363.35, option_chain=_SAMPLE_CHAIN)
        expected_pcr = sum(
            p.get("oi", 0) for p in _SAMPLE_CHAIN["puts"].values()
        ) / sum(c.get("oi", 0) for c in _SAMPLE_CHAIN["calls"].values())
        assert abs(result.put_call_ratio - expected_pcr) < 0.01

    def test_nearest_strikes_includes_max_pain(self):
        """Nearest strikes list should include the max pain strike."""
        result = compute_max_pain(23363.35, option_chain=_SAMPLE_CHAIN)
        strikes_near = [s["strike"] for s in result.nearest_strikes]
        assert result.max_pain_strike in strikes_near

    def test_empty_chain(self):
        """Empty option chain should return zeroed result."""
        result = compute_max_pain(23363.35, option_chain={"calls": {}, "puts": {}})
        assert result.max_pain_strike == 0.0
        assert result.total_oi == 0

    def test_calls_only_chain(self):
        """Chain with only calls should still work."""
        chain = {"calls": {25000: {"oi": 100, "ltp": 150}}, "puts": {}}
        result = compute_max_pain(25000, option_chain=chain)
        assert result.max_pain_strike > 0
        assert result.put_oi_total == 0

    def test_raises_on_invalid_spot(self):
        """Invalid spot price should raise ValueError."""
        with pytest.raises(ValueError):
            compute_max_pain(-100, option_chain=_SAMPLE_CHAIN)

    def test_raises_on_no_data(self):
        """No data provided should raise ValueError."""
        with pytest.raises(ValueError):
            compute_max_pain(25000)  # type: ignore[arg-type]

    def test_single_strike_chain(self):
        """Single strike chain should set max pain to that strike."""
        chain = {"calls": {25000: {"oi": 100, "ltp": 150}}, "puts": {25000: {"oi": 200, "ltp": 100}}}
        result = compute_max_pain(25000, option_chain=chain)
        assert result.max_pain_strike == 25000


class TestComputePainIndex:
    """Tests for compute_pain_index fast path."""

    def test_returns_dict(self):
        """Pain index should return a dict with expected keys."""
        idx = compute_pain_index(23363.35, _SAMPLE_CHAIN)
        assert isinstance(idx, dict)
        assert "max_pain_strike" in idx
        assert "pain_index" in idx
        assert "put_call_ratio" in idx
        assert "distance" in idx
        assert "imbalance" in idx

    def test_distance_calculation(self):
        """Distance should be (spot - max_pain)."""
        idx = compute_pain_index(23363.35, _SAMPLE_CHAIN)
        assert idx["distance"] == round(23363.35 - idx["max_pain_strike"], 2)

    def test_imbalance_detection(self):
        """Imbalance should reflect OI ratio."""
        chain = {
            "calls": {25000: {"oi": 1000, "ltp": 150}},
            "puts": {25000: {"oi": 100, "ltp": 100}},
        }
        idx = compute_pain_index(25000, chain)
        assert idx["imbalance"] == "CALLS_HEAVY"

    def test_balanced_imbalance(self):
        """Balanced OI should return BALANCED."""
        chain = {
            "calls": {25000: {"oi": 500, "ltp": 150}},
            "puts": {25000: {"oi": 400, "ltp": 100}},
        }
        idx = compute_pain_index(25000, chain)
        assert idx["imbalance"] == "BALANCED"


class TestMaxPainResult:
    """Tests for MaxPainResult dataclass."""

    def test_to_dict(self):
        """to_dict should be JSON-serializable."""
        result = compute_max_pain(23363.35, option_chain=_SAMPLE_CHAIN)
        d = result.to_dict()
        json.dumps(d)  # Must not raise

    def test_summary(self):
        """Summary should contain key metrics."""
        result = compute_max_pain(23363.35, option_chain=_SAMPLE_CHAIN)
        text = result.summary()
        assert "Max Pain" in text
        assert "pain index" in text.lower()
        assert "PCR" in text
