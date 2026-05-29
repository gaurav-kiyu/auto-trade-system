"""Tests for core.config_loader — ConfigLoader + get_effective_config."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("yaml", reason="PyYAML not installed")

from core.config_loader import ConfigLoader, get_effective_config, get_loader, load_config

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def config_dir(tmp_path: Path) -> Path:
    d = tmp_path / "config"
    d.mkdir()
    return d


@pytest.fixture()
def base_yaml(config_dir: Path) -> Path:
    p = config_dir / "base.yaml"
    p.write_text("""
NIFTY:
  enabled: true
  symbol: ^NSEI
BANKNIFTY:
  enabled: true
  symbol: ^BSESN
BASE_CAPITAL: 50000
SL_PCT: 0.05
TARGET_PCT: 0.10
""", encoding="utf-8")
    return p


@pytest.fixture()
def dev_yaml(config_dir: Path) -> Path:
    p = config_dir / "dev.yaml"
    p.write_text("""
BASE_CAPITAL: 10000
SL_PCT: 0.07
DEV_MODE: true
""", encoding="utf-8")
    return p


@pytest.fixture()
def loader(config_dir: Path) -> ConfigLoader:
    return ConfigLoader(config_dir=config_dir)


# ─── Tests – ConfigLoader ─────────────────────────────────────────────────────


class TestConfigLoaderInit:
    def test_init_with_default_dir(self):
        loader = ConfigLoader()
        assert loader.config_dir.name == "config"

    def test_init_with_custom_dir(self, tmp_path: Path):
        d = tmp_path / "myconfig"
        d.mkdir()
        loader = ConfigLoader(config_dir=d)
        assert loader.config_dir == d


class TestConfigLoaderLoad:
    def test_load_base(self, loader: ConfigLoader, base_yaml: Path):
        cfg = loader.load("base")
        assert cfg["NIFTY"]["enabled"] is True
        assert cfg["BASE_CAPITAL"] == 50000
        assert cfg["SL_PCT"] == 0.05

    def test_load_dev_merges_with_base(self, loader: ConfigLoader, base_yaml: Path, dev_yaml: Path):
        cfg = loader.load("dev")
        assert cfg["NIFTY"]["enabled"] is True  # from base
        assert cfg["BASE_CAPITAL"] == 10000  # overridden by dev
        assert cfg["SL_PCT"] == 0.07  # overridden
        assert cfg["DEV_MODE"] is True  # from dev only

    def test_load_caches_result(self, loader: ConfigLoader, base_yaml: Path):
        cfg1 = loader.load("base")
        cfg2 = loader.load("base")
        assert cfg1 is cfg2  # same cached object

    def test_load_missing_base_returns_empty(self, config_dir: Path):
        loader = ConfigLoader(config_dir=config_dir)
        cfg = loader.load("base")
        assert cfg == {}

    def test_load_missing_env_returns_base_only(self, loader: ConfigLoader, base_yaml: Path):
        cfg = loader.load("nonexistent")
        assert cfg["BASE_CAPITAL"] == 50000  # only base values

    def test_load_invalid_yaml_raises_error(self, config_dir: Path):
        """YAML parser errors are not caught — they propagate."""
        (config_dir / "base.yaml").write_text("{invalid: yaml: unclosed", encoding="utf-8")
        loader = ConfigLoader(config_dir=config_dir)
        with pytest.raises(Exception):
            loader.load("base")

    def test_load_empty_yaml_returns_empty(self, config_dir: Path):
        (config_dir / "base.yaml").write_text("", encoding="utf-8")
        loader = ConfigLoader(config_dir=config_dir)
        cfg = loader.load("base")
        assert cfg == {}


class TestConfigLoaderValidateSchema:
    def test_validate_schema_existing_returns_true(self, config_dir: Path, base_yaml: Path):
        schemas = config_dir.parent / "schemas"
        schemas.mkdir(exist_ok=True)
        (schemas / "base.schema.json").write_text("{}", encoding="utf-8")
        loader = ConfigLoader(config_dir=config_dir)
        assert loader.validate_schema("base") is True

    def test_validate_schema_missing_returns_true(self, loader: ConfigLoader):
        """Missing schema file logs a warning but returns True."""
        with patch("core.config_loader.SCHEMA_PATH", Path("_nonexistent_dir_xxxx")):
            with patch("core.config_loader.logger.warning") as mock_warn:
                assert loader.validate_schema("nonexistent") is True
                mock_warn.assert_called_once()

    def test_validate_schema_with_config_arg(self, loader: ConfigLoader):
        """validate_schema accepts config dict argument."""
        assert loader.validate_schema({"dummy": 1}, schema_name="index_config") is True


class TestConfigLoaderGetEffectiveConfig:
    def test_get_effective_config_delegates_to_load(self, loader: ConfigLoader, base_yaml: Path):
        cfg = loader.get_effective_config("base")
        assert cfg["BASE_CAPITAL"] == 50000

    def test_get_effective_config_calls_validate(self, loader: ConfigLoader, base_yaml: Path):
        with patch.object(loader, "validate_schema", wraps=loader.validate_schema) as mock_val:
            loader.get_effective_config("base")
            mock_val.assert_called_once()

    def test_get_effective_config_dev(self, loader: ConfigLoader, base_yaml: Path, dev_yaml: Path):
        cfg = loader.get_effective_config("dev")
        assert cfg["DEV_MODE"] is True


class TestConfigLoaderNestedMerge:
    def test_nested_deep_merge(self, config_dir: Path):
        (config_dir / "base.yaml").write_text("""
