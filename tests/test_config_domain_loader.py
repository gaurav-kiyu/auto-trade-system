"""Unit tests for index_app.domains.config.loader — ConfigLoader + helpers."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from index_app.domains.config.loader import (
    ConfigLoader,
    ConfigResult,
    _FAIL_SAFE_CONFIG,
    get_config_loader,
    load_config,
    make_fail_safe_config,
)

# A minimal valid config that passes core.config_validator.validate_and_log()
_MINIMAL_VALID_CONFIG = {
    "MANUAL_SIGNALS_ONLY": False,
    "EXECUTION_MODE": "AUTO",
    "BASE_CAPITAL": 100000,
    "MAX_DAILY_LOSS": -2000,
    "MAX_DRAWDOWN": 0.3,
    "RISK_MODE": "FIXED",
    "SL_PCT": 0.92,
    "TARGET_PCT": 1.3,
    "AI_THRESHOLD": 60,
    "TIER_STRONG_MIN": 85,
    "TIER_MODERATE_MIN": 70,
    "TIER_WEAK_MIN": 60,
    "QUALITY_MIN_SCORE": 50,
    "VIX_HALT_THRESHOLD": 35,
    "VIX_BLOCK_THRESHOLD": 30,
    "MAX_OPEN": 3,
    "MAX_TRADES_DAY": 5,
    "BROKER_API_ENABLED": False,
}


# ==============================================================================
# Fixtures
# ==============================================================================


@pytest.fixture()
def tmp_project(tmp_path: Path) -> Path:
    """A temporary project root directory."""
    return tmp_path


@pytest.fixture()
def config_path(tmp_project: Path) -> Path:
    """Write a minimal valid config.json inside tmp_project."""
    p = tmp_project / "config.json"
    p.write_text(json.dumps(_MINIMAL_VALID_CONFIG), encoding="utf-8")
    return p


@pytest.fixture()
def config_with_checksum(tmp_project: Path) -> Path:
    """Write a config.json with a correct _checksum field."""
    p = tmp_project / "checksum_config.json"
    body = dict(_MINIMAL_VALID_CONFIG)
    body["BASE_CAPITAL"] = 50000  # differentiate from default fixture
    # Compute checksum on the content WITHOUT the checksum field
    raw_body = json.dumps(body, sort_keys=True)
    checksum = hashlib.sha256(raw_body.encode("utf-8")).hexdigest()
    body["_checksum"] = checksum
    # Write the full JSON (with _checksum included)
    p.write_text(json.dumps(body, sort_keys=True), encoding="utf-8")
    return p


@pytest.fixture()
def loader(tmp_project: Path) -> ConfigLoader:
    return ConfigLoader(project_root=tmp_project)


# ==============================================================================
# Tests — ConfigLoader construction
# ==============================================================================


class TestConfigLoaderInit:
    def test_init_with_project_root(self, tmp_project: Path):
        loader = ConfigLoader(project_root=tmp_project)
        assert loader._project_root == tmp_project.resolve()

    def test_init_defaults_to_cwd(self):
        loader = ConfigLoader()
        assert loader._project_root == Path.cwd()

    def test_init_with_notifier(self):
        calls: list[str] = []
        loader = ConfigLoader(notifier=lambda msg: calls.append(msg))
        assert loader._notifier is not None
        loader._notifier("test")
        assert calls == ["test"]

    def test_load_count_starts_at_zero(self, loader: ConfigLoader):
        assert loader.load_count == 0


# ==============================================================================
# Tests — ConfigLoader.load()
# ==============================================================================


class TestConfigLoaderLoad:
    def test_load_success(self, loader: ConfigLoader, config_path: Path):
        result = loader.load(default_path=str(config_path))
        assert result.success is True
        assert result.cfg["MANUAL_SIGNALS_ONLY"] is False
        assert result.cfg["EXECUTION_MODE"] == "AUTO"
        assert result.cfg["BASE_CAPITAL"] == 100000
        assert result.resolved_path == str(config_path.resolve())
        assert result.checksum_ok is True

    def test_load_file_not_found(self, loader: ConfigLoader):
        """A path inside project root that does not exist should trigger notifier."""
        missing = loader._project_root / "_missing_file_.json"
        result = loader.load(default_path=str(missing))
        assert result.success is False
        assert "File not found" in result.error_message
        # Should return fail-safe config
        assert result.cfg["MANUAL_SIGNALS_ONLY"] is True
        assert result.cfg["EXECUTION_MODE"] == "MANUAL"

    def test_load_path_outside_project_root(self, tmp_project: Path):
        """Config paths that escape the project root should return DEFAULT_SAFE_CONFIG."""
        loader = ConfigLoader(project_root=tmp_project)
        outside = tmp_project.parent / "outside_config.json"
        outside.write_text(json.dumps({"KEY": "val"}), encoding="utf-8")
        result = loader.load(default_path=str(outside))
        assert result.success is True  # returns safe defaults, not fail
        assert "outside project root" in result.error_message
        # Should be DEFAULT_SAFE_CONFIG (MANUAL mode)
        assert result.cfg.get("MANUAL_SIGNALS_ONLY") is True
        assert result.cfg.get("EXECUTION_MODE") == "MANUAL"

    def test_load_invalid_json(self, loader: ConfigLoader, tmp_project: Path):
        bad_path = tmp_project / "bad.json"
        bad_path.write_text("{invalid", encoding="utf-8")
        result = loader.load(default_path=str(bad_path))
        assert result.success is False
        assert "JSON decode error" in result.error_message
        # Should return fail-safe config
        assert result.cfg == _FAIL_SAFE_CONFIG

    def test_load_checksum_mismatch(self, tmp_project: Path):
        """Tampered config should be detected via checksum."""
        body = {"MANUAL_SIGNALS_ONLY": False, "_checksum": "deadbeef" * 8}
        p = tmp_project / "tampered.json"
        p.write_text(json.dumps(body), encoding="utf-8")
        loader = ConfigLoader(project_root=tmp_project)
        result = loader.load(default_path=str(p))
        assert result.success is False
        assert result.checksum_ok is False
        assert result.cfg == _FAIL_SAFE_CONFIG

    def test_load_checksum_valid(self, loader: ConfigLoader, config_with_checksum: Path):
        result = loader.load(default_path=str(config_with_checksum))
        assert result.success is True
        assert result.checksum_ok is True
        assert result.cfg["BASE_CAPITAL"] == 50000
        assert "_checksum" not in result.cfg  # should be popped

    def test_load_increments_count_on_force(self, loader: ConfigLoader, config_path: Path):
        assert loader.load_count == 0
        loader.load(force=True, default_path=str(config_path))
        assert loader.load_count == 1
        loader.load(force=True, default_path=str(config_path))
        assert loader.load_count == 2

    def test_load_uses_env_var_override(self, loader: ConfigLoader, config_path: Path, monkeypatch):
        """OPBUYING_INDEX_CONFIG env var should override default_path."""
        monkeypatch.setenv("OPBUYING_INDEX_CONFIG", str(config_path))
        result = loader.load()
        assert result.success is True
        assert result.cfg["BASE_CAPITAL"] == 100000

    def test_load_notifier_invoked_on_failure(self, tmp_project: Path):
        """Notifier should be called when a config file within project root is missing."""
        calls: list[str] = []
        loader = ConfigLoader(project_root=tmp_project, notifier=lambda msg: calls.append(msg))
        missing = tmp_project / "_nonexistent_.json"
        loader.load(default_path=str(missing))
        assert len(calls) == 1
        assert "not found" in calls[0]


# ==============================================================================
# Tests — ConfigLoader.make_fail_safe_config()
# ==============================================================================


class TestMakeFailSafeConfig:
    def test_returns_fail_safe_dict(self, loader: ConfigLoader):
        cfg = loader.make_fail_safe_config()
        assert cfg["MANUAL_SIGNALS_ONLY"] is True
        assert cfg["EXECUTION_MODE"] == "MANUAL"
        assert cfg["BROKER_API_ENABLED"] is False

    def test_returns_copy_not_reference(self, loader: ConfigLoader):
        cfg1 = loader.make_fail_safe_config()
        cfg2 = loader.make_fail_safe_config()
        assert cfg1 is not cfg2


# ==============================================================================
# Tests — get_config_loader() singleton
# ==============================================================================


class TestGetConfigLoader:
    def test_returns_singleton(self):
        l1 = get_config_loader()
        l2 = get_config_loader()
        assert l1 is l2

    def test_is_configloader_instance(self):
        loader = get_config_loader()
        assert isinstance(loader, ConfigLoader)

    def test_singleton_preserves_first_notifier(self):
        calls1: list[str] = []
        calls2: list[str] = []
        l1 = get_config_loader(notifier=lambda msg: calls1.append(msg))
        l2 = get_config_loader(notifier=lambda msg: calls2.append(msg))
        assert l1 is l2
        # Notifier from first call should be the one used
        assert len(calls1) == 0
        assert len(calls2) == 0


# ==============================================================================
# Tests — Module-level convenience functions
# ==============================================================================


class TestMakeFailSafeConfigFn:
    def test_returns_correct_dict(self):
        cfg = make_fail_safe_config()
        assert cfg["EXECUTION_MODE"] == "MANUAL"
        assert cfg["MANUAL_SIGNALS_ONLY"] is True

    def test_returns_new_copy(self):
        assert make_fail_safe_config() is not make_fail_safe_config()
