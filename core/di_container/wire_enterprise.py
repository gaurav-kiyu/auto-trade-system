"""Enterprise wire functions for the DI container.

Contains all non-core, non-security wire functions.
"""

from __future__ import annotations

from core.di_container.container import DIContainer, _get_container


def wire_performance_services(container_instance: DIContainer | None = None) -> None:
    c = _get_container(container_instance)
    try:
        from core.performance_optimizer import PerformanceOptimizer, get_performance_optimizer
        if not c.is_registered(PerformanceOptimizer):
            c.register_instance(PerformanceOptimizer, get_performance_optimizer())
    except ImportError:
        pass


def wire_architecture_services(container_instance: DIContainer | None = None) -> None:
    c = _get_container(container_instance)
    try:
        from core.architecture_analyzer import ArchitectureAnalyzer, get_architecture_analyzer
        if not c.is_registered(ArchitectureAnalyzer):
            c.register_instance(ArchitectureAnalyzer, get_architecture_analyzer())
    except ImportError:
        pass


def wire_presentation_services(container_instance: DIContainer | None = None) -> None:
    c = _get_container(container_instance)
    try:
        from core.presentation_generator import PresentationGenerator, get_presentation_generator
        if not c.is_registered(PresentationGenerator):
            c.register_instance(PresentationGenerator, get_presentation_generator())
    except ImportError:
        pass


def wire_dependency_services(container_instance: DIContainer | None = None) -> None:
    c = _get_container(container_instance)
    try:
        from core.dependency_analyzer import DependencyAnalyzer, get_dependency_analyzer
        if not c.is_registered(DependencyAnalyzer):
            c.register_instance(DependencyAnalyzer, get_dependency_analyzer())
    except ImportError:
        pass


def wire_recommendation_services(container_instance: DIContainer | None = None) -> None:
    c = _get_container(container_instance)
    try:
        from core.recommendation_engine import RecommendationEngine, get_recommendation_engine
        if not c.is_registered(RecommendationEngine):
            c.register_instance(RecommendationEngine, get_recommendation_engine())
    except ImportError:
        pass


def wire_synthetic_monitor_services(container_instance: DIContainer | None = None) -> None:
    c = _get_container(container_instance)
    try:
        from core.synthetic_monitor import SyntheticMonitor, get_synthetic_monitor
        if not c.is_registered(SyntheticMonitor):
            c.register_instance(SyntheticMonitor, get_synthetic_monitor())
    except ImportError:
        pass


def wire_sbom_services(container_instance: DIContainer | None = None) -> None:
    c = _get_container(container_instance)
    try:
        from core.sbom_generator import SBOMGenerator, get_sbom_generator
        if not c.is_registered(SBOMGenerator):
            c.register_instance(SBOMGenerator, get_sbom_generator())
    except ImportError:
        pass


def wire_strategy_plugin_services(container_instance: DIContainer | None = None) -> None:
    c = _get_container(container_instance)
    try:
        from core.strategy.plugin_framework import StrategyRegistry, get_strategy_registry
        if not c.is_registered(StrategyRegistry):
            c.register_instance(StrategyRegistry, get_strategy_registry())
    except ImportError:
        pass


def wire_chaos_engine_services(container_instance: DIContainer | None = None) -> None:
    c = _get_container(container_instance)
    try:
        from core.chaos_engine import ChaosEngine, get_chaos_engine
        if not c.is_registered(ChaosEngine):
            c.register_instance(ChaosEngine, get_chaos_engine())
    except ImportError:
        pass


def wire_postmortem_automator_services(container_instance: DIContainer | None = None) -> None:
    c = _get_container(container_instance)
    try:
        from core.postmortem_automator import PostmortemAutomator, get_postmortem_automator
        if not c.is_registered(PostmortemAutomator):
            c.register_instance(PostmortemAutomator, get_postmortem_automator())
    except ImportError:
        pass


def wire_decision_memory_services(container_instance: DIContainer | None = None) -> None:
    c = _get_container(container_instance)
    try:
        from core.decision_memory import DecisionMemory, get_decision_memory
        if not c.is_registered(DecisionMemory):
            c.register_instance(DecisionMemory, get_decision_memory())
    except ImportError:
        pass


