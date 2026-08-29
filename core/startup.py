"""Constitution System Startup — single-function bootstrapper for all 13 modules.

Wires up the complete Constitution v4.0 ecosystem at application startup:

  1. AI Governance Gate         — non-blocking identity registration
  2. 10 Original Constitution   — lazy-imported via run_constitution_checks
  3. Continuous Intelligence    — background compliance monitor
  4. Incident Command System    — automated incident detection & management
  5. ICS → Telegram Bridge      — real-time alert delivery (if credentials set)

Usage:
    from core.startup import startup_constitution_system

    # Called once at application boot after DI container is ready
    startup_constitution_system(cfg=config_dict)

Design:
- Fail-soft: all errors are logged; no exception reaches the caller.
- Idempotent: safe to call multiple times (singletons handle dedup).
- Config-respectful: respects ``CONSTITUTION_ENABLED``,
  ``CONSTITUTION_CHECK_INTERVAL_SECONDS`` keys from the config dict.
- Returns a dict with per-module initialization status for dashboard/telemetry.
"""

from __future__ import annotations

import logging
import time
from typing import Any

_log = logging.getLogger(__name__)

# ── Module keys ──────────────────────────────────────────────────────────────

AI_GATE_KEY = "ai_gate"
CONSTITUTION_CHECKS_KEY = "constitution_checks"
INTELLIGENCE_PIPELINE_KEY = "intelligence_pipeline"
INCIDENT_COMMANDER_KEY = "incident_commander"
ICS_TELEGRAM_BRIDGE_KEY = "ics_telegram_bridge"
ICS_SELF_HEALING_BRIDGE_KEY = "ics_self_healing_bridge"
SCORECARD_KEY = "scorecard"
V4_HEALTH_KEY = "v4_comprehensive_health"
CONSTITUTION_SELF_HEALING_KEY = "constitution_self_healing"
CONSTITUTION_ALERT_BRIDGE_KEY = "constitution_alert_bridge"


def _ok(status: str = "active", detail: str = "") -> dict[str, Any]:
    return {"status": status, "error": ""}


def _fail(error: str) -> dict[str, Any]:
    return {"status": "error", "error": error}


def _skip(reason: str = "disabled") -> dict[str, Any]:
    return {"status": "skipped", "error": reason}


