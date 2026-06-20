"""
Tests for config_bootstrap — shared merged-config loading, env overrides, drift detection.

Covers:
- ConfigChange dataclass
- classify_change_risk: CRITICAL / HIGH / NORMAL
- diff_configs: change detection, secret redaction, risk classification
- write_config_changes_jsonl / read_recent_config_changes: JSONL persistence
- apply_env_overrides: env var prefix matching, type coercion
- coerce_config_values_to_defaults_types: type casting
- _freeze_config: immutable config dicts
- decode_secret_keys: backward compat
- Module constants: CRITICAL_CONFIG_KEYS, HIGH_RISK_CONFIG_KEYS
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from core.config_bootstrap import (
    CRITICAL_CONFIG_KEYS,
    HIGH_RISK_CONFIG_KEYS,
    ConfigChange,
    apply_env_overrides,
    classify_change_risk,
    coerce_config_values_to_defaults_types,
    decode_secret_keys,
    diff_configs,
    read_recent_config_changes,
    write_config_changes_jsonl,
)


# ── Module Constants ──────────────────────────────────────────────────────


class TestConstants:
    def test_critical_config_keys_present(self):
        assert "MAX_DAILY_LOSS" in CRITICAL_CONFIG_KEYS
        assert "MAX_DRAWDOWN" in CRITICAL_CONFIG_KEYS
        assert "SL_PCT" in CRITICAL_CONFIG_KEYS
        assert "EXECUTION_MODE" in CRITICAL_CONFIG_KEYS

    def test_high_risk_config_keys_present(self):
        assert "SCAN_INTERVAL" in HIGH_RISK_CONFIG_KEYS
        assert "SIGNAL_THRESHOLD_STRONG" in HIGH_RISK_CONFIG_KEYS
        assert "BASE_CAPITAL" in HIGH_RISK_CONFIG_KEYS


# ── ConfigChange Dataclass ────────────────────────────────────────────────


class TestConfigChange:
    def test_creation(self):
        change = ConfigChange(
            key="SL_PCT",
            old_value=0.05,
            new_value=0.10,
            changed_at="2024-01-01T00:00:00",
            changed_by="hot_reload",
            risk_level="CRITICAL",
        )
        assert change.key == "SL_PCT"
        assert change.old_value == 0.05
        assert change.new_value == 0.10
        assert change.risk_level == "CRITICAL"

    def test_frozen(self):
        change = ConfigChange(key="K", old_value=1, new_value=2, changed_at="ts", changed_by="me", risk_level="NORMAL")
        with pytest.raises(AttributeError):
            change.key = "OTHER"  # type: ignore[misc]

    def test_all_fields(self):
        change = ConfigChange(
            key="MAX_DAILY_LOSS",
            old_value=-4000,
            new_value=-5000,
            changed_at="2024-06-19T10:30:00",
            changed_by="startup",
            risk_level="CRITICAL",
        )
        assert change.changed_by == "startup"
        assert change.risk_level == "CRITICAL"


# ── classify_change_risk ──────────────────────────────────────────────────


class TestClassifyChangeRisk:
    def test_critical_keys(self):
        for key in CRITICAL_CONFIG_KEYS:
            assert classify_change_risk(key) == "CRITICAL", f"{key} should be CRITICAL"

    def test_high_risk_keys(self):
        for key in HIGH_RISK_CONFIG_KEYS:
            assert classify_change_risk(key) == "HIGH", f"{key} should be HIGH"

    def test_normal_keys(self):
        assert classify_change_risk("SOME_OTHER_KEY") == "NORMAL"

    def test_case_insensitive(self):
        assert classify_change_risk("max_daily_loss") == "CRITICAL"
        assert classify_change_risk("sl_pct") == "CRITICAL"
        assert classify_change_risk("scan_interval") == "HIGH"

    def test_empty_key(self):
        assert classify_change_risk("") == "NORMAL"

    def test_partial_match(self):
        """Keys that contain but don't match exactly are NORMAL."""
        assert classify_change_risk("MAX_DAILY_LOSS_EXTRA") == "NORMAL"


