"""
Property-Based Tests using Hypothesis for Options Analytics Modules.

Tests invariants and universal properties of:
  - Max Pain calculation (core/max_pain.py)
  - IV Surface interpolation (core/iv_surface.py)
  - Factor Model regression (core/factor_models.py)
"""

from __future__ import annotations

import math
from typing import Any

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from core.factor_models import (
    FamaFrench3Factor,
    FactorReturn,
    compute_factor_attribution,
    _ols_regression,
)
from core.iv_surface import IVSurfaceBuilder
from core.max_pain import MaxPainResult, compute_max_pain, compute_pain_index

# ==============================================================================
# Hypothesis Strategies
# ==============================================================================

# Generate a realistic option chain with OI > 0
@st.composite
def option_chain_strategy(draw: Any) -> tuple[float, dict[str, dict[float, dict[str, Any]]]]:
    """Generate a realistic options chain with randomized strikes and OI."""
    spot = draw(st.floats(min_value=1000, max_value=50000, allow_nan=False))
    n_strikes = draw(st.integers(min_value=3, max_value=15))
    base_strike = spot // 100 * 100  # Round to nearest 100
    strikes = sorted(set(
        base_strike + draw(st.integers(min_value=-20, max_value=20)) * 100
        for _ in range(n_strikes)
    ))
    if len(strikes) < 3:
        strikes = [spot - 200, spot, spot + 200]

    calls: dict[float, dict[str, Any]] = {}
    puts: dict[float, dict[str, Any]] = {}
    for s in strikes:
        oi = draw(st.integers(min_value=100, max_value=200000))
        ltp = draw(st.floats(min_value=5, max_value=2000, allow_nan=False, ))
        if s >= spot * 0.95:
            calls[s] = {"oi": oi, "ltp": ltp}
        oi = draw(st.integers(min_value=100, max_value=200000))
        ltp = draw(st.floats(min_value=5, max_value=2000, allow_nan=False, ))
        if s <= spot * 1.05:
            puts[s] = {"oi": oi, "ltp": ltp}

    return spot, {"calls": calls, "puts": puts}


# Generate a small set of return observations for factor models
return_list = st.lists(
    st.floats(min_value=-0.05, max_value=0.05, allow_nan=False, ),
    min_size=10,
    max_size=100,
)


# ==============================================================================
# Max Pain — Property-Based Tests
# ==============================================================================

