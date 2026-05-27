"""Core trading engines for the index option trading system. v1.2 Consolidated."""

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
from .backtest_engine import (
    BacktestConfig,
    BacktestEngine,
    BacktestReport,
    BacktestTrade,
    CsvReplaySource,
    ReplayConfig,
    ReplaySignal,
)
from .broker_capture import BrokerEvent, JsonlCaptureWriter
from .config_bootstrap import (
    CONFIG_B64_SECRET_KEYS_INDEX,
    CONFIG_B64_SECRET_KEYS_STOCK,
    coerce_config_values_to_defaults_types,
    merge_bot_config,
)
from .config_engine import ConfigIssue, ConfigValidationResult, ConfigValidator
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
from .defaults_loader import load_defaults_file
from .environment import Environment, guard_dev_config_in_production, guard_mode_env_compatibility, validate_environment
from .execution_engine import ExecutionEngine, ExecutionFill, ExecutionResult
from .hybrid_execution import apply_execution_mode, normalize_execution_mode
from .orchestrator import Orchestrator, OrchestratorCycle, OrchestratorSignal
from .presentation_engine import PresentationEngine
from .reconciliation_engine import ReconciliationEngine, ReconciliationItem, ReconciliationReport
from .replay_engine import ReplayEngine
from .retention_engine import RetentionEngine, RetentionPolicy
from .risk.legacy_adapter import RiskConfig, RiskDecision
from .safety_engine import SafetyConfig, SafetyContext, SafetyDecision, SafetyEngine
from .soft_reload_common import ignored_keys_warning
from .startup_checklist import StartupCheckItem, StartupCheckResult, run_startup_checklist
from .state_manager import SessionRecoveryReport, StateManager
from .strategy_engine import StrategyEngine
from .trade_journal import VALID_EXIT_REASONS, TradeJournal
from .utils_numeric import safe_float, safe_num
from .walkforward_engine import WalkForwardEngine, WalkForwardReport, WalkForwardWindow

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
    "BacktestConfig",
    "BacktestEngine",
    "BacktestReport",
    "BacktestTrade",
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
    "CsvReplaySource",
    "DataEngine",
    "decode_if_b64",
    "deep_merge_dict",
    "DashboardEngine",
    "ExecutionEngine",
    "ExecutionFill",
    "ExecutionResult",
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
    "Orchestrator",
    "recent_trade_learning_snapshot",
    "OrchestratorCycle",
    "OrchestratorSignal",
    "PresentationEngine",
    "ProviderChain",
    "ProviderResult",
    "redact",
    "ReconciliationEngine",
    "ReconciliationItem",
    "ReconciliationReport",
    "RetentionEngine",
    "RetentionPolicy",
    "ReplayConfig",
    "ReplayEngine",
    "ReplaySignal",
    "RiskConfig",
    "RiskDecision",
    "SafetyConfig",
    "SafetyContext",
    "SafetyDecision",
    "SafetyEngine",
    "SessionRecoveryReport",
    "StateManager",
    "update_learning_after_exit",
    "StrategyEngine",
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
]
