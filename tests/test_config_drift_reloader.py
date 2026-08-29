"""Tests for core.config_drift_reloader — CONFIG_DRIFT_AUTO_RELOAD.

Covers:
- check() no-ops when the file hasn't changed (mtime unchanged / missing)
- safe-allowlisted keys are hot-applied into the live cfg dict
- risk-sensitive (immutable) keys are never hot-applied, even if changed
- unlisted keys are left alone and reported as "ignored" (restart required)
- singleton accessor get_config_drift_reloader()/reset_config_drift_reloader()
"""
from __future__ import annotations

import json

import pytest
from core.config_drift_reloader import (
    IMMUTABLE_RELOAD_KEYS,
    SAFE_RELOAD_KEYS,
    ConfigDriftReloader,
    get_config_drift_reloader,
    reset_config_drift_reloader,
)


@pytest.fixture(autouse=True)
def _reset_singleton():
    reset_config_drift_reloader()
    yield
    reset_config_drift_reloader()


class TestNoChange:
    def test_missing_file_is_a_noop(self, tmp_path):
        cfg = {"BREAKOUT_BONUS": 8}
        reloader = ConfigDriftReloader(cfg, config_path=tmp_path / "no_such_config.json")
        result = reloader.check()
        assert result == {"reloaded": [], "blocked": [], "ignored": []}
        assert cfg == {"BREAKOUT_BONUS": 8}

    def test_unchanged_mtime_skips_reread(self, tmp_path):
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({"BREAKOUT_BONUS": 20}), encoding="utf-8")
        cfg = {"BREAKOUT_BONUS": 8}
        reloader = ConfigDriftReloader(cfg, config_path=config_path)
        reloader.check()
        assert cfg["BREAKOUT_BONUS"] == 20  # applied on first check

        # Mutate cfg back without touching the file's mtime; a second check
        # with the same mtime must not re-read and must not reapply.
        cfg["BREAKOUT_BONUS"] = 8
        reloader.check()
        assert cfg["BREAKOUT_BONUS"] == 8


class TestSafeKeyHotApply:
    def test_safe_key_change_is_applied_live(self, tmp_path):
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({"BREAKOUT_BONUS": 15}), encoding="utf-8")
        cfg = {"BREAKOUT_BONUS": 8}
        reloader = ConfigDriftReloader(cfg, config_path=config_path)
        result = reloader.check()
        assert cfg["BREAKOUT_BONUS"] == 15
        assert any(entry.startswith("BREAKOUT_BONUS:") for entry in result["reloaded"])

    def test_new_safe_key_not_previously_present_is_applied(self, tmp_path):
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({"TG_COOLDOWN_SECS": 90}), encoding="utf-8")
        cfg: dict = {}
        reloader = ConfigDriftReloader(cfg, config_path=config_path)
        reloader.check()
        assert cfg["TG_COOLDOWN_SECS"] == 90


class TestImmutableKeysNeverHotApplied:
    def test_risk_sensitive_key_change_is_blocked_not_applied(self, tmp_path):
        assert "MAX_DRAWDOWN" in IMMUTABLE_RELOAD_KEYS
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({"MAX_DRAWDOWN": 0.9}), encoding="utf-8")
        cfg = {"MAX_DRAWDOWN": 0.2}
        reloader = ConfigDriftReloader(cfg, config_path=config_path)
        result = reloader.check()
        assert cfg["MAX_DRAWDOWN"] == 0.2  # unchanged - never hot-applied
        assert "MAX_DRAWDOWN" in result["blocked"]

    def test_sl_pct_change_is_blocked(self, tmp_path):
        assert "SL_PCT" in IMMUTABLE_RELOAD_KEYS
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({"SL_PCT": 0.5}), encoding="utf-8")
        cfg = {"SL_PCT": 0.92}
        reloader = ConfigDriftReloader(cfg, config_path=config_path)
        reloader.check()
        assert cfg["SL_PCT"] == 0.92


class TestUnlistedKeysIgnored:
    def test_unlisted_key_change_is_ignored_not_applied(self, tmp_path):
        key = "SOME_RANDOM_KEY_NOT_ON_EITHER_LIST"
        assert key not in SAFE_RELOAD_KEYS
        assert key not in IMMUTABLE_RELOAD_KEYS
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({key: "new_value"}), encoding="utf-8")
        cfg = {key: "old_value"}
        reloader = ConfigDriftReloader(cfg, config_path=config_path)
        result = reloader.check()
        assert cfg[key] == "old_value"
        assert key in result["ignored"]


class TestFailOpen:
    def test_corrupt_json_does_not_raise(self, tmp_path):
        config_path = tmp_path / "config.json"
        config_path.write_text("{not valid json", encoding="utf-8")
        cfg = {"BREAKOUT_BONUS": 8}
        reloader = ConfigDriftReloader(cfg, config_path=config_path)
        result = reloader.check()  # must not raise
        assert result == {"reloaded": [], "blocked": [], "ignored": []}
        assert cfg == {"BREAKOUT_BONUS": 8}


class TestSingleton:
    def test_get_returns_same_instance(self):
        cfg = {}
        a = get_config_drift_reloader(cfg)
        b = get_config_drift_reloader(cfg)
        assert a is b

    def test_reset_creates_a_fresh_instance(self):
        cfg = {}
        a = get_config_drift_reloader(cfg)
        reset_config_drift_reloader()
        b = get_config_drift_reloader(cfg)
        assert a is not b
