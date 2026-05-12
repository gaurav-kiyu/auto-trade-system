"""Tests for config change audit trail in core/config_bootstrap.py (v2.44 Item 6)."""
import json
import os
import tempfile
import pytest
from core.config_bootstrap import (
    ConfigChange,
    classify_change_risk,
    diff_configs,
    write_config_changes_jsonl,
    read_recent_config_changes,
    CRITICAL_CONFIG_KEYS,
    HIGH_RISK_CONFIG_KEYS,
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
