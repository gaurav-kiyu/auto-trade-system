"""
Tests for core/iv_surface.py - IV Surface Calculator.
"""

from __future__ import annotations

import json
import math

import pytest

from core.iv_surface import IVSurfaceBuilder, IVSurfaceResult, quick_surface_metrics


class TestIVSurfaceBuilder:
    """Tests for IVSurfaceBuilder."""

    def test_build_empty(self):
        """Empty builder should return empty surface."""
        builder = IVSurfaceBuilder()
        surface = builder.build()
        assert isinstance(surface, IVSurfaceResult)
        assert len(surface.points) == 0

    def test_single_point(self):
        """Single point surface should have that point's IV as ATM."""
        builder = IVSurfaceBuilder()
        builder.add_point(25000, 7, 0.15, "CE", spot=25000)
        surface = builder.build()
        assert len(surface.points) == 1
        assert abs(surface.atm_iv - 0.15) < 0.001
        assert surface.interpolation_points == 1

    def test_multiple_points(self):
        """Multiple points should produce a valid surface."""
        builder = IVSurfaceBuilder()
        builder.add_point(24000, 7, 0.25, "PE", spot=25000)
        builder.add_point(24500, 7, 0.20, "PE")
        builder.add_point(25000, 7, 0.15, "")
        builder.add_point(25500, 7, 0.12, "CE")
        builder.add_point(26000, 7, 0.10, "CE")

        surface = builder.build()
        assert len(surface.points) == 5
        assert surface.dte_range == (7, 7)
        assert surface.atm_iv > 0

    def test_add_from_chain(self):
        """Add points from option chain data."""
        chain = {
            "calls": {
                25000: {"iv": 0.15, "oi": 1000, "ltp": 150},
                25500: {"iv": 0.12, "oi": 500, "ltp": 100},
            },
            "puts": {
                24500: {"iv": 0.25, "oi": 800, "ltp": 200},
                25000: {"iv": 0.16, "oi": 2000, "ltp": 180},
            },
        }
        builder = IVSurfaceBuilder()
        builder.add_from_chain(chain, dte=7, spot=25000)
        assert len(builder._points) == 4

    def test_spot_set_once(self):
        """Spot should only be set on first add_point with spot."""
        builder = IVSurfaceBuilder()
        builder.add_point(25000, 7, 0.15, spot=25000)
        builder.add_point(25500, 14, 0.12, spot=24000)  # Should NOT override
        assert builder._spot_price == 25000


