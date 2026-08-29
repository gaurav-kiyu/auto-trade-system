"""
Tests for core/startup_validation.py — DEBT-005 Fail-fast startup schema validation.

Covers:
  - validate_risk_engine (pass/fail, deprecated module warning)
  - validate_dependencies (pass/fail)
  - validate_config_config (valid config, type errors, schema errors, environment validation)
  - validate_config_config production checks (placeholder tokens, missing broker API)
  - validate_environment_vars (with and without OPBUYING_* overrides)
  - run_startup_validation (all pass, config failure, fail-fast raises SystemExit)
  - run_startup_validation with fail_fast=False (returns False without exit)
"""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

import pytest
from core.startup_validation import (
    run_startup_validation,
    validate_app_config,
    validate_dependencies,
    validate_environment_vars,
    validate_risk_engine,
)

# ═══════════════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════════════


def _valid_config() -> dict:
    """Return a minimal valid config that passes all checks."""
    return {
        "EXECUTION_MODE": "PAPER",
        "BASE_CAPITAL": 5000,
        "MAX_DAILY_LOSS": -600,
        "MAX_DRAWDOWN": 0.3,
        "RISK_MODE": "FIXED",
        "RISK_FIXED_AMOUNT": 150,
        "SL_PCT": 0.88,
        "TARGET_PCT": 1.3,
        "AI_THRESHOLD": 55,
        "TIER_STRONG_MIN": 80,
        "TIER_MODERATE_MIN": 68,
        "TIER_WEAK_MIN": 55,
        "QUALITY_MIN_SCORE": 68,
        "VIX_HALT_THRESHOLD": 30.0,
        "VIX_BLOCK_THRESHOLD": 40.0,
        "MAX_OPEN": 1,
        "MAX_TRADES_DAY": 3,
        "ENVIRONMENT": "dev",
        "BOT_TOKEN": "test_token",
        "CHAT_ID": "test_chat",
        "BROKER_CONFIG": {"api_key": "test_key"},
    }


# ═══════════════════════════════════════════════════════════════════════
#  validate_risk_engine
# ═══════════════════════════════════════════════════════════════════════


class TestValidateRiskEngine:
    def test_passes_when_importable(self):
        passed, msg = validate_risk_engine()
        assert passed is True
        assert "RiskService" in msg

    def test_deprecated_modules_do_not_block(self):
        """If a deprecated risk module happens to be in sys.modules, validation still passes."""
        # Temporarily add a deprecated module key
        old = sys.modules.get("core.risk_engine")
        sys.modules["core.risk_engine"] = MagicMock()
        try:
            passed, msg = validate_risk_engine()
            assert passed is True  # Deprecated modules warn but don't block
        finally:
            if old:
                sys.modules["core.risk_engine"] = old
            else:
                del sys.modules["core.risk_engine"]


# ═══════════════════════════════════════════════════════════════════════
#  validate_dependencies
# ═══════════════════════════════════════════════════════════════════════


class TestValidateDependencies:
    def test_passes_when_all_importable(self):
        passed, msg = validate_dependencies()
        assert passed is True
        assert "All required dependencies" in msg


# ═══════════════════════════════════════════════════════════════════════
#  validate_config_config — core DEBT-005 logic
# ═══════════════════════════════════════════════════════════════════════


class TestValidateAppConfig:
    def test_valid_config_passes(self):
        passed, errors = validate_app_config(_valid_config())
        assert passed is True
        assert errors == []

    def test_missing_required_keys(self):
        cfg = {"EXECUTION_MODE": "PAPER"}  # Missing BASE_CAPITAL etc.
        passed, errors = validate_app_config(cfg)
        assert passed is False
        missing = [e for e in errors if "Missing required" in e]
        assert len(missing) >= 1

    def test_invalid_execution_mode(self):
        cfg = _valid_config()
        cfg["EXECUTION_MODE"] = "INVALID_MODE"
        passed, errors = validate_app_config(cfg)
        assert passed is False
        assert any("EXECUTION_MODE" in e for e in errors)

    def test_invalid_risk_mode(self):
        cfg = _valid_config()
        cfg["RISK_MODE"] = "INVALID"
        passed, errors = validate_app_config(cfg)
        assert passed is False
        assert any("RISK_MODE" in e for e in errors)

    def test_tier_boundaries_wrong_order(self):
        cfg = _valid_config()
        cfg["TIER_WEAK_MIN"] = 90  # > TIER_MODERATE_MIN (68) — violates WEAK < MODERATE
        passed, errors = validate_app_config(cfg)
        assert passed is False
        assert any("Tier boundaries" in e for e in errors)

    def test_ai_threshold_dead_zone(self):
        cfg = _valid_config()
        cfg["AI_THRESHOLD"] = 80  # > TIER_WEAK_MIN=55 — creates dead zone
        passed, errors = validate_app_config(cfg)
        assert passed is False
        assert any("dead zone" in e for e in errors)

    def test_negative_base_capital(self):
        cfg = _valid_config()
        cfg["BASE_CAPITAL"] = 0
        passed, errors = validate_app_config(cfg)
        assert passed is False
        assert any("BASE_CAPITAL" in e for e in errors)

    def test_invalid_max_daily_loss(self):
        cfg = _valid_config()
        cfg["MAX_DAILY_LOSS"] = 100  # Must be negative
        passed, errors = validate_app_config(cfg)
        assert passed is False
        assert any("MAX_DAILY_LOSS" in e for e in errors)

    def test_vix_thresholds_inverted(self):
        cfg = _valid_config()
        cfg["VIX_HALT_THRESHOLD"] = 50.0  # > VIX_BLOCK_THRESHOLD=40
        cfg["VIX_BLOCK_THRESHOLD"] = 30.0  # < VIX_HALT_THRESHOLD
        passed, errors = validate_app_config(cfg)
        assert passed is False
        assert any("VIX" in e for e in errors)

    def test_invalid_environment(self):
        cfg = _valid_config()
        cfg["ENVIRONMENT"] = "invalid_env"
        passed, errors = validate_app_config(cfg)
        assert passed is False
        assert any("ENVIRONMENT" in e for e in errors)