def startup_constitution_system(
    cfg: dict[str, Any] | None = None,
    *,
    enable_ci_scheduler: bool = True,
) -> dict[str, Any]:
    """Initialize and wire the complete Constitution v4.0 system at boot.

    Safe to call multiple times — singleton factories handle dedup.
    All exceptions are caught and logged; no crash propagates to the caller.

    Args:
        cfg: Optional configuration dict. Supports keys:
            - ``CONSTITUTION_ENABLED`` (bool, default True) — master switch.
            - ``CONSTITUTION_CHECK_INTERVAL_SECONDS`` (int, default 3600) —
              interval between CI pipeline check cycles.
            - ``CONSTITUTION_INCIDENT_AUTO_DETECT`` (bool, default True).
            - ``CONSTITUTION_AUTO_SCORECARD`` (bool, default True).
        enable_ci_scheduler: If True (default), also start the background
            Continuous Intelligence Pipeline scheduler thread.

    Returns:
        A dict mapping module keys to their initialization status.
    """
    cfg = cfg or {}
    start_ts = time.time()

    results: dict[str, Any] = {}

    # Master switch
    if not cfg.get("CONSTITUTION_ENABLED", True):
        _log.info("[CONSTITUTION] Constitution system disabled by config")
        for key in (
            AI_GATE_KEY, CONSTITUTION_CHECKS_KEY, INTELLIGENCE_PIPELINE_KEY,
            INCIDENT_COMMANDER_KEY, ICS_TELEGRAM_BRIDGE_KEY, ICS_SELF_HEALING_BRIDGE_KEY,
            SCORECARD_KEY, CONSTITUTION_SELF_HEALING_KEY, CONSTITUTION_ALERT_BRIDGE_KEY,
            V4_HEALTH_KEY, "realestate_platform",
        ):
            results[key] = _skip("master switch off")
        results["_meta"] = {
            "duration_sec": round(time.time() - start_ts, 3),
            "enabled": False,
            "modules_initialized": 0,
            "modules_failed": 0,
        }
        return results

    # ── 1. AI Governance Gate ──────────────────────────────────────────────
    try:
        from core.constitution_ai_gate import get_gate
        gate = get_gate(identity="index_trader")
        ack = gate.acknowledge_constitution()
        results[AI_GATE_KEY] = _ok(detail=f"id={ack.get('identity', '?')}")
        _log.info("[CONSTITUTION] AI Governance Gate initialized")
    except Exception as exc:
        results[AI_GATE_KEY] = _fail(f"{type(exc).__name__}: {exc}")
        _log.warning("[CONSTITUTION] AI Governance Gate failed: %s", exc)

    # ── 2. Original 10 Constitution modules (health checks) ────────────────
    try:
        # Import lazily to avoid pulling in heavy deps at module level
        from scripts.run_constitution_checks import run_checks

        check_report = run_checks()
        results[CONSTITUTION_CHECKS_KEY] = _ok(
            detail=f"{check_report.passed}/{check_report.total} passed",
        )
        _log.info(
            "[CONSTITUTION] Module checks: %d/%d passed (%.1f%%)",
            check_report.passed,
            check_report.total,
            check_report.score_pct,
        )
    except Exception as exc:
        results[CONSTITUTION_CHECKS_KEY] = _fail(f"{type(exc).__name__}: {exc}")
        _log.warning("[CONSTITUTION] Module checks failed: %s", exc)

    # ── 3. Scorecard (optional) ────────────────────────────────────────────
    try:
        if cfg.get("CONSTITUTION_AUTO_SCORECARD", True):
            from scripts.constitution_scorecard import run_scorecard

            scorecard = run_scorecard()
            results[SCORECARD_KEY] = _ok(
                detail=f"{scorecard.overall_pct:.1f}% ({scorecard.total_passed}/{scorecard.total_requirements})",
            )
            _log.info(
                "[CONSTITUTION] Scorecard: %.1f%% (%d/%d)",
                scorecard.overall_pct,
                scorecard.total_passed,
                scorecard.total_requirements,
            )
        else:
            results[SCORECARD_KEY] = _skip("auto_scorecard disabled")
    except Exception as exc:
        results[SCORECARD_KEY] = _fail(f"{type(exc).__name__}: {exc}")
        _log.warning("[CONSTITUTION] Scorecard failed: %s", exc)

    # ── 4. Incident Command System ─────────────────────────────────────────
    try:
        from core.incident_command_system import get_incident_commander

        ics_config = {}
        if not cfg.get("CONSTITUTION_INCIDENT_AUTO_DETECT", True):
            ics_config["auto_detect"] = False
        if cfg.get("INCIDENTS_FILE"):
            ics_config["incidents_file"] = cfg["INCIDENTS_FILE"]

        commander = get_incident_commander(ics_config if ics_config else None)
        stats = commander.get_stats()
        results[INCIDENT_COMMANDER_KEY] = _ok(
            detail=f"open={stats['open_incidents']}, total={stats['total_incidents']}",
        )
        _log.info(
            "[CONSTITUTION] Incident Commander ready (%d open, %d total)",
            stats["open_incidents"],
            stats["total_incidents"],
        )
    except Exception as exc:
        results[INCIDENT_COMMANDER_KEY] = _fail(f"{type(exc).__name__}: {exc}")
        _log.warning("[CONSTITUTION] Incident Commander failed: %s", exc)

    # ── 5. Continuous Intelligence Pipeline ────────────────────────────────
    try:
        from core.continuous_intelligence import get_intelligence_pipeline

        interval = int(cfg.get(
            "CONSTITUTION_CHECK_INTERVAL_SECONDS",
            cfg.get("CONSTITUTION_CHECK_INTERVAL", 3600),
        ))

        pipeline = get_intelligence_pipeline(
            {"check_interval_seconds": max(60, interval)},
        )

        # Wire alert callback into the Incident Commander
        try:
            from core.incident_command_system import get_incident_commander as _get_ic
            pipeline.set_alert_fn(_get_ic()._send_alert)
        except Exception:
            pipeline.set_alert_fn(None)

        if enable_ci_scheduler:
            pipeline.start_scheduler()
            _log.info(
                "[CONSTITUTION] CI Pipeline scheduler started (interval=%ds)",
                interval,
            )
            detail = f"scheduler=active, interval={interval}s"
        else:
            detail = "scheduler=disabled"

        results[INTELLIGENCE_PIPELINE_KEY] = _ok(detail=detail)
    except Exception as exc:
        results[INTELLIGENCE_PIPELINE_KEY] = _fail(f"{type(exc).__name__}: {exc}")
        _log.warning("[CONSTITUTION] CI Pipeline failed: %s", exc)

    # ── 6. ICS → Telegram Alert Bridge ─────────────────────────────────────
    try:
        from core.ics_telegram_bridge import wire_ics_telegram_alerts

        active = wire_ics_telegram_alerts()
        results[ICS_TELEGRAM_BRIDGE_KEY] = _ok(
            detail="active" if active else "passive (no credentials)",
        )
        if active:
            _log.info("[CONSTITUTION] ICS → Telegram alerts ACTIVE")
        else:
            _log.info("[CONSTITUTION] ICS → Telegram alerts passive (no credentials)")
    except Exception as exc:
        results[ICS_TELEGRAM_BRIDGE_KEY] = _fail(f"{type(exc).__name__}: {exc}")
        _log.warning("[CONSTITUTION] ICS → Telegram bridge failed: %s", exc)

    # ── 7. ICS → Self-Healing Bridge ────────────────────────────────────────
    try:
        from core.ics_self_healing_bridge import wire_ics_self_healing

        wired = wire_ics_self_healing()
        results[ICS_SELF_HEALING_BRIDGE_KEY] = _ok(
            detail="wired" if wired else "failed (components not ready)",
        )
        if wired:
            _log.info("[CONSTITUTION] ICS ↔ Self-Healing bridge ACTIVE")
        else:
            _log.info(
                "[CONSTITUTION] ICS ↔ Self-Healing bridge not wired "
                "(IncidentCommander/SelfHealingOrchestrator not available)",
            )
    except Exception as exc:
        results[ICS_SELF_HEALING_BRIDGE_KEY] = _fail(f"{type(exc).__name__}: {exc}")
        _log.warning("[CONSTITUTION] ICS ↔ Self-Healing bridge failed: %s", exc)

    # ── 8. Constitution Self-Healing Bridge ───────────────────────────────
    try:
        from core.constitution_self_healing_bridge import wire_constitution_self_healing
        wired = wire_constitution_self_healing()
        results[CONSTITUTION_SELF_HEALING_KEY] = _ok(
            detail="wired" if wired else "patterns registered",
        )
        if wired:
            _log.info("[CONSTITUTION] Constitution ↔ Self-Healing bridge ACTIVE")
    except Exception as exc:
        results[CONSTITUTION_SELF_HEALING_KEY] = _fail(f"{type(exc).__name__}: {exc}")
        _log.warning("[CONSTITUTION] Constitution self-healing bridge failed: %s", exc)

    # ── 9. Constitution Alert Bridge ───────────────────────────────────────
    try:
        if cfg.get("CONSTITUTION_ALERT_BRIDGE_ENABLED", True):
            from core.constitution_alert_bridge import get_constitution_alert_bridge
            bridge = get_constitution_alert_bridge({
                "check_interval_seconds": max(
                    60, int(cfg.get("CONSTITUTION_ALERT_INTERVAL", 3600))
                ),
                "health_warn_threshold": float(
                    cfg.get("CONSTITUTION_WARN_THRESHOLD", 7.0)
                ),
                "health_crit_threshold": float(
                    cfg.get("CONSTITUTION_CRIT_THRESHOLD", 5.0)
                ),
            })
            bridge.start_scheduler()
            results[CONSTITUTION_ALERT_BRIDGE_KEY] = _ok(
                detail="scheduler=active",
            )
            _log.info("[CONSTITUTION] Alert bridge scheduler started")
        else:
            results[CONSTITUTION_ALERT_BRIDGE_KEY] = _skip("alert bridge disabled by config")
    except Exception as exc:
        results[CONSTITUTION_ALERT_BRIDGE_KEY] = _fail(f"{type(exc).__name__}: {exc}")
        _log.warning("[CONSTITUTION] Alert bridge failed: %s", exc)

    # ── 10. Architecture Standard Modules (v2.57 lazy init) ────────────────
    try:
        if cfg.get("INIT_ARCHITECTURE_STANDARDS", True):
            # Lazy-init all architecture standard modules to ensure they're
            # registered in the DI container and ready for dashboard queries.
            from core.feature_flags import get_feature_flag_manager
            get_feature_flag_manager()

            from core.event_bus import get_event_bus
            get_event_bus()

            from core.plugin_registry import get_plugin_registry
            get_plugin_registry()

            from core.secrets_vault import get_secrets_vault
            get_secrets_vault()

            from core.enterprise_evolution import get_evolution_engine
            get_evolution_engine()

            from core.event_sourcing import get_event_store
            get_event_store()

            from core.distributed_tracing import get_tracer
            get_tracer()

            from core.threat_intel import get_threat_intel
            get_threat_intel()

            from core.vulnerability_scanner import get_vulnerability_scanner
            get_vulnerability_scanner()

            _log.info("[CONSTITUTION] Architecture Standard modules initialized")
    except Exception as exc:
        _log.warning("[CONSTITUTION] Architecture Standard init failed: %s", exc)

    # ── 10. Initial health check cycle (non-blocking) ────────────────────────
    try:
        if results.get(INCIDENT_COMMANDER_KEY, {}).get("status") == "active":
            from core.incident_command_system import get_incident_commander

            ic = get_incident_commander()
            if ic._cfg.auto_detect:
                cycle_result = ic.run_detection_cycle()
                _log.info(
                    "[CONSTITUTION] Initial detection cycle: %d created, %d resolved",
                    cycle_result.get("created", 0),
                    cycle_result.get("resolved", 0),
                )
    except Exception as exc:
        _log.warning("[CONSTITUTION] Initial detection cycle failed: %s", exc)

    # ── 11. v4.0 Comprehensive Health Check ────────────────────────────────
    try:
        from core.constitution import get_validator
        validator = get_validator()
        health = validator.comprehensive_health_check()
        results[V4_HEALTH_KEY] = _ok(
            detail=(
                f"overall={health['overall_score']}, "
                f"layers={health['enterprise_layers']['count']}, "
                f"gates={health['quality_gates']['count']}, "
                f"principles={health['engineering_principles']['count']}, "
                f"arch_standards={health['architecture_standards']['count']}, "
                f"security={health['security_governance']['count']}, "
                f"platform={health['platform_engineering']['count']}, "
                f"sre={health['sre_reliability']['count']}, "
                f"roles={health['ai_specialist_roles']['count']}, "
                f"dod_items={health['definition_of_done']['items']}, "
                f"lifecycle_phases={health['continuous_lifecycle']['phases']}"
            ),
        )
        _log.info(
            "[CONSTITUTION] v4.0 Health: overall=%.2f, %d layers, %d gates, "
            "%d principles, %d arch, %d security, %d platform, %d SRE",
            health["overall_score"],
            health["enterprise_layers"]["count"],
            health["quality_gates"]["count"],
            health["engineering_principles"]["count"],
            health["architecture_standards"]["count"],
            health["security_governance"]["count"],
            health["platform_engineering"]["count"],
            health["sre_reliability"]["count"],
        )
    except Exception as exc:
        results["v4_comprehensive_health"] = _fail(f"{type(exc).__name__}: {exc}")
        _log.warning("[CONSTITUTION] v4.0 Health check failed: %s", exc)

    # ── 12. Real Estate Platform (Archived / Disabled) ────────────────────
    results["realestate_platform"] = _skip("disabled by config (trading core focus)")

    # ── Summary ────────────────────────────────────────────────────────────
    modules_count = len(results) - 1  # exclude _meta
    init_count = sum(
        1 for v in results.values()
        if isinstance(v, dict) and v.get("status") in ("active",)
    )
    fail_count = sum(
        1 for v in results.values()
        if isinstance(v, dict) and v.get("status") == "error"
    )
    results["_meta"] = {
        "duration_sec": round(time.time() - start_ts, 3),
        "enabled": True,
        "modules_initialized": init_count,
        "modules_failed": fail_count,
    }

    _log.info(
        "[CONSTITUTION] Startup complete: %d/%d initialized, %d failed (%.2fs)",
        init_count,
        modules_count,
        fail_count,
        results["_meta"]["duration_sec"],
    )
    return results


__all__ = [
    "startup_constitution_system",
]
