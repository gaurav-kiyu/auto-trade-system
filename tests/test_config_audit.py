"""Tests for config change audit trail in core/config_bootstrap.py (v2.44 Item 6)."""
import json
import logging
import os
import tempfile

import pytest
from core.config_bootstrap import (
    CRITICAL_CONFIG_KEYS,
    HIGH_RISK_CONFIG_KEYS,
    ConfigChange,
    classify_change_risk,
    diff_configs,
    read_recent_config_changes,
    write_config_changes_jsonl,
)

# ── classify_change_risk ──────────────────────────────────────────────────────

def test_critical_key_classified_critical():
    for key in ["MAX_DAILY_LOSS", "MAX_DRAWDOWN", "RISK_MODE", "SL_PCT"]:
        assert classify_change_risk(key) == "CRITICAL"


def test_high_key_classified_high():
    for key in ["SCAN_INTERVAL", "BASE_LOTS", "BASE_CAPITAL"]:
        assert classify_change_risk(key) == "HIGH"


def test_normal_key_classified_normal():
    assert classify_change_risk("SOME_RANDOM_KEY") == "NORMAL"


def test_classification_case_insensitive():
    assert classify_change_risk("max_daily_loss") == "CRITICAL"
    assert classify_change_risk("Max_Daily_Loss") == "CRITICAL"


def test_critical_keys_frozenset():
    assert isinstance(CRITICAL_CONFIG_KEYS, frozenset)
    assert "MAX_DAILY_LOSS" in CRITICAL_CONFIG_KEYS


def test_high_risk_keys_frozenset():
    assert isinstance(HIGH_RISK_CONFIG_KEYS, frozenset)


# ── diff_configs ──────────────────────────────────────────────────────────────

def test_no_diff_on_identical_configs():
    cfg = {"A": 1, "B": "hello"}
    changes = diff_configs(cfg, cfg, "startup")
    assert changes == []


def test_detects_value_change():
    old = {"MAX_DAILY_LOSS": -2000}
    new = {"MAX_DAILY_LOSS": -3000}
    changes = diff_configs(old, new)
    assert len(changes) == 1
    assert changes[0].key == "MAX_DAILY_LOSS"
    assert changes[0].old_value == -2000
    assert changes[0].new_value == -3000


def test_detects_added_key():
    old = {"A": 1}
    new = {"A": 1, "B": 2}
    changes = diff_configs(old, new)
    assert any(c.key == "B" for c in changes)


def test_detects_removed_key():
    old = {"A": 1, "B": 2}
    new = {"A": 1}
    changes = diff_configs(old, new)
    assert any(c.key == "B" for c in changes)


def test_assigns_correct_risk_level():
    old = {"MAX_DAILY_LOSS": -2000, "SCAN_INTERVAL": 30, "HEARTBEAT_INTERVAL": 1}
    new = {"MAX_DAILY_LOSS": -3000, "SCAN_INTERVAL": 60, "HEARTBEAT_INTERVAL": 2}
    changes = {c.key: c for c in diff_configs(old, new)}
    assert changes["MAX_DAILY_LOSS"].risk_level == "CRITICAL"
    assert changes["SCAN_INTERVAL"].risk_level == "HIGH"
    assert changes["HEARTBEAT_INTERVAL"].risk_level == "NORMAL"


def test_excludes_secret_keys():
    old = {"BOT_TOKEN": "abc", "A": 1}
    new = {"BOT_TOKEN": "xyz", "A": 2}
    changes = diff_configs(old, new)
    keys = [c.key for c in changes]
    assert "BOT_TOKEN" not in keys
    assert "A" in keys


def test_change_has_timestamp():
    old = {"A": 1}
    new = {"A": 2}
    changes = diff_configs(old, new)
    assert len(changes[0].changed_at) > 0


def test_change_has_changed_by():
    old = {"A": 1}
    new = {"A": 2}
    changes = diff_configs(old, new, changed_by="hot_reload")
    assert changes[0].changed_by == "hot_reload"


def test_config_change_is_frozen():
    c = ConfigChange(
        key="X", old_value=1, new_value=2,
        changed_at="2024-01-01T10:00:00", changed_by="startup", risk_level="NORMAL"
    )
    with pytest.raises((AttributeError, TypeError)):
        c.key = "Y"


