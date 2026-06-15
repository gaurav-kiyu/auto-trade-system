"""
Execution Hardening Integration

Wires together all execution hardening modules for seamless integration.
This module is optional - can be imported to enable all hardening features.

Usage:
    from core.execution_hardening_integration import init_execution_hardening
    init_execution_hardening(config, broker_port, send_alert_fn)
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

log = logging.getLogger("execution_hardening_integration")


def init_execution_hardening(
    config: dict,
    broker_port: Any,
    send_alert_fn: Callable[[str, bool], None] | None = None,
    get_price_fn: Callable[[str], float | None] | None = None
) -> dict:
    """
    Initialize all execution hardening modules.

    Returns dict with initialized services for reference.
    """
    services = {}

    # 1. System Mode Manager
    try:
        from core.system_mode import get_system_mode_manager

        def on_mode_change(old_mode, new_mode, reason):
            log.warning(f"System mode: {old_mode} -> {new_mode}: {reason}")
            if send_alert_fn:
                send_alert_fn(f"Mode change: {old_mode} -> {new_mode}", new_mode in ("BROKER_DOWN", "SAFE_MODE"))

        system_mode = get_system_mode_manager(
            on_mode_change=on_mode_change,
            config=config
        )
        services["system_mode"] = system_mode
        log.info("Execution hardening: SystemModeManager initialized")
    except (ImportError, AttributeError, OSError) as e:
        log.error(f"Failed to init SystemModeManager: {e}")

    # 2. Execution Guards
    try:
        from core.execution_guards import get_execution_guards

        guards = get_execution_guards(config)

        # Set alert callback
        if send_alert_fn:
            guards.set_alert_callback(
                lambda msg: send_alert_fn(f"Guard warning: {msg}", False)
            )

        services["execution_guards"] = guards
        log.info("Execution hardening: ExecutionGuards initialized")
    except (ImportError, AttributeError, OSError) as e:
        log.error(f"Failed to init ExecutionGuards: {e}")

    # 3. Audit Journal
    try:
        from core.audit_journal import get_audit_journal

        audit = get_audit_journal(config)
        services["audit_journal"] = audit
        log.info("Execution hardening: AuditJournal initialized")
    except (ImportError, AttributeError, OSError) as e:
        log.error(f"Failed to init AuditJournal: {e}")

    # 4. Incident Alerting
    try:
        from core.incident_alerting import get_incident_alerting

        incident_alerts = get_incident_alerting(send_alert_fn, config)
        incident_alerts.start()
        services["incident_alerting"] = incident_alerts
        log.info("Execution hardening: IncidentAlerting initialized")
    except (ImportError, AttributeError, OSError) as e:
        log.error(f"Failed to init IncidentAlerting: {e}")

    # 5. Continuous Reconciliation
    try:
        from core.execution.continuous_reconciliation import start_continuous_reconciliation

        def on_reconciliation_issue(issue):
            log.error(f"Reconciliation issue: {issue.issue_type} - {issue.description}")
            if send_alert_fn:
                send_alert_fn(f"Reconciliation issue: {issue.issue_type}", True)

        reconcile_svc = start_continuous_reconciliation(broker_port, config)
        reconcile_svc._on_issue_callback = on_reconciliation_issue
        services["continuous_reconciliation"] = reconcile_svc
        log.info("Execution hardening: ContinuousReconciliation initialized")
    except (ImportError, AttributeError, OSError) as e:
        log.error(f"Failed to init ContinuousReconciliation: {e}")

    # 6. Market Data Fallback
    try:
        from core.market_data_fallback import get_market_data

        fallback_getter = None
        if config.get("market_data_secondary_enabled"):
            # Use Yahoo Finance as fallback if enabled
            from core.market_data_fallback import get_yahoo_price
            fallback_getter = get_yahoo_price

        market_data = get_market_data(
            primary_getter=get_price_fn,
            fallback_getter=fallback_getter,
            config=config
        )
        services["market_data"] = market_data
        log.info("Execution hardening: DualSourceMarketData initialized")
    except (ImportError, AttributeError, OSError) as e:
        log.error(f"Failed to init DualSourceMarketData: {e}")

    # 7. Exposure Limits
    try:
        from core.exposure_limits import get_exposure_limiter

        exposure = get_exposure_limiter(config)
        services["exposure_limits"] = exposure
        log.info("Execution hardening: ExposureConcentrationLimiter initialized")
    except (ImportError, AttributeError, OSError) as e:
        log.error(f"Failed to init ExposureConcentrationLimiter: {e}")

    # 8. Secret Hygiene (validation only)
    try:
        from core.secret_hygiene import get_secret_checker

        secret_checker = get_secret_checker(config)

        # Run startup check if enabled
        if config.get("SECRET_HYGIENE_SCAN_ON_STARTUP"):
            result = secret_checker.check_config(config)
            if not result.passed:
                log.warning(f"Secret hygiene: found {len(result.secrets_found)} potential exposures")
                for secret in result.secrets_found:
                    log.warning(f"  - {secret}")

        services["secret_checker"] = secret_checker
        log.info("Execution hardening: SecretHygieneChecker initialized")
    except (ImportError, AttributeError, OSError) as e:
        log.error(f"Failed to init SecretHygieneChecker: {e}")

    # 9. Startup Validation
    try:
        from core.startup_validation import run_startup_validation

        validation_passed = run_startup_validation()
        services["startup_validation"] = validation_passed

        if not validation_passed:
            log.error("Startup validation failed - continuing but may have issues")
    except (ImportError, AttributeError, OSError, ValueError) as e:
        log.error(f"Failed to run startup validation: {e}")
        services["startup_validation"] = False

    log.info(f"Execution hardening initialized: {len(services)} services")
    return services


def shutdown_execution_hardening(services: dict) -> None:
    """Shutdown all execution hardening services."""
    log.info("Shutting down execution hardening services...")

    if "incident_alerting" in services:
        try:
            services["incident_alerting"].stop()
        except (AttributeError, OSError) as e:
            log.error(f"Error stopping IncidentAlerting: {e}")

    if "continuous_reconciliation" in services:
        try:
            services["continuous_reconciliation"].stop()
        except (AttributeError, OSError) as e:
            log.error(f"Error stopping ContinuousReconciliation: {e}")

    log.info("Execution hardening shutdown complete")
