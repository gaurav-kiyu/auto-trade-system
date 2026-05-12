"""
Unit tests for Metrics Service/Adapter.
"""
from __future__ import annotations

import pytest
from unittest.mock import Mock, patch

from infrastructure.adapters.metrics.metrics_adapter import MetricsAdapter
from core.ports.metrics import MetricsPort


class TestMetricsAdapter:
    """Test cases for MetricsAdapter."""

    def setup_method(self):
        """Set up test fixtures."""
        self.adapter = MetricsAdapter()

    def test_initialization(self):
        """Test adapter initialization."""
        assert self.adapter.config == {}
        assert self.adapter._initialized is False

    def test_initialization_with_config(self):
        """Test adapter initialization with config."""
        config = {"metrics_enabled": True, "metrics_port": 9090}
        adapter = MetricsAdapter(config=config)
        
        assert adapter.config == config

    @patch("infrastructure.adapters.metrics.metrics_adapter.start_metrics_server")
    def test_initialization_with_metrics_enabled(self, mock_start_server):
        """Test initialization starts server when metrics_enabled is True."""
        # Setup
        config = {"metrics_enabled": True, "metrics_port": 9090}
        
        # Execute
        adapter = MetricsAdapter(config=config)
        
        # Verify
        assert adapter._initialized is True
        mock_start_server.assert_called_once_with(config)

    @patch("infrastructure.adapters.metrics.metrics_adapter.start_metrics_server")
    def test_initialization_with_metrics_disabled(self, mock_start_server):
        """Test initialization does not start server when metrics_enabled is False."""
        # Setup
        config = {"metrics_enabled": False}
        
        # Execute
        adapter = MetricsAdapter(config=config)
        
        # Verify
        assert adapter._initialized is False
        mock_start_server.assert_not_called()

    @patch("infrastructure.adapters.metrics.metrics_adapter.update_metrics")
    def test_increment_counter(self, mock_update):
        """Test incrementing a counter metric."""
        # Setup
        self.adapter._initialized = True
        
        # Execute
        self.adapter.increment_counter("test_counter", 5, {"tag": "value"})
        
        # Verify
        mock_update.assert_called_once_with({"test_counter": 5})

    @patch("infrastructure.adapters.metrics.metrics_adapter.update_metrics")
    def test_set_gauge(self, mock_update):
        """Test setting a gauge metric."""
        # Setup
        self.adapter._initialized = True
        
        # Execute
        self.adapter.set_gauge("test_gauge", 3.14, {"tag": "value"})
        
        # Verify
        mock_update.assert_called_once_with({"test_gauge": 3.14})

    @patch("infrastructure.adapters.metrics.metrics_adapter.update_metrics")
    def test_record_timer(self, mock_update):
        """Test recording a timing metric."""
        # Setup
        self.adapter._initialized = True
        
        # Execute
        self.adapter.record_timer("test_timer", 1.5, {"tag": "value"})
        
        # Verify
        mock_update.assert_called_once_with({"test_timer": 1.5})

    @patch("infrastructure.adapters.metrics.metrics_adapter.update_metrics")
    def test_record_histogram(self, mock_update):
        """Test recording a histogram metric."""
        # Setup
        self.adapter._initialized = True
        
        # Execute
        self.adapter.record_histogram("test_histogram", 2.71, {"tag": "value"})
        
        # Verify
        mock_update.assert_called_once_with({"test_histogram": 2.71})

    def test_methods_when_not_initialized(self):
        """Test that methods work even when not initialized (should not crash)."""
        # Setup - not initialized
        self.adapter._initialized = False
        
        # Execute - should not raise exceptions
        self.adapter.increment_counter("test", 1)
        self.adapter.set_gauge("test", 1.0)
        self.adapter.record_timer("test", 1.0)
        self.adapter.record_histogram("test", 1.0)
        
        # Verify - no exception means test passed
        assert True

    @patch("infrastructure.adapters.metrics.metrics_adapter.update_metrics")
    def test_increment_counter_without_tags(self, mock_update):
        """Test incrementing counter without tags."""
        # Setup
        self.adapter._initialized = True
        
        # Execute
        self.adapter.increment_counter("test_counter", 3)
        
        # Verify
        mock_update.assert_called_once_with({"test_counter": 3})

    @patch("infrastructure.adapters.metrics.metrics_adapter.update_metrics")
    def test_set_gauge_without_tags(self, mock_update):
        """Test setting gauge without tags."""
        # Setup
        self.adapter._initialized = True
        
        # Execute
        self.adapter.set_gauge("test_gauge", 42.0)
        
        # Verify
        mock_update.assert_called_once_with({"test_gauge": 42.0})


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
