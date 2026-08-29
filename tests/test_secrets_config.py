"""Tests for core/integrations/secrets_config.py.

Verifies the Secrets Vault -> Config wiring bridge.
"""
from __future__ import annotations

from core.integrations.secrets_config import (
    SecretsConfigBridge,
    wire_secrets_to_config,
)


def test_bridge_class_importable():
    """The SecretsConfigBridge class must be importable."""
    assert SecretsConfigBridge is not None


def test_wire_secrets_to_config_returns_bool():
    """The wiring bridge must return a success boolean."""
    result = wire_secrets_to_config()
    assert isinstance(result, bool)
