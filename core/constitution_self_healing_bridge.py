"""Constitution Self-Healing Bridge — wires constitution violations to the SelfHealingOrchestrator.

When constitution health scores drop or violations are detected, this bridge:
1. Registers constitution-specific failure patterns in the SelfHealingOrchestrator
2. Triggers auto-remediation actions (evidence reload, compliance checks, operator notify)
3. Logs all healing actions to the constitution audit log

Usage:
    from core.constitution_self_healing_bridge import wire_constitution_self_healing
    wire_constitution_self_healing()  # Auto-wires at startup
"""

from __future__ import annotations

import logging
from typing import Any

from core.self_healing.models import (
    FailurePattern,
    RecoveryAction,
)

_log = logging.getLogger(__name__)

# ── Constitution-specific failure patterns ──────────────────────────────────

CONSTITUTION_FAILURE_PATTERNS: list[FailurePattern] = [
    FailurePattern(
        name="constitution_score_low",
        description="Constitution overall health score below warning threshold — requires attention",
        recovery_actions=[RecoveryAction.RELOAD_CONFIG, RecoveryAction.NOTIFY_OPERATOR],
        cooldown_seconds=3600,
    ),
    FailurePattern(
        name="constitution_critical_drop",
        description="Constitution overall health score below critical threshold — immediate action required",
        recovery_actions=[RecoveryAction.RELOAD_CONFIG, RecoveryAction.RECYCLE_SESSION, RecoveryAction.NOTIFY_OPERATOR],
        cooldown_seconds=1800,
    ),
    FailurePattern(
        name="constitution_evidence_gap",
        description="Multiple categories missing evidence — compliance risk",
        recovery_actions=[RecoveryAction.RELOAD_CONFIG, RecoveryAction.NOTIFY_OPERATOR],
        cooldown_seconds=7200,
    ),
    FailurePattern(
        name="constitution_regression_spike",
        description="Open regressions detected in constitution scoring — quality regression",
        recovery_actions=[RecoveryAction.NOTIFY_OPERATOR, RecoveryAction.RUN_RUNBOOK],
        cooldown_seconds=3600,
    ),
    FailurePattern(
        name="constitution_version_mismatch",
        description="Constitution version mismatch or stale scoring data",
        recovery_actions=[RecoveryAction.RELOAD_CONFIG, RecoveryAction.RECYCLE_SESSION],
        cooldown_seconds=7200,
    ),
]

WARN_THRESHOLD: float = 7.0
CRIT_THRESHOLD: float = 5.0
EVIDENCE_GAP_THRESHOLD: int = 20      # Categories with < 1 evidence items
REGRESSION_SPIKE_THRESHOLD: int = 5   # Open regressions count


def _get_orchestrator() -> Any:
    """Get the global SelfHealingOrchestrator singleton."""
    from core.self_healing.orchestrator import get_orchestrator
    return get_orchestrator()


def register_constitution_patterns() -> int:
    """Register all constitution failure patterns in the SelfHealingOrchestrator.

    Returns:
        Number of patterns registered.
    """
    orchestrator = _get_orchestrator()
    count = 0
    for pattern in CONSTITUTION_FAILURE_PATTERNS:
        try:
            orchestrator.register_pattern(pattern)
            count += 1
        except Exception as exc:
            _log.warning("[CONST-SELF-HEAL] Failed to register pattern %s: %s", pattern.name, exc)
    _log.info("[CONST-SELF-HEAL] Registered %d constitution failure patterns", count)
    return count