# ── write_config_changes_jsonl / read_recent_config_changes ──────────────────

def test_write_and_read_roundtrip():
    with tempfile.TemporaryDirectory() as tmp:
        log_path = os.path.join(tmp, "logs", "config_changes.jsonl")
        changes = diff_configs({"MAX_DAILY_LOSS": -2000}, {"MAX_DAILY_LOSS": -3000})
        write_config_changes_jsonl(changes, log_path=log_path)
        records = read_recent_config_changes(log_path=log_path)
        assert len(records) == 1
        assert records[0]["key"] == "MAX_DAILY_LOSS"


def test_write_creates_directory():
    with tempfile.TemporaryDirectory() as tmp:
        log_path = os.path.join(tmp, "deeply", "nested", "changes.jsonl")
        changes = diff_configs({"A": 1}, {"A": 2})
        write_config_changes_jsonl(changes, log_path=log_path)
        assert os.path.exists(log_path)


def test_read_empty_returns_empty_list():
    with tempfile.TemporaryDirectory() as tmp:
        log_path = os.path.join(tmp, "nonexistent.jsonl")
        result = read_recent_config_changes(log_path=log_path)
        assert result == []


def test_read_respects_limit():
    with tempfile.TemporaryDirectory() as tmp:
        log_path = os.path.join(tmp, "changes.jsonl")
        # Write 10 changes
        for i in range(10):
            changes = diff_configs({"A": i}, {"A": i + 1})
            write_config_changes_jsonl(changes, log_path=log_path)
        records = read_recent_config_changes(log_path=log_path, limit=3)
        assert len(records) == 3


# ── _check_config_drift (Audit Finding #12) ──────────────────────────────────

def _make_mock_secure_config(defaults_dict: dict, merged_dict: dict, defaults_path: str | None = None):
    """Create a mock object that quacks like SecureConfig for _check_config_drift."""
    class _MockSecureConfig:
        _merged_config = merged_dict
        _defaults_path = defaults_path
    return _MockSecureConfig()


def test_config_drift_logs_missing_defaults_key(caplog):
    """Keys in defaults.json but NOT in merged config should log WARNING."""
    with tempfile.TemporaryDirectory() as tmp:
        defaults_file = os.path.join(tmp, "defaults.json")
        with open(defaults_file, "w") as f:
            json.dump({"NEW_FEATURE_A": False, "NEW_FEATURE_B": 42}, f)

        merged = {"EXISTING_KEY": "value"}  # Missing both NEW_FEATURE_A and NEW_FEATURE_B
        mock_cfg = _make_mock_secure_config({}, merged, defaults_path=defaults_file)

        with caplog.at_level(logging.WARNING):
            from core.config_bootstrap import _check_config_drift
            _check_config_drift(mock_cfg)

        drift_msgs = [r for r in caplog.records if "CONFIG DRIFT" in r.message]
        # Expect 3 drift messages:
        #   2 for NEW_FEATURE_A, NEW_FEATURE_B (in defaults, missing from merged)
        #   1 for EXISTING_KEY (in merged, not in defaults)
        assert len(drift_msgs) == 3
        # The WARNING-level ones: missing defaults keys + normal-risk extra keys
        warning_msgs = [r for r in drift_msgs if r.levelno == logging.WARNING]
        assert len(warning_msgs) == 3  # All three are NORMAL risk or defaults-keys (low risk)
        # Verify missing defaults keys are warned
        missing_keys = [r for r in drift_msgs if "not found in merged config" in r.message]
        assert len(missing_keys) == 2
        missing_key_names = set()
        for r in missing_keys:
            if "NEW_FEATURE_A" in r.message:
                missing_key_names.add("NEW_FEATURE_A")
            if "NEW_FEATURE_B" in r.message:
                missing_key_names.add("NEW_FEATURE_B")
        assert missing_key_names == {"NEW_FEATURE_A", "NEW_FEATURE_B"}


