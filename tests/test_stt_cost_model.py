"""Tests for core/stt_cost_model.py — STT cost calculation for NSE options."""

from __future__ import annotations

from core.stt_cost_model import (
    OptionPositionType,
    STTCostBreakdown,
    STTCostModel,
    create_stt_model,
)


class TestConstants:
    def test_long_options_stt_free(self) -> None:
        assert STTCostModel.STT_LONG_OPTIONS_PCT == 0.0

    def test_short_options_rate(self) -> None:
        assert STTCostModel.STT_SHORT_OPTIONS_PCT == 0.0005

    def test_exercise_rate(self) -> None:
        assert STTCostModel.STT_EXERCISE_PCT == 0.00125


class TestCalculateStt:
    def test_disabled_returns_zero(self) -> None:
        model = STTCostModel(include_stt=False)
        result = model.calculate_stt(
            OptionPositionType.LONG_CALL, 100.0, 19500, 1, 50,
        )
        assert result.stt_amount == 0.0
        assert result.stt_rate == 0.0
        assert result.is_expiry_stt is False

    def test_long_call_no_cost(self) -> None:
        model = STTCostModel()
        result = model.calculate_stt(
            OptionPositionType.LONG_CALL, 100.0, 19500, 1, 50,
        )
        assert result.stt_amount == 0.0
        assert result.is_expiry_stt is False
        assert result.is_settled is False
        assert result.premium_value == 5000.0  # 100 * 1 * 50

    def test_long_put_no_cost(self) -> None:
        model = STTCostModel()
        result = model.calculate_stt(
            OptionPositionType.LONG_PUT, 80.0, 19500, 2, 50,
        )
        assert result.stt_amount == 0.0
        assert result.premium_value == 8000.0  # 80 * 2 * 50

    def test_short_call_cost(self) -> None:
        model = STTCostModel()
        result = model.calculate_stt(
            OptionPositionType.SHORT_CALL, 50.0, 19500, 1, 50,
        )
        assert result.stt_amount == 2500.0 * 0.0005  # premium * rate
        assert result.is_expiry_stt is False

    def test_short_put_cost(self) -> None:
        model = STTCostModel()
        result = model.calculate_stt(
            OptionPositionType.SHORT_PUT, 60.0, 19500, 3, 25,
        )
        expected_stt = (60.0 * 3 * 25) * 0.0005
        assert result.stt_amount == expected_stt
        assert result.stt_rate == 0.0005

    def test_exercised_uses_settlement_value(self) -> None:
        model = STTCostModel()
        result = model.calculate_stt(
            OptionPositionType.SHORT_CALL, 50.0, 19500, 1, 50,
            exercised=True,
        )
        expected_stt = 19500 * 1 * 50 * 0.00125
        assert result.stt_amount == expected_stt
        assert result.is_expiry_stt is True
        assert result.is_settled is True

    def test_expiry_stt_warning(self) -> None:
        model = STTCostModel()
        result = model.calculate_stt(
            OptionPositionType.SHORT_CALL, 50.0, 19500, 1, 50,
            is_expiry=True,
        )
        expected_stt = 19500 * 1 * 50 * 0.00125
        assert result.stt_amount == expected_stt
        assert result.is_expiry_stt is True
        assert result.is_settled is True

    def test_expiry_stt_disabled_falls_through(self) -> None:
        model = STTCostModel(apply_expiry_stt=False)
        result = model.calculate_stt(
            OptionPositionType.SHORT_CALL, 50.0, 19500, 1, 50,
            is_expiry=True,
        )
        assert result.stt_rate == 0.0005
        assert result.is_expiry_stt is False
        assert result.is_settled is False

    def test_multiple_lots(self) -> None:
        model = STTCostModel()
        result = model.calculate_stt(
            OptionPositionType.SHORT_CALL, 100.0, 19500, 5, 75,
        )
        assert result.premium_value == 37500.0  # 100 * 5 * 75
        assert result.stt_amount == 37500.0 * 0.0005

    def test_zero_premium(self) -> None:
        model = STTCostModel()
        result = model.calculate_stt(
            OptionPositionType.LONG_CALL, 0.0, 19500, 1, 50,
        )
        assert result.stt_amount == 0.0
        assert result.premium_value == 0.0


