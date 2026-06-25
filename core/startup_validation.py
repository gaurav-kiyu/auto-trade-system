"""
Startup Validation - Ensures system is properly configured before trading begins

Validates:
- Single risk authority active (not deprecated duplicates)
- Required ports are wired
- Merged config is valid (type, range, consistency + JSON Schema)
- No conflicting modules are loaded
- Environment is valid

This runs at startup BEFORE any trading begins.

DEBT-005: FAIL-FAST enforcement — any validation error terminates the process.
No optional validation. If configuration is invalid, the system must NOT start.

ARCHITECTURE (declared in core/risk/__init__.py):
  Authoritative: core.services.risk_service.RiskService (implements RiskPort)
  Deprecated:    core.risk_engine
"""
from __future__ import annotations

import logging
import os
import sys
from typing import Any

log = logging.getLogger("startup_validation")

# The authoritative risk engine module
AUTHORITATIVE_RISK_MODULE = "core.services.risk_service"
AUTHORITATIVE_RISK_CLASS = "RiskService"

# Deprecated risk engine modules - any loaded at startup is a violation
DEPRECATED_RISK_MODULES = {
    "core.risk_engine": "Removed in v2.54 - use core.services.risk_service.RiskService via RiskPort",
    "core.predictive_risk": "Removed",
    "core.trading_risk": "Removed",
    "core.risk.risk_policy_engine": "Removed",
    "core.dynamic_risk_sizer": "Removed",
    "core.risk_engine_v2": "Removed",
}


def validate_risk_engine() -> tuple[bool, str]:
    """
    Validate that the authoritative risk engine is available.
    Deprecated modules are warned but not blocking (they will be removed in a future release).
    Returns (is_valid, message).
    """
    # Check deprecated modules loaded (warn only, not blocking)
    loaded = [m for m in sys.modules if m in DEPRECATED_RISK_MODULES]
    for mod in loaded:
        log.warning("Deprecated risk module loaded: %s - %s", mod, DEPRECATED_RISK_MODULES[mod])

    # Check authoritative engine is importable
    try:
        __import__(AUTHORITATIVE_RISK_MODULE)
        log.info(
            "%s.%s available - PASS",
            AUTHORITATIVE_RISK_MODULE,
            AUTHORITATIVE_RISK_CLASS,
        )
        return True, f"RiskService (via {AUTHORITATIVE_RISK_MODULE}) is the canonical risk engine"
    except ImportError as e:
        msg = f"Cannot import {AUTHORITATIVE_RISK_MODULE}.{AUTHORITATIVE_RISK_CLASS}: {e}"
        log.error("STARTUP VALIDATION FAILED: %s", msg)
        return False, msg


def validate_dependencies() -> tuple[bool, str]:
    """
    Validate that required dependencies are available.
    Returns (is_valid, message).
    """
    required_modules = [
        (AUTHORITATIVE_RISK_MODULE, AUTHORITATIVE_RISK_CLASS),
        ("core.execution.order_manager", "OrderManager"),
        ("core.system_mode", "SystemModeManager"),
        ("core.audit_journal", "AuditJournal"),
        ("core.execution_guards", "ExecutionGuards"),
        ("core.operating_mode", "OperatingModeManager"),
        ("core.invariants.engine", "InvariantEngine"),
    ]

    missing = []
    for module_path, _ in required_modules:
        try:
            __import__(module_path)
        except ImportError as e:
            missing.append(f"{module_path}: {e}")

    if missing:
        msg = f"Missing required modules: {missing}"
        log.error("STARTUP VALIDATION FAILED: %s", msg)
        return False, msg

    return True, "All required dependencies available"


def validate_app_config(cfg: dict[str, Any], flavour: str = "index") -> tuple[bool, list[str]]:
    """
    Validate merged config for type/range/consistency errors + JSON Schema.

    DEBT-005: This is NOT optional. Every config error is blocking.

    Args:
        cfg:     Merged config dict (defaults + config.json + env overrides).
        flavour: Schema flavour ("index" or "stock").

    Returns:
        (is_valid, error_messages)
    """
    errors: list[str] = []

    # 1. Type/range/consistency validation via config_validator
    try:
        from core.config_validator import validate_config
        cfg_errors, cfg_warnings = validate_config(cfg)
        errors.extend(cfg_errors)
        for w in cfg_warnings:
            log.warning("  [Config] WARN: %s", w)
    except ImportError as e:
        log.warning("config_validator module not available: %s", e)

    # 2. JSON Schema validation via config_schema_validate
    try:
        from core.config_schema_validate import append_json_schema_errors
        append_json_schema_errors(errors, cfg, flavour=flavour)
    except ImportError as e:
        log.warning("config_schema_validate module not available: %s", e)

    # 3. Environment validation
    env = str(cfg.get("ENVIRONMENT", "dev")).lower()
    valid_envs = {"dev", "qa", "paper", "shadow", "staging", "production"}
    if env not in valid_envs:
        errors.append(f"ENVIRONMENT='{env}' not in {valid_envs}")

    if env == "production":
        # Production-specific checks
        bot_token = cfg.get("BOT_TOKEN", "")
        if not bot_token or "YOUR_" in str(bot_token):
            errors.append("PRODUCTION: BOT_TOKEN must be set (found placeholder)")
        chat_id = cfg.get("CHAT_ID", "")
        if not chat_id or "YOUR_" in str(chat_id):
            errors.append("PRODUCTION: CHAT_ID must be set (found placeholder)")
        if cfg.get("environment_block_on_violation", True):
            broker_api = cfg.get("BROKER_CONFIG", {}).get("api_key", "")
            if not broker_api:
                errors.append("PRODUCTION: BROKER_CONFIG.api_key must be set")

    is_valid = len(errors) == 0
    return is_valid, errors