def wire_digital_twin_services(container_instance: DIContainer | None = None) -> None:
    c = _get_container(container_instance)
    try:
        from core.digital_twin import DigitalTwin, get_digital_twin
        if not c.is_registered(DigitalTwin):
            c.register_instance(DigitalTwin, get_digital_twin())
    except ImportError:
        pass


def wire_api_versioning_services(container_instance: DIContainer | None = None) -> None:
    c = _get_container(container_instance)
    try:
        from core.api_versioning import APIVersionManager, get_api_version_manager
        if not c.is_registered(APIVersionManager):
            c.register_instance(APIVersionManager, get_api_version_manager())
    except ImportError:
        pass


def wire_executive_advisor_services(container_instance: DIContainer | None = None) -> None:
    c = _get_container(container_instance)
    try:
        from core.executive_advisor import ExecutiveAdvisor, get_executive_advisor
        if not c.is_registered(ExecutiveAdvisor):
            c.register_instance(ExecutiveAdvisor, get_executive_advisor())
    except ImportError:
        pass


def wire_service_catalog_services(container_instance: DIContainer | None = None) -> None:
    c = _get_container(container_instance)
    try:
        from core.service_catalog import ServiceCatalog, get_service_catalog
        if not c.is_registered(ServiceCatalog):
            c.register_instance(ServiceCatalog, get_service_catalog())
    except ImportError:
        pass


def wire_intelligence_pipeline_services(container_instance: DIContainer | None = None) -> None:
    c = _get_container(container_instance)
    try:
        from core.continuous_intelligence import ContinuousIntelligenceEngine, get_intelligence_pipeline
        if not c.is_registered(ContinuousIntelligenceEngine):
            c.register_instance(ContinuousIntelligenceEngine, get_intelligence_pipeline())
    except ImportError:
        pass


def wire_feature_flags_services(container_instance: DIContainer | None = None) -> None:
    c = _get_container(container_instance)
    try:
        from core.feature_flags import FeatureFlagManager, get_feature_flag_manager
        if not c.is_registered(FeatureFlagManager):
            c.register_instance(FeatureFlagManager, get_feature_flag_manager())
    except ImportError:
        pass


def wire_event_bus_services(container_instance: DIContainer | None = None) -> None:
    c = _get_container(container_instance)
    try:
        from core.event_bus import EventBus, get_event_bus
        if not c.is_registered(EventBus):
            c.register_instance(EventBus, get_event_bus())
    except ImportError:
        pass


def wire_plugin_registry_services(container_instance: DIContainer | None = None) -> None:
    c = _get_container(container_instance)
    try:
        from core.plugin_registry import PluginRegistry, get_plugin_registry
        if not c.is_registered(PluginRegistry):
            c.register_instance(PluginRegistry, get_plugin_registry())
    except ImportError:
        pass


def wire_enterprise_evolution_services(container_instance: DIContainer | None = None) -> None:
    c = _get_container(container_instance)
    try:
        from core.enterprise_evolution import EnterpriseEvolutionEngine, get_evolution_engine
        if not c.is_registered(EnterpriseEvolutionEngine):
            c.register_instance(EnterpriseEvolutionEngine, get_evolution_engine())
    except ImportError:
        pass


def wire_event_sourcing_services(container_instance: DIContainer | None = None) -> None:
    c = _get_container(container_instance)
    try:
        from core.event_sourcing import EventStore, get_event_store
        if not c.is_registered(EventStore):
            c.register_instance(EventStore, get_event_store())
    except ImportError:
        pass


def wire_command_bus_services(container_instance: DIContainer | None = None) -> None:
    c = _get_container(container_instance)
    try:
        from core.cqrs.command_bus import CommandBus
        if not c.is_registered(CommandBus):
            c.register_instance(CommandBus, CommandBus())
    except ImportError:
        pass


def wire_query_bus_services(container_instance: DIContainer | None = None) -> None:
    c = _get_container(container_instance)
    try:
        from core.cqrs.query_bus import QueryBus
        if not c.is_registered(QueryBus):
            c.register_instance(QueryBus, QueryBus())
    except ImportError:
        pass


def wire_distributed_tracing_services(container_instance: DIContainer | None = None) -> None:
    c = _get_container(container_instance)
    try:
        from core.distributed_tracing import Tracer, get_tracer
        if not c.is_registered(Tracer):
            c.register_instance(Tracer, get_tracer())
    except ImportError:
        pass


