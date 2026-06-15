"""Tests for config_validator — startup schema validation and consistency checks."""

from __future__ import annotations


import pytest

from core.config_validator import (
    append_tier_engine_errors,
    generate_config_checksum,
    get_financial_param,
    get_indicator_param,
    get_instrument_param,
    get_market_param,
    get_url,
    validate_and_log,
    validate_config,
    validate_structured_blocks,
)


# ── Helper: a config that should pass basic validation ────────────
_VALID_CFG = {
    "EXECUTION_MODE": "MANUAL",
    "BASE_CAPITAL": 5000,
    "MAX_DAILY_LOSS": -600,
    "MAX_DRAWDOWN": 0.3,
    "RISK_MODE": "FIXED",
    "RISK_FIXED_AMOUNT": 150,
    "SL_PCT": 0.88,
    "TARGET_PCT": 1.3,
    "AI_THRESHOLD": 60,
    "TIER_STRONG_MIN": 80,
    "TIER_MODERATE_MIN": 70,
    "TIER_WEAK_MIN": 60,
    "QUALITY_MIN_SCORE": 68,
    "VIX_HALT_THRESHOLD": 30,
    "VIX_BLOCK_THRESHOLD": 40,
    "MAX_OPEN": 1,
    "MAX_TRADES_DAY": 3,
    "SCAN_INTERVAL": 60,
    "COOLDOWN": 300,
    "MIN_NET_RR": 1.5,
}


class TestValidateConfig:
    """validate_config — type/range/consistency checks."""

    def test_valid_config_returns_empty_errors(self):
        errors, warnings = validate_config(dict(_VALID_CFG))
        assert len(errors) == 0

    def test_missing_required_key(self):
        cfg = dict(_VALID_CFG)
        del cfg["EXECUTION_MODE"]
        errors, _ = validate_config(cfg)
        assert any("EXECUTION_MODE" in e for e in errors)

    def test_invalid_execution_mode(self):
        cfg = dict(_VALID_CFG)
        cfg["EXECUTION_MODE"] = "INVALID"
        errors, _ = validate_config(cfg)
        assert any("EXECUTION_MODE" in e for e in errors)

    def test_auto_mode_needs_broker_api(self):
        cfg = dict(_VALID_CFG)
        cfg["EXECUTION_MODE"] = "AUTO"
        errors, _ = validate_config(cfg)
        assert any("BROKER_API_ENABLED" in e for e in errors)

    def test_tier_order_must_be_ascending(self):
        cfg = dict(_VALID_CFG)
        cfg["TIER_WEAK_MIN"] = 80
        cfg["TIER_MODERATE_MIN"] = 70
        cfg["TIER_STRONG_MIN"] = 60
        errors, _ = validate_config(cfg)
        assert any("Tier boundaries out of order" in e for e in errors)

    def test_vix_halt_less_than_block(self):
        cfg = dict(_VALID_CFG)
        cfg["VIX_HALT_THRESHOLD"] = 50
        cfg["VIX_BLOCK_THRESHOLD"] = 40
        errors, _ = validate_config(cfg)
        assert any("VIX" in e for e in errors)

    def test_max_daily_loss_must_be_negative(self):
        cfg = dict(_VALID_CFG)
        cfg["MAX_DAILY_LOSS"] = 600
        errors, _ = validate_config(cfg)
        assert any("MAX_DAILY_LOSS" in e for e in errors)

    def test_base_capital_must_be_positive(self):
        cfg = dict(_VALID_CFG)
        cfg["BASE_CAPITAL"] = 0
        errors, _ = validate_config(cfg)
        assert any("BASE_CAPITAL" in e for e in errors)

    def test_sl_pct_must_be_less_than_one(self):
        cfg = dict(_VALID_CFG)
        cfg["SL_PCT"] = 1.0
        errors, _ = validate_config(cfg)
        assert any("SL_PCT" in e for e in errors)

    def test_target_pct_must_be_greater_than_one(self):
        cfg = dict(_VALID_CFG)
        cfg["TARGET_PCT"] = 0.9
        errors, _ = validate_config(cfg)
        assert any("TARGET_PCT" in e for e in errors)

    def test_ai_threshold_dead_zone_error(self):
        cfg = dict(_VALID_CFG)
        cfg["AI_THRESHOLD"] = 75  # > TIER_WEAK_MIN=60
        errors, _ = validate_config(cfg)
        assert any("dead zone" in e for e in errors)


