"""Tests for core/config_v2.py — V2 config loading and legacy flattening."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from core.config_v2 import get_legacy_flat_config, load_config_v2, load_dotenv


class TestLoadDotenv:
    """Tests for the basic dotenv loader."""

    def test_env_file_not_found_does_nothing(self):
        load_dotenv("C:/nonexistent_dir/.env")
        # Should not raise

    def test_env_file_loaded(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False, encoding="utf-8") as f:
            f.write("# Comment\n")
            f.write("BOT_TOKEN=test-token-123\n")
            f.write("CHAT_ID=-1001234567\n")
            env_path = f.name
        try:
            load_dotenv(env_path)
            assert os.environ.get("BOT_TOKEN") == "test-token-123"
            assert os.environ.get("CHAT_ID") == "-1001234567"
        finally:
            os.unlink(env_path)
            os.environ.pop("BOT_TOKEN", None)
            os.environ.pop("CHAT_ID", None)

    def test_empty_line_skipped(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False, encoding="utf-8") as f:
            f.write("\n\n")
            f.write("KEY=value\n")
            env_path = f.name
        try:
            load_dotenv(env_path)
            assert os.environ.get("KEY") == "value"
        finally:
            os.unlink(env_path)
            os.environ.pop("KEY", None)

    def test_line_without_equals_skipped(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False, encoding="utf-8") as f:
            f.write("JUST_A_LINE\n")
            f.write("REAL_KEY=real_value\n")
            env_path = f.name
        try:
            load_dotenv(env_path)
            assert os.environ.get("JUST_A_LINE") is None
            assert os.environ.get("REAL_KEY") == "real_value"
        finally:
            os.unlink(env_path)
            os.environ.pop("REAL_KEY", None)


class TestLoadConfigV2:
    """Tests for load_config_v2."""

    def test_missing_config_returns_empty(self):
        cfg = load_config_v2("C:/nonexistent_dir/config_v2.json")
        assert cfg == {}

    def test_config_loaded_and_secrets_injected(self):
        data = {"thresholds": {"strong": 80}, "features": {}}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(data, f)
            config_path = f.name
        try:
            os.environ["BOT_TOKEN"] = "env-token"
            os.environ["CHAT_ID"] = "env-chat"
            load_config_v2(str(Path(config_path).name))
            # Since load_config_v2 resolves relative to CWD, use absolute
            cfg2 = load_config_v2(config_path)
            assert cfg2.get("thresholds", {}).get("strong") == 80
            assert cfg2.get("secrets", {}).get("bot_token") == "env-token"
            assert cfg2.get("secrets", {}).get("chat_id") == "env-chat"
        finally:
            os.unlink(config_path)
            os.environ.pop("BOT_TOKEN", None)
            os.environ.pop("CHAT_ID", None)

    def test_secrets_section_created_if_missing(self):
        data = {"thresholds": {"strong": 75}}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(data, f)
            config_path = f.name
        try:
            os.environ["BOT_TOKEN"] = "secret-token"
            cfg = load_config_v2(config_path)
            assert "secrets" in cfg
        finally:
            os.unlink(config_path)
            os.environ.pop("BOT_TOKEN", None)


class TestGetLegacyFlatConfig:
    """Tests for get_legacy_flat_config."""

    def test_empty_v2_config(self):
        flat = get_legacy_flat_config({})
        assert isinstance(flat, dict)

    def test_basic_mapping(self):
        v2 = {
            "thresholds": {"strong": 80, "rsi_overbought": 75},
            "risk": {"max_daily_loss": -500, "risk_mode": "FIXED"},
            "features": {"execution_mode": "MANUAL"},
            "timing": {"scan_interval": 60},
        }
        flat = get_legacy_flat_config(v2)
        assert flat["STRONG_THRESHOLD"] == 80
        assert flat["RSI_OVERBOUGHT"] == 75
        assert flat["MAX_DAILY_LOSS"] == -500
        assert flat["RISK_MODE"] == "FIXED"
        assert flat["EXECUTION_MODE"] == "MANUAL"
        assert flat["SCAN_INTERVAL"] == 60

    def test_secrets_mapped(self):
        v2 = {"secrets": {"bot_token": "tok", "chat_id": "cid"}}
        flat = get_legacy_flat_config(v2)
        assert flat["BOT_TOKEN"] == "tok"
        assert flat["CHAT_ID"] == "cid"

    def test_defaults_when_keys_missing(self):
        flat = get_legacy_flat_config({})
        assert flat["STRONG_THRESHOLD"] == 75
        assert flat["MAX_DAILY_LOSS"] == -400
        assert flat["EXECUTION_MODE"] == "MANUAL"
        assert flat["SCAN_INTERVAL"] == 30
        assert flat["BOT_TOKEN"] == ""

    def test_legacy_flat_preserved(self):
        v2 = {"legacy_flat": {"CUSTOM_KEY": "custom_value"}}
        flat = get_legacy_flat_config(v2)
        assert flat["CUSTOM_KEY"] == "custom_value"

    def test_nested_dicts_preserved(self):
        v2 = {
            "index_map": {"NIFTY": "NSE"},
            "broker_config": {"driver": "kite"},
        }
        flat = get_legacy_flat_config(v2)
        assert flat["INDEX_MAP"] == {"NIFTY": "NSE"}
        assert flat["BROKER_CONFIG"] == {"driver": "kite"}

    def test_all_timing_defaults(self):
        flat = get_legacy_flat_config({})
        assert flat["COOLDOWN"] == 300
        assert flat["SIGNAL_MAX_AGE"] == 65
        assert flat["MAX_POSITION_AGE"] == 120
        assert flat["SUMMARY_INTERVAL"] == 600

    def test_all_threshold_defaults(self):
        flat = get_legacy_flat_config({})
        assert flat["AI_THRESHOLD"] == 70
        assert flat["IV_SPIKE_THRESHOLD"] == 60.0
        assert flat["ATR_MIN_THRESHOLD"] == 0.5
        assert flat["VOL_RATIO_MIN"] == 1.2
        assert flat["RSI_OVERSOLD"] == 30
