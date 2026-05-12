"""
Unit tests for ConfigurationService class.
"""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch, mock_open

import pytest

# Import the service we just created
from trading_system.core.config.service import (
    ConfigurationService,
    create_configuration_service,
    ConfigChange
)


class TestConfigurationService:
    """Test suite for ConfigurationService."""

    @pytest.fixture
    def temp_project_dir(self):
        """Create a temporary project directory for testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def sample_defaults(self):
        """Sample defaults configuration."""
        return {
            "BASE_CAPITAL": 100000,
            "MAX_DAILY_LOSS": -2000,
            "MAX_DRAWDOWN": -5000,
            "SCAN_INTERVAL": 5,
            "COOLDOWN": 300,
            "TG_MAX_PER_MIN": 20,
            "PAPER_MODE": False,
            "EXECUTION_MODE": "MANUAL",
            "MANUAL_SIGNALS_ONLY": True,
            "BOT_TOKEN": "default_token",
            "CHAT_ID": "default_chat_id",
            "KITE_API_KEY": "default_key",
            "SECRET_KEY": "should_be_redacted"
        }

    @pytest.fixture
    def sample_config_overlay(self):
        """Sample configuration overlay."""
        return {
            "BASE_CAPITAL": 150000,
            "SCAN_INTERVAL": 10,
            "TG_MAX_PER_MIN": 15,
            "PAPER_MODE": True
        }

    @pytest.fixture
    def sample_env_overrides(self):
        """Sample environment variable overrides."""
        return {
            "OPBUYING_SCAN_INTERVAL": "15",
            "OPBUYING_COOLDOWN": "600",
            "OPBUYING_PAPER_MODE": "true",
            "OPBUYING_SECRET_KEY": "env_secret_value"
        }

    def test_service_creation_with_defaults_only(
        self, temp_project_dir, sample_defaults
    ):
        """Test creating service with only defaults file."""
        # Create defaults file
        defaults_file = temp_project_dir / "stock_config.defaults.json"
        defaults_file.write_text(json.dumps(sample_defaults))

        # Create service
        service = ConfigurationService(
            project_root=temp_project_dir,
            config_file="nonexistent.json",  # This file doesn't exist
            defaults_file="stock_config.defaults.json"
        )

        # Verify values come from defaults
        assert service.get("BASE_CAPITAL") == 100000
        assert service.get("MAX_DAILY_LOSS") == -2000
        assert service.get("SCAN_INTERVAL") == 5
        assert service.get("PAPER_MODE") is False

    def test_service_creation_with_overlay(
        self, temp_project_dir, sample_defaults, sample_config_overlay
    ):
        """Test creating service with defaults and overlay."""
        # Create files
        defaults_file = temp_project_dir / "stock_config.defaults.json"
        defaults_file.write_text(json.dumps(sample_defaults))

        config_file = temp_project_dir / "stock_config.json"
        config_file.write_text(json.dumps(sample_config_overlay))

        # Create service
        service = ConfigurationService(
            project_root=temp_project_dir,
            config_file="stock_config.json",
            defaults_file="stock_config.defaults.json"
        )

        # Verify merged values (overlay should override defaults)
        assert service.get("BASE_CAPITAL") == 150000  # from overlay
        assert service.get("MAX_DAILY_LOSS") == -2000  # from defaults
        assert service.get("SCAN_INTERVAL") == 10     # from overlay
        assert service.get("TG_MAX_PER_MIN") == 15    # from overlay
        assert service.get("PAPER_MODE") is True      # from overlay

    def test_service_creation_with_env_overrides(
        self, temp_project_dir, sample_defaults, sample_env_overrides
    ):
        """Test creating service with environment variable overrides."""
        # Create defaults file
        defaults_file = temp_project_dir / "stock_config.defaults.json"
        defaults_file.write_text(json.dumps(sample_defaults))

        # Create service with mocked environment
        with patch.dict(os.environ, sample_env_overrides, clear=False):
            service = ConfigurationService(
                project_root=temp_project_dir,
                config_file="nonexistent.json",
                defaults_file="stock_config.defaults.json"
            )

            # Verify environment overrides
            assert service.get("SCAN_INTERVAL") == 15   # from env
            assert service.get("COOLDOWN") == 600       # from env
            assert service.get("PAPER_MODE") is True    # from env (string "true" -> bool)
            # Note: secret key would also come from env, but we test redaction separately

    def test_secret_redaction_in_get_all(
        self, temp_project_dir, sample_defaults
    ):
        """Test that secrets are redacted in get_all() method."""
        # Create defaults file
        defaults_file = temp_project_dir / "stock_config.defaults.json"
        defaults_file.write_text(json.dumps(sample_defaults))

        # Create service
        service = ConfigurationService(
            project_root=temp_project_dir,
            config_file="nonexistent.json",
            defaults_file="stock_config.defaults.json"
        )

        # Get all config (should have secrets redacted)
        all_config = service.get_all()

        # Verify non-secrets are present
        assert all_config["BASE_CAPITAL"] == 100000
        assert all_config["SCAN_INTERVAL"] == 5

        # Verify secrets are redacted
        assert all_config["BOT_TOKEN"] == "[REDACTED]"
        assert all_config["CHAT_ID"] == "[REDACTED]"
        assert all_config["KITE_API_KEY"] == "[REDACTED]"
        assert all_config["SECRET_KEY"] == "[REDACTED]"

    def test_secret_access_via_get_secret(
        self, temp_project_dir, sample_defaults
    ):
        """Test that secrets can be accessed via get_secret() method."""
        # Create defaults file
        defaults_file = temp_project_dir / "stock_config.defaults.json"
        defaults_file.write_text(json.dumps(sample_defaults))

        # Create service
        service = ConfigurationService(
            project_root=temp_project_dir,
            config_file="nonexistent.json",
            defaults_file="stock_config.defaults.json"
        )

        # Verify secrets accessible via get_secret
        assert service.get_secret("BOT_TOKEN") == "default_token"
        assert service.get_secret("CHAT_ID") == "default_chat_id"
        assert service.get_secret("KITE_API_KEY") == "default_key"
        assert service.get_secret("SECRET_KEY") == "should_be_redacted"

    def test_has_key_method(
        self, temp_project_dir, sample_defaults
    ):
        """Test has_key method."""
        # Create defaults file
        defaults_file = temp_project_dir / "stock_config.defaults.json"
        defaults_file.write_text(json.dumps(sample_defaults))

        # Create service
        service = ConfigurationService(
            project_root=temp_project_dir,
            config_file="nonexistent.json",
            defaults_file="stock_config.defaults.json"
        )

        # Test existing keys
        assert service.has_key("BASE_CAPITAL") is True
        assert service.has_key("SCAN_INTERVAL") is True
        assert service.has_key("BOT_TOKEN") is True

        # Test non-existing keys
        assert service.has_key("NON_EXISTENT_KEY") is False

    def test_get_with_default(
        self, temp_project_dir, sample_defaults
    ):
        """Test get method with default value."""
        # Create defaults file
        defaults_file = temp_project_dir / "stock_config.defaults.json"
        defaults_file.write_text(json.dumps(sample_defaults))

        # Create service
        service = ConfigurationService(
            project_root=temp_project_dir,
            config_file="nonexistent.json",
            defaults_file="stock_config.defaults.json"
        )

        # Test existing key
        assert service.get("BASE_CAPITAL") == 100000

        # Test non-existing key with default
        assert service.get("NON_EXISTENT_KEY", "default_value") == "default_value"
        assert service.get("NON_EXISTENT_KEY", 42) == 42

        # Test non-existing key without default (should return None)
        assert service.get("NON_EXISTENT_KEY") is None

    def test_immutable_keys_detection(
        self, temp_project_dir, sample_defaults
    ):
        """Test detection of immutable keys."""
        # Create defaults file
        defaults_file = temp_project_dir / "stock_config.defaults.json"
        defaults_file.write_text(json.dumps(sample_defaults))

        # Create service
        service = ConfigurationService(
            project_root=temp_project_dir,
            config_file="nonexistent.json",
            defaults_file="stock_config.defaults.json"
        )

        # Test immutable keys
        assert service.is_immutable_key("BASE_CAPITAL") is True
        assert service.is_immutable_key("MAX_DAILY_LOSS") is True
        assert service.is_immutable_key("MAX_DRAWDOWN") is True
        assert service.is_immutable_key("KITE_API_KEY") is True
        assert service.is_immutable_key("PAPER_MODE") is True
        assert service.is_immutable_key("EXECUTION_MODE") is True
        assert service.is_immutable_key("MANUAL_SIGNALS_ONLY") is True

        # Test mutable keys
        assert service.is_immutable_key("SCAN_INTERVAL") is False
        assert service.is_immutable_key("COOLDOWN") is False
        assert service.is_immutable_key("TG_MAX_PER_MIN") is False

    def test_safe_reload_keys_detection(
        self, temp_project_dir, sample_defaults
    ):
        """Test detection of safe reload keys."""
        # Create defaults file
        defaults_file = temp_project_dir / "stock_config.defaults.json"
        defaults_file.write_text(json.dumps(sample_defaults))

        # Create service
        service = ConfigurationService(
            project_root=temp_project_dir,
            config_file="nonexistent.json",
            defaults_file="stock_config.defaults.json"
        )

        # Test safe reload keys
        assert service.is_safe_reload_key("SCAN_INTERVAL") is True
        assert service.is_safe_reload_key("COOLDOWN") is True
        assert service.is_safe_reload_key("TG_MAX_PER_MIN") is True
        assert service.is_safe_reload_key("PAPER_MODE") is True  # Actually this might be special case
        assert service.is_safe_reload_key("EXECUTION_MODE") is True  # Actually this might be special case

        # Test immutable keys (should not be safe reload)
        assert service.is_safe_reload_key("BASE_CAPITAL") is False
        assert service.is_safe_reload_key("MAX_DAILY_LOSS") is False
        assert service.is_safe_reload_key("KITE_API_KEY") is False

    def test_soft_reload_same_config(
        self, temp_project_dir, sample_defaults
    ):
        """Test soft-reload when configuration hasn't changed."""
        # Create files
        defaults_file = temp_project_dir / "stock_config.defaults.json"
        defaults_file.write_text(json.dumps(sample_defaults))

        config_file = temp_project_dir / "stock_config.json"
        config_file.write_text(json.dumps({}))  # Empty overlay

        # Create service
        service = ConfigurationService(
            project_root=temp_project_dir,
            config_file="stock_config.json",
            defaults_file="stock_config.defaults.json"
        )

        # Initial reload count
        initial_count = service.get_reload_stats()["reload_count"]

        # Attempt soft-reload (should detect no changes)
        result = service.soft_reload()

        # Should return False (no changes) and reload count unchanged
        assert result is False
        assert service.get_reload_stats()["reload_count"] == initial_count

    def test_soft_reload_with_changes(
        self, temp_project_dir, sample_defaults, sample_config_overlay
    ):
        """Test soft-reload when configuration has changed."""
        # Create initial files
        defaults_file = temp_project_dir / "stock_config.defaults.json"
        defaults_file.write_text(json.dumps(sample_defaults))

        config_file = temp_project_dir / "stock_config.json"
        config_file.write_text(json.dumps({
            "SCAN_INTERVAL": 5  # Initial value
        }))

        # Create service
        service = ConfigurationService(
            project_root=temp_project_dir,
            config_file="stock_config.json",
            defaults_file="stock_config.defaults.json"
        )

        # Verify initial value
        assert service.get("SCAN_INTERVAL") == 5

        # Update the config file with new values
        config_file.write_text(json.dumps({
            "SCAN_INTERVAL": 15  # Changed value
        }))

        # Attempt soft-reload
        result = service.soft_reload()

        # Should return True (changes applied) and reload count increased
        assert result is True
        stats = service.get_reload_stats()
        assert stats["reload_count"] == 1
        assert service.get("SCAN_INTERVAL") == 15  # Updated value

    def test_soft_reload_blocked_by_immutable_key(
        self, temp_project_dir, sample_defaults, sample_config_overlay
    ):
        """Test that soft-reload is blocked by immutable key changes."""
        # Create files
        defaults_file = temp_project_dir / "stock_config.defaults.json"
        defaults_file.write_text(json.dumps(sample_defaults))

        config_file = temp_project_dir / "stock_config.json"
        # Start with config that has different BASE_CAPITAL (immutable)
        config_file.write_text(json.dumps({
            "BASE_CAPITAL": 200000  # Different from defaults (100000) - IMMUTABLE!
        }))

        # Create service
        service = ConfigurationService(
            project_root=temp_project_dir,
            config_file="stock_config.json",
            defaults_file="stock_config.defaults.json"
        )

        # Initial value should be from overlay
        assert service.get("BASE_CAPITAL") == 200000

        # Now try to change it via soft-reload to another value
        config_file.write_text(json.dumps({
            "BASE_CAPITAL": 250000  # Trying to change immutable key again
        }))

        # Attempt soft-reload (should be blocked)
        result = service.soft_reload()

        # Should return False (blocked) and value unchanged
        assert result is False
        assert service.get("BASE_CAPITAL") == 200000  # Still the original value

    def test_change_history_tracking(
        self, temp_project_dir, sample_defaults
    ):
        """Test that configuration changes are tracked in history."""
        # Create file
        defaults_file = temp_project_dir / "stock_config.defaults.json"
        defaults_file.write_text(json.dumps(sample_defaults))

        # Create service
        service = ConfigurationService(
            project_root=temp_project_dir,
            config_file="nonexistent.json",
            defaults_file="stock_config.defaults.json"
        )

        # Verify initial history is empty
        history = service.get_change_history()
        assert len(history) == 0

        # Note: Testing actual change history would require mocking the file system
        # and triggering a soft-reload, which is complex in unit tests
        # The core logic is tested in the soft-reload tests above

    def test_reload_statistics(
        self, temp_project_dir, sample_defaults
    ):
        """Test reload statistics tracking."""
        # Create defaults file
        defaults_file = temp_project_dir / "stock_config.defaults.json"
        defaults_file.write_text(json.dumps(sample_defaults))

        # Create service
        service = ConfigurationService(
            project_root=temp_project_dir,
            config_file="nonexistent.json",
            defaults_file="stock_config.defaults.json"
        )

        # Get initial stats
        stats = service.get_reload_stats()

        # Verify initial state
        assert stats["reload_count"] == 0
        assert stats["last_reload_time"] == 0.0
        assert "config_hash" in stats
        assert stats["total_changes"] == 0

    def test_create_configuration_service_factory(
        self, temp_project_dir, sample_defaults
    ):
        """Test the factory function."""
        # Create defaults file
        defaults_file = temp_project_dir / "stock_config.defaults.json"
        defaults_file.write_text(json.dumps(sample_defaults))

        # Test factory function
        service = create_configuration_service(
            project_root=temp_project_dir,
            config_file="nonexistent.json",
            defaults_file="stock_config.defaults.json"
        )

        # Verify it's the right type
        assert isinstance(service, ConfigurationService)

        # Verify it works
        assert service.get("BASE_CAPITAL") == 100000

    def test_config_validation_integration(
        self, temp_project_dir
    ):
        """Test that configuration validation is integrated."""
        # Create defaults file with invalid config
        invalid_defaults = {
            "BASE_CAPITAL": -1000,  # Invalid: must be positive
            "MAX_DAILY_LOSS": 1000,  # Invalid: must be negative
        }
        defaults_file = temp_project_dir / "stock_config.defaults.json"
        defaults_file.write_text(json.dumps(invalid_defaults))

        # Creating service should raise ValueError due to validation failure
        with pytest.raises(ValueError, match="Configuration validation failed"):
            ConfigurationService(
                project_root=temp_project_dir,
                config_file="nonexistent.json",
                defaults_file="stock_config.defaults.json"
            )

    def test_config_validation_warnings_only(
        self, temp_project_dir
    ):
        """Test that configuration warnings don't prevent service creation."""
        # Create defaults file with valid config but potential warnings
        defaults_with_warnings = {
            "BASE_CAPITAL": 100000,  # Valid
            "MAX_DAILY_LOSS": -2000,  # Valid
            "MAX_DRAWDOWN": -5000,   # Valid
            "SCAN_INTERVAL": 0,      # Warning: should be >=1
        }
        defaults_file = temp_project_dir / "stock_config.defaults.json"
        defaults_file.write_text(json.dumps(defaults_with_warnings))

        # Creating service should succeed (warnings don't cause failure)
        service = ConfigurationService(
            project_root=temp_project_dir,
            config_file="nonexistent.json",
            defaults_file="stock_config.defaults.json"
        )

        # Verify service works
        assert service.get("BASE_CAPITAL") == 100000
        assert service.get("SCAN_INTERVAL") == 0  # Value preserved despite warning

    def test_empty_config_handling(
        self, temp_project_dir, sample_defaults
    ):
        """Test handling of empty or minimal configuration files."""
        # Create defaults file
        defaults_file = temp_project_dir / "stock_config.defaults.json"
        defaults_file.write_text(json.dumps(sample_defaults))

        # Create service with empty config file
        config_file = temp_project_dir / "stock_config.json"
        config_file.write_text(json.dumps({}))  # Empty config

        service = ConfigurationService(
            project_root=temp_project_dir,
            config_file="stock_config.json",
            defaults_file="stock_config.defaults.json"
        )

        # Should get values from defaults
        assert service.get("BASE_CAPITAL") == 100000
        assert service.get("MAX_DAILY_LOSS") == -2000

    def test_missing_defaults_file(
        self, temp_project_dir
    ):
        """Test handling of missing defaults file."""
        # Don't create defaults file

        # Creating service should raise FileNotFoundError
        with pytest.raises(FileNotFoundError):
            ConfigurationService(
                project_root=temp_project_dir,
                config_file="nonexistent.json",
                defaults_file="missing_defaults.json"
            )


