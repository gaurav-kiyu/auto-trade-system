"""Tests for core.config_bootstrap (shared index/stock merge path)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from core.config_bootstrap import (
    CONFIG_B64_SECRET_KEYS_STOCK,
    apply_env_overrides,
    coerce_config_values_to_defaults_types,
    merge_bot_config,
)


def test_coerce_bool_from_string(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    defaults = {"X": True, "Y": 1}
    cfg = {"X": "true", "Y": "2"}
    coerce_config_values_to_defaults_types(cfg, defaults, debug=False)
    assert cfg["X"] is True and cfg["Y"] == 2


def test_merge_overlay_and_coerce(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    defaults = {"A": 1, "B": True, "C": 1.5}
    (tmp_path / "overlay.json").write_text(json.dumps({"A": "5", "B": "false"}), encoding="utf-8")
    out = merge_bot_config(
        defaults=dict(defaults),
        project_root=tmp_path,
        overlay_path="overlay.json",
        local_overlay_relpath=None,
        secret_keys_to_decode=CONFIG_B64_SECRET_KEYS_STOCK,
        apply_hybrid_execution=None,
        debug=False,
    )
    assert out["A"] == 5
    assert out["B"] is False
    assert out["C"] == 1.5


def test_merge_local_overlay_deep_merge(tmp_path: Path, monkeypatch):
    """Index-style config.local.json deep-merge over main overlay."""
    monkeypatch.chdir(tmp_path)
    defaults = {"GUI_THEME": {"a": 1}, "Z": 0}
    (tmp_path / "main.json").write_text(json.dumps({"Z": 1}), encoding="utf-8")
    (tmp_path / "config.local.json").write_text(json.dumps({"GUI_THEME": {"b": 2}}), encoding="utf-8")
    out = merge_bot_config(
        defaults=dict(defaults),
        project_root=tmp_path,
        overlay_path="main.json",
        local_overlay_relpath="config.local.json",
        secret_keys_to_decode=CONFIG_B64_SECRET_KEYS_STOCK,
        apply_hybrid_execution=None,
        debug=False,
    )
    assert out["Z"] == 1
    assert out["GUI_THEME"] == {"a": 1, "b": 2}


# ── apply_env_overrides ────────────────────────────────────────────────────────

class TestApplyEnvOverrides:
    def test_string_override(self, monkeypatch):
        cfg = {"BOT_TOKEN": ""}
        monkeypatch.setenv("OPBUYING_BOT_TOKEN", "my-secret")
        apply_env_overrides(cfg, cfg)
        assert cfg["BOT_TOKEN"] == "my-secret"

    def test_int_override_via_json(self, monkeypatch):
        cfg = {"VIX_HALT_THRESHOLD": 30}
        monkeypatch.setenv("OPBUYING_VIX_HALT_THRESHOLD", "35")
        apply_env_overrides(cfg, cfg)
        assert cfg["VIX_HALT_THRESHOLD"] == 35

    def test_float_override_via_json(self, monkeypatch):
        cfg = {"SL_PCT": 0.88}
        monkeypatch.setenv("OPBUYING_SL_PCT", "0.92")
        apply_env_overrides(cfg, cfg)
        assert cfg["SL_PCT"] == pytest.approx(0.92)

    def test_bool_false_override(self, monkeypatch):
        cfg = {"correlation_guard_enabled": True}
        monkeypatch.setenv("OPBUYING_CORRELATION_GUARD_ENABLED", "false")
        apply_env_overrides(cfg, cfg)
        assert cfg["correlation_guard_enabled"] is False

    def test_bool_true_override(self, monkeypatch):
        cfg = {"BROKER_API_ENABLED": False}
        monkeypatch.setenv("OPBUYING_BROKER_API_ENABLED", "true")
        apply_env_overrides(cfg, cfg)
        assert cfg["BROKER_API_ENABLED"] is True

    def test_unknown_key_ignored(self, monkeypatch):
        cfg = {"A": 1}
        monkeypatch.setenv("OPBUYING_NONEXISTENT_KEY", "99")
        count = apply_env_overrides(cfg, cfg)
        assert cfg == {"A": 1}
        assert count == 0

    def test_prefix_not_matched_ignored(self, monkeypatch):
        cfg = {"A": 1}
        monkeypatch.setenv("OTHER_A", "99")
        count = apply_env_overrides(cfg, cfg, prefix="OPBUYING_")
        assert cfg["A"] == 1
        assert count == 0

    def test_empty_prefix_returns_zero(self, monkeypatch):
        cfg = {"A": 1}
        monkeypatch.setenv("A", "99")
        count = apply_env_overrides(cfg, cfg, prefix="")
        assert count == 0
        assert cfg["A"] == 1

    def test_returns_count_of_overrides(self, monkeypatch):
        cfg = {"A": 1, "B": 2}
        monkeypatch.setenv("OPBUYING_A", "10")
        monkeypatch.setenv("OPBUYING_B", "20")
        count = apply_env_overrides(cfg, cfg)
        assert count == 2

    def test_case_insensitive_env_key(self, monkeypatch):
        cfg = {"VIX_HALT_THRESHOLD": 30}
        monkeypatch.setenv("opbuying_vix_halt_threshold", "40")
        apply_env_overrides(cfg, cfg, prefix="opbuying_")
        assert cfg["VIX_HALT_THRESHOLD"] == 40

    def test_merge_bot_config_applies_env_overrides(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OPBUYING_A", "99")
        defaults = {"A": 1, "B": True}
        (tmp_path / "cfg.json").write_text(json.dumps({}), encoding="utf-8")
        out = merge_bot_config(
            defaults=defaults,
            project_root=tmp_path,
            overlay_path="cfg.json",
            local_overlay_relpath=None,
            secret_keys_to_decode=frozenset(),
            apply_hybrid_execution=None,
            env_prefix="OPBUYING_",
        )
        assert out["A"] == 99

    def test_merge_bot_config_no_env_override_when_prefix_empty(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OPBUYING_A", "99")
        defaults = {"A": 1}
        (tmp_path / "cfg.json").write_text(json.dumps({}), encoding="utf-8")
        out = merge_bot_config(
            defaults=defaults,
            project_root=tmp_path,
            overlay_path="cfg.json",
            local_overlay_relpath=None,
            secret_keys_to_decode=frozenset(),
            apply_hybrid_execution=None,
            env_prefix="",
        )
        assert out["A"] == 1