class TestMaxPainProperties:
    """Invariant properties of Max Pain calculation."""

    @given(st.floats(min_value=100, max_value=100000, allow_nan=False, ))
    @settings(max_examples=50)
    def test_pain_non_negative(self, spot: float):
        """Pain values should always be non-negative."""
        assume(spot > 0)
        chain = {
            "calls": {spot: {"oi": 1000, "ltp": 100}},
            "puts": {spot: {"oi": 1000, "ltp": 100}},
        }
        result = compute_max_pain(spot, option_chain=chain)
        assert isinstance(result, MaxPainResult)
        assert result.pain_index >= 0
        for pain_val in result.pain_curve.values():
            assert pain_val >= 0

    @given(st.floats(min_value=100, max_value=100000, allow_nan=False, ))
    @settings(max_examples=50)
    def test_strike_within_range(self, spot: float):
        """Max pain strike should always be within the available strike range."""
        assume(spot > 500)
        base = round(spot / 100) * 100
        chain = {
            "calls": {base - 100: {"oi": 5000, "ltp": 200}, base: {"oi": 10000, "ltp": 150}, base + 100: {"oi": 5000, "ltp": 100}},
            "puts": {base - 100: {"oi": 3000, "ltp": 100}, base: {"oi": 8000, "ltp": 120}, base + 100: {"oi": 3000, "ltp": 150}},
        }
        result = compute_max_pain(spot, option_chain=chain)
        strikes = sorted(chain["calls"].keys())
        assert strikes[0] <= result.max_pain_strike <= strikes[-1]

    @given(st.floats(min_value=100, max_value=100000, allow_nan=False, ))
    @settings(max_examples=50)
    def test_pcr_non_negative(self, spot: float):
        """Put/Call ratio should always be non-negative."""
        assume(spot > 0)
        chain = {
            "calls": {spot: {"oi": 50000, "ltp": 200}},
            "puts": {spot: {"oi": 30000, "ltp": 150}},
        }
        result = compute_max_pain(spot, option_chain=chain)
        assert result.put_call_ratio >= 0

    def test_oi_sums_reasonable(self):
        """Total OI should equal sum of call and put OI."""
        chain = {
            "calls": {25000: {"oi": 1000, "ltp": 100}},
            "puts": {25000: {"oi": 2000, "ltp": 100}},
        }
        result = compute_max_pain(25000, option_chain=chain)
        assert result.total_oi == result.call_oi_total + result.put_oi_total

    def test_empty_chain_zeros(self):
        """Empty chain should produce zeroed result."""
        result = compute_max_pain(25000, option_chain={"calls": {}, "puts": {}})
        assert result.max_pain_strike == 0.0
        assert result.total_oi == 0

    def test_nearest_strikes_includes_max_pain_property(self):
        """Nearest strikes list must always include the max pain strike."""
        chain = {
            "calls": {25000: {"oi": 10000, "ltp": 500}, 25100: {"oi": 8000, "ltp": 450}},
            "puts": {25000: {"oi": 12000, "ltp": 400}, 25100: {"oi": 6000, "ltp": 350}},
        }
        result = compute_max_pain(25000, option_chain=chain)
        nearest = [s["strike"] for s in result.nearest_strikes]
        assert result.max_pain_strike in nearest

    def test_pcr_zero_with_no_puts(self):
        """PCR should be 0 when there are no puts."""
        chain = {"calls": {25000: {"oi": 1000, "ltp": 100}}, "puts": {}}
        result = compute_max_pain(25000, option_chain=chain)
        assert result.put_call_ratio == 0.0

    def test_pcr_infinite_with_no_calls(self):
        """PCR should handle zero calls gracefully."""
        chain = {"calls": {}, "puts": {25000: {"oi": 1000, "ltp": 100}}}
        result = compute_max_pain(25000, option_chain=chain)
        # PCR = put_oi_total / max(call_oi_total, 1) = 1000 / 1 = 1000.0
        assert result.put_call_ratio == 1000.0

    def test_to_dict_json_serializable(self):
        """to_dict output must be JSON-serializable."""
        import json
        chain = {
            "calls": {25000: {"oi": 100, "ltp": 100}},
            "puts": {25000: {"oi": 200, "ltp": 100}},
        }
        result = compute_max_pain(25000, option_chain=chain)
        d = result.to_dict()
        json.dumps(d)  # Must not raise

    def test_pain_index_distance(self):
        """compute_pain_index distance should equal (spot - max_pain_strike)."""
        chain = {
            "calls": {25000: {"oi": 1000, "ltp": 200}, 25100: {"oi": 500, "ltp": 150}},
            "puts": {25000: {"oi": 800, "ltp": 180}, 25100: {"oi": 400, "ltp": 120}},
        }
        result = compute_max_pain(25000, option_chain=chain)
        idx = compute_pain_index(25000, chain)
        assert idx["distance"] == round(25000 - result.max_pain_strike, 2)


# ==============================================================================
# IV Surface — Property-Based Tests
# ==============================================================================

@st.composite
def surface_builder_strategy(draw: Any) -> IVSurfaceBuilder:
    """Build an IVSurfaceBuilder with random points (no duplicate coordinates)."""
    spot = draw(st.floats(min_value=10000, max_value=50000, allow_nan=False))
    n_points = draw(st.integers(min_value=3, max_value=10))
    builder = IVSurfaceBuilder()
    seen: set[tuple[int, int]] = set()
    for _ in range(n_points):
        # Ensure unique (strike, dte) pairs
        for _attempt in range(10):
            strike_offset = draw(st.integers(min_value=-10, max_value=10)) * 100
            strike = int(spot + strike_offset)
            dte = draw(st.integers(min_value=1, max_value=60))
            key = (strike, dte)
            if key not in seen:
                seen.add(key)
                break
        else:
            continue
        iv = draw(st.floats(min_value=0.05, max_value=0.50, allow_nan=False))
        ot = draw(st.sampled_from(["CE", "PE", ""]))
        builder.add_point(float(strike), dte, iv, option_type=ot, spot=spot)
    return builder