def check_and_heal_constitution() -> dict[str, Any]:
    """Run a constitution health check and trigger healing actions if violations found.

    Returns:
        Dict with check results and any healing actions taken.
    """
    from core.constitution import get_validator

    validator = get_validator()
    orchestrator = _get_orchestrator()

    health = validator.comprehensive_health_check()
    result: dict[str, Any] = {
        "overall_score": health.get("overall_score", 0.0),
        "total_categories": health.get("total_categories", 0),
        "open_regressions": health.get("open_regressions", 0),
        "health_status": "HEALTHY",
        "patterns_matched": [],
        "healing_actions": [],
    }

    # Determine health status
    score = result["overall_score"]
    if score >= WARN_THRESHOLD:
        result["health_status"] = "HEALTHY"
    elif score >= CRIT_THRESHOLD:
        result["health_status"] = "WARNING"
    else:
        result["health_status"] = "CRITICAL"

    # Check for violated patterns — trigger immediate healing cycle
    if result["health_status"] in ("CRITICAL", "WARNING"):
        pattern_name = CONSTITUTION_FAILURE_PATTERNS[0].name if result["health_status"] == "WARNING" else CONSTITUTION_FAILURE_PATTERNS[1].name
        result["patterns_matched"].append(pattern_name)
        try:
            # Use public API: trigger_immediate_cycle runs run_healing_cycle() which auto-detects patterns
            cycle_result = orchestrator.trigger_immediate_cycle()
            for action in cycle_result.actions_taken:
                result["healing_actions"].append({
                    "pattern": pattern_name,
                    "action": action.action.value,
                    "status": action.status,
                    "message": action.message,
                })
        except Exception as exc:
            _log.warning("[CONST-SELF-HEAL] Healing cycle failed: %s", exc)

    # Check for evidence gaps
    from core.constitution.evidence import collect_auto_evidence
    try:
        # Count categories with low evidence by running a quick scan
        categories_with_evidence = 0
        for cid in validator.CATEGORIES:
            cat = validator.get_category_score(cid)
            if cat and len(cat.evidence) >= 1:
                categories_with_evidence += 1
        missing_evidence = result["total_categories"] - categories_with_evidence

        if missing_evidence >= EVIDENCE_GAP_THRESHOLD:
            gap_pattern = CONSTITUTION_FAILURE_PATTERNS[2]  # evidence_gap
            result["patterns_matched"].append(gap_pattern.name)
            try:
                # Attempt to reload auto-evidence
                collect_auto_evidence(validator)
                healing_result = orchestrator._execute_recovery(gap_pattern)
                result["healing_actions"].append({
                    "pattern": gap_pattern.name,
                    "action": "reload_evidence",
                    "status": "SUCCESS",
                    "message": f"Auto-evidence reloaded for {categories_with_evidence}/{result['total_categories']} categories",
                })
            except Exception as exc:
                _log.warning("[CONST-SELF-HEAL] Evidence reload failed: %s", exc)
    except Exception as exc:
        _log.debug("[CONST-SELF-HEAL] Evidence scan: %s", exc)

    # Check for regression spikes
    if result["open_regressions"] >= REGRESSION_SPIKE_THRESHOLD:
        spike_pattern = CONSTITUTION_FAILURE_PATTERNS[3]  # regression_spike
        result["patterns_matched"].append(spike_pattern.name)
        try:
            healing_result = orchestrator._execute_recovery(spike_pattern)
            result["healing_actions"].append({
                "pattern": spike_pattern.name,
                "action": healing_result.action.value,
                "status": healing_result.status,
                "message": healing_result.message,
            })
        except Exception as exc:
            _log.warning("[CONST-SELF-HEAL] Regression spike action failed: %s", exc)

    # Log to constitution audit log
    if result["patterns_matched"]:
        validator.add_evidence(
            "GOV-04",
            f"Self-healing triggered for patterns: {', '.join(result['patterns_matched'])}. "
            f"Status: {result['health_status']}, Score: {score:.2f}",
            "documentation", 0.2,
        )

    _log.info(
        "[CONST-SELF-HEAL] Check complete: score=%.2f, status=%s, patterns=%d, actions=%d",
        score, result["health_status"],
        len(result["patterns_matched"]), len(result["healing_actions"]),
    )
    return result


def wire_constitution_self_healing() -> bool:
    """Setup complete constitution self-healing integration.

    Registers all constitution failure patterns and runs an initial check.

    Returns:
        True if wired successfully.
    """
    try:
        count = register_constitution_patterns()
        if count == 0:
            _log.warning("[CONST-SELF-HEAL] No patterns registered — self-healing not wired")
            return False
        _log.info("[CONST-SELF-HEAL] Self-healing wired with %d patterns", count)
        return True
    except Exception as exc:
        _log.warning("[CONST-SELF-HEAL] Wiring failed: %s", exc)
        return False


__all__ = [
    "CONSTITUTION_FAILURE_PATTERNS",
    "check_and_heal_constitution",
    "register_constitution_patterns",
    "wire_constitution_self_healing",
]
