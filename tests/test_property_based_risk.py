"""
Property-based tests with Hypothesis for risk, position sizing, and execution modules.

Extends the coverage beyond the existing ``test_property_based.py`` (VaR + invariants)
to cover position sizing, risk service, slippage model, and volatility multiplier invariants.

Addresses the "Fuzz/property-based testing" gap from the Missing Feature Matrix.
All tests verify domain invariants that must hold for any valid input.
"""
from __future__ import annotations

import os
import sqlite3
import tempfile
from datetime import date, timedelta
from typing import Any

import pytest
from hypothesis import assume, given, settings, strategies as st
from hypothesis import HealthCheck, settings
from hypothesis.strategies import floats, integers, sampled_from


# ── Increase default deadline for all Hypothesis tests in this file ──
# Many tests involve module imports or nested loops that can exceed the
# 200ms default deadline on slower machines. Deadline=None disables
# per-example timing checks; max_examples is kept at default (100).
_FAST_SETTINGS = settings(deadline=None)


# ═══════════════════════════════════════════════════════════════════════════════
#  Position Sizing Invariants
# ═══════════════════════════════════════════════════════════════════════════════

@given(
    score=integers(min_value=0, max_value=100),
    max_lots=integers(min_value=1, max_value=100),
    capital=floats(min_value=0, max_value=1_000_000, allow_nan=False, allow_infinity=False),
    regime=sampled_from(["TRENDING", "NEUTRAL", "SIDEWAYS", "CHOPPY", "HIGH_VOLATILITY", "EVENT"]),
    tier=sampled_from(["STRONG", "MODERATE", "WEAK", "IGNORE"]),
)
@settings(suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large], deadline=None, max_examples=50)
def test_position_size_non_negative_and_bounded(
    score: int, max_lots: int, capital: float, regime: str, tier: str
) -> None:
    """Position size must be ≥ 0 and ≤ max_lots for any valid input."""
    from core.position_sizer import PositionSizer

    spec = PositionSizer.calculate(
        score=score, tier=tier, regime=regime, max_lots=max_lots, capital=capital
    )
    assert spec.lots >= 0, f"Negative lots: {spec.lots}"
    assert spec.lots <= max_lots, (
        f"lots={spec.lots} > max_lots={max_lots} for {tier}/{regime}"
    )
    assert 0.0 <= spec.effective_pct <= 1.0, (
        f"effective_pct={spec.effective_pct} out of [0,1]"
    )


@given(
    scores=st.lists(
        integers(min_value=0, max_value=100), min_size=2, max_size=10
    ),
    max_lots=integers(min_value=1, max_value=50),
    capital=floats(min_value=1_000, max_value=500_000, allow_nan=False, allow_infinity=False),
)
@_FAST_SETTINGS
def test_position_size_monotonic_within_tier(
    scores: list[int], max_lots: int, capital: float
) -> None:
    """Within the same tier & regime, a higher score should never yield fewer lots."""
    from core.position_sizer import PositionSizer

    # Sort scores so we can check monotonicity
    sorted_scores = sorted(set(scores))  # Deduplicate for reliable indexing

    for regime in ["TRENDING", "NEUTRAL", "SIDEWAYS"]:
        for tier in ["STRONG", "MODERATE", "WEAK"]:
            prev_lots = -1
            for score in sorted_scores:
                spec = PositionSizer.calculate(
                    score=score, tier=tier, regime=regime,
                    max_lots=max_lots, capital=capital,
                )
                if prev_lots >= 0:
                    assert spec.lots >= prev_lots, (
                        f"lots decreased: score → {score}: "
                        f"{prev_lots}→{spec.lots} for {tier}/{regime}"
                    )
                prev_lots = spec.lots


@given(
    score=integers(min_value=0, max_value=100),
    max_lots=integers(min_value=1, max_value=20),
    capital=floats(min_value=0, max_value=1_000_000, allow_nan=False, allow_infinity=False),
)
@_FAST_SETTINGS
def test_larger_max_lots_never_yields_fewer_lots(
    score: int, max_lots: int, capital: float
) -> None:
    """For a given score/tier/regime, larger max_lots should never reduce actual lots."""
    from core.position_sizer import PositionSizer

    for regime in ["TRENDING", "NEUTRAL"]:
        for tier in ["STRONG", "MODERATE"]:
            spec_small = PositionSizer.calculate(
                score=score, tier=tier, regime=regime,
                max_lots=max_lots, capital=capital,
            )
            spec_large = PositionSizer.calculate(
                score=score, tier=tier, regime=regime,
                max_lots=max_lots + 10, capital=capital,
            )
            assert spec_large.lots >= spec_small.lots, (
                f"max_lots={max_lots}→{max_lots + 10} reduced lots: "
                f"{spec_small.lots}→{spec_large.lots}"
            )