# ── diff_configs ──────────────────────────────────────────────────────────


class TestDiffConfigs:
    def test_no_changes(self):
        cfg = {"PARAM_A": 1, "PARAM_B": 2}
        changes = diff_configs(cfg, cfg)
        assert changes == []

    def test_value_changed(self):
        old = {"PARAM_A": 1, "PARAM_B": 2}
        new = {"PARAM_A": 1, "PARAM_B": 3}
        changes = diff_configs(old, new)
        assert len(changes) == 1
        assert changes[0].key == "PARAM_B"
        assert changes[0].old_value == 2
        assert changes[0].new_value == 3

    def test_key_added(self):
        old = {"PARAM_A": 1}
        new = {"PARAM_A": 1, "PARAM_B": 2}
        changes = diff_configs(old, new)
        assert len(changes) == 1
        assert changes[0].key == "PARAM_B"
        assert changes[0].old_value is None

    def test_key_removed(self):
        old = {"PARAM_A": 1, "PARAM_B": 2}
        new = {"PARAM_A": 1}
        changes = diff_configs(old, new)
        assert len(changes) == 1
        assert changes[0].key == "PARAM_B"
        assert changes[0].new_value is None

    def test_secret_key_redacted(self):
        """Keys containing token/key/secret/password are skipped."""
        old = {"API_TOKEN": "old_secret", "NORMAL": 1}
        new = {"API_TOKEN": "new_secret", "NORMAL": 2}
        changes = diff_configs(old, new)
        # Only NORMAL should appear, API_TOKEN should be redacted
        keys = [c.key for c in changes]
        assert "API_TOKEN" not in keys
        assert "NORMAL" in keys

    def test_risk_level_classification(self):
        old = {"MAX_DAILY_LOSS": -4000, "SOME_PARAM": 1}
        new = {"MAX_DAILY_LOSS": -5000, "SOME_PARAM": 2}
        changes = diff_configs(old, new)
        risks = {c.key: c.risk_level for c in changes}
        assert risks["MAX_DAILY_LOSS"] == "CRITICAL"
        assert risks["SOME_PARAM"] == "NORMAL"

    def test_changed_by_default(self):
        old = {"PARAM_X": 1}
        new = {"PARAM_X": 2}
        changes = diff_configs(old, new)
        assert changes[0].changed_by == "startup"

    def test_changed_by_custom(self):
        old = {"PARAM_X": 1}
        new = {"PARAM_X": 2}
        changes = diff_configs(old, new, changed_by="hot_reload")
        assert changes[0].changed_by == "hot_reload"

    def test_both_none_skipped(self):
        old = {"PARAM_X": None}
        new = {"PARAM_X": None}
        changes = diff_configs(old, new)
        assert len(changes) == 0

    def test_multiple_changes(self):
        old = {"PARAM_A": 1, "PARAM_B": 2, "PARAM_C": 3}
        new = {"PARAM_A": 10, "PARAM_B": 20, "PARAM_C": 3}
        changes = diff_configs(old, new)
        assert len(changes) == 2


# ── write_config_changes_jsonl / read_recent_config_changes ──────────────