# ═══════════════════════════════════════════════════════════════════════
#  Production environment checks
# ═══════════════════════════════════════════════════════════════════════


class TestValidateAppConfigProduction:
    def test_placeholder_bot_token_in_production(self):
        cfg = _valid_config()
        cfg["ENVIRONMENT"] = "production"
        cfg["BOT_TOKEN"] = "YOUR_TELEGRAM_BOT_TOKEN"
        passed, errors = validate_app_config(cfg)
        assert passed is False
        assert any("BOT_TOKEN" in e for e in errors)

    def test_placeholder_chat_id_in_production(self):
        cfg = _valid_config()
        cfg["ENVIRONMENT"] = "production"
        cfg["CHAT_ID"] = "YOUR_TELEGRAM_CHAT_ID"
        passed, errors = validate_app_config(cfg)
        assert passed is False
        assert any("CHAT_ID" in e for e in errors)

    def test_missing_broker_api_key_in_production(self):
        cfg = _valid_config()
        cfg["ENVIRONMENT"] = "production"
        cfg["BROKER_CONFIG"] = {"api_key": ""}
        passed, errors = validate_app_config(cfg)
        assert passed is False
        assert any("BROKER_CONFIG" in e for e in errors)

    def test_valid_production_config_passes(self):
        cfg = _valid_config()
        cfg["ENVIRONMENT"] = "production"
        cfg["BOT_TOKEN"] = "real_token_12345"
        cfg["CHAT_ID"] = "-1001234567890"
        cfg["BROKER_CONFIG"] = {"api_key": "real_api_key"}
        passed, errors = validate_app_config(cfg)
        assert passed is True


# ═══════════════════════════════════════════════════════════════════════
#  validate_environment_vars
# ═══════════════════════════════════════════════════════════════════════


class TestValidateEnvironmentVars:
    def test_passes_when_no_overrides(self):
        passed, msg = validate_environment_vars()
        assert passed is True

    def test_logs_active_overrides(self):
        with patch.dict(os.environ, {"OPBUYING_BOT_TOKEN": "secret"}, clear=False):
            passed, msg = validate_environment_vars()
            assert passed is True


# ═══════════════════════════════════════════════════════════════════════
#  run_startup_validation — full pipeline with DEBT-005 fail-fast
# ═══════════════════════════════════════════════════════════════════════


class TestRunStartupValidation:
    def test_all_validations_pass(self):
        """With valid config and fail_fast=False, returns True."""
        result = run_startup_validation(
            cfg=_valid_config(),
            flavour="index",
            fail_fast=False,
        )
        assert result is True

    def test_config_errors_return_false(self):
        """With invalid config and fail_fast=False, returns False."""
        cfg = {"EXECUTION_MODE": "BAD"}
        result = run_startup_validation(
            cfg=cfg,
            flavour="index",
            fail_fast=False,
        )
        assert result is False

    def test_fail_fast_raises_system_exit(self):
        """With invalid config and fail_fast=True, raises SystemExit."""
        cfg = {"EXECUTION_MODE": "BAD"}
        with pytest.raises(SystemExit) as excinfo:
            run_startup_validation(
                cfg=cfg,
                flavour="index",
                fail_fast=True,
            )
        assert "Startup validation failed" in str(excinfo.value)

    def test_fail_fast_without_config_still_validates(self):
        """Even without config, risk engine and dependencies are checked."""
        result = run_startup_validation(
            cfg=None,
            fail_fast=False,
        )
        assert result is True

    def test_production_fail_fast(self):
        """Production config with placeholder values raises SystemExit."""
        cfg = _valid_config()
        cfg["ENVIRONMENT"] = "production"
        cfg["BOT_TOKEN"] = "YOUR_TELEGRAM_BOT_TOKEN"
        with pytest.raises(SystemExit) as excinfo:
            run_startup_validation(
                cfg=cfg,
                flavour="index",
                fail_fast=True,
            )
        assert "Startup validation failed" in str(excinfo.value)
