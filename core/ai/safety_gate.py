"""
AI Safety Gate (Phase 9).

Enforces that AI can ONLY:
  - Score signals
  - Rank strategies
  - Optimize parameters
  - Recommend actions

AI can NEVER:
  - Place orders directly
  - Override risk limits (MAX_DAILY_LOSS, MAX_DRAWDOWN, SL_PCT, etc.)
  - Bypass safety controls (_trip_hard_halt, expiry_entry_allowed, etc.)
  - Modify risk configuration at runtime
  - Disable circuit breakers or hard halt

Risk Engine remains the FINAL AUTHORITY for all execution decisions.

Usage
-----
    from core.ai.safety_gate import AISafetyGate, AISafetyVerdict

    gate = AISafetyGate()
    verdict = gate.check_action(
        action_type="place_order",
        params={"symbol": "NIFTY", "qty": 50},
        source="ai_agent",
    )
    if not verdict.allowed:
        print(f"BLOCKED: {verdict.reason}")
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)


# ── Definitions of forbidden actions ────────────────────────────────────────

# Categories of actions that AI is NEVER allowed to perform
FORBIDDEN_ACTIONS: dict[str, str] = {
    "place_order": "AI cannot place orders - use RiskService + ExecutionPort",
    "modify_risk_limit": "AI cannot modify risk limits - hard-coded in safety_state",
    "disable_hard_halt": "AI cannot disable hard halt - safety mechanism",
    "bypass_circuit_breaker": "AI cannot bypass circuit breaker - market safety",
    "override_position_size": "AI cannot override position sizing - RiskService authority",
    "change_sl_pct": "AI cannot change stop-loss percentage - risk parameter",
    "change_target_pct": "AI cannot change target percentage - risk parameter",
    "disable_expiry_gate": "AI cannot disable expiry entry gate - risk control",
    "modify_config": "AI cannot modify runtime config - operator action",
    "execute_trade": "AI cannot execute trades - execution port only",
}

# Risk keys that AI can NEVER modify
PROTECTED_RISK_KEYS: set[str] = {
    "MAX_DAILY_LOSS",
    "MAX_DRAWDOWN",
    "SL_PCT",
    "TARGET_PCT",
    "TRAIL_PCT",
    "PORTFOLIO_MAX_SL_RISK_PCT",
    "MAX_OPEN_POSITIONS",
    "MAX_CONSECUTIVE_LOSSES",
}

# Actions that AI IS allowed to perform (score/rank/optimize/recommend only)
ALLOWED_ACTIONS: set[str] = {
    "score_signal",
    "rank_strategies",
    "optimize_parameter",
    "recommend_entry",
    "recommend_exit",
    "suggest_adjustment",
    "classify_regime",
    "predict_probability",
    "generate_narrative",
    "analyze_risk",
}


@dataclass
class AISafetyVerdict:
    """Result of an AI safety check."""

    allowed: bool
    action_type: str = ""
    reason: str = ""
    source: str = ""
    suggested_action: str = ""
    failures: list[str] = field(default_factory=list)
    timestamp: float = 0.0

    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.time()

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "action_type": self.action_type,
            "reason": self.reason,
            "source": self.source,
            "suggested_action": self.suggested_action,
            "timestamp": self.timestamp,
        }


class AISafetyGate:
    """
    Safety gate that enforces AI restrictions.

    Every AI action must pass through this gate before being executed.
    The gate ensures:
      - AI can only score/rank/optimize/recommend
      - AI cannot place orders or override risk
      - Risk engine remains final authority
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._audit_log: list[dict[str, Any]] = []
        self._order_count = 0  # Always 0 - AI never places orders

    def check_action(
        self,
        action_type: str,
        params: dict[str, Any] | None = None,
        source: str = "unknown",
    ) -> AISafetyVerdict:
        """
        Check if an AI action is allowed.

        Args:
            action_type: Type of action AI wants to perform
            params: Parameters of the action (e.g., {"symbol": "NIFTY", "qty": 50})
            source: Source identifier for the AI agent

        Returns:
            AISafetyVerdict - allowed=False with reason if forbidden
        """
        norm_action = action_type.lower().strip()

        # ── Block forbidden actions ───────────────────────────────────
        if norm_action in FORBIDDEN_ACTIONS:
            reason = FORBIDDEN_ACTIONS[norm_action]
            verdict = AISafetyVerdict(
                allowed=False,
                action_type=norm_action,
                reason=reason,
                source=source,
                failures=[reason],
            )
            self._audit("BLOCKED", verdict)
            log.warning("[AI_SAFETY] BLOCKED %s from %s: %s", norm_action, source, reason)
            return verdict

        # ── Check protected risk keys in params ───────────────────────
        if params:
            for key in params:
                if key.upper() in PROTECTED_RISK_KEYS:
                    reason = f"AI cannot modify protected risk key: {key}"
                    verdict = AISafetyVerdict(
                        allowed=False,
                        action_type=norm_action,
                        reason=reason,
                        source=source,
                        failures=[reason],
                    )
                    self._audit("BLOCKED", verdict)
                    log.warning("[AI_SAFETY] BLOCKED %s: %s", norm_action, reason)
                    return verdict

        # ── Allow safe actions ────────────────────────────────────────
        if norm_action in ALLOWED_ACTIONS:
            verdict = AISafetyVerdict(
                allowed=True,
                action_type=norm_action,
                reason="AI action allowed - score/rank/optimize/recommend only",
                source=source,
                suggested_action="Route through RiskService for execution",
            )
            self._audit("ALLOWED", verdict)
            return verdict

        # ── Unknown actions - deny by default (fail-safe) ─────────────
        verdict = AISafetyVerdict(
            allowed=False,
            action_type=norm_action,
            reason=f"Unknown action type '{norm_action}' - denied by default (fail-safe)",
            source=source,
            failures=[f"Unknown action: {norm_action} - AI can only score/rank/optimize/recommend"],
        )
        self._audit("BLOCKED", verdict)
        log.warning("[AI_SAFETY] BLOCKED unknown action %s from %s", norm_action, source)
        return verdict

    def check_signal_modification(
        self,
        original_signal: dict[str, Any],
        modified_signal: dict[str, Any],
        source: str = "unknown",
    ) -> AISafetyVerdict:
        """
        Check that AI modifications to a signal do not violate safety rules.

        Specifically checks that:
        - Risk parameters were not modified
        - Order placement flags were not added
        - Position sizing was not overridden

        Args:
            original_signal: Signal before AI modification
            modified_signal: Signal after AI modification
            source: Source identifier

        Returns:
            AISafetyVerdict
        """
        failures: list[str] = []

        # Check risk keys haven't changed
        for key in PROTECTED_RISK_KEYS:
            lower_key = key.lower()
            if lower_key in original_signal and lower_key in modified_signal:
                if original_signal[lower_key] != modified_signal[lower_key]:
                    failures.append(f"AI modified protected risk key '{lower_key}'")

        # Check no order placement flags were added
        dangerous_keys = {"place_order", "execute", "force_entry", "bypass_risk"}
        for key in dangerous_keys:
            if key in modified_signal and key not in original_signal:
                failures.append(f"AI added order placement flag '{key}'")

        # Check position sizing wasn't overridden
        if "position_size" in original_signal and "position_size" in modified_signal:
            if original_signal["position_size"] != modified_signal["position_size"]:
                # Allow only if the new size is SMALLER (AI can reduce, not increase)
                if modified_signal["position_size"] > original_signal["position_size"]:
                    failures.append("AI increased position size - only reduction allowed")

        if failures:
            verdict = AISafetyVerdict(
                allowed=False,
                action_type="modify_signal",
                reason="Signal modification violates safety rules",
                source=source,
                failures=failures,
            )
            self._audit("BLOCKED", verdict)
            return verdict

        verdict = AISafetyVerdict(
            allowed=True,
            action_type="modify_signal",
            reason="Signal modification passed safety checks",
            source=source,
        )
        self._audit("ALLOWED", verdict)
        return verdict

    def check_config_modification(
        self,
        config_key: str,
        new_value: Any,
        source: str = "unknown",
    ) -> AISafetyVerdict:
        """
        Check that AI config modifications are safe.

        Args:
            config_key: Config key being modified
            new_value: New value proposed
            source: Source identifier

        Returns:
            AISafetyVerdict
        """
        if config_key.upper() in PROTECTED_RISK_KEYS:
            verdict = AISafetyVerdict(
                allowed=False,
                action_type="modify_config",
                reason=f"AI cannot modify protected config key: {config_key}",
                source=source,
                failures=[f"Protected risk key: {config_key}"],
            )
            self._audit("BLOCKED", verdict)
            return verdict

        # All other config modifications are allowed (tuning params, thresholds, etc.)
        verdict = AISafetyVerdict(
            allowed=True,
            action_type="modify_config",
            reason=f"Config key '{config_key}' modification allowed",
            source=source,
            suggested_action="Verify change with ConstitutionValidator",
        )
        self._audit("ALLOWED", verdict)
        return verdict

    def get_stats(self) -> dict[str, Any]:
        """Get safety gate statistics."""
        with self._lock:
            blocked = len([e for e in self._audit_log if e.get("result") == "BLOCKED"])
            allowed = len([e for e in self._audit_log if e.get("result") == "ALLOWED"])
            return {
                "total_checks": len(self._audit_log),
                "blocked": blocked,
                "allowed": allowed,
                "ai_placed_orders": self._order_count,
            }

    # ── Audit ─────────────────────────────────────────────────────────

    def _audit(self, result: str, verdict: AISafetyVerdict) -> None:
        with self._lock:
            self._audit_log.append({
                "ts": verdict.timestamp,
                "action": verdict.action_type,
                "source": verdict.source,
                "result": result,
                "reason": verdict.reason,
            })

    def get_audit_log(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._audit_log[-limit:])


# ── Module-level singleton ────────────────────────────────────────────────────

_GATE: AISafetyGate | None = None
_GATE_LOCK = threading.RLock()


def get_safety_gate() -> AISafetyGate:
    """Get or create the singleton AI safety gate."""
    global _GATE
    if _GATE is None:
        with _GATE_LOCK:
            if _GATE is None:
                _GATE = AISafetyGate()
    return _GATE


def check_ai_action(
    action_type: str,
    params: dict[str, Any] | None = None,
    source: str = "ai_agent",
) -> AISafetyVerdict:
    """Quick check helper for AI actions."""
    gate = get_safety_gate()
    return gate.check_action(action_type, params, source)
