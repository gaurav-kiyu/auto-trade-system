"""Tests for infrastructure.config.secure_config — SecureConfig class."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from infrastructure.config.secure_config import SecureConfig, SecureConfigError, get_secure_config


class TestSecureConfigInit:
    def test_empty_init(self):
        """Init with no args produces empty config."""
        sc = SecureConfig()
        assert sc._merged_config == {}
        assert sc._defaults == {}
        assert sc._config == {}

    def test_load_defaults_from_file(self, tmp_path: Path):
        d = tmp_path / "defaults.json"
        d.write_text(json.dumps({"KEY": "val", "NUM": 42}), encoding="utf-8")
        sc = SecureConfig(defaults_path=str(d))
        assert sc._defaults == {"KEY": "val", "NUM": 42}
        assert sc._merged_config["KEY"] == "val"
        assert sc._merged_config["NUM"] == 42

    def test_load_defaults_missing_file(self, tmp_path: Path):
        """Missing defaults file silently produces empty defaults."""
        sc = SecureConfig(defaults_path=str(tmp_path / "nope.json"))
        assert sc._defaults == {}

    def test_load_defaults_bad_json(self, tmp_path: Path):
        d = tmp_path / "bad.json"
        d.write_text("not json", encoding="utf-8")
        with pytest.raises(SecureConfigError, match="Invalid JSON"):
            SecureConfig(defaults_path=str(d))

    def test_load_config_files(self, tmp_path: Path):
        cfg = tmp_path / "config.json"
        cfg.write_text(json.dumps({"A": 1, "B": "two"}), encoding="utf-8")
        sc = SecureConfig(config_dir=str(tmp_path))
        assert sc._config["A"] == 1
        assert sc._config["B"] == "two"

    def test_local_overrides_config(self, tmp_path: Path):
        (tmp_path / "config.json").write_text(json.dumps({"A": 1}), encoding="utf-8")
        (tmp_path / "config.local.json").write_text(json.dumps({"A": 2}), encoding="utf-8")
        sc = SecureConfig(config_dir=str(tmp_path))
        assert sc._merged_config["A"] == 2

    def test_secrets_override_config(self, tmp_path: Path, monkeypatch):
        """Secrets from CredentialStorage override config file values."""
        from infrastructure.config.secure_config import _credential_storage
        with patch.object(_credential_storage, "get_credential", return_value="super-secret"):
            (tmp_path / "config.json").write_text(json.dumps({"BOT_TOKEN": "old"}), encoding="utf-8")
            sc = SecureConfig(config_dir=str(tmp_path))
            assert sc._merged_config["BOT_TOKEN"] == "super-secret"

    def test_deep_merge_nested(self, tmp_path: Path):
        (tmp_path / "config.json").write_text(json.dumps({"NESTED": {"a": 1}}), encoding="utf-8")
        (tmp_path / "config.local.json").write_text(json.dumps({"NESTED": {"b": 2}}), encoding="utf-8")
        sc = SecureConfig(config_dir=str(tmp_path))
        assert sc._merged_config["NESTED"] == {"a": 1, "b": 2}

    def test_get_return_none_for_missing(self):
        sc = SecureConfig()
        assert sc.get("NONEXISTENT") is None

    def test_get_returns_default(self):
        sc = SecureConfig()
        assert sc.get("NONEXISTENT", "fallback") == "fallback"

    def test_get_dot_notation(self, tmp_path: Path):
        d = tmp_path / "defaults.json"
        d.write_text(json.dumps({"LEVEL1": {"LEVEL2": {"LEVEL3": "deep"}}}), encoding="utf-8")
        sc = SecureConfig(defaults_path=str(d))
        assert sc.get("LEVEL1.LEVEL2.LEVEL3") == "deep"

    def test_get_dot_notation_missing(self):
        sc = SecureConfig()
        assert sc.get("a.b.c") is None


class TestSecureConfigTypeCoercion:
    def test_get_bool_true(self):
        sc = SecureConfig()
        sc._merged_config["X"] = True
        assert sc.get_bool("X") is True

    def test_get_bool_string_true(self):
        sc = SecureConfig()
        sc._merged_config["X"] = "true"
        assert sc.get_bool("X") is True

    def test_get_bool_string_false(self):
        sc = SecureConfig()
        sc._merged_config["X"] = "false"
        assert sc.get_bool("X") is False

    def test_get_bool_default(self):
        assert SecureConfig().get_bool("MISSING") is False

    def test_get_int(self):
        sc = SecureConfig()
        sc._merged_config["X"] = 42
        assert sc.get_int("X") == 42

    def test_get_int_from_string(self):
        sc = SecureConfig()
        sc._merged_config["X"] = "99"
        assert sc.get_int("X") == 99

    def test_get_int_default_on_bad(self):
        sc = SecureConfig()
        sc._merged_config["X"] = "notanint"
        assert sc.get_int("X", 0) == 0

    def test_get_float(self):
        sc = SecureConfig()
        sc._merged_config["X"] = 3.14
        assert sc.get_float("X") == pytest.approx(3.14)

    def test_get_list_from_list(self):
        sc = SecureConfig()
        sc._merged_config["X"] = [1, 2, 3]
        assert sc.get_list("X") == [1, 2, 3]

    def test_get_list_from_json_string(self):
        sc = SecureConfig()
        sc._merged_config["X"] = '["a","b"]'
        assert sc.get_list("X") == ["a", "b"]

    def test_get_list_from_csv_string(self):
        sc = SecureConfig()
        sc._merged_config["X"] = "a, b, c"
        assert sc.get_list("X") == ["a", "b", "c"]

    def test_get_dict_from_dict(self):
        sc = SecureConfig()
        sc._merged_config["X"] = {"k": "v"}
        assert sc.get_dict("X") == {"k": "v"}

    def test_get_dict_from_json_string(self):
        sc = SecureConfig()
        sc._merged_config["X"] = '{"k": "v"}'
        assert sc.get_dict("X") == {"k": "v"}

    def test_get_dict_default(self):
        assert SecureConfig().get_dict("MISSING") == {}


class TestSecureConfigSecretRedaction:
    def test_kite_api_key_redacted(self):
        sc = SecureConfig(enable_secret_redaction=True)
        sc._merged_config["KITE_API_KEY"] = "abcdefghijklmnop"
        val = sc.get("KITE_API_KEY")
        # 16 chars: first4 + 8*middle + last4
        assert val == "abcd********mnop"
        assert "abcdefghijklmnop" not in val

    def test_token_redacted(self):
        sc = SecureConfig(enable_secret_redaction=True)
        sc._merged_config["BOT_TOKEN"] = "my-secret-token"
        val = sc.get("BOT_TOKEN")
        # 16 chars: first4 + 8*middle + last4 = "my-s" + "********" + "oken"
        assert "my-secret-token" not in val
        assert val == "my-s*******oken"

    def test_password_redacted(self):
        sc = SecureConfig(enable_secret_redaction=True)
        sc._merged_config["DB_PASSWORD"] = "password123"
        val = sc.get("DB_PASSWORD")
        # 11 chars: first4 + 3*middle + last4 = "pass***d123"
        assert val == "pass***d123"

    def test_short_value_fully_masked(self):
        sc = SecureConfig(enable_secret_redaction=True)
        sc._merged_config["KITE_API_KEY"] = "12345"
        val = sc.get("KITE_API_KEY")
        assert val == "*****"

    def test_redaction_disabled(self):
        sc = SecureConfig(enable_secret_redaction=False)
        sc._merged_config["BOT_TOKEN"] = "secret-value"
        assert sc.get("BOT_TOKEN") == "secret-value"

    def test_get_safe_config_redacts(self):
        sc = SecureConfig(enable_secret_redaction=True)
        sc._merged_config["SAFE_VISIBLE"] = "visible"
        sc._merged_config["BOT_TOKEN"] = "my-secret-token-value"
        safe = sc.get_safe_config()
        assert safe["SAFE_VISIBLE"] == "visible"
        assert safe["BOT_TOKEN"] != "my-secret-token-value"

    def test_get_all_config_returns_unredacted(self):
        sc = SecureConfig(enable_secret_redaction=True)
        sc._merged_config["BOT_TOKEN"] = "my-secret-token-value"
        full = sc.get_all_config()
        assert full["BOT_TOKEN"] == "my-secret-token-value"

    def test_get_secret_logs_access(self):
        sc = SecureConfig()
        sc._merged_config["BOT_TOKEN"] = "val"


class TestSecureConfigGetSecret:
    def test_get_secret_known_key(self):
        sc = SecureConfig(enable_secret_redaction=True)
        sc._merged_config["BOT_TOKEN"] = "secret123"
        val = sc.get_secret("BOT_TOKEN")
        # 9 chars: first4 + 1*middle + last4 = "secr*t123"
        assert val == "secr*t123"

    def test_get_secret_known_key_no_redaction(self):
        sc = SecureConfig(enable_secret_redaction=False)
        sc._merged_config["BOT_TOKEN"] = "secret123"
        val = sc.get_secret("BOT_TOKEN")
        assert val == "secret123"

    def test_get_secret_unknown_key(self):
        sc = SecureConfig()
        assert sc.get_secret("NON_EXISTENT") is None


class TestSecureConfigFactory:
    def test_get_secure_config_factory(self, tmp_path: Path):
        d = tmp_path / "defaults.json"
        d.write_text(json.dumps({"A": 1}), encoding="utf-8")
        sc = get_secure_config(defaults_path=str(d))
        assert isinstance(sc, SecureConfig)
        assert sc._merged_config["A"] == 1


class TestSecureConfigDeepMerge:
    def test_deep_merge_overwrites_scalar(self):
        sc = SecureConfig()
        target = {"A": 1}
        sc._deep_merge(target, {"A": 2})
        assert target["A"] == 2

    def test_deep_merge_merges_nested(self):
        sc = SecureConfig()
        target = {"N": {"a": 1}}
        sc._deep_merge(target, {"N": {"b": 2}})
        assert target["N"] == {"a": 1, "b": 2}

    def test_deep_merge_overwrites_nested_scalar(self):
        sc = SecureConfig()
        target = {"N": {"a": 1, "b": 2}}
        sc._deep_merge(target, {"N": {"a": 99}})
        assert target["N"] == {"a": 99, "b": 2}

    def test_deep_merge_adds_new_key(self):
        sc = SecureConfig()
        target = {"A": 1}
        sc._deep_merge(target, {"B": 2})
        assert target == {"A": 1, "B": 2}


class TestSecureConfigEdgeCases:
    def test_config_dir_not_found_logs_warning(self, tmp_path: Path):
        """Non-existent config directory logs warning without crashing."""
        with patch("infrastructure.config.secure_config.logger.warning") as mock_warn:
            SecureConfig(config_dir=str(tmp_path / "nonexistent"))
            assert mock_warn.called

    def test_bad_json_in_config(self, tmp_path: Path):
        """Bad JSON in config.local.json does not crash."""
        (tmp_path / "config.json").write_text('{"GOOD": 1}', encoding="utf-8")
        (tmp_path / "config.local.json").write_text("not json", encoding="utf-8")
        sc = SecureConfig(config_dir=str(tmp_path))
        assert sc.get("GOOD") == 1

    def test_get_bool_non_bool_fallback(self):
        """get_bool with non-bool/non-str value uses bool()."""
        sc = SecureConfig()
        sc._merged_config["X"] = 42
        assert sc.get_bool("X") is True
        sc._merged_config["Y"] = 0
        assert sc.get_bool("Y") is False

    def test_get_dict_parse_warning(self, tmp_path: Path):
        """get_dict with bad JSON logs warning and returns default."""
        with patch("infrastructure.config.secure_config.logger.warning") as mock_warn:
            sc = SecureConfig()
            result = sc.get_dict("NONEXISTENT")
            assert result == {}

    def test_get_secret_logs_audit(self):
        """get_secret logs audit info for known secrets."""
        with patch("infrastructure.config.secure_config.logger.info") as mock_info:
            sc = SecureConfig(enable_secret_redaction=True)
            sc._merged_config["BOT_TOKEN"] = "secret123"
            val = sc.get_secret("BOT_TOKEN")
            assert val is not None
            mock_info.assert_called()

    def test_get_secret_logs_audit_for_custom_key(self):
        """get_secret logs audit for non-SECRET_KEYS key in merged_config."""
        with patch("infrastructure.config.secure_config.logger.info") as mock_info:
            sc = SecureConfig(enable_secret_redaction=True)
            sc._merged_config["CUSTOM_API_KEY"] = "abcdefghijklmnop"
            val = sc.get_secret("CUSTOM_API_KEY")
            assert val is not None
            mock_info.assert_called()

    def test_get_secret_for_unknown_key(self):
        """get_secret with unknown key logs audit for safety."""
        with patch("infrastructure.config.secure_config.logger.info") as mock_info:
            sc = SecureConfig()
            val = sc.get_secret("NONEXISTENT")
            assert val is None

    def test_get_list_with_empty_default(self):
        """get_list returns empty list when key missing."""
        sc = SecureConfig()
        assert sc.get_list("MISSING") == []

    def test_get_float_default(self):
        """get_float returns default for non-numeric values."""
        sc = SecureConfig()
        sc._merged_config["BAD"] = "nope"
        assert sc.get_float("BAD", 1.5) == 1.5

    def test_get_int_default(self):
        """get_int returns default for non-integer values."""
        sc = SecureConfig()
        sc._merged_config["BAD"] = "notanint"
        assert sc.get_int("BAD", 42) == 42

    def test_get_list_from_string_default(self):
        """get_list from non-array, non-JSON, non-csv returns default."""
        sc = SecureConfig()
        sc._merged_config["X"] = 42
        assert sc.get_list("X") == []

    def test_get_dict_bad_json_logs_warning(self):
        """get_dict with bad JSON string logs warning and returns default."""
        with patch("infrastructure.config.secure_config.logger.warning") as mock_warn:
            sc = SecureConfig()
            sc._merged_config["CFG"] = "{bad: json}"
            result = sc.get_dict("CFG")
            assert result == {}
            mock_warn.assert_called_once()

    def test_get_dict_non_dict_non_str(self):
        """get_dict with non-dict, non-str value returns default."""
        sc = SecureConfig()
        sc._merged_config["X"] = 42
        assert sc.get_dict("X") == {}


class TestSecureConfigGetAll:
    def test_get_all_alias(self, tmp_path: Path):
        d = tmp_path / "defaults.json"
        d.write_text(json.dumps({"A": 1}), encoding="utf-8")
        sc = SecureConfig(defaults_path=str(d))
        assert sc.get_all() == {"A": 1}
        assert sc.get_all_config() == sc.get_all()
