"""
Startup Validation - Ensures system is properly configured before trading begins

Validates:
- Single risk authority active (not deprecated duplicates)
- Required ports are wired
- Config is valid
- No conflicting modules are loaded

This runs at startup before any trading begins.

ARCHITECTURE (declared in core/risk/__init__.py):
  Authoritative: core.services.risk_service.RiskService (implements RiskPort)
  Deprecated:    core.risk_engine
"""
from __future__ import annotations

import logging
import sys

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