def test_config_drift_logs_extra_keys_in_merged(caplog):
    """Keys in merged config but NOT in defaults should log WARNING (or CRITICAL for high-risk)."""
    with tempfile.TemporaryDirectory() as tmp:
        defaults_file = os.path.join(tmp, "defaults.json")
        with open(defaults_file, "w") as f:
            json.dump({"KNOWN_KEY": 1}, f)

        merged = {"KNOWN_KEY": 1, "DEPRECATED_KEY": "old", "MAX_DAILY_LOSS": -5000}
        mock_cfg = _make_mock_secure_config({}, merged, defaults_path=defaults_file)

        with caplog.at_level(logging.WARNING):
            from core.config_bootstrap import _check_config_drift
            _check_config_drift(mock_cfg)

        drift_msgs = [r for r in caplog.records if "CONFIG DRIFT" in r.message]
        assert len(drift_msgs) == 2

        # DEPRECATED_KEY is NORMAL risk → WARNING
        normal_msgs = [r for r in drift_msgs if "DEPRECATED_KEY" in r.message]
        assert len(normal_msgs) == 1
        assert normal_msgs[0].levelno == logging.WARNING

        # MAX_DAILY_LOSS is CRITICAL risk → CRITICAL level
        critical_msgs = [r for r in drift_msgs if "MAX_DAILY_LOSS" in r.message]
        assert len(critical_msgs) == 1
        assert critical_msgs[0].levelno == logging.CRITICAL


def test_config_drift_skips_when_no_defaults_file(caplog):
    """No crash when defaults file doesn't exist."""
    mock_cfg = _make_mock_secure_config({}, {"A": 1}, defaults_path="/nonexistent/path.json")
    from core.config_bootstrap import _check_config_drift
    # Should not raise
    _check_config_drift(mock_cfg)
    # No CONFIG DRIFT messages
    assert not any("CONFIG DRIFT" in r.message for r in caplog.records)


def test_config_drift_skips_when_defaults_path_is_none(caplog):
    """No crash when _defaults_path is None."""
    mock_cfg = _make_mock_secure_config({}, {"A": 1}, defaults_path=None)
    from core.config_bootstrap import _check_config_drift
    _check_config_drift(mock_cfg)
    assert not any("CONFIG DRIFT" in r.message for r in caplog.records)


def test_config_drift_no_drift_with_matching_configs(caplog):
    """When defaults and merged have same keys, no drift logged."""
    with tempfile.TemporaryDirectory() as tmp:
        defaults_file = os.path.join(tmp, "defaults.json")
        with open(defaults_file, "w") as f:
            json.dump({"A": 1, "B": "hello"}, f)

        merged = {"A": 1, "B": "hello"}  # Same keys
        mock_cfg = _make_mock_secure_config({}, merged, defaults_path=defaults_file)

        with caplog.at_level(logging.WARNING):
            from core.config_bootstrap import _check_config_drift
            _check_config_drift(mock_cfg)

        assert not any("CONFIG DRIFT" in r.message for r in caplog.records)


def test_config_drift_handles_invalid_defaults_json_gracefully(caplog):
    """Invalid JSON in defaults file should not crash — just debug log and return."""
    with tempfile.TemporaryDirectory() as tmp:
        defaults_file = os.path.join(tmp, "defaults.json")
        with open(defaults_file, "w") as f:
            f.write("{invalid json!!!}")

        merged = {"A": 1}
        mock_cfg = _make_mock_secure_config({}, merged, defaults_path=defaults_file)

        with caplog.at_level(logging.DEBUG):
            from core.config_bootstrap import _check_config_drift
            _check_config_drift(mock_cfg)  # Should not raise

        assert not any("CONFIG DRIFT" in r.message for r in caplog.records)


def test_config_drift_wired_in_initialize_secure_config(monkeypatch):
    """Verify that initialize_secure_config calls _check_config_drift."""
    from core.config_bootstrap import initialize_secure_config
    called = []

    def _tracking_drift(secure_cfg):
        called.append(secure_cfg)

    monkeypatch.setattr("core.config_bootstrap._check_config_drift", _tracking_drift)

    with tempfile.TemporaryDirectory() as tmp:
        defaults_file = os.path.join(tmp, "defaults.json")
        with open(defaults_file, "w") as f:
            json.dump({"A": 1}, f)
        config_file = os.path.join(tmp, "config.json")
        with open(config_file, "w") as f:
            json.dump({"A": 2}, f)

        result = initialize_secure_config(defaults_path=defaults_file, config_dir=tmp)
        assert len(called) == 1
        assert called[0] is result
