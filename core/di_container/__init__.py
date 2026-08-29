"""Dependency Injection Container Package.

Provides a simple inversion of control container for managing service lifetimes
and resolving interfaces to concrete implementations.

This package replaces the original monolithic core/di_container.py with a
modular structure organized by domain:
  - container.py: DIContainer class + core helpers + global container management
  - wire_core.py: Mediator and multi-asset dispatcher wiring
  - wire_security.py: All security-related wiring
  - wire_enterprise.py: All enterprise/non-core wiring
  - wire_default.py: Orchestrator that wires all default services

Backward-compatible: exists at the same ``core.di_container`` import path.
All existing ``from core.di_container import X`` imports continue to work.
"""

from __future__ import annotations

# 1. Core container class and helpers (no circular deps)
from core.di_container.container import (
    DIContainer,
    T,
    _get_global_container,
    _register_multi_asset_adapters,
    _resolve_config_manager,
    _set_global_container,
)

# 2. Wire functions (import modules, not __init__.py, so no circular deps)
from core.di_container.wire_core import (
    wire_mediator_services,
    wire_multi_asset_dispatcher,
)

# 3. Default wiring orchestrator (imports all wire modules above)
from core.di_container.wire_default import wire_default_services
from core.di_container.wire_enterprise import (
    wire_api_versioning_services,
    wire_architecture_services,
    wire_chaos_engine_services,
    wire_command_bus_services,
    wire_decision_memory_services,
    wire_dependency_services,
    wire_digital_twin_services,
    wire_distributed_tracing_services,
    wire_enterprise_evolution_services,
    wire_event_bus_services,
    wire_event_sourcing_services,
    wire_executive_advisor_services,
    wire_feature_flags_services,
    wire_integration_services,
    wire_intelligence_pipeline_services,
    wire_performance_services,
    wire_plugin_registry_services,
    wire_postmortem_automator_services,
    wire_presentation_services,
    wire_query_bus_services,
    wire_recommendation_services,
    wire_sbom_services,
    wire_service_catalog_services,
    wire_strategy_plugin_services,
    wire_synthetic_monitor_services,
)
from core.di_container.wire_security import (
    wire_accessibility_gate_services,
    wire_ai_security_gate_services,
    wire_runtime_security_services,
    wire_secrets_vault_services,
    wire_security_services,
    wire_threat_intel_services,
    wire_threat_modeler_services,
    wire_vulnerability_scanner_services,
)

# ── Backward-compatible aliases for wire functions ────────────────────────
# These are part of the constitution system but share wire_intelligence_pipeline_services
# since Incident Commander, ICS Telegram Bridge, and Self-Healing Bridge are
# all components of the intelligence pipeline system.
wire_incident_commander_services = wire_intelligence_pipeline_services
wire_ics_telegram_bridge_services = wire_intelligence_pipeline_services
wire_ics_self_healing_bridge_services = wire_intelligence_pipeline_services

# 4. Initialize global container AFTER all sub-modules are loaded
#    This avoids circular imports when wire functions reference the global.
container = wire_default_services(DIContainer())
_set_global_container(container)


def get_container() -> DIContainer:
    """Get the global DI container instance."""
    c = _get_global_container()
    if c is None:
        raise RuntimeError("DI container not initialized")
    return c


def reset_container() -> None:
    """Clear the global container and re-wire default services.

    Primarily useful for testing isolation.
    """
    new_container = wire_default_services(DIContainer())
    _set_global_container(new_container)
    global container
    container = new_container


__all__ = [
    "DIContainer",
    "T",
    "container",
    "get_container",
    "reset_container",
    "wire_default_services",
    "wire_mediator_services",
    "wire_security_services",
    "wire_performance_services",
    "wire_architecture_services",
    "wire_multi_asset_dispatcher",
    "wire_presentation_services",
    "wire_recommendation_services",
    "wire_dependency_services",
    "wire_synthetic_monitor_services",
    "wire_sbom_services",
    "wire_strategy_plugin_services",
    "wire_chaos_engine_services",
    "wire_ai_security_gate_services",
    "wire_threat_modeler_services",
    "wire_postmortem_automator_services",
    "wire_decision_memory_services",
    "wire_digital_twin_services",
    "wire_runtime_security_services",
    "wire_api_versioning_services",
    "wire_executive_advisor_services",
    "wire_accessibility_gate_services",
    "wire_service_catalog_services",
    "wire_intelligence_pipeline_services",
    "wire_feature_flags_services",
    "wire_event_bus_services",
    "wire_plugin_registry_services",
    "wire_secrets_vault_services",
    "wire_enterprise_evolution_services",
    "wire_event_sourcing_services",
    "wire_command_bus_services",
    "wire_query_bus_services",
    "wire_distributed_tracing_services",
    "wire_threat_intel_services",
    "wire_vulnerability_scanner_services",
    "wire_integration_services",
    "wire_incident_commander_services",
    "wire_ics_telegram_bridge_services",
    "wire_ics_self_healing_bridge_services",
    "_register_multi_asset_adapters",
    "_resolve_config_manager",
]
