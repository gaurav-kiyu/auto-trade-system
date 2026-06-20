"""
Tests for core/mandate_validator.py - MandateValidator.

Covers:
  - ValidationConfig dataclass defaults
  - ValidationResult constants
  - MandateValidator init with config
  - validate_parameter (insufficient data, walkforward pass/fail, regime breakdown, win rate)
  - _check_walkforward (profitable, unprofitable, degradation limits)
  - _is_positive (empty list, negative, positive)
  - _calculate_win_rate (empty, mixed, all wins, all losses)
  - check_system_health (win rate threshold, negative weeks, OK state)
  - get_validation_status (validated, insufficient data)
  - create_mandate_validator convenience function
"""

from __future__ import annotations

from core.mandate_validator import (
    MandateValidator,
    ValidationConfig,
    ValidationResult,
    create_mandate_validator,
)


def _make_validator(**config_overrides: dict) -> MandateValidator:
    config = {
        "MANDATE_VALIDATION_MIN_OBSERVATIONS": 80,
        "MANDATE_WALKFORWARD_DEGRADATION_MAX": 0.20,
        "MANDATE_MIN_WIN_RATE_THRESHOLD": 0.48,
        "MANDATE_NEGATIVE_WEEKS_THRESHOLD": 3,
    }
    config.update(config_overrides)
    return MandateValidator(config)


# ═══════════════════════════════════════════════════════════════════════
#  ValidationConfig
# ═══════════════════════════════════════════════════════════════════════


class TestValidationConfig:
    def test_defaults(self):
        c = ValidationConfig()
        assert c.min_observations == 80
        assert c.walkforward_degradation_max == 0.20
        assert c.min_regimes_positive == 2
        assert c.min_win_rate == 0.48
        assert c.negative_weeks_threshold == 3

    def test_custom_values(self):
        c = ValidationConfig(
            min_observations=50,
            walkforward_degradation_max=0.15,
            min_regimes_positive=3,
            min_win_rate=0.50,
            negative_weeks_threshold=5,
        )
        assert c.min_observations == 50
        assert c.walkforward_degradation_max == 0.15


class TestValidationResult:
    def test_constants(self):
        assert ValidationResult.PASSED == "PASSED"
        assert ValidationResult.FAILED == "FAILED"
        assert ValidationResult.INSUFFICIENT_DATA == "INSUFFICIENT_DATA"


# ═══════════════════════════════════════════════════════════════════════
#  Initialization
# ═══════════════════════════════════════════════════════════════════════


class TestInitialization:
    def test_default_config_loading(self):
        v = _make_validator()
        assert v.cfg.min_observations == 80
        assert v.cfg.min_win_rate == 0.48

    def test_custom_config_loading(self):
        v = _make_validator(MANDATE_VALIDATION_MIN_OBSERVATIONS=100,
                            MANDATE_MIN_WIN_RATE_THRESHOLD=0.55)
        assert v.cfg.min_observations == 100
        assert v.cfg.min_win_rate == 0.55

    def test_empty_config_uses_defaults(self):
        v = MandateValidator({})
        assert v.cfg.min_observations == 80

    def test_param_history_initialized(self):
        v = _make_validator()
        assert v._param_history == {}


# ═══════════════════════════════════════════════════════════════════════
#  validate_parameter
# ═══════════════════════════════════════════════════════════════════════