NESTED:
  A: 1
  B: 2
""", encoding="utf-8")
        (config_dir / "dev.yaml").write_text("""
NESTED:
  B: 99
  C: 3
""", encoding="utf-8")
        loader = ConfigLoader(config_dir=config_dir)
        cfg = loader.load("dev")
        assert cfg["NESTED"]["A"] == 1
        assert cfg["NESTED"]["B"] == 99
        assert cfg["NESTED"]["C"] == 3

    def test_nested_overwrite_scalar(self, config_dir: Path):
        (config_dir / "base.yaml").write_text("""
SCALAR: original
""", encoding="utf-8")
        (config_dir / "dev.yaml").write_text("""
SCALAR: overridden
""", encoding="utf-8")
        loader = ConfigLoader(config_dir=config_dir)
        cfg = loader.load("dev")
        assert cfg["SCALAR"] == "overridden"

    def test_nested_add_new_key(self, config_dir: Path):
        (config_dir / "base.yaml").write_text("""
EXISTING_KEY: 1
""", encoding="utf-8")
        (config_dir / "dev.yaml").write_text("""
NEW_KEY: 2
""", encoding="utf-8")
        loader = ConfigLoader(config_dir=config_dir)
        cfg = loader.load("dev")
        assert cfg["EXISTING_KEY"] == 1
        assert cfg["NEW_KEY"] == 2


class TestConfigLoaderCache:
    def test_cache_returns_same_object(self, loader: ConfigLoader, base_yaml: Path):
        """load() returns the cached dict — identical objects."""
        cfg1 = loader.load("base")
        cfg2 = loader.load("base")
        assert cfg1 is cfg2

    def test_separate_loaders_have_separate_caches(self, config_dir: Path, base_yaml: Path):
        """Different ConfigLoader instances have separate caches."""
        l1 = ConfigLoader(config_dir=config_dir)
        c1 = l1.load("base")
        l2 = ConfigLoader(config_dir=config_dir)
        c2 = l2.load("base")
        assert c1 is not c2
        assert c1 == c2


class TestEnvOverride:
    def test_env_override_parses_int(self, config_dir: Path, monkeypatch):
        monkeypatch.setenv("OPBUYING_BASE_CAPITAL", "75000")
        (config_dir / "base.yaml").write_text("BASE_CAPITAL: 50000", encoding="utf-8")
        loader = ConfigLoader(config_dir=config_dir)
        cfg = loader.load("base")
        assert cfg["BASE_CAPITAL"] == 75000

    def test_env_override_parses_bool(self, config_dir: Path, monkeypatch):
        monkeypatch.setenv("OPBUYING_FEATURE_FLAG", "true")
        (config_dir / "base.yaml").write_text("", encoding="utf-8")
        loader = ConfigLoader(config_dir=config_dir)
        cfg = loader.load("base")
        assert cfg["FEATURE_FLAG"] is True

    def test_env_override_parses_bool_false(self, config_dir: Path, monkeypatch):
        monkeypatch.setenv("OPBUYING_DISABLED", "false")
        (config_dir / "base.yaml").write_text("", encoding="utf-8")
        loader = ConfigLoader(config_dir=config_dir)
        cfg = loader.load("base")
        assert cfg["DISABLED"] is False

    def test_env_override_parses_float(self, config_dir: Path, monkeypatch):
        monkeypatch.setenv("OPBUYING_SL_PCT", "0.08")
        (config_dir / "base.yaml").write_text("", encoding="utf-8")
        loader = ConfigLoader(config_dir=config_dir)
        cfg = loader.load("base")
        assert cfg["SL_PCT"] == 0.08

    def test_env_override_string_fallback(self, config_dir: Path, monkeypatch):
        monkeypatch.setenv("OPBUYING_INDEX", "NIFTY")
        (config_dir / "base.yaml").write_text("", encoding="utf-8")
        loader = ConfigLoader(config_dir=config_dir)
        cfg = loader.load("base")
        assert cfg["INDEX"] == "NIFTY"


# ─── Tests – Module-level functions ───────────────────────────────────────────


class TestLoadConfig:
    def test_load_config_base(self, config_dir: Path):
        (config_dir / "base.yaml").write_text("KEY: val", encoding="utf-8")
        loader = ConfigLoader(config_dir=config_dir)
        cfg = loader.load("base")
        assert cfg["KEY"] == "val"

    def test_load_config_paper_override(self, config_dir: Path):
        (config_dir / "base.yaml").write_text("KEY: base_val", encoding="utf-8")
        (config_dir / "paper.yaml").write_text("KEY: paper_val", encoding="utf-8")
        loader = ConfigLoader(config_dir=config_dir)
        cfg = loader.load("paper")
        assert cfg["KEY"] == "paper_val"

    def test_load_config_no_base_file(self, config_dir: Path):
        """When no base.yaml exists, load returns empty."""
        loader = ConfigLoader(config_dir=config_dir)
        cfg = loader.load("base")
        assert cfg == {}


class TestGetLoader:
    def test_get_loader_returns_singleton(self):
        l1 = get_loader()
        l2 = get_loader()
        assert l1 is l2

    def test_get_loader_is_configloader(self):
        loader = get_loader()
        assert isinstance(loader, ConfigLoader)


class TestModuleLevelFunctions:
    def test_load_config_delegates(self, config_dir: Path):
        """Test load_config via mocked get_loader."""
        mock_loader = MagicMock()
        mock_loader.load.return_value = {"KEY": "mocked"}
        with patch("core.config_loader.get_loader", return_value=mock_loader):
            result = load_config("base")
        assert result["KEY"] == "mocked"
        mock_loader.load.assert_called_with("base")

    def test_get_effective_config_delegates(self):
        """Test get_effective_config via mocked get_loader."""
        mock_loader = MagicMock()
        mock_loader.get_effective_config.return_value = {"KEY": "mocked"}
        with patch("core.config_loader.get_loader", return_value=mock_loader):
            result = get_effective_config("dev")
        assert result["KEY"] == "mocked"
        mock_loader.get_effective_config.assert_called_with("dev")