class TestAppendTierEngineErrors:
    """append_tier_engine_errors — tier/intelligence checks."""

    def test_no_errors_for_valid_config(self):
        errors, warnings = [], []
        append_tier_engine_errors(errors, warnings, _VALID_CFG)
        assert len(errors) == 0

    def test_tier_boundary_order(self):
        errors, warnings = [], []
        cfg = dict(_VALID_CFG)
        cfg["TIER_STRONG_MIN"] = 60
        cfg["TIER_MODERATE_MIN"] = 70
        cfg["TIER_WEAK_MIN"] = 80
        append_tier_engine_errors(errors, warnings, cfg)
        assert any("out of order" in e for e in errors)

    def test_ai_threshold_above_weak(self):
        errors, warnings = [], []
        cfg = dict(_VALID_CFG)
        cfg["AI_THRESHOLD"] = 75
        cfg["TIER_WEAK_MIN"] = 60
        append_tier_engine_errors(errors, warnings, cfg)
        assert any("dead zone" in e for e in errors)

    def test_quality_min_score_warning(self):
        errors, warnings = [], []
        cfg = dict(_VALID_CFG)
        cfg["QUALITY_MIN_SCORE"] = 50  # below TIER_WEAK_MIN=60
        append_tier_engine_errors(errors, warnings, cfg)
        assert any("QUALITY_MIN_SCORE" in w for w in warnings)


class TestGenerateConfigChecksum:
    """generate_config_checksum — SHA-256 fingerprint."""

    def test_returns_16_char_hex(self):
        cs = generate_config_checksum(_VALID_CFG)
        assert len(cs) == 16
        assert all(c in "0123456789abcdef" for c in cs)

    def test_same_config_same_checksum(self):
        cs1 = generate_config_checksum(_VALID_CFG)
        cs2 = generate_config_checksum(dict(_VALID_CFG))
        assert cs1 == cs2

    def test_different_config_different_checksum(self):
        cfg2 = dict(_VALID_CFG)
        cfg2["AI_THRESHOLD"] = 70
        assert generate_config_checksum(_VALID_CFG) != generate_config_checksum(cfg2)


class TestValidateStructuredBlocks:
    """validate_structured_blocks — v2.46 structured config."""

    def test_empty_blocks_no_errors(self):
        errors, warnings = validate_structured_blocks({})
        assert len(errors) == 0

    def test_valid_instruments(self):
        cfg = {
            "instruments": {
                "NIFTY": {
                    "enabled": True, "yf_symbol": "^NSEI", "lot_size": 50,
                    "strike_step": 50, "expiry_weekday": 3, "scan_priority": 1,
                    "max_lots": 10, "min_premium": 5.0,
                }
            }
        }
        errors, warnings = validate_structured_blocks(cfg)
        assert len(errors) == 0

    def test_invalid_lot_size(self):
        cfg = {"instruments": {"NIFTY": {"lot_size": -1}}}
        errors, _ = validate_structured_blocks(cfg)
        assert any("lot_size" in e for e in errors)

    def test_invalid_expiry_weekday(self):
        cfg = {"instruments": {"NIFTY": {"expiry_weekday": 9}}}
        errors, _ = validate_structured_blocks(cfg)
        assert any("expiry_weekday" in e for e in errors)

    def test_financial_rate_validation(self):
        cfg = {"financial": {"gst_rate": -1}}
        _, warnings = validate_structured_blocks(cfg)
        assert any("gst_rate" in w for w in warnings)


class TestValidateAndLog:
    """validate_and_log — one-shot validation + logging."""

    def test_valid_config_returns_true(self):
        assert validate_and_log(_VALID_CFG, abort_on_error=False) is True

    def test_invalid_config_returns_false(self):
        result = validate_and_log({"EXECUTION_MODE": "INVALID"}, abort_on_error=False)
        assert result is False

    def test_invalid_config_raises_with_abort(self):
        with pytest.raises(SystemExit):
            validate_and_log({"EXECUTION_MODE": "INVALID"}, abort_on_error=True)


class TestConfigAccessors:
    """get_*_param accessor functions."""

    def test_get_instrument_param(self):
        cfg = {"instruments": {"NIFTY": {"lot_size": 50}}}
        assert get_instrument_param(cfg, "NIFTY", "lot_size") == 50

    def test_get_instrument_param_fallback(self):
        cfg = {}
        assert get_instrument_param(cfg, "NIFTY", "nonexistent", 42) == 42

    def test_get_indicator_param(self):
        cfg = {"indicator": {"rsi_period": 14}}
        assert get_indicator_param(cfg, "rsi_period") == 14

    def test_get_indicator_param_top_level_fallback(self):
        cfg = {"RSI_OVERBOUGHT": 70}
        assert get_indicator_param(cfg, "RSI_OVERBOUGHT", 50) == 70

    def test_get_market_param(self):
        cfg = {"market": {"open_time": "09:15"}}
        assert get_market_param(cfg, "open_time") == "09:15"

    def test_get_financial_param(self):
        cfg = {"financial": {"gst_rate": 0.18}}
        assert get_financial_param(cfg, "gst_rate") == 0.18

    def test_get_url(self):
        cfg = {"data_source_urls": {"nse_vix": "https://example.com"}}
        assert get_url(cfg, "nse_vix") == "https://example.com"

    def test_get_url_fallback(self):
        assert get_url({}, "missing", "fallback") == "fallback"