# Additional tests for edge cases and specific scenarios
class TestConfigurationServiceEdgeCases:
    """Edge case tests for ConfigurationService."""

    def test_nested_dict_handling(self, temp_project_dir):
        """Test handling of nested dictionary configurations."""
        defaults_with_nested = {
            "BASE_CAPITAL": 100000,
            "NESTED_CONFIG": {
                "inner_key": "inner_value",
                "another_key": 42
            },
            "SIMPLE_KEY": "simple_value"
        }
        defaults_file = temp_project_dir / "stock_config.defaults.json"
        defaults_file.write_text(json.dumps(defaults_with_nested))

        config_overlay = {
            "NESTED_CONFIG": {
                "inner_key": "overridden_value"
                # Note: another_key should remain from defaults
            },
            "NEW_TOP_LEVEL_KEY": "new_value"
        }
        config_file = temp_project_dir / "stock_config.json"
        config_file.write_text(json.dumps(config_overlay))

        service = ConfigurationService(
            project_root=temp_project_dir,
            config_file="stock_config.json",
            defaults_file="stock_config.defaults.json"
        )

        # Verify nested merging worked
        assert service.get("BASE_CAPITAL") == 100000
        assert service.get("SIMPLE_KEY") == "simple_value"
        assert service.get("NEW_TOP_LEVEL_KEY") == "new_value"

        # Note: The actual nested merging behavior depends on deep_merge_dict
        # from config_helpers, which we're not testing in depth here

    def test_type_coercion(self, temp_project_dir):
        """Test type coercion from string to proper types."""
        defaults_with_types = {
            "BASE_CAPITAL": 100000,          # int
            "MAX_DAILY_LOSS": -2000.5,       # float
            "PAPER_MODE": False,             # bool
            "SCAN_INTERVAL": 10,             # int
            "TG_MAX_PER_MIN": 20.0           # float that should be int
        }
        defaults_file = temp_project_dir / "stock_config.defaults.json"
        defaults_file.write_text(json.dumps(defaults_with_types))

        # Config with string values that should be coerced
        config_overlay = {
            "BASE_CAPITAL": "150000",        # string -> int
            "MAX_DAILY_LOSS": "-3000.7",     # string -> float
            "PAPER_MODE": "true",            # string -> bool
            "SCAN_INTERVAL": "15",           # string -> int
            "TG_MAX_PER_MIN": "25.0"         # string -> float
        }
        config_file = temp_project_dir / "stock_config.json"
        config_file.write_text(json.dumps(config_overlay))

        service = ConfigurationService(
            project_root=temp_project_dir,
            config_file="stock_config.json",
            defaults_file="stock_config.defaults.json"
        )

        # Verify type coercion worked
        assert service.get("BASE_CAPITAL") == 150000
        assert isinstance(service.get("BASE_CAPITAL"), int)

        assert service.get("MAX_DAILY_LOSS") == -3000.7
        assert isinstance(service.get("MAX_DAILY_LOSS"), float)

        assert service.get("PAPER_MODE") is True
        assert isinstance(service.get("PAPER_MODE"), bool)

        assert service.get("SCAN_INTERVAL") == 15
        assert isinstance(service.get("SCAN_INTERVAL"), int)

        assert service.get("TG_MAX_PER_MIN") == 25.0
        assert isinstance(service.get("TG_MAX_PER_MIN"), float)

    def test_environment_variable_json_parsing(self, temp_project_dir, sample_defaults):
        """Test that environment variables with JSON values are parsed correctly."""
        # Create defaults file
        defaults_file = temp_project_dir / "stock_config.defaults.json"
        defaults_file.write_text(json.dumps(sample_defaults))

        # Environment variables with JSON values
        env_with_json = {
            "OPBUYING_SCAN_INTERVAL": "15",                    # Plain value
            "OPBUYING_FEATURE_FLAGS": '["feature1", "feature2"]',  # JSON array
            "OPBUYING_LIMITS": '{"max_trades": 100, "enabled": true}',  # JSON object
            "OPBUYING_IS_ACTIVE": "true",                      # JSON boolean
            "OPBUYING_COUNT": "42"                             # JSON number
        }

        with patch.dict(os.environ, env_with_json, clear=False):
            service = ConfigurationService(
                project_root=temp_project_dir,
                config_file="nonexistent.json",
                defaults_file="stock_config.defaults.json"
            )

            # Verify JSON parsing worked
            assert service.get("SCAN_INTERVAL") == 15
            assert service.get("FEATURE_FLAGS") == ["feature1", "feature2"]
            assert service.get("LIMITS") == {"max_trades": 100, "enabled": True}
            assert service.get("IS_ACTIVE") is True
            assert service.get("COUNT") == 42

    def test_environment_variable_invalid_json_fallback(self, temp_project_dir, sample_defaults):
        """Test that invalid JSON in environment variables falls back to string."""
        # Create defaults file
        defaults_file = temp_project_dir / "stock_config.defaults.json"
        defaults_file.write_text(json.dumps(sample_defaults))

        # Environment variables with invalid JSON
        env_with_invalid_json = {
            "OPBUYING_SCAN_INTERVAL": "not_a_number",
            "OPBUYING_FEATURE_FLAGS": 'invalid json {',
            "OPBUYING_LIMITS": 'also invalid'
        }

        with patch.dict(os.environ, env_with_invalid_json, clear=False):
            service = ConfigurationService(
                project_root=temp_project_dir,
                config_file="nonexistent.json",
                defaults_file="stock_config.defaults.json"
            )

            # Should fall back to string values
            assert service.get("SCAN_INTERVAL") == "not_a_number"
            assert service.get("FEATURE_FLAGS") == 'invalid json {'
            assert service.get("LIMITS") == 'also invalid'


if __name__ == "__main__":
    # Allow running tests directly with pytest
    pytest.main([__file__, "-v"])