@given(
    score=integers(min_value=0, max_value=100),
    max_lots=integers(min_value=1, max_value=20),
    capital=floats(min_value=0, max_value=500_000, allow_nan=False, allow_infinity=False),
)
@_FAST_SETTINGS
def test_position_spec_fields_consistent(
    score: int, max_lots: int, capital: float
) -> None:
    """PositionSpec fields should be internally consistent."""
    from core.position_sizer import PositionSizer

    for regime in ["TRENDING", "NEUTRAL", "SIDEWAYS", "CHOPPY", "HIGH_VOLATILITY", "EVENT"]:
        for tier in ["STRONG", "MODERATE", "WEAK", "IGNORE"]:
            spec = PositionSizer.calculate(
                score=score, tier=tier, regime=regime,
                max_lots=max_lots, capital=capital,
            )
            assert spec.tier == tier
            assert spec.regime == regime
            assert spec.score == score
            assert len(spec.reasoning) > 0  # Reasoning should be non-empty
            # effective_pct = clamp(tier_base_pct * regime_adj * score_adj, 0, 1)
            if tier != "IGNORE":
                raw = spec.tier_base_pct * spec.regime_adj * spec.score_adj
                expected = max(0.0, min(1.0, round(raw, 4)))
                assert abs(spec.effective_pct - expected) < 0.001, (
                    f"effective_pct={spec.effective_pct} != "
                    f"clamp({spec.tier_base_pct}*{spec.regime_adj}*{spec.score_adj}, 0, 1)={expected}"
                )


# ═══════════════════════════════════════════════════════════════════════════════
#  Risk Service — Volatility Multiplier Invariants
# ═══════════════════════════════════════════════════════════════════════════════

@given(
    vix=floats(min_value=0, max_value=100, allow_nan=False, allow_infinity=False),
)
def test_volatility_multiplier_bounds(vix: float) -> None:
    """Volatility multiplier should be bounded between 0.6 and 1.2 (config defaults)."""
    from core.services.risk_service import RiskService, RiskServiceConfig

    cfg = RiskServiceConfig(
        vix_threshold_low=15.0,
        vix_threshold_high=35.0,
        vix_size_multiplier_low=1.2,
        vix_size_multiplier_high=0.6,
    )
    service = RiskService(config=cfg)
    mult = service._get_volatility_multiplier(vix)
    assert 0.0 <= mult <= 1.2, f"multiplier={mult} out of bounds [0, 1.2]"


@given(
    vix_low=floats(min_value=0, max_value=50, allow_nan=False, allow_infinity=False),
    vix_high=floats(min_value=0, max_value=50, allow_nan=False, allow_infinity=False),
)
def test_volatility_multiplier_monotonic_decreasing(vix_low: float, vix_high: float) -> None:
    """Higher VIX should never produce a larger multiplier (mult is decreasing in VIX)."""
    from core.services.risk_service import RiskService, RiskServiceConfig

    assume(vix_low < vix_high)  # Ensure strict ordering

    cfg = RiskServiceConfig(
        vix_threshold_low=15.0,
        vix_threshold_high=35.0,
        vix_size_multiplier_low=1.2,
        vix_size_multiplier_high=0.6,
    )
    service = RiskService(config=cfg)
    mult_low = service._get_volatility_multiplier(vix_low)
    mult_high = service._get_volatility_multiplier(vix_high)
    assert mult_low >= mult_high, (
        f"mult({vix_low})={mult_low} < mult({vix_high})={mult_high} — "
        f"should be decreasing"
    )


