"""Live regression smoke test — runs during market hours."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

MODULES = [
    "core.adaptive_signal",
    "core.pure_index_signal",
    "core.services.risk_service",
    "core.position_sizer",
    "core.capital_manager",
    "core.execution_policy",
    "core.session_classifier",
    "core.iv_rank",
    "core.ml_classifier",
    "core.tier_engine",
    "core.execution_engine",
    "core.data_freshness_guard",
    "core.regime_transition_detector",
    "core.gex_analyzer",
    "core.kelly_sizer",
    "core.var_calculator",
    "core.stress_tester",
    "core.scalein_manager",
    "core.straddle_strategy",
    "core.iron_condor_strategy",
    "core.limit_order_engine",
    "core.pnl_attribution",
    "core.slippage_model",
    "core.underlying_analyzer",
    "core.param_optimizer",
    "core.metrics_exporter",
    "core.broker_failover",
    "core.fii_dii_tracker",
    "core.implied_move",
    "core.health_checker",
    "core.live_readiness_checker",
    "core.trade_replayer",
    "core.sensitivity_analyzer",
    "core.slippage_model",
    "core.ab_strategy_tester",
    "core.concept_drift_detector",
    "core.oi_snapshot_store",
    "core.monte_carlo",
    "core.signal_autopsy",
    "core.benchmark",
    "core.news_sentinel",
    "core.telegram_queue",
    "core.trade_journal",
    "core.performance_metrics",
    "core.liquidity_guard",
    "core.reentry_evaluator",
    "core.intraday_performance_monitor",
    "core.web_dashboard",
    "core.report_generator",
    "core.walkforward_engine",
    "core.spread_strategy",
]

def main() -> int:
    print("=" * 60)
    print("  LIVE REGRESSION SMOKE TEST — OPB v2.45")
    print("=" * 60)
    errors = []
    for m in MODULES:
        try:
            __import__(m)
            print(f"  [OK]  {m}")
        except Exception as e:
            errors.append((m, str(e)[:100]))
            print(f"  [ERR] {m}: {e}"[:100])

    print()
    passed = len(MODULES) - len(errors)
    print(f"  Result: {passed}/{len(MODULES)} modules loaded OK")
    if errors:
        print(f"  FAILURES ({len(errors)}):")
        for m, e in errors:
            print(f"    {m}")
            print(f"    -> {e}")
        return 1
    print("  ALL CLEAR")
    return 0

if __name__ == "__main__":
    sys.exit(main())