class TestValidateParameter:
    def test_insufficient_data(self):
        v = _make_validator(MANDATE_VALIDATION_MIN_OBSERVATIONS=80)
        # Only 10 observations - below 80 minimum
        result, reason = v.validate_parameter("test_param", [{"pnl": 100}] * 10)
        assert result == ValidationResult.INSUFFICIENT_DATA
        assert "10 observations" in reason

    def test_walkforward_failure(self):
        v = _make_validator(MANDATE_VALIDATION_MIN_OBSERVATIONS=5)
        observations = [{"pnl": 100}] * 10
        # Period A profitable (100), Period B negative (-10) → degradation > 100%
        result, reason = v.validate_parameter(
            "test_param",
            observations,
            period_a_results={"net_pnl": 100},
            period_b_results={"net_pnl": -10},
        )
        assert result == ValidationResult.FAILED
        assert "Walk-forward" in reason

    def test_walkforward_passes_without_degradation(self):
        v = _make_validator(MANDATE_VALIDATION_MIN_OBSERVATIONS=5)
        observations = [{"pnl": 100}] * 10
        result, reason = v.validate_parameter(
            "test_param",
            observations,
            period_a_results={"net_pnl": 100},
            period_b_results={"net_pnl": 90},  # 10% degradation, within 20%
        )
        # Should still pass if win rate is OK (all wins = 100% > 48%)
        assert result == ValidationResult.PASSED

    def test_regime_breakdown_fails(self):
        v = _make_validator(MANDATE_VALIDATION_MIN_OBSERVATIONS=5)
        observations = [{"pnl": 100}] * 10
        # All regimes have net negative P&L → 0 positive regimes out of 3
        result, reason = v.validate_parameter(
            "test_param",
            observations,
            regime_breakdown={
                "bull": [{"pnl": -50}, {"pnl": -30}],
                "bear": [{"pnl": -20}],
                "sideways": [{"pnl": -10}],
            },
        )
        assert result == ValidationResult.FAILED
        assert "regimes" in reason

    def test_regime_breakdown_passes(self):
        v = _make_validator(MANDATE_VALIDATION_MIN_OBSERVATIONS=5)
        observations = [{"pnl": 100}] * 10
        result, reason = v.validate_parameter(
            "test_param",
            observations,
            regime_breakdown={
                "bull": [{"pnl": 100}, {"pnl": 50}],
                "bear": [{"pnl": -20}],
                "sideways": [{"pnl": 30}],
            },
        )
        # 2 regimes positive (bull, sideways) ≥ 2 → passes, win rate 100% > 48%
        assert result == ValidationResult.PASSED

    def test_win_rate_below_threshold(self):
        v = _make_validator(MANDATE_VALIDATION_MIN_OBSERVATIONS=5,
                            MANDATE_MIN_WIN_RATE_THRESHOLD=0.50)
        observations = [{"pnl": -100}] * 6 + [{"pnl": 100}] * 4  # 4/10 = 40%
        result, reason = v.validate_parameter("test_param", observations)
        assert result == ValidationResult.FAILED
        assert "win rate" in reason.lower()

    def test_passes_all_gates(self):
        v = _make_validator(MANDATE_VALIDATION_MIN_OBSERVATIONS=5)
        observations = [{"pnl": 100}] * 8 + [{"pnl": -50}] * 2  # 8/10 = 80%
        result, reason = v.validate_parameter("test_param", observations)
        assert result == ValidationResult.PASSED
        assert "passed" in reason

    def test_empty_observations(self):
        v = _make_validator(MANDATE_VALIDATION_MIN_OBSERVATIONS=1)
        result, reason = v.validate_parameter("test_param", [])
        assert result == ValidationResult.INSUFFICIENT_DATA


# ═══════════════════════════════════════════════════════════════════════
#  _check_walkforward
# ═══════════════════════════════════════════════════════════════════════


class TestCheckWalkforward:
    def test_period_a_profit_b_within_degradation(self):
        v = _make_validator()
        assert v._check_walkforward({"net_pnl": 100}, {"net_pnl": 85}) is True  # 15%

    def test_period_a_profit_b_exceeds_degradation(self):
        v = _make_validator(MANDATE_WALKFORWARD_DEGRADATION_MAX=0.10)
        assert v._check_walkforward({"net_pnl": 100}, {"net_pnl": 70}) is False  # 30%

    def test_period_a_unprofitable_returns_true(self):
        v = _make_validator()
        assert v._check_walkforward({"net_pnl": -50}, {"net_pnl": 100}) is True

    def test_period_a_zero_returns_true(self):
        v = _make_validator()
        assert v._check_walkforward({"net_pnl": 0}, {"net_pnl": 10}) is True

    def test_both_profitable_no_degradation(self):
        v = _make_validator()
        assert v._check_walkforward({"net_pnl": 200}, {"net_pnl": 200}) is True

    def test_b_pnl_missing_defaults_to_zero(self):
        v = _make_validator()
        # Period B defaults to 0 when empty dict, so degradation = (100-0)/100 = 100%
        assert v._check_walkforward({"net_pnl": 100}, {}) is False  # 100% > 20%

    def test_both_unprofitable(self):
        v = _make_validator()
        assert v._check_walkforward({"net_pnl": -100}, {"net_pnl": -200}) is True


# ═══════════════════════════════════════════════════════════════════════
#  _is_positive
# ═══════════════════════════════════════════════════════════════════════


class TestIsPositive:
    def test_empty_returns_false(self):
        v = _make_validator()
        assert v._is_positive([]) is False

    def test_positive_pnl_returns_true(self):
        v = _make_validator()
        assert v._is_positive([{"pnl": 100}, {"pnl": 50}]) is True

    def test_negative_pnl_returns_false(self):
        v = _make_validator()
        assert v._is_positive([{"pnl": -100}, {"pnl": 50}]) is False  # net = -50

    def test_zero_net_pnl_returns_false(self):
        v = _make_validator()
        assert v._is_positive([{"pnl": 100}, {"pnl": -100}]) is False

    def test_single_positive_observation(self):
        v = _make_validator()
        assert v._is_positive([{"pnl": 50}]) is True

    def test_single_negative_observation(self):
        v = _make_validator()
        assert v._is_positive([{"pnl": -50}]) is False


