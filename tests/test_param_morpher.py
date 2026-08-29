"""Tests for core.param_morpher - dynamic parameter adjustment by regime."""

from __future__ import annotations

from core.param_morpher import MorphedParams, ParamMorpher


class TestMorphedParams:
    """Tests for MorphedParams dataclass."""

    def test_defaults(self) -> None:
        params = MorphedParams(sl_mult=1.0, tgt_mult=1.0, risk_mult=1.0, label="NEUTRAL")
        assert params.sl_mult == 1.0
        assert params.tgt_mult == 1.0


class TestParamMorpher:
    """Tests for ParamMorpher - regime-based parameter adjustment."""

    def setup_method(self) -> None:
        self.morpher = ParamMorpher({})

    def test_trending_regime(self) -> None:
        params = self.morpher.get_morphed_params("TRENDING")
        assert params.sl_mult == 1.2
        assert params.tgt_mult == 1.5
        assert params.risk_mult == 1.0
        assert params.label == "TRENDING"

    def test_choppy_regime(self) -> None:
        params = self.morpher.get_morphed_params("CHOPPY")
        assert params.sl_mult == 0.8
        assert params.tgt_mult == 0.7
        assert params.risk_mult == 0.6
        assert params.label == "CHOPPY"

    def test_panic_regime(self) -> None:
        params = self.morpher.get_morphed_params("PANIC")
        assert params.sl_mult == 0.5
        assert params.tgt_mult == 0.4
        assert params.risk_mult == 0.3
        assert params.label == "PANIC"

    def test_neutral_regime(self) -> None:
        params = self.morpher.get_morphed_params("NEUTRAL")
        assert params.sl_mult == 1.0
        assert params.tgt_mult == 1.0
        assert params.risk_mult == 1.0
        assert params.label == "NEUTRAL"

    def test_unknown_regime_falls_back_to_neutral(self) -> None:
        params = self.morpher.get_morphed_params("UNKNOWN")
        assert params.sl_mult == 1.0
        assert params.tgt_mult == 1.0
        assert params.risk_mult == 1.0
        assert params.label == "UNKNOWN"

    def test_case_insensitive_upper(self) -> None:
        params = self.morpher.get_morphed_params("trending")
        assert params.sl_mult == 1.2

    def test_apply_to_config(self) -> None:
        result = self.morpher.apply_to_config(100.0, 0.7)
        assert result == 70.0

    def test_apply_to_config_rounding(self) -> None:
        result = self.morpher.apply_to_config(1.23456, 0.7)
        assert result == 0.8642  # rounds to 4 decimal places