def wire_hallucination_detector_services(container_instance: DIContainer | None = None) -> None:
    c = _get_container(container_instance)
    try:
        from core.hallucination_detector import HallucinationDetector, get_hallucination_detector
        if not c.is_registered(HallucinationDetector):
            c.register_instance(HallucinationDetector, get_hallucination_detector())
    except ImportError:
        pass


def wire_token_cost_tracker_services(container_instance: DIContainer | None = None) -> None:
    c = _get_container(container_instance)
    try:
        from core.ai_token_cost_tracker import TokenCostTracker, get_token_cost_tracker
        if not c.is_registered(TokenCostTracker):
            c.register_instance(TokenCostTracker, get_token_cost_tracker())
    except ImportError:
        pass


def wire_enterprise_kg_services(container_instance: DIContainer | None = None) -> None:
    c = _get_container(container_instance)
    try:
        from core.enterprise_knowledge_graph import EnterpriseKnowledgeGraph, get_enterprise_knowledge_graph
        if not c.is_registered(EnterpriseKnowledgeGraph):
            c.register_instance(EnterpriseKnowledgeGraph, get_enterprise_knowledge_graph())
    except ImportError:
        pass


def wire_autonomous_optimizer_services(container_instance: DIContainer | None = None) -> None:
    c = _get_container(container_instance)
    try:
        from core.autonomous_optimizer import AutonomousOptimizer, get_autonomous_optimizer
        if not c.is_registered(AutonomousOptimizer):
            c.register_instance(AutonomousOptimizer, get_autonomous_optimizer())
    except ImportError:
        pass


def wire_decision_analyzer_services(container_instance: DIContainer | None = None) -> None:
    c = _get_container(container_instance)
    try:
        from core.decision_analyzer import DecisionAnalyzer, get_decision_analyzer
        if not c.is_registered(DecisionAnalyzer):
            c.register_instance(DecisionAnalyzer, get_decision_analyzer())
    except ImportError:
        pass


def wire_bias_detector_services(container_instance: DIContainer | None = None) -> None:
    c = _get_container(container_instance)
    try:
        from core.bias_detector import BiasDetector, get_bias_detector
        if not c.is_registered(BiasDetector):
            c.register_instance(BiasDetector, get_bias_detector())
    except ImportError:
        pass


def wire_integration_services(container_instance: DIContainer | None = None) -> None:
    import logging
    _log = logging.getLogger(__name__)
    try:
        from core.integrations import (
            wire_cqrs_to_event_sourcing,
            wire_event_bus_to_mediator,
            wire_feature_flag_guards,
            wire_plugin_to_strategy,
            wire_secrets_to_config,
            wire_security_feeds,
            wire_tracing_to_mediator,
        )
        wire_event_bus_to_mediator()
        wire_cqrs_to_event_sourcing()
        wire_plugin_to_strategy()
        wire_secrets_to_config()
        wire_tracing_to_mediator()
        wire_security_feeds()
        wire_feature_flag_guards()
        _log.info("[DI] Integration bridges: ALL 7 WIRED")
    except ImportError:
        _log.debug("[DI] Integration bridges: optional deps not available")


__all__ = [
    "wire_performance_services",
    "wire_architecture_services",
    "wire_presentation_services",
    "wire_dependency_services",
    "wire_recommendation_services",
    "wire_synthetic_monitor_services",
    "wire_sbom_services",
    "wire_strategy_plugin_services",
    "wire_chaos_engine_services",
    "wire_postmortem_automator_services",
    "wire_decision_memory_services",
    "wire_digital_twin_services",
    "wire_api_versioning_services",
    "wire_executive_advisor_services",
    "wire_service_catalog_services",
    "wire_intelligence_pipeline_services",
    "wire_feature_flags_services",
    "wire_event_bus_services",
    "wire_plugin_registry_services",
    "wire_enterprise_evolution_services",
    "wire_event_sourcing_services",
    "wire_command_bus_services",
    "wire_query_bus_services",
    "wire_distributed_tracing_services",
    "wire_hallucination_detector_services",
    "wire_token_cost_tracker_services",
    "wire_enterprise_kg_services",
    "wire_autonomous_optimizer_services",
    "wire_decision_analyzer_services",
    "wire_bias_detector_services",
    "wire_integration_services",
]