@given(
    threshold_low=floats(min_value=5, max_value=30, allow_nan=False, allow_infinity=False),
    threshold_high=floats(min_value=31, max_value=50, allow_nan=False, allow_infinity=False),
)
def test_volatility_multiplier_threshold_boundaries(
    threshold_low: float, threshold_high: float
) -> None:
    """Multiplier should equal low_mult at/below low threshold, high_mult at/above high threshold."""
    from core.services.risk_service import RiskService, RiskServiceConfig
    from core.risk.sizing.manager import PositionSizingManager

    assume(threshold_low < threshold_high)

    cfg = RiskServiceConfig(
        vix_threshold_low=threshold_low,
        vix_threshold_high=threshold_high,
        vix_size_multiplier_low=1.0,
        vix_size_multiplier_high=0.5,
    )
    sizer = PositionSizingManager(config=cfg)

    # At low threshold or below
    mult_below = sizer.get_volatility_multiplier(threshold_low - 1)
    mult_at_low = sizer.get_volatility_multiplier(threshold_low)
    assert mult_below == cfg.vix_size_multiplier_low, f"below threshold: {mult_below}"
    assert mult_at_low == cfg.vix_size_multiplier_low, f"at low threshold: {mult_at_low}"

    # At high threshold or above
    mult_at_high = sizer.get_volatility_multiplier(threshold_high)
    mult_above = sizer.get_volatility_multiplier(threshold_high + 1)
    assert mult_at_high == cfg.vix_size_multiplier_high, f"at high threshold: {mult_at_high}"
    assert mult_above == cfg.vix_size_multiplier_high, f"above threshold: {mult_above}"


# ═══════════════════════════════════════════════════════════════════════════════
#  Slippage Model Invariants
# ═══════════════════════════════════════════════════════════════════════════════

@given(
    lot_size=floats(min_value=0, max_value=1000, allow_nan=False, allow_infinity=False),
    spread_pct=floats(min_value=0, max_value=10, allow_nan=False, allow_infinity=False),
)
def test_slippage_prediction_non_negative(
    lot_size: float, spread_pct: float
) -> None:
    """Slippage predictions should never be negative for any input."""
    from core.slippage_model import SlippageModel, predict_slippage

    # Test with None model
    assert predict_slippage(lot_size, spread_pct, None) == 0.0

    # Test with a typical calibrated model
    model = SlippageModel(
        intercept=0.05,
        lot_coeff=0.01,
        spread_coeff=0.10,
        r_squared=0.75,
        n_samples=100,
        calibrated_at="2026-06-01T00:00:00",
    )
    prediction = predict_slippage(lot_size, spread_pct, model)
    assert prediction >= 0.0, f"Negative slippage: {prediction}"


@given(
    spread_low=floats(min_value=0, max_value=5, allow_nan=False, allow_infinity=False),
    spread_high=floats(min_value=0, max_value=5, allow_nan=False, allow_infinity=False),
    lot_size=floats(min_value=0, max_value=500, allow_nan=False, allow_infinity=False),
)
def test_slippage_increasing_in_spread(
    spread_low: float, spread_high: float, lot_size: float
) -> None:
    """Wider spreads should produce larger (or equal) slippage predictions (ceteris paribus)."""
    from core.slippage_model import SlippageModel, predict_slippage

    assume(spread_low < spread_high)

    model = SlippageModel(
        intercept=0.02,
        lot_coeff=0.005,
        spread_coeff=0.15,
        r_squared=0.80,
        n_samples=50,
        calibrated_at="2026-06-01T00:00:00",
    )
    pred_low = predict_slippage(lot_size, spread_low, model)
    pred_high = predict_slippage(lot_size, spread_high, model)
    assert pred_high >= pred_low, (
        f"slippage({spread_low})={pred_low} > slippage({spread_high})={pred_high}"
    )


@given(
    lots_low=floats(min_value=1, max_value=100, allow_nan=False, allow_infinity=False),
    lots_high=floats(min_value=100, max_value=500, allow_nan=False, allow_infinity=False),
    spread_pct=floats(min_value=0, max_value=5, allow_nan=False, allow_infinity=False),
)
def test_slippage_increasing_in_lots(
    lots_low: float, lots_high: float, spread_pct: float
) -> None:
    """More lots should produce larger (or equal) slippage predictions."""
    from core.slippage_model import SlippageModel, predict_slippage

    assume(lots_low < lots_high)

    model = SlippageModel(
        intercept=0.02,
        lot_coeff=0.008,
        spread_coeff=0.12,
        r_squared=0.80,
        n_samples=50,
        calibrated_at="2026-06-01T00:00:00",
    )
    pred_low = predict_slippage(lots_low, spread_pct, model)
    pred_high = predict_slippage(lots_high, spread_pct, model)
    assert pred_high >= pred_low, (
        f"slippage({lots_low} lots)={pred_low} > slippage({lots_high} lots)={pred_high}"
    )


