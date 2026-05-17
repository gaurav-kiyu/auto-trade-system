"""
Risk Policy Engine - Item 10

Declarative rules instead of hardcoded logic:
- max_daily_loss: 25000
- max_trades: 10
- max_consecutive_losses: 3
- disable_after_time: 14:30

Cleaner long-term maintenance.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import time
from enum import Enum
from typing import Any

from core.time_provider import time_provider

_log = logging.getLogger(__name__)


class PolicyType(Enum):
    """Types of risk policies"""
    MAX_DAILY_LOSS = "MAX_DAILY_LOSS"
    MAX_TRADES = "MAX_TRADES"
    MAX_CONSECUTIVE_LOSSES = "MAX_CONSECUTIVE_LOSSES"
    DISABLE_AFTER_TIME = "DISABLE_AFTER_TIME"
    MAX_POSITION_SIZE = "MAX_POSITION_SIZE"
    MAX_PORTFOLIO_RISK = "MAX_PORTFOLIO_RISK"
    MIN_CAPITAL = "MIN_CAPITAL"
    CIRCUIT_BREAKER = "CIRCUIT_BREAKER"


class PolicyAction(Enum):
    """Actions when policy is triggered"""
    BLOCK_NEW_TRADES = "BLOCK_NEW_TRADES"
    PAUSE_ALL = "PAUSE_ALL"
    HARD_HALT = "HARD_HALT"
    WARN = "WARN"
    REDUCE_SIZE = "REDUCE_SIZE"


@dataclass
class RiskPolicy:
    """Individual risk policy definition"""
    policy_type: PolicyType
    threshold: Any
    action: PolicyAction
    enabled: bool = True
    description: str = ""
    cooldown_seconds: int = 0
    _last_triggered: str | None = None


@dataclass
class PolicyEvaluationResult:
    """Result of policy evaluation"""
    policy_name: str
    passed: bool
    current_value: Any
    threshold: Any
    action_taken: PolicyAction
    message: str


class RiskPolicyEngine:
    """
    Declarative risk policy engine.
    Policies are defined as data, not hardcoded logic.
    """

    def __init__(self):
        self._policies: dict[str, RiskPolicy] = {}
        self._lock = threading.Lock()
        self._stats = {
            "evaluations": 0,
            "violations": 0,
            "warnings": 0,
            "last_violation": None,
        }

    def load_policies_from_config(self, config: dict[str, Any]) -> int:
        """Load policies from configuration"""
        loaded = 0

        if "max_daily_loss" in config:
            self.add_policy(RiskPolicy(
                policy_type=PolicyType.MAX_DAILY_LOSS,
                threshold=config["max_daily_loss"],
                action=PolicyAction.BLOCK_NEW_TRADES,
                description=f"Maximum daily loss threshold: {config['max_daily_loss']}",
            ))
            loaded += 1

        if "max_trades_per_day" in config:
            self.add_policy(RiskPolicy(
                policy_type=PolicyType.MAX_TRADES,
                threshold=config["max_trades_per_day"],
                action=PolicyAction.BLOCK_NEW_TRADES,
                description=f"Maximum trades per day: {config['max_trades_per_day']}",
            ))
            loaded += 1

        if "max_consecutive_losses" in config:
            self.add_policy(RiskPolicy(
                policy_type=PolicyType.MAX_CONSECUTIVE_LOSSES,
                threshold=config["max_consecutive_losses"],
                action=PolicyAction.PAUSE_ALL,
                description=f"Maximum consecutive losses: {config['max_consecutive_losses']}",
            ))
            loaded += 1

        if "disable_trading_after_time" in config:
            time_str = config["disable_trading_after_time"]
            if isinstance(time_str, str):
                hour, minute = map(int, time_str.split(":"))
                self.add_policy(RiskPolicy(
                    policy_type=PolicyType.DISABLE_AFTER_TIME,
                    threshold=time(hour, minute),
                    action=PolicyAction.BLOCK_NEW_TRADES,
                    description=f"Disable trading after: {time_str}",
                ))
                loaded += 1

        if "max_position_risk_pct" in config:
            self.add_policy(RiskPolicy(
                policy_type=PolicyType.MAX_POSITION_SIZE,
                threshold=config["max_position_risk_pct"],
                action=PolicyAction.REDUCE_SIZE,
                description=f"Max position risk %: {config['max_position_risk_pct']}",
            ))
            loaded += 1

        if "max_portfolio_risk_pct" in config:
            self.add_policy(RiskPolicy(
                policy_type=PolicyType.MAX_PORTFOLIO_RISK,
                threshold=config["max_portfolio_risk_pct"],
                action=PolicyAction.HARD_HALT,
                description=f"Max portfolio risk %: {config['max_portfolio_risk_pct']}",
            ))
            loaded += 1

        if "min_capital" in config:
            self.add_policy(RiskPolicy(
                policy_type=PolicyType.MIN_CAPITAL,
                threshold=config["min_capital"],
                action=PolicyAction.HARD_HALT,
                description=f"Minimum capital required: {config['min_capital']}",
            ))
            loaded += 1

        _log.info(f"Loaded {loaded} risk policies from config")
        return loaded

    def add_policy(self, policy: RiskPolicy) -> None:
        """Add a policy"""
        with self._lock:
            self._policies[policy.policy_type.value] = policy
            _log.info(f"Added policy: {policy.policy_type.value} = {policy.threshold}")

    def remove_policy(self, policy_type: PolicyType) -> bool:
        """Remove a policy"""
        with self._lock:
            if policy_type.value in self._policies:
                del self._policies[policy_type.value]
                return True
            return False

    def enable_policy(self, policy_type: PolicyType) -> bool:
        """Enable a policy"""
        with self._lock:
            if policy_type.value in self._policies:
                self._policies[policy_type.value].enabled = True
                return True
            return False

    def disable_policy(self, policy_type: PolicyType) -> bool:
        """Disable a policy"""
        with self._lock:
            if policy_type.value in self._policies:
                self._policies[policy_type.value].enabled = False
                return True
            return False

    def evaluate(
        self,
        current_metrics: dict[str, Any],
        trade_context: dict[str, Any] | None = None,
    ) -> list[PolicyEvaluationResult]:
        """
        Evaluate all policies against current metrics.
        
        Args:
            current_metrics: Dict with keys like:
                - daily_pnl: float
                - trades_today: int
                - consecutive_losses: int
                - current_time: datetime.time
                - portfolio_risk_pct: float
                - available_capital: float
                - position_risk_pct: float
            trade_context: Optional context for proposed trade
            
        Returns:
            List of evaluation results
        """
        results = []

        with self._lock:
            self._stats["evaluations"] += 1

            current_time = current_metrics.get("current_time")

            for policy in self._policies.values():
                if not policy.enabled:
                    continue

                passed, current_value = self._evaluate_policy(policy, current_metrics)

                result = PolicyEvaluationResult(
                    policy_name=policy.policy_type.value,
                    passed=passed,
                    current_value=current_value,
                    threshold=policy.threshold,
                    action_taken=policy.action if not passed else PolicyAction.WARN,
                    message=f"{policy.policy_type.value}: {current_value} vs {policy.threshold}",
                )

                if not passed:
                    self._stats["violations"] += 1
                    self._stats["last_violation"] = time_provider.format_ts()
                    _log.warning(f"Policy violation: {result.message}")

                    if policy.action == PolicyAction.HARD_HALT:
                        _log.critical(f"HARD_HALT triggered by {policy.policy_type.value}")
                else:
                    self._stats["warnings"] += 1

                results.append(result)

        return results

    def _evaluate_policy(self, policy: RiskPolicy, metrics: dict[str, Any]) -> tuple[bool, Any]:
        """Evaluate a single policy"""

        if policy.policy_type == PolicyType.MAX_DAILY_LOSS:
            daily_pnl = metrics.get("daily_pnl", 0)
            return daily_pnl >= policy.threshold, daily_pnl

        elif policy.policy_type == PolicyType.MAX_TRADES:
            trades_today = metrics.get("trades_today", 0)
            return trades_today >= policy.threshold, trades_today

        elif policy.policy_type == PolicyType.MAX_CONSECUTIVE_LOSSES:
            consecutive = metrics.get("consecutive_losses", 0)
            return consecutive >= policy.threshold, consecutive

        elif policy.policy_type == PolicyType.DISABLE_AFTER_TIME:
            current_time = metrics.get("current_time")
            if isinstance(current_time, str):
                from datetime import datetime
                current_time = datetime.strptime(current_time, "%H:%M").time()
            if current_time and isinstance(policy.threshold, time):
                return current_time >= policy.threshold, str(current_time)

        elif policy.policy_type == PolicyType.MAX_PORTFOLIO_RISK:
            risk_pct = metrics.get("portfolio_risk_pct", 0)
            return risk_pct >= policy.threshold, risk_pct

        elif policy.policy_type == PolicyType.MAX_POSITION_SIZE:
            risk_pct = metrics.get("position_risk_pct", 0)
            return risk_pct >= policy.threshold, risk_pct

        elif policy.policy_type == PolicyType.MIN_CAPITAL:
            capital = metrics.get("available_capital", 0)
            return capital <= policy.threshold, capital

        return True, None

    def can_trade(self, metrics: dict[str, Any]) -> tuple[bool, list[str]]:
        """
        Check if trading is allowed based on policy evaluation.
        
        Returns:
            (can_trade: bool, blocked_reasons: List[str])
        """
        results = self.evaluate(metrics)

        blocked = False
        reasons = []

        for result in results:
            if not result.passed:
                if result.action_taken in [PolicyAction.BLOCK_NEW_TRADES, PolicyAction.HARD_HALT]:
                    blocked = True
                    reasons.append(f"{result.policy_name}: {result.message}")

        return not blocked, reasons

    def get_stats(self) -> dict[str, Any]:
        """Get policy engine statistics"""
        return self._stats.copy()

    def get_policies(self) -> dict[str, dict[str, Any]]:
        """Get all policies"""
        with self._lock:
            return {
                name: {
                    "policy_type": p.policy_type.value,
                    "threshold": str(p.threshold),
                    "action": p.action.value,
                    "enabled": p.enabled,
                    "description": p.description,
                }
                for name, p in self._policies.items()
            }


_policy_engine: RiskPolicyEngine | None = None
_engine_lock = threading.Lock()


def get_risk_policy_engine() -> RiskPolicyEngine:
    """Get singleton risk policy engine"""
    global _policy_engine
    with _engine_lock:
        if _policy_engine is None:
            _policy_engine = RiskPolicyEngine()
        return _policy_engine
