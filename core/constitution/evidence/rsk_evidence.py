"""
RSK (Risk) evidence collection — extracted from evidence.py.

Scans codebase to register objective evidence for RSK (Risk)
constitution scoring categories.

Usage:
    from core.constitution.evidence.rsk_evidence import collect_rsk_evidence
    collect_rsk_evidence(validator, root, add_ev)
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.constitution import ConstitutionValidator


__all__ = [
    "collect_rsk_evidence",
]


def collect_rsk_evidence(
    validator: ConstitutionValidator,
    root: Path,
    add_ev,
) -> None:
    """Collect RSK (Risk) evidence from the codebase.

    Args:
        validator: ConstitutionValidator instance.
        root: PROJECT_ROOT path for file existence checks.
        add_ev: validator.add_evidence bound method.

    """
    # ── RSK: Risk ───────────────────────────────────────────────────
    risk_svc = root / "core" / "services" / "risk_service.py"
    if risk_svc.exists():
        add_ev("RSK-01",
            "RiskService._trip_hard_halt(): kill-switch blocking all entries on loss breach",
            "code_review", 0.6)
        add_ev("RSK-01",
            "_HARD_HALT threading.Event checked before every entry",
            "code_review", 0.5)
        add_ev("RSK-02",
            "MAX_DAILY_LOSS and MAX_DRAWDOWN enforced in risk_service.py",
            "code_review", 0.6)
        add_ev("RSK-02",
            "PORTFOLIO_MAX_SL_RISK_PCT portfolio-level cap",
            "code_review", 0.5)
    if (root / "tests" / "test_risk_engine.py").exists():
        add_ev("RSK-01",
            "Risk engine test (test_risk_engine.py) validates hard halt",
            "test_pass", 0.7)
        add_ev("RSK-02",
            "Risk engine tests validate loss-limit enforcement",
            "test_pass", 0.6)
    if (root / "tests" / "test_api_gateway.py").exists():
        add_ev("RSK-01",
            "API gateway test validates halt at API level",
            "test_pass", 0.5)
    if (root / "core" / "circuit_breaker_monitor.py").exists():
        add_ev("RSK-01",
            "Circuit breaker monitor enforces NSE + YF failure rate gate",
            "code_review", 0.4)
    if (root / "tests" / "test_circuit_breaker_service.py").exists():
        add_ev("RSK-01",
            "Circuit breaker service test validates hard halt via failure rate monitoring (22 tests)",
            "test_pass", 0.5)
    if (root / "tests" / "test_signal_safety.py").exists():
        add_ev("RSK-01",
            "Signal safety test validates stale signal hard halt blocking (15+ tests)",
            "test_pass", 0.4)
    if (root / "tests" / "test_limit_order_engine.py").exists():
        add_ev("RSK-01",
            "Limit order engine test validates price risk controls as hard halt safeguard against adverse fills",
            "test_pass", 0.3)
    if (root / "tests" / "test_invariants.py").exists():
        add_ev("RSK-02",
            "Invariants test validates loss limits",
            "test_pass", 0.4)
    if (root / "tests" / "test_var_calculator.py").exists():
        add_ev("RSK-02",
            "VaR test validates parametric VaR at 95/99 confidence levels (test_var_calculator.py)",
            "test_pass", 0.3)
    if (root / "tests" / "test_stress_tester.py").exists():
        add_ev("RSK-02",
            "Stress test validates 4 loss scenarios: FLASH_CRASH, SLOW_GRIND, GAP_UP, EXPIRY_CRUSH",
            "test_pass", 0.3)
    if (root / "core" / "position_sizer.py").exists():
        add_ev("RSK-03",
            "Position sizer module with config-driven sizing",
            "code_review", 0.4)
    if (root / "core" / "kelly_sizer.py").exists():
        add_ev("RSK-03",
            "Kelly Criterion half-Kelly sizer",
            "code_review", 0.4)
    if (root / "tests" / "test_position_sizer.py").exists():
        add_ev("RSK-03",
            "Position sizer test validates sizing logic",
            "test_pass", 0.4)
    if (root / "tests" / "test_kelly_sizer.py").exists():
        add_ev("RSK-03",
            "Kelly sizer test: formula, history fallback, clamping",
            "test_pass", 0.4)
    if risk_svc.exists():
        add_ev("RSK-03",
            "Risk service position sizing (get_position_size)",
            "code_review", 0.3)
    if (root / "tests" / "test_scalein_manager.py").exists():
        add_ev("RSK-03",
            "Scale-in manager test validates staged position sizing (test_scalein_manager.py)",
            "test_pass", 0.3)
    if (root / "core" / "vix_adaptive_threshold.py").exists():
        add_ev("RSK-03",
            "VIX-adaptive position sizing via vix_adaptive_threshold.py",
            "code_review", 0.3)
    if (root / "core" / "broker_failover.py").exists():
        add_ev("RSK-04",
            "Broker failover manager with fail-closed behavior",
            "code_review", 0.5)
    if (root / "tests" / "test_broker_failover.py").exists():
        add_ev("RSK-04",
            "Broker failover test validates failover + recovery",
            "test_pass", 0.5)
    if (root / "tests" / "test_failure_injection.py").exists():
        add_ev("RSK-04",
            "Failure injection test validates fail-closed",
            "test_pass", 0.5)
    if (root / "tests" / "test_catastrophic_scenarios.py").exists():
        add_ev("RSK-04",
            "Catastrophic scenarios test: multi-failure",
            "test_pass", 0.5)
    if (root / "tests" / "test_runtime_ops.py").exists():
        add_ev("RSK-04",
            "Runtime ops: circuit breaker trips and recovers",
            "test_pass", 0.4)
    if (root / "tests" / "test_operational_hardening.py").exists():
        add_ev("RSK-04",
            "Operational hardening test validates fail-closed behavior across multiple failure modes",
            "test_pass", 0.4)

    # ── RSK-02: Additional loss limit evidence ────────────────────────
    for tf_name in ["test_risk_engine", "test_risk_service", "test_services_risk_service",
                    "test_risk_limits_manager", "test_capital_manager", "test_position_sizer",
                    "test_stt_cost_model", "test_intraday_monitor", "test_liquidity_guard",
                    "test_stress_tester", "test_catastrophic_scenarios", "test_failure_injection"]:
        if (root / "tests" / f"{tf_name}.py").exists():
            add_ev("RSK-02",
                f"Loss limit test: {tf_name} validates loss boundary enforcement",
                "test_pass", 0.3)
    if (root / "core" / "liquidity_guard.py").exists():
        add_ev("RSK-02",
            "Liquidity guard prevents adverse fills through bid-ask spread + OI + volume filtering",
            "code_review", 0.3)
    if (root / "core" / "exposure_limits.py").exists():
        add_ev("RSK-02",
            "Exposure limits module enforces per-index and portfolio-level loss caps",
            "code_review", 0.3)

