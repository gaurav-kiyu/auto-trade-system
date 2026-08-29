"""Core trading engines for the index option trading system. v1.2 Consolidated.

Sub-packages exposed at top level:
  - core.domains       : All domain models (execution, fo, equity, commodity, etc.)
  - core.ports         : All port interfaces (broker, risk, strategy, etc.)
  - core.risk          : Risk subsystem (Greeks, limits, sizing, margin)
"""

import warnings

from .adapters import (
    BrokerRuntimeContext,
    DataRuntimeContext,
    PaperBrokerAdapter,
    PaperFill,
    broker_connection_secrets,
    build_broker_runtime_context,
    build_provider_chain,
    create_broker_adapter,
    create_broker_adapter_with_runtime_context,
    fetch_yfinance_frames,
)
from .adaptive_learning import (
    adaptive_threshold_adjustment,
    clamp_learning_state,
    live_signal_confidence,
    recent_trade_learning_snapshot,
    update_learning_after_exit,
)
from .ai_engine import (
    AIDecision,
    AIEngine,
    AIEngineConfig,
    ai_engine_config_from_cfg,
    get_ai_engine,
    reset_ai_engine,
)
from .audit_engine import AuditEngine, AuditRecord
from .auto_learner import (
    AutoLearner,
    LearnerConfig,
    get_auto_learner,
    learner_config_from_cfg,
    reset_auto_learner,
)
from .broker_capture import BrokerEvent, JsonlCaptureWriter
from .config_bootstrap import (
    CONFIG_B64_SECRET_KEYS_INDEX,
    CONFIG_B64_SECRET_KEYS_STOCK,
    coerce_config_values_to_defaults_types,
    merge_bot_config,
)

with warnings.catch_warnings():
    warnings.filterwarnings("ignore", message=".*DEPRECATED.*", category=DeprecationWarning)
    from .config_engine import ConfigIssue, ConfigValidationResult, ConfigValidator
# ── Domain models (accessible as core.domains) ──────────────────────────
# Lazy import: walkforward_engine has pandas dependency
# WalkForwardEngine/WalkForwardReport/WalkForwardWindow loaded via __getattr__
# ── Lazy loading — heavy-dependency modules (pandas/numpy) deferred ───
import importlib as _importlib
import types as _types
import typing as _typing

from . import domains as domains_module

# ── Port interfaces (accessible as core.ports) ──────────────────────────
from . import ports as ports_module