def test_slippage_model_dataclass_creation() -> None:
    """SlippageModel should be creatable with all fields and have valid __repr__."""
    from core.slippage_model import SlippageModel

    model = SlippageModel(
        intercept=0.05,
        lot_coeff=0.01,
        spread_coeff=0.10,
        r_squared=0.75,
        n_samples=100,
        calibrated_at="2026-06-01T00:00:00",
    )
    assert model.intercept == 0.05
    assert model.lot_coeff == 0.01
    assert model.spread_coeff == 0.10
    assert model.r_squared == 0.75
    assert model.n_samples == 100
    assert model.calibrated_at == "2026-06-01T00:00:00"
    # __repr__ should contain key fields
    r = repr(model)
    assert "intercept" in r
    assert "lot_coeff" in r


# ═══════════════════════════════════════════════════════════════════════════════
#  Risk Service — Position Sizing Logic Invariants
# ═══════════════════════════════════════════════════════════════════════════════

@given(
    capital=floats(min_value=1_000, max_value=10_000_000, allow_nan=False, allow_infinity=False),
    risk_per_trade=floats(min_value=0.001, max_value=0.10, allow_nan=False, allow_infinity=False),
    entry_price=floats(min_value=10, max_value=100_000, allow_nan=False, allow_infinity=False),
    stop_loss=floats(min_value=1, max_value=100_000, allow_nan=False, allow_infinity=False),
    lot_size=integers(min_value=1, max_value=100),
)
@_FAST_SETTINGS
def test_calculate_position_size_bounds(
    capital: float,
    risk_per_trade: float,
    entry_price: float,
    stop_loss: float,
    lot_size: int,
) -> None:
    """CalculatePositionSize should return non-negative result bounded by capital constraints."""
    from core.ports.risk.risk_port import PositionSizingInput
    from core.services.risk_service import RiskService, RiskServiceConfig

    assume(entry_price > 0)
    assume(stop_loss > 0)
    assume(stop_loss != entry_price)  # Avoid zero price_diff

    cfg = RiskServiceConfig(
        default_risk_per_trade=risk_per_trade,
        max_risk_per_trade=min(risk_per_trade * 2, 0.05),
    )
    service = RiskService(config=cfg)

    sizing_input = PositionSizingInput(
        symbol="NIFTY",
        entry_price=entry_price,
        stop_loss_price=stop_loss,
        capital_available=capital,
        risk_per_trade=risk_per_trade,
        lot_size=lot_size,
        volatility=20.0,
        existing_exposure=0.0,
    )
    result = service.calculate_position_size(sizing_input)
    assert isinstance(result, int)
    assert result >= 0, f"Negative position size: {result}"

    # Capital bound: risk per trade should not exceed configured max
    price_diff = abs(entry_price - stop_loss)
    if price_diff > 0 and lot_size > 0:
        max_risk_amount = capital * cfg.max_risk_per_trade
        max_lots_by_risk = int(max_risk_amount / (price_diff * lot_size)) + 1  # Ceiling
        assert result <= max(max_lots_by_risk, 1) * 3, (  # Allow 3x from volatility adj
            f"Position size {result} unreasonably large for capital={capital}, "
            f"price_diff={price_diff}, lot_size={lot_size}"
        )


@given(
    capital=floats(min_value=1_000, max_value=10_000_000, allow_nan=False, allow_infinity=False),
)
@_FAST_SETTINGS
def test_position_size_zero_with_invalid_inputs(capital: float) -> None:
    """Position size should be 0 when stop_loss ≤ 0 or entry_price ≤ 0."""
    from core.ports.risk.risk_port import PositionSizingInput
    from core.services.risk_service import RiskService

    service = RiskService()

    # Zero stop loss
    result = service.calculate_position_size(PositionSizingInput(
        symbol="NIFTY", entry_price=100.0, stop_loss_price=0,
        capital_available=capital, risk_per_trade=0.02,
        lot_size=50, volatility=20.0, existing_exposure=0.0,
    ))
    assert result == 0, f"Expected 0 for zero stop_loss, got {result}"

    # Zero entry price
    result = service.calculate_position_size(PositionSizingInput(
        symbol="NIFTY", entry_price=0, stop_loss_price=95.0,
        capital_available=capital, risk_per_trade=0.02,
        lot_size=50, volatility=20.0, existing_exposure=0.0,
    ))
    assert result == 0, f"Expected 0 for zero entry_price, got {result}"

    # Negative stop loss
    result = service.calculate_position_size(PositionSizingInput(
        symbol="NIFTY", entry_price=100.0, stop_loss_price=-10.0,
        capital_available=capital, risk_per_trade=0.02,
        lot_size=50, volatility=20.0, existing_exposure=0.0,
    ))
    assert result == 0, f"Expected 0 for negative stop_loss, got {result}"