class TestIVSurfaceResult:
    """Tests for IVSurfaceResult metrics and interpolation."""

    @pytest.fixture
    def surface(self):
        builder = IVSurfaceBuilder()
        builder.add_point(24000, 7, 0.25, "PE", spot=25000)
        builder.add_point(24500, 7, 0.20, "PE")
        builder.add_point(25000, 7, 0.15, "")
        builder.add_point(25500, 7, 0.12, "CE")
        builder.add_point(26000, 7, 0.10, "CE")
        builder.add_point(25000, 30, 0.16, "")
        builder.add_point(25000, 60, 0.17, "")
        return builder.build()

    def test_atm_iv(self, surface):
        """ATM IV should be computed from near-moneyness points."""
        assert surface.atm_iv > 0

    def test_dte_range(self, surface):
        """DTE range should be (7, 60)."""
        assert surface.dte_range == (7, 60)

    def test_interpolate_exact_strike(self, surface):
        """Interpolation at observed strike should return observed IV (exact match)."""
        iv = surface.interpolate(strike=25000, dte=7)
        assert iv is not None
        assert abs(iv - 0.15) < 0.001  # Exact match precision

    def test_interpolate_near_strike(self, surface):
        """Interpolation near an observed strike should be reasonable."""
        iv = surface.interpolate(strike=25200, dte=7)
        assert iv is not None
        assert iv > 0.01  # Positive IV
        assert iv < 2.0   # Not insane

    def test_interpolate_range(self, surface):
        """IV should be bounded between 0 and 2."""
        for strike in [23500, 25000, 26500]:
            iv = surface.interpolate(strike=strike, dte=7)
            if iv is not None:
                assert 0.0 <= iv <= 2.0

    def test_nearest_method(self, surface):
        """Nearest method should return the nearest observed IV."""
        iv = surface.interpolate(strike=24900, dte=7, method="nearest")
        assert iv is not None

    def test_get_skew_slice(self, surface):
        """Skew slice should return points for a specific DTE."""
        slice_points = surface.get_skew_slice(dte=7, tolerance=1)
        assert len(slice_points) > 0
        assert all(abs(p.dte - 7) <= 1 for p in slice_points)

    def test_get_term_slice(self, surface):
        """Term slice should return points for a specific strike."""
        slice_points = surface.get_term_slice(strike=25000, tolerance_pct=0.02)
        assert len(slice_points) > 0
        assert all(
            abs(p.strike - 25000) / surface.spot_price <= 0.02
            for p in slice_points
        )

    def test_interpolate_empty(self):
        """Empty surface should return None for interpolation."""
        surface = IVSurfaceResult(spot_price=25000)
        assert surface.interpolate(25000, 7) is None

    def test_to_dict_json(self, surface):
        """to_dict should be JSON-serializable."""
        d = surface.to_dict()
        json.dumps(d)

    def test_summary(self, surface):
        """Summary should contain key metrics."""
        text = surface.summary()
        assert "IV Surface" in text
        assert "ATM IV" in text
        assert "Skew" in text


class TestQuickSurfaceMetrics:
    """Tests for quick_surface_metrics helper."""

    def test_basic_metrics(self):
        """Basic metrics should compute correctly."""
        metrics = quick_surface_metrics(
            atm_iv=0.15,
            otm_put_iv=0.22,
            otm_call_iv=0.10,
            short_term_iv=0.15,
            long_term_iv=0.18,
        )
        assert "skew_slope_bp" in metrics
        assert "term_slope_bp" in metrics
        assert "atm_iv_pct" in metrics
        # Skew: (0.22 - 0.10) * 10000 = 1200 bp
        assert abs(metrics["skew_slope_bp"] - 1200.0) < 1
        # Term: (0.18 - 0.15) * 10000 = 300 bp
        assert abs(metrics["term_slope_bp"] - 300.0) < 1

    def test_negative_skew(self):
        """Call skew (calls > puts) should produce negative slope."""
        metrics = quick_surface_metrics(0.15, 0.12, 0.18, 0.15, 0.15)
        assert metrics["skew_slope_bp"] < 0


class TestCorners:
    """Edge case and corner case tests."""

    def test_duplicate_points(self):
        """Duplicate points should not break interpolation."""
        builder = IVSurfaceBuilder()
        builder.add_point(25000, 7, 0.15, "CE", spot=25000)
        builder.add_point(25000, 7, 0.20, "CE")  # Different IV at same (strike, DTE)
        surface = builder.build()
        # Interpolation should return a value between the two IVs
        iv = surface.interpolate(25000, 7)
        assert iv is not None
        assert 0.12 < iv < 0.22

    def test_large_term_structure(self):
        """Long DTE should show different IV from short DTE."""
        builder = IVSurfaceBuilder()
        builder.add_point(25000, 1, 0.12, "CE", spot=25000)
        builder.add_point(25000, 90, 0.20, "CE")
        surface = builder.build()
        assert surface.term_slope != 0

    def test_interpolate_out_of_range(self):
        """Interpolation far from any point should still return a reasonable value."""
        builder = IVSurfaceBuilder()
        builder.add_point(24000, 7, 0.25, "PE", spot=25000)
        builder.add_point(26000, 7, 0.10, "CE")
        surface = builder.build()
        # Far from both points
        iv = surface.interpolate(strike=25000, dte=7)
        assert iv is not None
        # Should be between 0.10 and 0.25
        assert 0.10 <= iv <= 0.25