# ═══════════════════════════════════════════════════════════════════════
#  _calculate_win_rate
# ═══════════════════════════════════════════════════════════════════════


class TestCalculateWinRate:
    def test_empty_returns_zero(self):
        v = _make_validator()
        assert v._calculate_win_rate([]) == 0.0

    def test_all_wins(self):
        v = _make_validator()
        assert v._calculate_win_rate([{"pnl": 100}, {"pnl": 50}, {"pnl": 75}]) == 1.0

    def test_all_losses(self):
        v = _make_validator()
        assert v._calculate_win_rate([{"pnl": -100}, {"pnl": -50}]) == 0.0

    def test_mixed(self):
        v = _make_validator()
        result = v._calculate_win_rate([
            {"pnl": 100}, {"pnl": -50}, {"pnl": 75}, {"pnl": -20},
        ])
        assert result == 0.5  # 2/4

    def test_zero_pnl_not_win(self):
        v = _make_validator()
        assert v._calculate_win_rate([{"pnl": 0}]) == 0.0


# ═══════════════════════════════════════════════════════════════════════
#  check_system_health
# ═══════════════════════════════════════════════════════════════════════


class TestCheckSystemHealth:
    def test_healthy_state(self):
        v = _make_validator()
        trades = [{"pnl": 100}] * 30 + [{"pnl": -50}] * 10  # 75% win rate
        weeks = [100, 50, -20, 30]
        ok, msg = v.check_system_health(trades, weeks)
        assert ok is True
        assert "OK" in msg

    def test_low_win_rate(self):
        v = _make_validator(MANDATE_MIN_WIN_RATE_THRESHOLD=0.50)
        trades = [{"pnl": -100}] * 30 + [{"pnl": 100}] * 20  # 20/50 = 40%
        weeks = [100, 50, -20, 30]
        ok, msg = v.check_system_health(trades, weeks)
        assert ok is False
        assert "win rate" in msg.lower()

    def test_few_trades_skips_win_rate_check(self):
        v = _make_validator()
        # 10 trades < 50 → skip win rate check
        trades = [{"pnl": -100}] * 10
        weeks = [100, 50, -20, 30]
        ok, msg = v.check_system_health(trades, weeks)
        assert ok is True  # Win rate check skipped, weeks OK

    def test_many_negative_weeks(self):
        v = _make_validator(MANDATE_NEGATIVE_WEEKS_THRESHOLD=2)
        trades = [{"pnl": 100}] * 60  # Plenty of trades, good win rate
        weeks = [-50, -30, -20, 100]  # 4 negative weeks > 2 threshold
        ok, msg = v.check_system_health(trades, weeks)
        assert ok is False
        assert "negative weeks" in msg.lower()

    def test_empty_trades_list(self):
        v = _make_validator()
        ok, msg = v.check_system_health([], [])
        assert ok is True

    def test_empty_weeks_list(self):
        v = _make_validator()
        trades = [{"pnl": 100}] * 60
        ok, msg = v.check_system_health(trades, [])
        assert ok is True


# ═══════════════════════════════════════════════════════════════════════
#  get_validation_status
# ═══════════════════════════════════════════════════════════════════════


class TestGetValidationStatus:
    def test_insufficient_data_no_history(self):
        v = _make_validator()
        status = v.get_validation_status("unseen_param")
        assert status["parameter"] == "unseen_param"
        assert status["observations"] == 0
        assert status["validation_status"] == "INSUFFICIENT_DATA"

    def test_validated_with_history(self):
        v = _make_validator(MANDATE_VALIDATION_MIN_OBSERVATIONS=5)
        # Manually populate param_history since validate_parameter doesn't store
        v._param_history["seen_param"] = [{"pnl": 100}] * 10
        status = v.get_validation_status("seen_param")
        assert status["observations"] == 10
        assert status["validation_status"] == "VALIDATED"

    def test_insufficient_data_with_some_history(self):
        v = _make_validator(MANDATE_VALIDATION_MIN_OBSERVATIONS=100)
        v._param_history["partial_param"] = [{"pnl": 100}] * 50
        status = v.get_validation_status("partial_param")
        assert status["observations"] == 50
        assert status["validation_status"] == "INSUFFICIENT_DATA"


# ═══════════════════════════════════════════════════════════════════════
#  create_mandate_validator convenience function
# ═══════════════════════════════════════════════════════════════════════


class TestCreateMandateValidator:
    def test_returns_mandate_validator_instance(self):
        v = create_mandate_validator({})
        assert isinstance(v, MandateValidator)
        assert v.cfg.min_observations == 80