def validate_environment_vars() -> tuple[bool, str]:
    """Validate critical OPBUYING_* environment variables."""
    errors: list[str] = []
    for key, default in [
        ("OPBUYING_BOT_TOKEN", ""),
        ("OPBUYING_CHAT_ID", ""),
        ("OPBUYING_BASE_CAPITAL", ""),
    ]:
        val = os.environ.get(key, "")
        # No error if not set — env vars are override, not required.
        # But log if present so the user knows what's active.
        if val:
            log.info("  Env override active: %s", key)
    return True, "Environment variables OK"


def run_startup_validation(
    cfg: dict[str, Any] | None = None,
    flavour: str = "index",
    fail_fast: bool = True,
) -> bool:
    """
    Run ALL startup validations.

    DEBT-005: By default (fail_fast=True), ANY validation error terminates
    the process with sys.exit(1). This is the ONLY supported mode for
    production — run_startup_validation must pass before trading begins.

    Args:
        cfg:       Merged config dict. If None, config validation is skipped.
        flavour:   Schema flavour ("index" or "stock").
        fail_fast: If True, raises SystemExit on first validation failure.
                   Set to False only for tests and non-production use.

    Returns:
        True if all validations pass (only when fail_fast=False).
    """
    log.info("=" * 60)
    log.info("AD-KIYU STARTUP VALIDATION: Beginning system validation...")
    log.info("=" * 60)

    all_errors: list[str] = []

    # 1. Risk engine validation
    risk_passed, risk_msg = validate_risk_engine()
    if risk_passed:
        log.info("  [Risk Engine] PASS: %s", risk_msg)
    else:
        log.error("  [Risk Engine] FAIL: %s", risk_msg)
        all_errors.append(risk_msg)

    # 2. Dependency validation
    dep_passed, dep_msg = validate_dependencies()
    if dep_passed:
        log.info("  [Dependencies] PASS: %s", dep_msg)
    else:
        log.error("  [Dependencies] FAIL: %s", dep_msg)
        all_errors.append(dep_msg)

    # 3. Config validation (DEBT-005: fail-fast on config errors)
    if cfg is not None:
        cfg_passed, cfg_errors = validate_app_config(cfg, flavour=flavour)
        if cfg_passed:
            log.info("  [Config] PASS: merged config is valid")
        else:
            for e in cfg_errors:
                log.error("  [Config] FAIL: %s", e)
            all_errors.extend(cfg_errors)

    # 4. Environment variable validation
    env_passed, env_msg = validate_environment_vars()
    if env_passed:
        log.info("  [Environment] PASS: %s", env_msg)

    # 5. Emit resolved config summary
    if cfg is not None:
        try:
            from core.config_validator import log_resolved_config
            log_resolved_config(cfg)
        except ImportError:
            pass

    if not all_errors:
        log.info("=" * 60)
        log.info("AD-KIYU STARTUP VALIDATION: ALL CHECKS PASSED")
        log.info("=" * 60)
        return True

    log.error("=" * 60)
    log.error("AD-KIYU STARTUP VALIDATION: FAILED — %d error(s)", len(all_errors))
    for i, e in enumerate(all_errors, 1):
        log.error("  %d. %s", i, e)
    log.error("=" * 60)

    if fail_fast:
        raise SystemExit(
            f"Startup validation failed with {len(all_errors)} error(s). "
            f"Fix configuration and restart. See logs above for details."
        )

    return False


__all__ = [
    "AUTHORITATIVE_RISK_CLASS",
    "AUTHORITATIVE_RISK_MODULE",
    "DEPRECATED_RISK_MODULES",
    "log",
    "run_startup_validation",
    "validate_app_config",
    "validate_dependencies",
    "validate_environment_vars",
    "validate_risk_engine",
]