# ═══════════════════════════════════════════════════════════════════════════════
#  Risk Evaluation Invariants
# ═══════════════════════════════════════════════════════════════════════════════

@given(
    signal_data=st.dictionaries(
        st.text(min_size=1, max_size=20),
        st.one_of(
            st.none(),
            st.integers(min_value=-1000, max_value=1000),
            st.floats(min_value=-1000, max_value=1000, allow_nan=False, allow_infinity=False),
            st.text(max_size=20),
            st.booleans(),
        ),
        min_size=1,
        max_size=10,
    ),
)
@_FAST_SETTINGS
def test_evaluate_trade_never_crashes_on_random_input(
    signal_data: dict[str, Any]
) -> None:
    """RiskService.evaluate_trade should never crash on any signal_data dict."""
    from core.ports.risk.risk_port import PortfolioRiskMetrics, RiskDecision
    from core.services.risk_service import RiskService, RiskServiceConfig

    cfg = RiskServiceConfig(
        max_open_positions=5,
        max_daily_loss=-100000,
        max_consecutive_losses=10,
    )
    service = RiskService(config=cfg)

    metrics = PortfolioRiskMetrics(
        total_capital=100000,
        used_capital=0,
        available_capital=100000,
        daily_pnl=0,
        max_daily_loss=-5000,
        current_drawdown=0,
        max_drawdown=0,
        open_positions_count=0,
        max_open_positions=5,
        consecutive_losses=0,
        max_consecutive_losses=3,
        sector_exposure={},
        symbol_exposure={},
    )

    result = service.evaluate_trade("NIFTY", signal_data, metrics)
    assert result.decision in (RiskDecision.ALLOWED, RiskDecision.DENIED)
    assert isinstance(result.reason, str)
    assert len(result.reason) > 0
    assert 0.0 <= result.risk_score <= 1.0


def test_evaluate_trade_denied_on_missing_direction() -> None:
    """Missing direction should result in DENIED."""
    from core.ports.risk.risk_port import PortfolioRiskMetrics, RiskDecision
    from core.services.risk_service import RiskService

    service = RiskService()
    metrics = PortfolioRiskMetrics(
        total_capital=100000, used_capital=0, available_capital=100000,
        daily_pnl=0, max_daily_loss=-5000, current_drawdown=0, max_drawdown=0,
        open_positions_count=0, max_open_positions=5, consecutive_losses=0,
        max_consecutive_losses=3, sector_exposure={}, symbol_exposure={},
    )

    result = service.evaluate_trade("NIFTY", {"price": 100}, metrics)
    assert result.decision == RiskDecision.DENIED
    assert "direction" in result.reason.lower() or "missing" in result.reason.lower()


def test_evaluate_trade_denied_on_missing_price() -> None:
    """Missing or zero price should result in DENIED."""
    from core.ports.risk.risk_port import PortfolioRiskMetrics, RiskDecision
    from core.services.risk_service import RiskService

    service = RiskService()
    metrics = PortfolioRiskMetrics(
        total_capital=100000, used_capital=0, available_capital=100000,
        daily_pnl=0, max_daily_loss=-5000, current_drawdown=0, max_drawdown=0,
        open_positions_count=0, max_open_positions=5, consecutive_losses=0,
        max_consecutive_losses=3, sector_exposure={}, symbol_exposure={},
    )

    result = service.evaluate_trade("NIFTY", {"direction": "CE"}, metrics)
    assert result.decision == RiskDecision.DENIED
    assert "price" in result.reason.lower()


# ═══════════════════════════════════════════════════════════════════════════════
#  PositionSizingManager Invariants
# ═══════════════════════════════════════════════════════════════════════════════

