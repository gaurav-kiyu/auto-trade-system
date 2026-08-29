"""Security wire functions for the DI container.

Contains all security-related wire functions.
"""

from __future__ import annotations

from core.di_container.container import DIContainer, _get_container


def wire_security_services(container_instance: DIContainer | None = None) -> None:
    """Register Security Auditor into the DI container."""
    c = _get_container(container_instance)
    try:
        from core.security_auditor import SecurityAuditor, get_security_auditor
        if not c.is_registered(SecurityAuditor):
            auditor = get_security_auditor()
            c.register_instance(SecurityAuditor, auditor)
    except ImportError:
        pass


def wire_ai_security_gate_services(container_instance: DIContainer | None = None) -> None:
    """Register AI Security Gate into the DI container."""
    c = _get_container(container_instance)
    try:
        from core.ai_security_gate import AISecurityGate, get_ai_security_gate
        if not c.is_registered(AISecurityGate):
            gate = get_ai_security_gate()
            c.register_instance(AISecurityGate, gate)
    except ImportError:
        pass


def wire_threat_modeler_services(container_instance: DIContainer | None = None) -> None:
    """Register Threat Modeler into the DI container."""
    c = _get_container(container_instance)
    try:
        from core.threat_modeler import ThreatModeler, get_threat_modeler
        if not c.is_registered(ThreatModeler):
            modeler = get_threat_modeler()
            c.register_instance(ThreatModeler, modeler)
    except ImportError:
        pass


def wire_runtime_security_services(container_instance: DIContainer | None = None) -> None:
    """Register Runtime Security into the DI container."""
    c = _get_container(container_instance)
    try:
        from core.runtime_security import RuntimeSecurity, get_runtime_security
        if not c.is_registered(RuntimeSecurity):
            sec = get_runtime_security()
            c.register_instance(RuntimeSecurity, sec)
    except ImportError:
        pass


def wire_threat_intel_services(container_instance: DIContainer | None = None) -> None:
    """Register Threat Intelligence into the DI container."""
    c = _get_container(container_instance)
    try:
        from core.threat_intel import ThreatIntel, get_threat_intel
        if not c.is_registered(ThreatIntel):
            intel = get_threat_intel()
            c.register_instance(ThreatIntel, intel)
    except ImportError:
        pass


def wire_vulnerability_scanner_services(container_instance: DIContainer | None = None) -> None:
    """Register Vulnerability Scanner into the DI container."""
    c = _get_container(container_instance)
    try:
        from core.vulnerability_scanner import VulnerabilityScanner, get_vulnerability_scanner
        if not c.is_registered(VulnerabilityScanner):
            scanner = get_vulnerability_scanner()
            c.register_instance(VulnerabilityScanner, scanner)
    except ImportError:
        pass


def wire_secrets_vault_services(container_instance: DIContainer | None = None) -> None:
    """Register Secrets Vault into the DI container."""
    c = _get_container(container_instance)
    try:
        from core.secrets_vault import SecretsVault, get_secrets_vault
        if not c.is_registered(SecretsVault):
            vault = get_secrets_vault()
            c.register_instance(SecretsVault, vault)
    except ImportError:
        pass


def wire_accessibility_gate_services(container_instance: DIContainer | None = None) -> None:
    """Register Accessibility Gate into the DI container."""
    c = _get_container(container_instance)
    try:
        from core.accessibility_gate import AccessibilityGate, get_accessibility_gate
        if not c.is_registered(AccessibilityGate):
            gate = get_accessibility_gate()
            c.register_instance(AccessibilityGate, gate)
    except ImportError:
        pass


__all__ = [
    "wire_security_services",
    "wire_ai_security_gate_services",
    "wire_threat_modeler_services",
    "wire_runtime_security_services",
    "wire_threat_intel_services",
    "wire_vulnerability_scanner_services",
    "wire_secrets_vault_services",
    "wire_accessibility_gate_services",
]