# ── Database Port Adapters (Sprint 8) ──────────────────────────────────
from .adapters.database import SQLiteDatabaseAdapter
from .ai_token_cost_tracker import (
    MonthlyCostReport,
    TokenCostTracker,
    UsageRecord,
    get_token_cost_tracker,
    reset_token_cost_tracker,
)
from .autonomous_optimizer import (
    AutonomousOptimizer,
    OptimizationApplied,
    OptimizationReport,
    OptimizerFinding,
    get_autonomous_optimizer,
    reset_autonomous_optimizer,
)
from .bias_detector import (
    BiasDetector,
    BiasFinding,
    BiasReport,
    get_bias_detector,
    reset_bias_detector,
)
from .config_helpers import (
    build_audit_config_snapshot,
    decode_if_b64,
    deep_merge_dict,
    normalize_tg_trade_patterns,
    redact,
)
from .dashboard_engine import DashboardEngine
from .data_engine import DataEngine, MarketDataSnapshot, ProviderChain, ProviderResult
from .data_governance import CleanupScheduler, DataGovernor
from .data_lineage import (
    DataLineageEngine,
    DataLineageRecord,
    ImpactAnalysis,
    ProvenanceChain,
    get_lineage_engine,
)
from .datetime_ist import (
    IST_OFFSET,
    apply_nse_session_from_cfg,
    configure_nse_cash_session,
    format_weekday_bias_str,
    is_nse_cash_session,
    is_nse_continuous_trading_window,
    mins_until_nse_cash_close,
    now_ist,
    nse_cash_close_time,
    nse_cash_open_time,
)
from .db_migration import (
    Migration,
    ensure_schema_version,
    get_migration_log,
    get_schema_version,
    migrate_to_latest,
    register_schema,
)
from .db_provider import DatabaseProvider, get_database, reset_database
from .decision_analyzer import (
    AnalyzerReport,
    DecisionAnalyzer,
    DecisionScore,
    get_decision_analyzer,
    reset_decision_analyzer,
)
from .decision_memory import (
    DecisionMemory,
    DecisionMemoryReport,
    DecisionRecord,
    DecisionSearchResult,
    DecisionTimelineEntry,
    QuestionAnswer,
    get_decision_memory,
    reset_decision_memory,
)
from .defaults_loader import load_defaults_file
from .enterprise_knowledge_graph import (
    EnterpriseKGReport,
    EnterpriseKnowledgeGraph,
    KGNode,
    KGRelation,
    get_enterprise_knowledge_graph,
    reset_enterprise_knowledge_graph,
)
from .environment import Environment, guard_dev_config_in_production, guard_mode_env_compatibility, validate_environment
from .fundamental_analyzer import (
    DEFAULT_WEIGHTS,
    DimensionScore,
    FundamentalAnalyzer,
    FundamentalData,
    ScreeningResult,
    get_fundamental_analyzer,
)
from .hallucination_detector import (
    HallucinationDetector,
    HallucinationFinding,
    HallucinationResult,
    get_hallucination_detector,
    reset_hallucination_detector,
)
from .hybrid_execution import apply_execution_mode, normalize_execution_mode
from .ics_telegram_bridge import (
    ICSTelegramBridge,
    get_ics_telegram_bridge,
    reset_ics_telegram_bridge,
    wire_ics_telegram_alerts,
)
from .incident_command_system import IncidentCommander, get_incident_commander, reset_incident_commander
from .knowledge_base import (
    BEST_PRACTICE,
    CODE_REVIEW_PATTERN,
    INCIDENT_PATTERN,
    LESSON_LEARNED,
    OPTIMIZATION_PATTERN,
    TEST_FAILURE_PATTERN,
    KnowledgeBase,
    KnowledgeBaseReport,
    KnowledgeEntry,
    get_knowledge_base,
    reset_knowledge_base,
)
from .pattern_learner import (
    LearnedPattern,
    PatternLearner,
    PatternLearnerReport,
    get_pattern_learner,
    reset_pattern_learner,
)

# ── Multi-asset portfolio adapters ─────────────────────────────────────────
from .portfolio.adapters import (
    AssetClassExposure,
    CapitalAllocationService,
    MultiAssetPortfolioAggregator,
)
from .reconciliation_engine import ReconciliationEngine, ReconciliationItem, ReconciliationReport

# Lazy import: replay_engine has pandas/numpy dependency
# ReplayEngine is loaded on demand via __getattr__
from .retention_engine import RetentionEngine, RetentionPolicy
from .risk.legacy_adapter import RiskConfig, RiskDecision
from .safety_engine import SafetyConfig, SafetyContext, SafetyDecision, SafetyEngine
from .soft_reload_common import ignored_keys_warning
from .startup_checklist import StartupCheckItem, StartupCheckResult, run_startup_checklist
from .state_manager import SessionRecoveryReport, StateManager
from .trade_journal import VALID_EXIT_REASONS, TradeJournal
from .utils_numeric import safe_float, safe_num

_LazyModuleCache: dict[str, _types.ModuleType] = {}


