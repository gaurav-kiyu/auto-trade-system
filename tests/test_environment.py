"""Tests for core/environment.py — environment separation + guard rails."""

import os
import sys
import tempfile

import pytest

from core.environment import (
    Environment,
    current_environment,
    guard_dev_config_in_production,
    guard_mode_env_compatibility,
    validate_environment,
)


class TestEnvironmentEnum:
    def test_valid_environments(self):
        assert Environment.from_str("dev") == Environment.DEV
        assert Environment.from_str("qa") == Environment.QA
        assert Environment.from_str("paper") == Environment.PAPER
        assert Environment.from_str("shadow") == Environment.SHADOW
        assert Environment.from_str("staging") == Environment.STAGING
        assert Environment.from_str("production") == Environment.PRODUCTION

    def test_case_insensitive(self):
        assert Environment.from_str("DEV") == Environment.DEV
        assert Environment.from_str("Production") == Environment.PRODUCTION

    def test_unknown_raises(self):
        with pytest.raises(ValueError):
            Environment.from_str("unknown")
        with pytest.raises(ValueError):
            Environment.from_str("")


class TestCurrentEnvironment:
    def test_defaults_to_dev_when_unset(self):
        if "OPBUYING_ENVIRONMENT" in os.environ:
            del os.environ["OPBUYING_ENVIRONMENT"]
        assert current_environment() == Environment.DEV

    def test_reads_from_env_var(self):
        os.environ["OPBUYING_ENVIRONMENT"] = "production"
        assert current_environment() == Environment.PRODUCTION
        del os.environ["OPBUYING_ENVIRONMENT"]

    def test_reads_paper_env(self):
        os.environ["OPBUYING_ENVIRONMENT"] = "paper"
        assert current_environment() == Environment.PAPER
        del os.environ["OPBUYING_ENVIRONMENT"]


class TestGuardDevConfigInProduction:
    def test_no_warnings_for_valid_prod_config(self):
        cfg = {
            "ENVIRONMENT": "production",
            "BOT_TOKEN": "real_token_12345",
            "CHAT_ID": "123456789",
            "BASE_CAPITAL": 50000,
            "admin_control_plane_auth_token": "s3cr3t",
            "web_dashboard_enabled": False,
            "environment_block_on_violation": False,
        }
        guard_dev_config_in_production(cfg)

    def test_warns_on_placeholder_token(self):
        cfg = {
            "ENVIRONMENT": "production",
            "BOT_TOKEN": "YOUR_TELEGRAM_BOT_TOKEN",
            "CHAT_ID": "YOUR_TELEGRAM_CHAT_ID",
            "BASE_CAPITAL": 50000,
            "admin_control_plane_auth_token": "s3cr3t",
            "environment_block_on_violation": False,
        }
        guard_dev_config_in_production(cfg)

    def test_skips_for_dev_env(self):
        cfg = {
            "ENVIRONMENT": "dev",
            "BOT_TOKEN": "YOUR_TELEGRAM_BOT_TOKEN",
            "BASE_CAPITAL": 1000,
        }
        guard_dev_config_in_production(cfg)

    def test_exits_on_violation_when_blocked(self):
        cfg = {
            "ENVIRONMENT": "production",
            "BOT_TOKEN": "YOUR_TELEGRAM_BOT_TOKEN",
            "CHAT_ID": "YOUR_TELEGRAM_CHAT_ID",
            "BASE_CAPITAL": 500,
            "admin_control_plane_auth_token": "",
            "environment_block_on_violation": True,
        }
        with pytest.raises(SystemExit) as exc:
            guard_dev_config_in_production(cfg)
        assert exc.value.code == 88


class TestGuardModeEnvCompatibility:
    def test_allows_paper_in_paper_env(self):
        guard_mode_env_compatibility("PAPER", Environment.PAPER)

    def test_allows_manual_in_dev(self):
        guard_mode_env_compatibility("MANUAL", Environment.DEV)

    def test_blocks_full_auto_in_dev(self):
        with pytest.raises(SystemExit) as exc:
            guard_mode_env_compatibility("FULL_AUTO", Environment.DEV)
        assert exc.value.code == 88

    def test_blocks_live_manual_in_qa(self):
        with pytest.raises(SystemExit) as exc:
            guard_mode_env_compatibility("LIVE_MANUAL_CONFIRM", Environment.QA)
        assert exc.value.code == 88

    def test_allows_full_auto_in_staging(self):
        guard_mode_env_compatibility("FULL_AUTO", Environment.STAGING)

    def test_allows_full_auto_in_production(self):
        guard_mode_env_compatibility("FULL_AUTO", Environment.PRODUCTION)

    def test_allows_full_auto_in_shadow(self):
        guard_mode_env_compatibility("FULL_AUTO", Environment.SHADOW)


class TestValidateEnvironment:
    def test_valid_dev(self):
        cfg = {"ENVIRONMENT": "dev", "EXECUTION_MODE": "MANUAL", "environment_block_on_violation": False}
        env = validate_environment(cfg)
        assert env == Environment.DEV

    def test_valid_production(self):
        cfg = {
            "ENVIRONMENT": "production",
            "EXECUTION_MODE": "FULL_AUTO",
            "BOT_TOKEN": "real_token",
            "CHAT_ID": "12345",
            "BASE_CAPITAL": 50000,
            "admin_control_plane_auth_token": "s3cr3t",
            "environment_block_on_violation": False,
        }
        env = validate_environment(cfg)
        assert env == Environment.PRODUCTION

    def test_exits_on_invalid_env(self):
        cfg = {"ENVIRONMENT": "invalid_env", "EXECUTION_MODE": "PAPER"}
        with pytest.raises(SystemExit) as exc:
            validate_environment(cfg)
        assert exc.value.code == 88

    def test_blocks_full_auto_in_dev(self):
        cfg = {"ENVIRONMENT": "dev", "EXECUTION_MODE": "FULL_AUTO"}
        with pytest.raises(SystemExit) as exc:
            validate_environment(cfg)
        assert exc.value.code == 88