class TestIVSurfaceProperties:
    """Invariant properties of IV Surface interpolation."""

    @given(surface_builder_strategy())
    @settings(max_examples=50)
    def test_interpolation_bounded(self, builder: IVSurfaceBuilder):
        """Interpolated IV should always be between 0 and 2."""
        surface = builder.build()
        spot = surface.spot_price
        for p in surface.points:
            iv = surface.interpolate(strike=p.strike, dte=p.dte)
            if iv is not None:
                assert 0.0 <= iv <= 2.0

    @given(surface_builder_strategy())
    @settings(max_examples=50)
    def test_exact_match_at_observed_points(self, builder: IVSurfaceBuilder):
        """Nearest-neighbor interpolation at exact observed (strike, dte) should match observed IV."""
        surface = builder.build()
        for p in surface.points:
            iv = surface.interpolate(strike=p.strike, dte=p.dte, method="nearest")
            if iv is not None:
                # Nearest neighbor should return the exact observed IV
                assert abs(iv - p.iv) < 0.001, (
                    f"IV mismatch at strike={p.strike}, dte={p.dte}: "
                    f"expected {p.iv:.4f}, got {iv:.4f}"
                )

    @given(surface_builder_strategy())
    @settings(max_examples=50)
    def test_atm_iv_reasonable(self, builder: IVSurfaceBuilder):
        """ATM IV should be a reasonable positive value."""
        surface = builder.build()
        if surface.points:
            assert 0.01 <= surface.atm_iv <= 1.0

    @given(surface_builder_strategy())
    @settings(max_examples=50)
    def test_dte_range(self, builder: IVSurfaceBuilder):
        """DTE range should be bounded by actual point DTEs."""
        surface = builder.build()
        if surface.points:
            dtss = [p.dte for p in surface.points]
            assert surface.dte_range[0] >= min(dtss) - 1
            assert surface.dte_range[1] <= max(dtss) + 1

    @given(surface_builder_strategy())
    @settings(max_examples=50)
    def test_strike_range(self, builder: IVSurfaceBuilder):
        """Strike range should be bounded by actual strike values."""
        surface = builder.build()
        if surface.points:
            strikes = [p.strike for p in surface.points]
            assert surface.strike_range[0] >= min(strikes) - 1
            assert surface.strike_range[1] <= max(strikes) + 1

    def test_empty_builder(self):
        """Empty builder should produce empty surface."""
        builder = IVSurfaceBuilder()
        surface = builder.build()
        assert len(surface.points) == 0
        assert surface.interpolate(25000, 7) is None

    def test_duplicate_points_not_crash(self):
        """Duplicate (strike, dte) pairs should not crash interpolation."""
        builder = IVSurfaceBuilder()
        builder.add_point(25000, 7, 0.15, "CE", spot=25000)
        builder.add_point(25000, 7, 0.20, "CE")  # Same point, different IV
        surface = builder.build()
        iv = surface.interpolate(25000, 7)
        assert iv is not None
        assert 0.12 <= iv <= 0.22

    def test_interpolation_methods_consistent(self):
        """Linear and nearest methods should return positive values."""
        builder = IVSurfaceBuilder()
        for dte in [7, 30]:
            for strike in [24500, 25000, 25500]:
                iv = 0.15 + (dte / 365) * 0.02
                builder.add_point(strike, dte, iv, spot=25000)
        surface = builder.build()
        iv1 = surface.interpolate(25000, 14, method="linear")
        iv2 = surface.interpolate(25000, 14, method="nearest")
        if iv1 is not None:
            assert iv1 > 0
        if iv2 is not None:
            assert iv2 > 0


# ==============================================================================
# Factor Models — Property-Based Tests
# ==============================================================================

