"""
Metrics Adapter

Adapter that implements the MetricsPort interface using the existing metrics_exporter module.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import logging

# Import the port interface
from core.ports.metrics import MetricsPort

# Import the existing metrics exporter functions
from core.metrics_exporter import (
    start_metrics_server,
    update_metrics,
)

_log = logging.getLogger(__name__)


class MetricsAdapter(MetricsPort):
    """
    Adapter that implements MetricsPort using the existing metrics_exporter module.

    This follows the Dependency Inversion Principle - high-level modules (trading logic)
    depend on abstractions (MetricsPort), not concretions (specific metrics implementation).
    """

    def __init__(self, config: Dict[str, Any] | None = None):
        """
        Initialize the metrics adapter.

        Args:
            config: Configuration dictionary. If None, empty dict is used.
        """
        self.config = config or {}
        self._initialized = False

        # Initialize metrics server if enabled in config
        if self.config.get("metrics_enabled", False):
            start_metrics_server(self.config)
            self._initialized = True

    def increment_counter(self, name: str, value: int = 1, tags: Optional[Dict[str, str]] = None) -> None:
        """Increment a counter metric."""
        if tags:
            _log.warning(f"Ignoring tags for counter {name}: {tags}")
        update_metrics({name: value})

    def set_gauge(self, name: str, value: float, tags: Optional[Dict[str, str]] = None) -> None:
        """Set a gauge metric."""
        if tags:
            _log.warning(f"Ignoring tags for gauge {name}: {tags}")
        update_metrics({name: value})

    def record_timer(self, name: str, value: float, tags: Optional[Dict[str, str]] = None) -> None:
        """Record a timing metric."""
        if tags:
            _log.warning(f"Ignoring tags for timer {name}: {tags}")
        update_metrics({name: value})

    def record_histogram(self, name: str, value: float, tags: Optional[Dict[str, str]] = None) -> None:
        """Record a histogram metric."""
        if tags:
            _log.warning(f"Ignoring tags for histogram {name}: {tags}")
        update_metrics({name: value})