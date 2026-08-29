"""ICS-Self-Healing Bridge — connects Incident Commander incidents to automated recovery.

Completes the autonomous loop:

    Detect ──→ Heal ──→ Resolve ──→ Learn
      │            │          │         │
      │            ▼          │         │
      │   Self-Healing       │         │
      │   Orchestrator       │         │
      │   attempts recovery   │         │
      ▼                      ▼         ▼
  Incident             Auto-resolve   Audit log
  Commander            on success     +

Bidirectional wiring (both hooks installed automatically):
  **Incident → Healing:** When an incident is created via the commander's
  alert callback, the bridge triggers the orchestrator to attempt recovery.

  **Healing → Incident:** Every healing cycle result is automatically
  processed — recovery successes auto-resolve corresponding incidents,
  failures create/escalate incidents.

Usage:
    from core.ics_self_healing_bridge import wire_ics_self_healing

    wire_ics_self_healing()  # Auto-wires both sides

Design:
- Thread-safe with RLock
- Idempotent — safe to call wire() multiple times
- Fail-soft — all errors are logged, never crash
- Chains with existing callbacks (Telegram bridge, etc.)
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

_log = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

# Mapping of failure pattern names to incident source names
PATTERN_TO_INCIDENT_SOURCE: dict[str, str] = {
    "circuit_breaker_open": "circuit_breaker",
    "broker_disconnected": "broker",
    "stale_market_feed": "market_feed",
    "database_connection": "database",
    "config_corruption": "configuration",
    "hard_halt_stuck": "safety_system",
    "watchdog_timeout": "watchdog",
    "disk_space_low": "system_resources",
    "wal_lag": "database",
    "stale_locks": "system_resources",
    "auth_expiry": "authentication",
    "network_jitter": "network",
    "split_brain": "consensus",
}

# Recovery action → incident source mapping
RECOVERY_TO_SOURCE: dict[str, str] = {
    "reset_circuit_breaker": "circuit_breaker",
    "reconnect_broker": "broker",
    "restart_stale_feed": "market_feed",
    "reconnect_database": "database",
    "reload_config": "configuration",
    "clear_hard_halt": "safety_system",
    "restart_watchdog": "watchdog",
    "disk_cleanup": "system_resources",
    "force_wal_checkpoint": "database",
    "clear_stale_locks": "system_resources",
    "recycle_session": "trading_engine",
    "notify_operator": "operator",
    "run_runbook": "runbook",
}


# ── ICS Self-Healing Bridge ─────────────────────────────────────────────────


class ICSSelfHealingBridge:
    """Bidirectional bridge between Incident Commander and Self-Healing Orchestrator.

    When an incident is created, the bridge triggers the orchestrator to
    attempt automated recovery. When the orchestrator detects a failure
    and attempts recovery, the bridge creates/updates incidents and
    auto-resolves on success.

    Args:
        enabled: Whether the bridge is active (default True).
    """

    def __init__(self, enabled: bool = True) -> None:
        self._enabled = enabled
        self._lock = threading.RLock()
        self._wired: bool = False
        self._commander: Any = None  # IncidentCommander instance
        self._orchestrator: Any = None  # SelfHealingOrchestrator instance
        self._handler_history: list[dict[str, Any]] = []
        self._max_history: int = 200
        # Stored original callback references for unwiring
        self._original_notify_fn: Any = None
        self._original_run_healing: Any = None

    # ── Properties ────────────────────────────────────────────────────────

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def is_wired(self) -> bool:
        return self._wired

    @property
    def commander(self) -> Any:
        return self._commander

    @property
    def orchestrator(self) -> Any:
        return self._orchestrator

    # ── Wiring ────────────────────────────────────────────────────────────

    def wire(
        self,
        commander: Any,
        orchestrator: Any,
    ) -> bool:
        """Wire the bridge between an IncidentCommander and SelfHealingOrchestrator.

        Installs two auto-hooks:
        1. Hooks into the orchestrator's healing cycle to auto-process results.
        2. Hooks into the commander's alert callback to trigger healing on incidents.

        Args:
            commander: IncidentCommander instance.
            orchestrator: SelfHealingOrchestrator instance.

        Returns:
            True if wired successfully.
        """
        if not self._enabled:
            _log.info("[ICS_SELF_HEAL] Bridge disabled — not wiring")
            return False

        with self._lock:
            if self._wired:
                return True  # Already wired

            self._commander = commander
            self._orchestrator = orchestrator

            # ── Hook 1: Auto-process healing cycle results ─────────────
            # Wrap the orchestrator's run_healing_cycle so every cycle
            # automatically calls process_healing_result()
            self._original_run_healing = orchestrator.run_healing_cycle

            def _wrapped_healing_cycle() -> Any:
                result = self._original_run_healing()
                try:
                    self.process_healing_result(result)
                except Exception as _wrap_exc:
                    _log.debug(
                        "[ICS_SELF_HEAL] Auto-process healing result: %s",
                        _wrap_exc,
                    )
                return result

            orchestrator.run_healing_cycle = _wrapped_healing_cycle  # type: ignore[method-assign]

            # ── Hook 2: Incident → Healing via alert callback ─────────
            # Chain into the commander's alert callback so new incidents
            # trigger healing
            original_alert_fn = None
            try:
                if hasattr(commander, "_alert_fn"):
                    original_alert_fn = commander._alert_fn
            except Exception:
                pass

            def _incident_alert_handler(message: str, is_critical: bool) -> None:
                """Chained alert handler: trigger healing, then call original."""
                # Step 1: Trigger healing for this incident
                if is_critical:
                    try:
                        # Look up open incidents that match this message
                        self._trigger_healing_for_message(message)
                    except Exception as _h_exc:
                        _log.debug(
                            "[ICS_SELF_HEAL] Incident→healing trigger: %s",
                            _h_exc,
                        )

                # Step 2: Chain to the original alert callback (e.g., Telegram bridge)
                if original_alert_fn:
                    try:
                        original_alert_fn(message, is_critical)
                    except Exception as _o_exc:
                        _log.debug(
                            "[ICS_SELF_HEAL] Chained alert callback: %s",
                            _o_exc,
                        )

            commander.set_alert_fn(_incident_alert_handler)

            # ── Also set the orchestrator's notification handler ────────
            self._original_notify_fn = None
            try:
                if hasattr(orchestrator, "_notify_fn"):
                    self._original_notify_fn = orchestrator._notify_fn
            except Exception:
                pass
            orchestrator.set_notify_fn(self._orchestrator_alert_handler)

            self._wired = True
            _log.info(
                "[ICS_SELF_HEAL] Bridge wired: ICS ↔ Self-Healing Orchestrator "
                "(auto-heal on incident, auto-resolve on recovery)",
            )
            return True

    def unwire(self) -> None:
        """Remove all wiring and restore originals."""
        with self._lock:
            if not self._wired:
                return
            try:
                # Restore original run_healing_cycle
                if self._orchestrator and self._original_run_healing:
                    self._orchestrator.run_healing_cycle = self._original_run_healing
                # Restore original notify_fn
                if self._orchestrator:
                    self._orchestrator.set_notify_fn(self._original_notify_fn)
                # Clear commander alert callback (don't restore — we can't know
                # if the original caller also wired it; the caller should re-wire)
                if self._commander:
                    # Clear the alert callback (original was captured in closure)
                    try:
                        self._commander.set_alert_fn(None)
                    except Exception:
                        pass
            except Exception as exc:
                _log.debug("[ICS_SELF_HEAL] Unwire: %s", exc)
            self._commander = None
            self._orchestrator = None
            self._original_notify_fn = None
            self._original_run_healing = None
            self._wired = False
            _log.info("[ICS_SELF_HEAL] Bridge unwired")

    # ── Orchestrator alert handler ─────────────────────────────────────────

    def _orchestrator_alert_handler(self, message: str) -> None:
        """Called by the Self-Healing Orchestrator when it sends an alert.

        Creates an incident in the Incident Commander.
        """
        if not self._enabled or not self._commander:
            return

        try:
            lines = message.split("\n")
            description = lines[-1] if len(lines) > 1 else message
            source = self._match_component(description)

            self._commander.create_incident(
                title=f"Self-healing alert: {description[:60]}",
                description=description[:300],
                source=source,
                severity="HIGH",
                detected_by="self_healing_bridge",
                affected_modules=[source] if source != "unknown" else [],
            )
        except Exception as exc:
            _log.warning("[ICS_SELF_HEAL] Alert handler failed: %s", exc)

    # ── Process healing cycle results ──────────────────────────────────────

    def process_healing_result(self, result: Any) -> dict[str, Any]:
        """Process the result of a self-healing cycle.

        Successes → auto-resolve corresponding incidents.
        Failures → create/escalate incidents.
        Called automatically after every healing cycle via Hook 1.

        Args:
            result: A HealingCycleResult from SelfHealingOrchestrator.run_healing_cycle().

        Returns:
            Dict with summary of actions taken.
        """
        if not self._enabled or not self._commander:
            return {"created": 0, "resolved": 0, "escalated": 0}

        created = 0
        resolved = 0
        escalated = 0

        try:
            actions = []
            if hasattr(result, "actions_taken"):
                actions = result.actions_taken
            elif isinstance(result, dict):
                actions = result.get("actions_taken", result.get("actions", []))

            for action in actions:
                action_name = self._get_action_name(action)
                component = self._get_action_component(action)
                status = self._get_action_status(action)
                message = self._get_action_message(action)
                source = RECOVERY_TO_SOURCE.get(action_name, component)

                if status == "SUCCESS":
                    resolved += self._resolve_incident_for_component(
                        source,
                        f"Auto-resolved by self-healing: {message}",
                    )
                elif status == "FAILED":
                    inc = self._commander.create_incident(
                        title=f"Recovery failed: {action_name} on {component}",
                        description=f"Self-healing recovery failed "
                                    f"on {component}: {message[:200]}",
                        source=source,
                        severity="CRITICAL",
                        detected_by="self_healing_bridge",
                        affected_modules=[source],
                    )
                    if inc:
                        created += 1
                        escalated += 1

                self._record_handler_event(action_name, component, status, message)

        except Exception as exc:
            _log.error("[ICS_SELF_HEAL] Process healing result failed: %s", exc)

        return {"created": created, "resolved": resolved, "escalated": escalated}

    def _resolve_incident_for_component(self, source: str, notes: str) -> int:
        """Resolve all open incidents matching a source component."""
        resolved = 0
        try:
            incidents = self._commander.get_open_incidents()
            for inc in incidents:
                if inc.get("source") == source:
                    self._commander.resolve_incident(inc["incident_id"], notes)
                    resolved += 1
        except Exception as exc:
            _log.debug("[ICS_SELF_HEAL] Resolve incidents: %s", exc)
        return resolved

    # ── Incident-triggered healing ─────────────────────────────────────────

    def _trigger_healing_for_message(self, message: str) -> None:
        """Trigger healing for an incident alert message.

        Called automatically by the chained alert handler (Hook 2).
        Matches the message to a component and runs a healing cycle.
        """
        if not self._enabled or not self._orchestrator:
            return

        source = self._match_component(message)
        if source == "unknown":
            return

        try:
            result = self._orchestrator.trigger_immediate_cycle()
            # Auto-processing happens via Hook 1 (wrapped run_healing_cycle),
            # but trigger_immediate_cycle calls run_healing_cycle which is already wrapped.
            _log.debug(
                "[ICS_SELF_HEAL] Healing triggered for %s: %s",
                source,
                getattr(result, "summary", "done"),
            )
        except Exception as exc:
            _log.warning("[ICS_SELF_HEAL] Trigger healing for %s failed: %s", source, exc)

    def trigger_healing_for_incident(self, incident: dict[str, Any] | None) -> dict[str, Any]:
        """Trigger the self-healing orchestrator for a specific incident.

        Called when a new incident is created — attempts automated recovery
        for the affected component.

        Args:
            incident: The incident dict (from Incident.to_dict()).

        Returns:
            Dict with healing result summary.
        """
        if not self._enabled or not self._orchestrator:
            return {"healing_triggered": False, "reason": "Bridge not active"}

        if incident is None:
            return {"healing_triggered": False, "reason": "No incident provided"}

        incident.get("source", "unknown")
        severity = str(incident.get("severity", "LOW"))

        if severity not in ("CRITICAL", "HIGH"):
            return {"healing_triggered": False, "reason": f"Severity {severity} too low"}

        try:
            result = self._orchestrator.trigger_immediate_cycle()
            # Auto-processing is handled by the wrapped run_healing_cycle (Hook 1)
            return {
                "healing_triggered": True,
                "healing_result": {
                    "n_actions": getattr(result, "n_actions", 0),
                    "n_success": getattr(result, "n_success", 0),
                    "n_failed": getattr(result, "n_failed", 0),
                    "summary": getattr(result, "summary", ""),
                },
            }
        except Exception as exc:
            _log.warning("[ICS_SELF_HEAL] Trigger healing failed: %s", exc)
            return {"healing_triggered": False, "reason": str(exc)}

    # ── Internal helpers ───────────────────────────────────────────────────

    def _get_action_name(self, action: Any) -> str:
        if hasattr(action, "action"):
            val = action.action
            return val.value if hasattr(val, "value") else str(val)
        if isinstance(action, dict):
            return action.get("action", action.get("name", "unknown"))
        return str(action)

    def _get_action_component(self, action: Any) -> str:
        if hasattr(action, "component"):
            return action.component
        if isinstance(action, dict):
            return action.get("component", "unknown")
        return "unknown"

    def _get_action_status(self, action: Any) -> str:
        if hasattr(action, "status"):
            return action.status
        if isinstance(action, dict):
            return action.get("status", "UNKNOWN")
        return "UNKNOWN"

    def _get_action_message(self, action: Any) -> str:
        if hasattr(action, "message"):
            return action.message
        if isinstance(action, dict):
            return action.get("message", action.get("details", ""))
        return ""

    def _match_component(self, text: str) -> str:
        """Try to match a text description to a known component name."""
        if not text:
            return "unknown"
        lower = text.lower()
        for pattern, source in PATTERN_TO_INCIDENT_SOURCE.items():
            if pattern.replace("_", " ") in lower:
                return source
            if pattern in lower:
                return source
        keyword_map: dict[str, str] = {
            "broker": "broker", "kite": "broker", "angel": "broker",
            "circuit": "circuit_breaker",
            "database": "database",
            "disk": "system_resources", "space": "system_resources",
            "wal": "database",
            "config": "configuration",
            "token": "authentication", "auth": "authentication",
            "network": "network",
            "feed": "market_feed", "market": "market_feed",
        }
        for keyword, source in keyword_map.items():
            if keyword in lower:
                return source
        return "unknown"

    def _record_handler_event(
        self, action_name: str, component: str, status: str, message: str,
    ) -> None:
        event = {
            "timestamp": time.time(),
            "action": action_name,
            "component": component,
            "status": status,
            "message": message[:100],
        }
        with self._lock:
            self._handler_history.append(event)
            if len(self._handler_history) > self._max_history:
                self._handler_history = self._handler_history[-self._max_history:]

    # ── Query ─────────────────────────────────────────────────────────────

    def get_stats(self) -> dict[str, Any]:
        """Get bridge statistics."""
        with self._lock:
            n_events = len(self._handler_history)
            n_success = sum(1 for e in self._handler_history if e["status"] == "SUCCESS")
            n_failed = sum(1 for e in self._handler_history if e["status"] == "FAILED")
            return {
                "enabled": self._enabled,
                "wired": self._wired,
                "total_events": n_events,
                "success_count": n_success,
                "failed_count": n_failed,
                "commander_available": self._commander is not None,
                "orchestrator_available": self._orchestrator is not None,
            }

    def get_history(self, limit: int = 20) -> list[dict[str, Any]]:
        """Get recent bridge event history."""
        with self._lock:
            return list(reversed(self._handler_history))[:limit]


# ── Singleton ────────────────────────────────────────────────────────────────

_bridge: ICSSelfHealingBridge | None = None
_bridge_lock = threading.RLock()


def get_ics_self_healing_bridge() -> ICSSelfHealingBridge:
    """Get or create the singleton ICSSelfHealingBridge."""
    global _bridge
    if _bridge is None:
        with _bridge_lock:
            if _bridge is None:
                _bridge = ICSSelfHealingBridge()
    return _bridge


def reset_ics_self_healing_bridge() -> None:
    """Reset the singleton (for testing)."""
    global _bridge
    with _bridge_lock:
        if _bridge is not None:
            _bridge.unwire()
            _bridge = None


def wire_ics_self_healing() -> bool:
    """Convenience function to wire ICS ↔ Self-Healing.

    Resolves singletons for IncidentCommander and SelfHealingOrchestrator
    and wires them together via the bridge.

    Returns:
        True if wired successfully, False if components not available.
    """
    try:
        bridge = get_ics_self_healing_bridge()

        from core.incident_command_system import get_incident_commander
        from core.self_healing.orchestrator import get_orchestrator

        commander = get_incident_commander()
        orchestrator = get_orchestrator()

        return bridge.wire(commander, orchestrator)
    except Exception as exc:
        _log.warning("[ICS_SELF_HEAL] Auto-wire failed: %s", exc)
        return False


__all__ = [
    "ICSSelfHealingBridge",
    "PATTERN_TO_INCIDENT_SOURCE",
    "RECOVERY_TO_SOURCE",
    "get_ics_self_healing_bridge",
    "reset_ics_self_healing_bridge",
    "wire_ics_self_healing",
]
