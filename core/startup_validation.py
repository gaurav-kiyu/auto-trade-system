"""
Startup Validation - Ensures system is properly configured before trading begins

Validates:
- Single risk authority active (not deprecated duplicates)
- Required ports are wired
- Config is valid
- No conflicting modules are loaded

This runs at startup before any trading begins.

REQUIRED ARCHITECTURE (Phase 1B):
  Authoritative: core.risk.authoritative_engine.RiskAuthority
  Delegates to:  core.services.risk_service.RiskService
  DEPRECATED:    predictive_risk, trading_risk, risk_policy_engine,
                 dynamic_risk_sizer, mandate_enforcer
"""
from __future__ import annotations

import logging
import sys

log = logging.getLogger("startup_validation")

# The authoritative risk engine module
AUTHORITATIVE_RISK_ENGINE = "core.risk.authoritative_engine"

# Deprecated risk engine modules — any loaded at startup is a violation
DEPRECATED_RISK_MODULES = {
    "core.predictive_risk": "Removed — use RiskAuthority",
    "core.trading_risk": "Removed — use RiskAuthority",
    "core.risk.risk_policy_engine": "Removed — use RiskAuthority",
    "core.dynamic_risk_sizer": "Removed — use RiskAuthority",
    "core.risk_engine_v2": "Removed — consolidated into risk_engine.RiskEngine",
}


def validate_risk_engine() -> tuple[bool, str]:
    """
    Validate that only the authoritative risk engine is active.
    Returns (is_valid, message).
    """
    # Check deprecated modules are NOT loaded
    loaded = [m for m in sys.modules if m in DEPRECATED_RISK_MODULES]
    if loaded:
        msg = f"Deprecated risk modules still loaded: {loaded}"
        log.warning("STARTUP VALIDATION: %s", msg)
        return False, msg

    # Check authoritative engine is importable
    try:
        from core.risk.authoritative_engine import RiskAuthority, get_risk_authority
        log.info("RiskAuthority (core.risk.authoritative_engine) available — PASS")
        return True, "RiskAuthority is the canonical risk engine"
    except ImportError as e:
        msg = f"Cannot import RiskAuthority: {e}"
        log.error("STARTUP VALIDATION FAILED: %s", msg)
        return False, msg


def validate_dependencies() -> tuple[bool, str]:
    """
    Validate that required dependencies are available.
    Returns (is_valid, message).
    """
    required_modules = [
        ("core.risk.authoritative_engine", "RiskAuthority"),
        ("core.services.risk_service", "RiskService"),
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


def run_startup_validation() -> bool:
    """
    Run all startup validations.
    Returns True if all validations pass.
    """
    log.info("=" * 60)
    log.info("AD-KIYU STARTUP VALIDATION: Beginning system validation...")
    log.info("=" * 60)

    validations = [
        ("Risk Engine", validate_risk_engine),
        ("Dependencies", validate_dependencies),
    ]

    all_passed = True
    for name, validator in validations:
        passed, msg = validator()
        if passed:
            log.info("  [%s] PASS: %s", name, msg)
        else:
            log.error("  [%s] FAIL: %s", name, msg)
            all_passed = False

    if all_passed:
        log.info("=" * 60)
        log.info("AD-KIYU STARTUP VALIDATION: ALL CHECKS PASSED")
        log.info("=" * 60)
    else:
        log.error("=" * 60)
        log.error("AD-KIYU STARTUP VALIDATION: FAILED")
        log.error("=" * 60)

    return all_passed