class TestConfigChangesJsonl:
    def test_write_single_change(self, tmp_path: Path):
        path = tmp_path / "changes.jsonl"
        change = ConfigChange(key="K", old_value=1, new_value=2, changed_at="ts", changed_by="me", risk_level="NORMAL")
        write_config_changes_jsonl([change], path)
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["key"] == "K"
        assert data["risk_level"] == "NORMAL"

    def test_append_multiple_writes(self, tmp_path: Path):
        path = tmp_path / "changes.jsonl"
        c1 = ConfigChange(key="A", old_value=1, new_value=2, changed_at="ts1", changed_by="me", risk_level="NORMAL")
        c2 = ConfigChange(key="B", old_value=3, new_value=4, changed_at="ts2", changed_by="you", risk_level="HIGH")
        write_config_changes_jsonl([c1], path)
        write_config_changes_jsonl([c2], path)
        lines = path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2

    def test_read_no_file(self, tmp_path: Path):
        path = tmp_path / "nonexistent.jsonl"
        result = read_recent_config_changes(path)
        assert result == []

    def test_read_basic(self, tmp_path: Path):
        path = tmp_path / "changes.jsonl"
        c = ConfigChange(key="K", old_value=1, new_value=2, changed_at="ts", changed_by="me", risk_level="NORMAL")
        write_config_changes_jsonl([c], path)
        result = read_recent_config_changes(path)
        assert len(result) == 1
        assert result[0]["key"] == "K"

    def test_read_limit(self, tmp_path: Path):
        path = tmp_path / "changes.jsonl"
        for i in range(5):
            c = ConfigChange(key=f"K{i}", old_value=i, new_value=i+1, changed_at=f"ts{i}", changed_by="me", risk_level="NORMAL")
            write_config_changes_jsonl([c], path)
        result = read_recent_config_changes(path, limit=2)
        assert len(result) == 2

    def test_skips_invalid_json_lines(self, tmp_path: Path):
        path = tmp_path / "changes.jsonl"
        path.write_text('{"valid": true}\ninvalid json\n{"also_valid": true}\n', encoding="utf-8")
        result = read_recent_config_changes(path)
        assert len(result) == 2

    def test_creates_parent_directory(self, tmp_path: Path):
        path = tmp_path / "subdir" / "nested" / "changes.jsonl"
        c = ConfigChange(key="K", old_value=1, new_value=2, changed_at="ts", changed_by="me", risk_level="NORMAL")
        write_config_changes_jsonl([c], path)
        assert path.exists()


# ── apply_env_overrides ────────────────────────────────────────────────────


class TestApplyEnvOverrides:
    def test_matching_env_var_overrides(self):
        cfg = {"BASE_CAPITAL": 100000, "SL_PCT": 0.05}
        defaults = {"BASE_CAPITAL": 100000, "SL_PCT": 0.05}
        with patch.dict(os.environ, {"OPBUYING_BASE_CAPITAL": "150000"}, clear=False):
            applied = apply_env_overrides(cfg, defaults)
            assert applied == 1
            assert cfg["BASE_CAPITAL"] == 150000

    def test_non_matching_prefix_ignored(self):
        cfg = {"KEY": 1}
        defaults = {"KEY": 1}
        with patch.dict(os.environ, {"OTHER_KEY": "2"}, clear=False):
            applied = apply_env_overrides(cfg, defaults)
            assert applied == 0

    def test_type_coercion_int(self):
        cfg = {"SCAN_INTERVAL": 30}
        defaults = {"SCAN_INTERVAL": 30}
        with patch.dict(os.environ, {"OPBUYING_SCAN_INTERVAL": "60"}, clear=False):
            apply_env_overrides(cfg, defaults)
            assert cfg["SCAN_INTERVAL"] == 60
            assert isinstance(cfg["SCAN_INTERVAL"], int)

    def test_type_coercion_float(self):
        cfg = {"SL_PCT": 0.05}
        defaults = {"SL_PCT": 0.05}
        with patch.dict(os.environ, {"OPBUYING_SL_PCT": "0.10"}, clear=False):
            apply_env_overrides(cfg, defaults)
            assert cfg["SL_PCT"] == 0.10
            assert isinstance(cfg["SL_PCT"], float)

    def test_type_coercion_bool_true(self):
        cfg = {"FEATURE_ENABLED": False}
        defaults = {"FEATURE_ENABLED": False}
        with patch.dict(os.environ, {"OPBUYING_FEATURE_ENABLED": "true"}, clear=False):
            apply_env_overrides(cfg, defaults)
            assert cfg["FEATURE_ENABLED"] is True

    def test_type_coercion_bool_false(self):
        cfg = {"FEATURE_ENABLED": True}
        defaults = {"FEATURE_ENABLED": True}
        with patch.dict(os.environ, {"OPBUYING_FEATURE_ENABLED": "false"}, clear=False):
            apply_env_overrides(cfg, defaults)
            assert cfg["FEATURE_ENABLED"] is False

    def test_case_insensitive_key_match(self):
        cfg = {"base_capital": 100000}  # lowercase key
        defaults = {"base_capital": 100000}
        with patch.dict(os.environ, {"OPBUYING_BASE_CAPITAL": "200000"}, clear=False):
            apply_env_overrides(cfg, defaults)
            assert cfg["base_capital"] == 200000

    def test_no_prefix_returns_zero(self):
        cfg = {"K": 1}
        defaults = {"K": 1}
        with patch.dict(os.environ, {"OPBUYING_K": "2"}, clear=False):
            applied = apply_env_overrides(cfg, defaults, prefix="")
            assert applied == 0

    def test_int_coercion_fallback_to_string(self):
        """When int coercion fails, keep raw string."""
        cfg = {"SCAN_INTERVAL": 30}
        defaults = {"SCAN_INTERVAL": 30}
        with patch.dict(os.environ, {"OPBUYING_SCAN_INTERVAL": "not_an_int"}, clear=False):
            apply_env_overrides(cfg, defaults)
            assert cfg["SCAN_INTERVAL"] == "not_an_int"

    def test_unknown_key_ignored(self):
        cfg = {"EXISTING_KEY": 1}
        defaults = {"EXISTING_KEY": 1}
        with patch.dict(os.environ, {"OPBUYING_UNKNOWN_KEY": "2", "OPBUYING_EXISTING_KEY": "3"}, clear=False):
            applied = apply_env_overrides(cfg, defaults)
            assert applied == 1
            assert cfg["EXISTING_KEY"] == 3


