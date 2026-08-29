"""Default wiring orchestrator for the DI container.

This module contains the wire_default_services function that orchestrates
the registration of all default services into the DI container.
Extracted from the monolithic di_container.py for maintainability.
"""

from __future__ import annotations

from core.di_container.container import DIContainer, _register_multi_asset_adapters, _resolve_config_manager
from core.di_container.wire_core import wire_mediator_services, wire_multi_asset_dispatcher
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

# Global container reference — set on first call to get_container()
_container: DIContainer | None = None


def wire_default_services(container_instance: DIContainer | None = None) -> DIContainer:
    """Register default service implementations into the container.

    This wires the standard port-to-implementation mappings so callers
    can resolve interfaces without manual setup.  Safe to call multiple
    times (idempotent via is_registered checks).
    """
    c = container_instance if container_instance is not None else DIContainer()

    # Wire mediator services first (registers Mediator singleton)
    wire_mediator_services(c)

    # Wire security auditor (Pillar 3 — autonomous security assessment)
    wire_security_services(c)

    # Wire performance optimizer (Vision module — performance analysis)
    wire_performance_services(c)

    # Wire architecture analyzer (Vision module — architecture compliance)
    wire_architecture_services(c)

    # Capital Allocation (multi-asset)
    try:
        from core.portfolio.adapters.multi_asset_aggregator import CapitalAllocationService
        from core.ports.capital_allocation import CapitalAllocationPort
        if not c.is_registered(CapitalAllocationPort):  # type: ignore[type-abstract]
            c.register_singleton(CapitalAllocationPort, CapitalAllocationService)  # type: ignore[type-abstract]
    except ImportError:
        pass  # Optional dependency - container works without it

    # Multi-Asset Portfolio Aggregator (wired with CapitalAllocationPort from container if available)
    try:
        from core.portfolio.adapters.multi_asset_aggregator import MultiAssetPortfolioAggregator
        if not c.is_registered(MultiAssetPortfolioAggregator):
            # Use factory to resolve CapitalAllocationPort from container
            def _make_aggregator() -> MultiAssetPortfolioAggregator:
                cap_alloc = c.try_resolve(CapitalAllocationPort) if hasattr(c, "try_resolve") else None  # type: ignore[type-abstract]
                return MultiAssetPortfolioAggregator(capital_allocation=cap_alloc)
            c.register_factory(MultiAssetPortfolioAggregator, _make_aggregator)
    except ImportError:
        pass

    # Market Data Adapters (multi-asset) - deferred registration
    # These are registered in index_app/domains/trading/container.py (app layer)
    # to avoid core/ -> infrastructure/ import violations (ADR-0010)
    _register_multi_asset_adapters(c)

    # Market Data Service - multi-adapter aggregator
    try:
        from core.services.market_data_service import MarketDataService
        if not c.is_registered(MarketDataService):
            c.register_singleton(MarketDataService, MarketDataService)
    except ImportError:
        pass

    # ConfigManager — register via factory so it's lazily resolved from
    # the module-level _cfg_manager set by index_trader._load_config()
    try:
        from index_app.domains.config.manager import ConfigManager as _ConfigManager
        if not c.is_registered(_ConfigManager):
            c.register_factory(_ConfigManager, _resolve_config_manager)
    except ImportError:
        pass

    # Portfolio Optimizer
    try:
        from core.portfolio.optimizer import PortfolioOptimizer
        if not c.is_registered(PortfolioOptimizer):
            c.register_singleton(PortfolioOptimizer, PortfolioOptimizer)
    except ImportError:
        pass

    # Self-Healing Orchestrator — uses factory to resolve CircuitBreakerService from container
    try:
        from core.self_healing.orchestrator import SelfHealingOrchestrator
        if not c.is_registered(SelfHealingOrchestrator):
            from core.health_checker import run_full_health_check
            def _make_healing() -> SelfHealingOrchestrator:
                from core.services.circuit_breaker_service import CircuitBreakerService
                cb = c.try_resolve(CircuitBreakerService)
                if cb is None:
                    cb = CircuitBreakerService()
                return SelfHealingOrchestrator(
                    cfg={},
                    health_check_fn=run_full_health_check,
                    circuit_breaker_service=cb,
                )
            c.register_factory(SelfHealingOrchestrator, _make_healing)
    except ImportError:
        pass

    # Capacity Planner
    try:
        from core.capacity_planning import CapacityPlanner
        if not c.is_registered(CapacityPlanner):
            c.register_singleton(CapacityPlanner, CapacityPlanner)
    except ImportError:
        pass

    # Cost Governance (FinOps)
    try:
        from core.finops import CostGovernance
        if not c.is_registered(CostGovernance):
            c.register_singleton(CostGovernance, CostGovernance)
    except ImportError:
        pass

    # Version Compatibility Matrix
    try:
        from core.version_compatibility import VersionCompatibilityMatrix
        if not c.is_registered(VersionCompatibilityMatrix):
            c.register_singleton(VersionCompatibilityMatrix, VersionCompatibilityMatrix)
    except ImportError:
        pass

    # SLO / SLA Governance
    try:
        from core.slo_governance import SLOGovernance
        if not c.is_registered(SLOGovernance):
            c.register_singleton(SLOGovernance, SLOGovernance)
    except ImportError:
        pass

    # Global Risk Dashboard
    try:
        from core.risk_dashboard import RiskDashboard
        if not c.is_registered(RiskDashboard):
            c.register_singleton(RiskDashboard, RiskDashboard)
    except ImportError:
        pass

    # Change Management & Approval Workflow
    try:
        from core.change_management import ChangeManager
        if not c.is_registered(ChangeManager):
            c.register_singleton(ChangeManager, ChangeManager)
    except ImportError:
        pass

    # Multi-Asset Strategy Dispatcher — unified signal→route pipeline
    wire_multi_asset_dispatcher(c)

    # Presentation Generator (Pillar 11 — stakeholder presentations)
    wire_presentation_services(c)

    # Recommendation Engine (Vision Module — trade recommendations)
    wire_recommendation_services(c)

    # Dependency Analyzer (Vision Module — dependency mapping)
    wire_dependency_services(c)

    # Synthetic Monitor (Pillar 15 — health probes)
    wire_synthetic_monitor_services(c)

    # SBOM Generator (Pillar 14 — compliance reporting)
    wire_sbom_services(c)

    # Plugin Framework (Pillar 1 — plugin-based extensibility)
    wire_strategy_plugin_services(c)

    # Chaos Engine (Phase 21 — chaos & black swan testing)
    wire_chaos_engine_services(c)

    # AI Security Gate (Constitution v4.0 — prompt injection detection)
    wire_ai_security_gate_services(c)

    # Threat Modeler (Constitution v4.0 — STRIDE threat modeling)
    wire_threat_modeler_services(c)

    # Postmortem Automator (Constitution v4.0 — auto-generated postmortems)
    wire_postmortem_automator_services(c)

    # Decision Memory (Constitution v4.0 — enterprise decision memory)
    wire_decision_memory_services(c)

    # Digital Twin (Constitution v4.0 Layer 5 — real-time system state)
    wire_digital_twin_services(c)

    # Runtime Security (Constitution v4.0 Layer 7 — file integrity + runtime protection)
    wire_runtime_security_services(c)

    # API Versioning (Constitution v4.0 — versioned APIs)
    wire_api_versioning_services(c)

    # Executive Advisor (Constitution v4.0 Layer 10 — executive insights)
    wire_executive_advisor_services(c)

    # Accessibility Gate (Constitution v4.0 — accessibility quality gate)
    wire_accessibility_gate_services(c)

    # Service Catalog (Constitution v4.0 — Platform Engineering / Internal Developer Platform)
    wire_service_catalog_services(c)

    # Continuous Intelligence Pipeline (Constitution v4.0 — automated monitoring)
    wire_intelligence_pipeline_services(c)

    # ── NEW MODULES (v2.57 Architecture Standards) ───────────────────────
    # Feature Flags (Constitution Architecture Standard — toggle management)
    wire_feature_flags_services(c)

    # Event Bus (Constitution Architecture Standard — pub/sub communication)
    wire_event_bus_services(c)

    # Plugin Registry (Constitution Architecture Standard — plugin architecture)
    wire_plugin_registry_services(c)

    # Secrets Vault (Constitution Security Standard — secrets management)
    wire_secrets_vault_services(c)

    # Enterprise Evolution Engine (Constitution Layer 12 — self-improvement)
    wire_enterprise_evolution_services(c)

    # Event Sourcing (Constitution Architecture Standard — event store)
    wire_event_sourcing_services(c)

    # CQRS Command Bus (Constitution Architecture Standard — command query separation)
    wire_command_bus_services(c)

    # CQRS Query Bus (Constitution Architecture Standard — query handling)
    wire_query_bus_services(c)

    # Distributed Tracing (Constitution SRE Standard — observability)
    wire_distributed_tracing_services(c)

    # Threat Intelligence (Constitution Security Standard — CVE scanning)
    wire_threat_intel_services(c)

    # Vulnerability Scanner (Constitution Security Standard — weakness detection)
    wire_vulnerability_scanner_services(c)

    # ── Cross-Module Integrations (v2.57) ────────────────────────────────
    wire_integration_services(c)

    return c


__all__ = [
    "wire_default_services",
]