class TestEstimateExpirySttRisk:
    def test_long_position_no_risk(self) -> None:
        model = STTCostModel()
        risk = model.estimate_expiry_stt_risk(
            OptionPositionType.LONG_CALL, 100.0, 19500, 20000, 50,
        )
        assert risk["risk_level"] == "NONE"

    def test_short_call_itm_high_risk(self) -> None:
        model = STTCostModel()
        risk = model.estimate_expiry_stt_risk(
            OptionPositionType.SHORT_CALL, 100.0, 19500, 20000, 50,
        )
        assert risk["risk_level"] in ("HIGH", "MEDIUM")
        assert risk["stt_if_exercised"] > 0

    def test_short_call_otm_low_risk(self) -> None:
        model = STTCostModel()
        risk = model.estimate_expiry_stt_risk(
            OptionPositionType.SHORT_CALL, 100.0, 20000, 19500, 50,
        )
        assert risk["risk_level"] == "LOW"

    def test_short_put_itm_medium_risk(self) -> None:
        model = STTCostModel()
        risk = model.estimate_expiry_stt_risk(
            OptionPositionType.SHORT_PUT, 100.0, 20000, 18000, 50,
        )
        assert risk["risk_level"] in ("HIGH", "MEDIUM")
        assert risk["stt_if_exercised"] > 0

    def test_short_put_otm_low_risk(self) -> None:
        model = STTCostModel()
        risk = model.estimate_expiry_stt_risk(
            OptionPositionType.SHORT_PUT, 100.0, 19500, 20000, 50,
        )
        assert risk["risk_level"] == "LOW"

    def test_risk_returns_stt_as_pct(self) -> None:
        model = STTCostModel()
        risk = model.estimate_expiry_stt_risk(
            OptionPositionType.SHORT_CALL, 1000.0, 19500, 20000, 50,
        )
        if risk["risk_level"] == "HIGH":
            assert "stt_as_pct_of_premium" in risk


class TestShouldCloseBeforeExpiry:
    def test_long_returns_false(self) -> None:
        model = STTCostModel()
        close, reason = model.should_close_before_expiry(
            OptionPositionType.LONG_CALL, 100.0, 19500, 20000, 50, 20.0,
        )
        assert close is False
        assert "Long position" in reason

    def test_short_otm_not_high_risk_returns_false(self) -> None:
        model = STTCostModel()
        close, _ = model.should_close_before_expiry(
            OptionPositionType.SHORT_CALL, 100.0, 20000, 19500, 50, 20.0,
        )
        assert close is False

    def test_short_itm_triggers_close(self) -> None:
        """Short call ITM: STT risk (121%) > exit cost (0.5%) => close."""
        model = STTCostModel()
        close, reason = model.should_close_before_expiry(
            OptionPositionType.SHORT_CALL, 1000.0, 19500, 20000, 50, 5.0,
        )
        assert close is True
        assert "STT" in reason

    def test_empty_reason_when_not_triggered(self) -> None:
        model = STTCostModel()
        _, reason = model.should_close_before_expiry(
            OptionPositionType.SHORT_PUT, 100.0, 19500, 20000, 50, 20.0,
        )
        assert reason == ""


class TestCreateSttModel:
    def test_defaults(self) -> None:
        model = create_stt_model()
        assert model._include_stt is True
        assert model._apply_expiry_stt is True

    def test_custom(self) -> None:
        model = create_stt_model(include_stt=False, apply_expiry_stt=False)
        assert model._include_stt is False
        assert model._apply_expiry_stt is False

    def test_instance_type(self) -> None:
        model = create_stt_model()
        assert isinstance(model, STTCostModel)


class TestSttCostBreakdown:
    def test_dataclass(self) -> None:
        b = STTCostBreakdown(
            stt_rate=0.0005,
            premium_value=5000.0,
            stt_amount=2.5,
            is_expiry_stt=False,
            is_settled=False,
        )
        assert b.stt_rate == 0.0005
        assert b.premium_value == 5000.0
        assert b.stt_amount == 2.5
        assert b.is_expiry_stt is False
        assert b.is_settled is False