def __getattr__(name: str) -> _typing.Any:
    """Lazy-load modules with heavy dependencies (pandas, numpy, etc.).

    This prevents ``core/__init__.py`` from eagerly importing
    ``backtest_engine`` (and hence ``pandas``/``numpy``) at module-load
    time, which breaks ``coverage`` on Python 3.14 (numpy multiprocessing
    limitation).
    """
    _LAZY_ATTRS: dict[str, tuple[str, str]] = {
        "ReplayEngine": ("core.replay_engine", "ReplayEngine"),
        "PresentationEngine": ("core.presentation_engine", "PresentationEngine"),
        "WalkForwardEngine": ("core.walkforward_engine", "WalkForwardEngine"),
        "WalkForwardReport": ("core.walkforward_engine", "WalkForwardReport"),
        "WalkForwardWindow": ("core.walkforward_engine", "WalkForwardWindow"),
        # backtest_engine (pandas/numpy dependency)
        "BacktestConfig": ("core.backtest_engine", "BacktestConfig"),
        "BacktestEngine": ("core.backtest_engine", "BacktestEngine"),
        "BacktestReport": ("core.backtest_engine", "BacktestReport"),
        "BacktestTrade": ("core.backtest_engine", "BacktestTrade"),
        "CsvReplaySource": ("core.backtest_engine", "CsvReplaySource"),
        "ReplayConfig": ("core.backtest_engine", "ReplayConfig"),
        "ReplaySignal": ("core.backtest_engine", "ReplaySignal"),
    }
    if name in _LAZY_ATTRS:
        module_path, attr_name = _LAZY_ATTRS[name]
        if module_path not in _LazyModuleCache:
            _LazyModuleCache[module_path] = _importlib.import_module(module_path)
        return getattr(_LazyModuleCache[module_path], attr_name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "AIDecision",
    "AIEngine",
    "AIEngineConfig",
    "ai_engine_config_from_cfg",
    "get_ai_engine",
    "reset_ai_engine",
    "AutoLearner",
    "LearnerConfig",
    "get_auto_learner",
    "learner_config_from_cfg",
    "reset_auto_learner",
    "adaptive_threshold_adjustment",
    "apply_execution_mode",
    "AuditEngine",
    "AuditRecord",
    "clamp_learning_state",
    "BrokerEvent",
    "BrokerRuntimeContext",
    "PaperBrokerAdapter",
    "PaperFill",
    "broker_connection_secrets",
    "build_broker_runtime_context",
    "DataRuntimeContext",
    "build_provider_chain",
    "create_broker_adapter",
    "create_broker_adapter_with_runtime_context",
    "ConfigIssue",
    "ConfigValidationResult",
    "ConfigValidator",
    "DataEngine",
    "decode_if_b64",
    "deep_merge_dict",
    "DashboardEngine",
    "JsonlCaptureWriter",
    "CleanupScheduler",
    "CONFIG_B64_SECRET_KEYS_INDEX",
    "CONFIG_B64_SECRET_KEYS_STOCK",
    "coerce_config_values_to_defaults_types",
    "DataGovernor",
    "Environment",
    "ensure_schema_version",
    "get_migration_log",
    "get_schema_version",
    "guard_dev_config_in_production",
    "guard_mode_env_compatibility",
    "load_defaults_file",
    "merge_bot_config",
    "migrate_to_latest",
    "Migration",
    "register_schema",
    "validate_environment",
    "live_signal_confidence",
    "MarketDataSnapshot",
    "normalize_execution_mode",
    "normalize_tg_trade_patterns",
    "recent_trade_learning_snapshot",
    "ProviderChain",
    "ProviderResult",
    "redact",
    "ReconciliationEngine",
    "ReconciliationItem",
    "ReconciliationReport",
    "RetentionEngine",
    "RetentionPolicy",
    "ReplayEngine",
    "PresentationEngine",
    "RiskConfig",
    "RiskDecision",
    "SafetyConfig",
    "SafetyContext",
    "SafetyDecision",
    "SafetyEngine",
    "SessionRecoveryReport",
    "StateManager",
    "update_learning_after_exit",
    "WalkForwardEngine",
    "WalkForwardReport",
    "WalkForwardWindow",
    "fetch_yfinance_frames",
    "format_weekday_bias_str",
    "build_audit_config_snapshot",
    "ignored_keys_warning",
    "run_startup_checklist",
    "StartupCheckItem",
    "StartupCheckResult",
    "VALID_EXIT_REASONS",
    "TradeJournal",
    "IST_OFFSET",
    "apply_nse_session_from_cfg",
    "now_ist",
    "is_nse_cash_session",
    "is_nse_continuous_trading_window",
    "mins_until_nse_cash_close",
    "configure_nse_cash_session",
    "nse_cash_close_time",
    "nse_cash_open_time",
    "safe_float",
    "safe_num",
    # Database Port
    "SQLiteDatabaseAdapter",
    # Domain & port packages
    "domains_module",
    "ports_module",
    # Multi-asset portfolio adapters
    "AssetClassExposure",
    "CapitalAllocationService",
    "MultiAssetPortfolioAggregator",
    # Data Lineage Engine
    "DataLineageEngine",
    "DataLineageRecord",
    "ImpactAnalysis",
    "ProvenanceChain",
    "get_lineage_engine",
    # Fundamental Analyzer
    "DEFAULT_WEIGHTS",
    "DimensionScore",
    "FundamentalAnalyzer",
    "FundamentalData",
    "ScreeningResult",
    "get_fundamental_analyzer",
    # Backward-compatible lazy-loaded symbols
    "BacktestConfig",
    "BacktestEngine",
    "BacktestReport",
    "BacktestTrade",
    "CsvReplaySource",
    "ReplayConfig",
    "ReplaySignal",
    # Database Provider
    "DatabaseProvider",
    "get_database",
    "reset_database",
    # Incident Command System
    "IncidentCommander",
    "get_incident_commander",
    "reset_incident_commander",
    # ICS-Telegram Bridge
    "ICSTelegramBridge",
    "get_ics_telegram_bridge",
    "reset_ics_telegram_bridge",
    "wire_ics_telegram_alerts",
    # Hallucination Detection
    "HallucinationDetector",
    "HallucinationFinding",
    "HallucinationResult",
    "get_hallucination_detector",
    "reset_hallucination_detector",
    # AI Token Cost Tracking
    "TokenCostTracker",
    "UsageRecord",
    "MonthlyCostReport",
    "get_token_cost_tracker",
    "reset_token_cost_tracker",
    # Enterprise Knowledge Graph
    "EnterpriseKnowledgeGraph",
    "EnterpriseKGReport",
    "KGNode",
    "KGRelation",
    "get_enterprise_knowledge_graph",
    "reset_enterprise_knowledge_graph",
    # Bias Detection Engine
    "BiasDetector",
    "BiasFinding",
    "BiasReport",
    "get_bias_detector",
    "reset_bias_detector",
    # Autonomous Optimization Engine
    "AutonomousOptimizer",
    "OptimizationReport",
    "OptimizationApplied",
    "OptimizerFinding",
    "get_autonomous_optimizer",
    "reset_autonomous_optimizer",
    # Decision Memory
    "DecisionMemory",
    "DecisionMemoryReport",
    "DecisionRecord",
    "DecisionSearchResult",
    "DecisionTimelineEntry",
    "QuestionAnswer",
    "get_decision_memory",
    "reset_decision_memory",
    # Decision Analyzer
    "AnalyzerReport",
    "DecisionAnalyzer",
    "DecisionScore",
    "get_decision_analyzer",
    "reset_decision_analyzer",
    # Recommendations
    "Recommendation",
    "RecommendationEngine",
    "RecommendationReport",
    "generate_recommendations",
    "generate_engineering_recommendations",
    "get_recommendation_engine",
    "reset_recommendation_engine",
    # Root Cause Analyzer
    "EvidenceItem",
    "KNOWN_INCIDENT_PATTERNS",
    "RootCauseAnalyzer",
    "RootCauseResult",
    "get_root_cause_analyzer",
    "investigate_incident",
    "reset_root_cause_analyzer",
    # Engineering Analytics
    "EngineeringAnalyticsEngine",
    "EngineeringMetricsReport",
    "GitCommitRecord",
    "IncidentRecord",
    "get_engineering_analytics",
    "reset_engineering_analytics",
    # MTTR Tracker
    "MTTRTracker",
    "MTTRReport",
    "get_mttr_tracker",
    "get_mttr_report",
    # Knowledge Base
    "BEST_PRACTICE",
    "CODE_REVIEW_PATTERN",
    "INCIDENT_PATTERN",
    "LESSON_LEARNED",
    "OPTIMIZATION_PATTERN",
    "TEST_FAILURE_PATTERN",
    "KnowledgeBase",
    "KnowledgeBaseReport",
    "KnowledgeEntry",
    "get_knowledge_base",
    "reset_knowledge_base",
    # Pattern Learner
    "LearnedPattern",
    "PatternLearner",
    "PatternLearnerReport",
    "get_pattern_learner",
    "reset_pattern_learner",
]