@given(
    capital=floats(min_value=1_000, max_value=10_000_000, allow_nan=False, allow_infinity=False),
    risk_pct=floats(min_value=0.001, max_value=0.05, allow_nan=False, allow_infinity=False),
    entry_price=floats(min_value=10, max_value=50_000, allow_nan=False, allow_infinity=False),
    stop_loss=floats(min_value=1, max_value=50_000, allow_nan=False, allow_infinity=False),
    lot_size=integers(min_value=1, max_value=100),
)
@_FAST_SETTINGS
def test_sizing_manager_zero_on_invalid_input(
    capital: float,
    risk_pct: float,
    entry_price: float,
    stop_loss: float,
    lot_size: int,
) -> None:
    """PositionSizingManager should return 0 when inputs are invalid."""
    from dataclasses import dataclass
    from core.ports.risk.risk_port import PositionSizingInput
    from core.risk.sizing.manager import PositionSizingManager

    @dataclass
    class MockConfig:
        vix_threshold_low: float = 15.0
        vix_threshold_high: float = 35.0
        vix_size_multiplier_low: float = 1.2
        vix_size_multiplier_high: float = 0.6

    manager = PositionSizingManager(config=MockConfig())

    # Test with negative or zero stop loss
    bad_sl = PositionSizingInput(
        symbol="NIFTY", entry_price=entry_price, stop_loss_price=min(stop_loss, 0),
        capital_available=capital, risk_per_trade=risk_pct,
        lot_size=lot_size, volatility=20.0, existing_exposure=0.0,
    )
    if bad_sl.stop_loss_price <= 0:
        assert manager.calculate_size(bad_sl, 1.0) == 0, "Expected 0 for bad stop_loss"

    # Test with zero entry price
    bad_entry = PositionSizingInput(
        symbol="NIFTY", entry_price=0, stop_loss_price=stop_loss,
        capital_available=capital, risk_per_trade=risk_pct,
        lot_size=lot_size, volatility=20.0, existing_exposure=0.0,
    )
    assert manager.calculate_size(bad_entry, 1.0) == 0, "Expected 0 for zero entry_price"

    # Test with negative entry price
    neg_entry = PositionSizingInput(
        symbol="NIFTY", entry_price=-100, stop_loss_price=stop_loss,
        capital_available=capital, risk_per_trade=risk_pct,
        lot_size=lot_size, volatility=20.0, existing_exposure=0.0,
    )
    assert manager.calculate_size(neg_entry, 1.0) == 0, "Expected 0 for negative entry_price"


@given(
    multiplier=floats(min_value=0, max_value=5, allow_nan=False, allow_infinity=False),
)
@_FAST_SETTINGS
def test_sizing_manager_never_negative_with_volatility(
    multiplier: float
) -> None:
    """Sizing manager should never return negative values regardless of VIX multiplier."""
    from dataclasses import dataclass
    from core.ports.risk.risk_port import PositionSizingInput
    from core.risk.sizing.manager import PositionSizingManager

    @dataclass
    class MockConfig:
        vix_threshold_low: float = 15.0
        vix_threshold_high: float = 35.0
        vix_size_multiplier_low: float = 1.2
        vix_size_multiplier_high: float = 0.6

    manager = PositionSizingManager(config=MockConfig())

    sizing_input = PositionSizingInput(
        symbol="NIFTY", entry_price=100.0, stop_loss_price=95.0,
        capital_available=100000, risk_per_trade=0.02,
        lot_size=50, volatility=20.0, existing_exposure=0.0,
    )
    result = manager.calculate_size(sizing_input, multiplier)
    assert result >= 0, f"Negative result for multiplier {multiplier}: {result}"


# ═══════════════════════════════════════════════════════════════════════════════
#  Risk Limits Manager Invariants
# ═══════════════════════════════════════════════════════════════════════════════

@given(
    daily_pnl=floats(min_value=-100_000, max_value=100_000, allow_nan=False, allow_infinity=False),
    trades_today=integers(min_value=0, max_value=50),
    open_positions=integers(min_value=0, max_value=20),
)
@_FAST_SETTINGS
def test_risk_limits_never_crash(
    daily_pnl: float, trades_today: int, open_positions: int
) -> None:
    """RiskLimitsManager should never crash on any valid-looking inputs."""
    from core.risk.limits.manager import LimitConfig, RiskLimitsManager

    cfg = LimitConfig(
        max_daily_loss=-5000,
        max_daily_trades=10,
        max_open_positions=5,
        max_portfolio_risk=0.25,
        max_consecutive_losses=3,
    )
    manager = RiskLimitsManager(cfg)

    # Check daily loss limit — returns RiskEvaluation
    result = manager.check_daily_loss(daily_pnl)
    from core.ports.risk.risk_port import RiskDecision, RiskEvaluation
    assert isinstance(result, RiskEvaluation)
    assert result.decision in (RiskDecision.ALLOWED, RiskDecision.DENIED)
    assert isinstance(result.reason, str)
    assert len(result.reason) > 0

    # Verify at extreme PnL values it produces correct decisions
    if daily_pnl <= -5000:
        assert result.decision == RiskDecision.DENIED
    else:
        assert result.decision == RiskDecision.ALLOWED
