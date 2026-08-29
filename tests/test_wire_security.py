"""Tests for core/di_container/wire_security.py.

Verifies security service wiring functions run against a fresh container.
"""
from __future__ import annotations

from core.di_container.container import DIContainer
from core.di_container.wire_security import (
    wire_ai_security_gate_services,
    wire_runtime_security_services,
    wire_secrets_vault_services,
    wire_security_services,
    wire_threat_modeler_services,
    wire_vulnerability_scanner_services,
)


def test_wire_security_services_runs():
    wire_security_services(DIContainer())


def test_wire_ai_security_gate_services_runs():
    wire_ai_security_gate_services(DIContainer())


def test_wire_threat_modeler_services_runs():
    wire_threat_modeler_services(DIContainer())


def test_wire_runtime_security_services_runs():
    wire_runtime_security_services(DIContainer())


def test_wire_vulnerability_scanner_services_runs():
    wire_vulnerability_scanner_services(DIContainer())


def test_wire_secrets_vault_services_runs():
    wire_secrets_vault_services(DIContainer())
