"""Tests for core/ports/broker/health_port.py."""

from __future__ import annotations

import core.ports.broker.health_port as _mod


class TestPortsBrokerHealth_port:
    """Test suite for core/ports/broker/health_port.py."""

    def test_import(self):
        """Verify module imports successfully."""
        assert _mod is not None