class TestFactorModelProperties:
    """Invariant properties of Factor Model regression."""

    @given(
        st.lists(
            st.floats(min_value=-0.03, max_value=0.03, allow_nan=False, ),
            min_size=5,
            max_size=50,
        )
    )
    @settings(max_examples=50)
    def test_r_squared_bounded(self, returns: list[float]):
        """R-squared should always be between 0 and 1."""
        assume(len(set(returns)) > 1)
        import random
        random.seed(42)
        n = len(returns)
        mkt = [random.gauss(0, 0.01) for _ in range(n)]
        # Build a simple attribution
        result = compute_factor_attribution(returns, mkt, include_momentum=False)
        assert 0.0 <= result.r_squared <= 1.0
        assert result.n_observations == n

    @given(
        st.lists(
            st.floats(min_value=-0.05, max_value=0.05, allow_nan=False, ),
            min_size=5,
            max_size=50,
        )
    )
    @settings(max_examples=50)
    def test_loadings_finite(self, returns: list[float]):
        """Factor loadings should always be finite."""
        import random
        random.seed(42)
        n = len(returns)
        mkt = [random.gauss(0, 0.01) for _ in range(n)]
        result = compute_factor_attribution(returns, mkt, include_momentum=False)
        for name, val in result.loadings.items():
            assert math.isfinite(val), f"Loading {name} is not finite: {val}"

    @given(
        st.lists(
            st.floats(min_value=-0.03, max_value=0.03, allow_nan=False, ),
            min_size=5,
            max_size=50,
        )
    )
    @settings(max_examples=50)
    def test_alpha_finite(self, returns: list[float]):
        """Alpha should always be finite."""
        import random
        random.seed(42)
        n = len(returns)
        mkt = [random.gauss(0, 0.01) for _ in range(n)]
        result = compute_factor_attribution(returns, mkt, include_momentum=False)
        assert math.isfinite(result.alpha)
        assert math.isfinite(result.annualized_alpha)

    @given(
        st.lists(
            st.floats(min_value=-0.03, max_value=0.03, allow_nan=False, ),
            min_size=3,
            max_size=50,
        )
    )
    @settings(max_examples=50)
    def test_insufficient_data(self, returns: list[float]):
        """Fewer than 3 obs for 1-factor or 4 for 4-factor should return zeros."""
        import random
        random.seed(42)
        n = len(returns)
        if n < 4:
            mkt = [random.gauss(0, 0.01) for _ in range(n)]
            smb = [random.gauss(0, 0.005) for _ in range(n)]
            hml = [random.gauss(0, 0.004) for _ in range(n)]
            mom = [random.gauss(0, 0.003) for _ in range(n)]
            result = compute_factor_attribution(returns, mkt, smb, hml, mom, include_momentum=True)
            for v in result.loadings.values():
                assert v == 0.0
            assert result.r_squared == 0.0

    def test_no_observations(self):
        """Empty model should return zero loadings."""
        model = FamaFrench3Factor()
        result = model.fit()
        assert result.loadings["market"] == 0.0
        assert result.n_observations == 0
        assert result.r_squared == 0.0

    def test_factor_names_consistent(self):
        """Factor names should match loadings keys for Carhart 4-factor."""
        import random
        random.seed(42)
        n = 50
        mkt = [random.gauss(0, 0.01) for _ in range(n)]
        smb = [random.gauss(0, 0.005) for _ in range(n)]
        hml = [random.gauss(0, 0.004) for _ in range(n)]
        mom = [random.gauss(0, 0.003) for _ in range(n)]
        pf = [0.0005 + mkt[i] + 0.3 * smb[i] + 0.2 * hml[i] + 0.1 * mom[i] + random.gauss(0, 0.005) for i in range(n)]
        result = compute_factor_attribution(pf, mkt, smb, hml, mom, include_momentum=True)
        for name in result.factor_names:
            assert name in result.loadings, f"Missing loading for factor {name}"

    def test_residual_std_non_negative(self):
        """Residual standard deviation should always be non-negative."""
        import random
        random.seed(42)
        n = 50
        mkt = [random.gauss(0, 0.01) for _ in range(n)]
        pf = [mkt[i] + random.gauss(0, 0.005) for i in range(n)]
        result = compute_factor_attribution(pf, mkt, include_momentum=False)
        assert result.residual_std >= 0

    def test_to_dict_json_serializable(self):
        """FactorResult.to_dict must be JSON-serializable."""
        import json
        import random
        random.seed(42)
        n = 50
        mkt = [random.gauss(0, 0.01) for _ in range(n)]
        pf = [mkt[i] + random.gauss(0, 0.005) for i in range(n)]
        result = compute_factor_attribution(pf, mkt, include_momentum=False)
        d = result.to_dict()
        json.dumps(d)  # Must not raise
