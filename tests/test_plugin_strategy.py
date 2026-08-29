"""Tests for core/integrations/plugin_strategy.py — Plugin Registry -> Strategy Framework.

Covers:
- wire_plugin_to_strategy() success path
- Missing dependencies (ImportError handling)
- Exception handling during wiring
- Auto-registration of strategies as plugins
"""

from __future__ import annotations

from unittest.mock import MagicMock, Mock, patch

from core.integrations.plugin_strategy import wire_plugin_to_strategy


class TestWirePluginToStrategy:
    """Tests for wire_plugin_to_strategy function."""

    def test_successful_wiring(self):
        """When all dependencies available, wiring should succeed."""
        with patch("core.plugin_registry.get_plugin_registry") as mock_get_pr:
            with patch("core.strategy.plugin_framework.get_strategy_registry") as mock_get_sr:
                # Mock plugin registry
                mock_pr = MagicMock()
                mock_pr.get_plugin.return_value = None
                mock_get_pr.return_value = mock_pr

                # Mock strategy registry
                mock_strategy = MagicMock()
                mock_strategy.name = "TestStrategy"
                mock_sr = MagicMock()
                mock_sr.get_all.return_value = [mock_strategy]
                mock_get_sr.return_value = mock_sr

                result = wire_plugin_to_strategy()
                assert result is True
                mock_pr.register_plugin.assert_called_once()
                mock_pr.load_plugin.assert_called_once()
                mock_pr.enable_plugin.assert_called_once()

    def test_missing_plugin_registry(self):
        """When plugin registry is missing, wiring should return False."""
        with patch("core.plugin_registry.get_plugin_registry", side_effect=ImportError("no plugin")):
            result = wire_plugin_to_strategy()
            assert result is False

    def test_missing_strategy_registry(self):
        """When strategy registry is missing, wiring should return False."""
        with patch("core.plugin_registry.get_plugin_registry") as mock_get_pr:
            with patch("core.strategy.plugin_framework.get_strategy_registry", side_effect=ImportError("no strategy")):
                mock_get_pr.return_value = MagicMock()
                result = wire_plugin_to_strategy()
                assert result is False

    def test_strategy_without_name(self):
        """Strategy without name attribute should use class name."""
        with patch("core.plugin_registry.get_plugin_registry") as mock_get_pr:
            with patch("core.strategy.plugin_framework.get_strategy_registry") as mock_get_sr:
                mock_pr = MagicMock()
                mock_pr.get_plugin.return_value = None
                mock_get_pr.return_value = mock_pr

                # Strategy without .name attribute
                # Use Mock() instead of MagicMock() - Mock doesn't auto-create attributes
                mock_strategy = Mock()
                mock_sr = MagicMock()
                mock_sr.get_all.return_value = [mock_strategy, "string_strategy"]
                mock_get_sr.return_value = mock_sr

                result = wire_plugin_to_strategy()
                assert result is True

    def test_plugin_already_registered(self):
        """If plugin already registered, it should not be re-registered."""
        with patch("core.plugin_registry.get_plugin_registry") as mock_get_pr:
            with patch("core.strategy.plugin_framework.get_strategy_registry") as mock_get_sr:
                mock_pr = MagicMock()
                mock_pr.get_plugin.return_value = {"name": "Existing"}  # Already exists
                mock_get_pr.return_value = mock_pr

                mock_sr = MagicMock()
                mock_sr.get_all.return_value = [MagicMock()]
                mock_get_sr.return_value = mock_sr

                result = wire_plugin_to_strategy()
                assert result is True
                # register_plugin should NOT be called since plugin exists
                mock_pr.register_plugin.assert_not_called()

    def test_exception_during_strategy_iteration(self):
        """Exception during strategy iteration should not crash."""
        with patch("core.plugin_registry.get_plugin_registry") as mock_get_pr:
            with patch("core.strategy.plugin_framework.get_strategy_registry") as mock_get_sr:
                mock_sr = MagicMock()
                mock_sr.get_all.side_effect = RuntimeError("Registry busy")
                mock_get_sr.return_value = mock_sr

                mock_get_pr.return_value = MagicMock()

                result = wire_plugin_to_strategy()
                assert result is True  # Exception is caught and logged

    def test_unknown_exception_handled(self):
        """Unknown exception during wiring should return False."""
        with patch("core.plugin_registry.get_plugin_registry") as mock_get_pr:
            mock_get_pr.side_effect = ValueError("Unknown error")
            result = wire_plugin_to_strategy()
            assert result is False