# ── coerce_config_values_to_defaults_types ────────────────────────────────


class TestCoerceConfigValues:
    def test_bool_from_string(self):
        result = coerce_config_values_to_defaults_types({"FLAG": "true"}, {"FLAG": False})
        assert result["FLAG"] is True

    def test_int_from_string(self):
        result = coerce_config_values_to_defaults_types({"COUNT": "42"}, {"COUNT": 0})
        assert result["COUNT"] == 42

    def test_float_from_string(self):
        result = coerce_config_values_to_defaults_types({"PCT": "0.15"}, {"PCT": 0.0})
        assert result["PCT"] == 0.15

    def test_no_default_unchanged(self):
        """Keys not in defaults remain unchanged."""
        result = coerce_config_values_to_defaults_types({"EXTRA": "42"}, {})
        assert result["EXTRA"] == "42"

    def test_type_already_matches(self):
        result = coerce_config_values_to_defaults_types({"COUNT": 42}, {"COUNT": 0})
        assert result["COUNT"] == 42

    def test_int_coercion_failure(self):
        """When int coercion fails, original value is kept."""
        result = coerce_config_values_to_defaults_types({"COUNT": "not_int"}, {"COUNT": 0})
        assert result["COUNT"] == "not_int"  # kept as-is


# ── decode_secret_keys ─────────────────────────────────────────────────────


class TestDecodeSecretKeys:
    def test_returns_dict_copy(self):
        result = decode_secret_keys({"KEY": "value"}, frozenset())
        assert result == {"KEY": "value"}
        assert result is not {"KEY": "value"}  # different object


# ── _freeze_config (tested via behavior) ──────────────────────────────────


class TestFreezeConfig:
    def test_freeze_prevents_mutation(self):
        """_freeze_config returns an immutable mapping."""
        from core.config_bootstrap import _freeze_config
        frozen = _freeze_config({"KEY": "value", "NESTED": {"inner": "val"}})
        with pytest.raises(TypeError):
            frozen["KEY"] = "new"  # type: ignore[index]

    def test_freeze_nested_dict_immutable(self):
        """Nested dicts are frozen too."""
        from core.config_bootstrap import _freeze_config
        frozen = _freeze_config({"NESTED": {"inner": "val"}})
        with pytest.raises(TypeError):
            frozen["NESTED"]["inner"] = "new"  # type: ignore[index]

    def test_freeze_converts_lists_to_tuples(self):
        """Lists become tuples for immutability."""
        from core.config_bootstrap import _freeze_config
        frozen = _freeze_config({"ITEMS": [1, 2, 3]})
        assert isinstance(frozen["ITEMS"], tuple)
        assert frozen["ITEMS"] == (1, 2, 3)
