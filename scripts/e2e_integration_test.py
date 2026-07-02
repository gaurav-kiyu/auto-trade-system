#!/usr/bin/env python3
"""
Comprehensive End-to-End Integration Test for OPB Trading System.

Tests the complete trading flow in paper mode:
  Phase 1: Module import integrity (22 core modules)
  Phase 2: Configuration loading & validation
  Phase 3: Signal generation pipeline
  Phase 4: Market data layer
  Phase 5: Broker/paper adapter with order placement
  Phase 6: Risk service with metrics
  Phase 7: Safety systems & execution guards
  Phase 8: Broker truth reconciliation
  Phase 9: ML pipeline imports
  Phase 10: Notifications & audit
  Phase 11: Live bot startup simulation

Generates a detailed timestamped report.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime

# Ensure project root is on path
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

logging.basicConfig(level=logging.WARNING, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("e2e")

NOW = datetime.now().strftime("%Y-%m-%d %H:%M:%S")


@dataclass
class TestResult:
    phase: str
    name: str
    passed: bool
    detail: str = ""
    duration_s: float = 0.0


results: list[TestResult] = []


def test(phase: str, name: str, fn: callable) -> None:
    start = time.time()
    try:
        fn()
        results.append(TestResult(phase=phase, name=name, passed=True, duration_s=time.time() - start))
        print(f"  [{phase}] [PASS] {name} ({time.time()-start:.1f}s)")
    except Exception as e:
        results.append(TestResult(phase=phase, name=name, passed=False, detail=str(e), duration_s=time.time() - start))
        print(f"  [{phase}] [FAIL] {name}: {e}")


# ═══════════════════════════════════════════════════════════════════
# PHASE 1: Module Import Integrity
# ═══════════════════════════════════════════════════════════════════
def run_phase1():
    mods = [
        "core.datetime_ist", "core.yf_data_provider", "core.iv_rank",
        "core.adaptive_signal", "core.strike_selector", "core.session_classifier",
        "core.ml_classifier", "core.oi_snapshot_store", "core.monte_carlo",
        "core.signal_autopsy", "core.performance_metrics", "core.trade_journal",
        "core.liquidity_guard", "core.reentry_evaluator", "core.news_sentinel",
        "core.kelly_sizer", "core.var_calculator", "core.slippage_model",
        "core.fii_dii_tracker", "core.gex_analyzer",
        "core.regime_transition_detector", "core.pnl_attribution",
        "core.scalein_manager", "core.services.risk_service",
        "core.adapters.broker_adapters", "core.audit_engine",
        "core.services.notification_service", "core.telegram_queue",
        "core.execution.broker_truth_reconciliation",
    ]
    for mod_name in mods:
        def _import(mod=mod_name):
            __import__(mod)
        test("P1-IMPORTS", mod_name, _import)


# ═══════════════════════════════════════════════════════════════════
# PHASE 2: Configuration Loading
# ═══════════════════════════════════════════════════════════════════
def run_phase2():
    def test_config():
        from core.config_bootstrap import get_effective_config
        cfg = get_effective_config()
        assert cfg is not None, "Config is None"
        assert len(cfg) > 0, "Config is empty"
        cfg_keys = {k.lower() for k in cfg.keys()}
        for key in ["SL_PCT", "TARGET_PCT", "MAX_DAILY_LOSS"]:
            assert key.lower() in cfg_keys or key in cfg, f"Missing key: {key}"
    test("P2-CONFIG", "Config loading", test_config)

    def test_defaults():
        from pathlib import Path
        data = json.loads(Path("index_config.defaults.json").read_text(encoding="utf-8"))
        assert len(data) > 100, f"Only {len(data)} defaults keys"
    test("P2-CONFIG", "Defaults file integrity", test_defaults)

    def test_env_overrides():
        from core.config_bootstrap import apply_env_overrides
        cfg = {"BASE_CAPITAL": 5000}
        count = apply_env_overrides(cfg, cfg, prefix="OPBUYING_")
        assert count >= 0
    test("P2-CONFIG", "Env override function", test_env_overrides)


# ═══════════════════════════════════════════════════════════════════
# PHASE 3: Signal Pipeline
# ═══════════════════════════════════════════════════════════════════
def run_phase3():
    def test_signal_utils():
        from core.signal_utils import breakout_strength_ok
        assert breakout_strength_ok is not None
    test("P3-SIGNAL", "Signal engine import", test_signal_engine)

    def test_pure_signal():
        from core.pure_index_signal import compute_index_score, evaluate_dual_direction_signal
        assert callable(compute_index_score)
        assert callable(evaluate_dual_direction_signal)
    test("P3-SIGNAL", "Pure index signal functions", test_pure_signal)

    def test_adaptive():
        from core.adaptive_signal import evaluate_adaptive_signal
        assert callable(evaluate_adaptive_signal)
    test("P3-SIGNAL", "Adaptive signal function", test_adaptive)


# ═══════════════════════════════════════════════════════════════════
# PHASE 4: Market Data
# ═══════════════════════════════════════════════════════════════════
def run_phase4():
    def test_yf():
        import yfinance as yf
        assert yf is not None
    test("P4-DATA", "yfinance import", test_yf)

    def test_yf_provider():
        from index_app.domains.market.data import fetch_intraday_data
        r = fetch_intraday_data("")
        assert r == (None, None, None), "Empty symbol should return None tuple"
    test("P4-DATA", "yf_data_provider API", test_yf_provider)

    def test_dt():
        from core.datetime_ist import now_ist
        dt = now_ist()
        assert dt is not None
        assert hasattr(dt, "hour")
    test("P4-DATA", "IST datetime", test_dt)


# ═══════════════════════════════════════════════════════════════════
# PHASE 5: Broker/Paper Adapter
# ═══════════════════════════════════════════════════════════════════
def run_phase5():
    def test_paper():
        from core.adapters.broker_adapters import BrokerAdapter, PaperBrokerAdapter
        paper = PaperBrokerAdapter()
        broker = BrokerAdapter(paper)
        assert broker is not None
    test("P5-BROKER", "BrokerAdapter creation", test_paper)

    def test_order():
        from core.adapters.broker_adapters import PaperBrokerAdapter
        paper = PaperBrokerAdapter()
        # PaperBrokerAdapter.place_order(name, direction, qty, strike) -> str
        result = paper.place_order("NIFTY", "CALL", 75, 50000)
        assert result is not None
        assert isinstance(result, str) and len(result) > 0
        assert result.startswith("PAPER_")
    test("P5-BROKER", "Paper order placement", test_order)

    def test_health():
        from core.adapters.broker_adapters import PaperBrokerAdapter
        paper = PaperBrokerAdapter()
        hc = paper.health_check()
        assert isinstance(hc, dict)
        assert hc.get("status") == "healthy"
        assert hc.get("mode") == "PAPER"
    test("P5-BROKER", "Paper broker health check", test_health)


# ═══════════════════════════════════════════════════════════════════
# PHASE 6: Risk Service
# ═══════════════════════════════════════════════════════════════════
def run_phase6():
    def test_risk():
        from core.services.risk_service import RiskService, RiskServiceConfig
        cfg = RiskServiceConfig(max_daily_loss=-2000, max_daily_trades=10, max_open_positions=5, max_consecutive_losses=3)
        svc = RiskService(config=cfg)
        assert svc is not None
    test("P6-RISK", "RiskService creation", test_risk)

    def test_metrics():
        from core.services.risk_service import RiskService, RiskServiceConfig
        cfg = RiskServiceConfig(max_daily_loss=-2000, max_daily_trades=10, max_open_positions=5, max_consecutive_losses=3)
        svc = RiskService(config=cfg)
        metrics = svc.get_portfolio_risk_metrics()
        assert metrics is not None
        assert hasattr(metrics, "daily_pnl"), f"No daily_pnl in {dir(metrics)}"
    test("P6-RISK", "Risk metrics", test_metrics)


# ═══════════════════════════════════════════════════════════════════
# PHASE 7: Safety Systems
# ═══════════════════════════════════════════════════════════════════
def run_phase7():
    def test_safety():
        from core.safety_state import _HARD_HALT, is_hard_halted, is_shutting_down
        assert callable(is_hard_halted)
        assert callable(is_shutting_down)
        assert not _HARD_HALT.is_set(), "HALT should not be set at startup"
    test("P7-SAFETY", "Halt state check", test_safety)

    def test_circuit():
        from core.ports.circuit_breaker.circuit_breaker_port import CircuitBreakerPort
        from core.services.circuit_breaker_service import CircuitBreakerService
        cb = CircuitBreakerService()
        assert cb is not None
        assert isinstance(cb, CircuitBreakerPort)
    test("P7-SAFETY", "Circuit breaker", test_circuit)


# ═══════════════════════════════════════════════════════════════════
# PHASE 8: Reconciliation
# ═══════════════════════════════════════════════════════════════════
def run_phase8():
    def test_recon():
        from core.execution.broker_truth_reconciliation import reconcile_broker_truth
        r = reconcile_broker_truth(broker_port=None)
        assert r is not None
        assert r.get("status") == "WARN", f"Expected WARN, got {r.get('status')}"
    test("P8-RECON", "Broker truth reconciliation", test_recon)


# ═══════════════════════════════════════════════════════════════════
# PHASE 9: ML Pipeline
# ═══════════════════════════════════════════════════════════════════
def run_phase9():
    def test_ml():
        from core.ml_classifier import get_classifier, predict_win_prob
        assert callable(get_classifier)
        assert callable(predict_win_prob)
    test("P9-ML", "ML classifier API", test_ml)

    def test_ml_tracker():
        from core.ml_performance_tracker import record_prediction
        assert callable(record_prediction)
    test("P9-ML", "ML performance tracker", test_ml_tracker)


# ═══════════════════════════════════════════════════════════════════
# PHASE 10: Notifications & Audit
# ═══════════════════════════════════════════════════════════════════
def run_phase10():
    def test_notif():
        from core.services.notification_service import NotificationService
        svc = NotificationService()
        assert svc is not None
    test("P10-NOTIF", "NotificationService creation", test_notif)

    def test_queue():
        import core.telegram_queue as tq
        assert tq is not None
    test("P10-NOTIF", "Telegram queue module", test_queue)

    def test_audit():
        import os

        from core.audit_engine import AuditEngine
        tmp = tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False)
        tmp.close()
        try:
            ae = AuditEngine(path=tmp.name, enabled=True)
            ae.record("test_event", trace_id="test-001", symbol="NIFTY")
        finally:
            os.unlink(tmp.name)
    test("P10-NOTIF", "AuditEngine event recording", test_audit)


# ═══════════════════════════════════════════════════════════════════
# PHASE 11: Live Bot Startup Simulation
# ═══════════════════════════════════════════════════════════════════
def run_phase11():
    def test_selftest():
        result = subprocess.run(
            [sys.executable, "-m", "index_app.index_trader", "--selftest"],
            capture_output=True, text=True, timeout=30, cwd=_ROOT,
        )
        assert result.returncode == 0, f"selftest failed: {result.stderr[:200]}"
    test("P11-BOT", "--selftest", test_selftest)


# ═══════════════════════════════════════════════════════════════════
# REPORT
# ═══════════════════════════════════════════════════════════════════
def generate_report() -> str:
    passed = sum(1 for r in results if r.passed)
    failed = sum(1 for r in results if not r.passed)
    total = len(results)

    lines = [
        "=" * 70,
        "  END-TO-END INTEGRATION TEST REPORT",
        f"  Generated: {NOW}",
        "=" * 70,
        "",
        f"  Total Tests: {total}",
        f"  Passed:      {passed}",
        f"  Failed:      {failed}",
        f"  Pass Rate:   {passed/total*100:.0f}%" if total > 0 else "  Pass Rate:   N/A",
        "",
    ]

    lines.append("  --- Results by Phase ---")
    phases = {}
    for r in results:
        phases.setdefault(r.phase, {"passed": 0, "failed": 0, "total": 0})
        phases[r.phase]["total"] += 1
        if r.passed:
            phases[r.phase]["passed"] += 1
        else:
            phases[r.phase]["failed"] += 1

    for ph in sorted(phases):
        d = phases[ph]
        lines.append(f"    {ph}: {d['passed']}/{d['total']} passed" +
                     (f" ({d['failed']} failed)" if d['failed'] else ""))

    if failed > 0:
        lines.append("")
        lines.append("  --- Failures ---")
        for r in results:
            if not r.passed:
                lines.append(f"    [{r.phase}] {r.name}")
                lines.append(f"      Error: {r.detail}")

    lines.append("")
    lines.append("  --- Latency Summary ---")
    total_time = sum(r.duration_s for r in results)
    avg_time = total_time / total if total > 0 else 0
    max_time = max((r.duration_s for r in results), default=0)
    lines.append(f"    Total:  {total_time:.1f}s")
    lines.append(f"    Avg:    {avg_time:.2f}s")
    lines.append(f"    Max:    {max_time:.2f}s")
    lines.append(f"    Slowest: {max((r.name for r in results if r.duration_s == max_time), default='')}")

    lines.append("")
    lines.append("=" * 70)
    lines.append(f"  VERDICT: {'ALL TESTS PASSED' if failed == 0 else f'{failed} FAILURE(S)'}")
    lines.append("=" * 70)

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print()
    print("=" * 70)
    print("  OPB TRADING SYSTEM - END-TO-END INTEGRATION TEST")
    print(f"  Started at: {NOW}")
    print("=" * 70)
    print()

    run_phase1()
    print()
    run_phase2()
    print()
    run_phase3()
    print()
    run_phase4()
    print()
    run_phase5()
    print()
    run_phase6()
    print()
    run_phase7()
    print()
    run_phase8()
    print()
    run_phase9()
    print()
    run_phase10()
    print()
    run_phase11()
    print()

    report = generate_report()
    print(report)

    # Save report
    report_path = os.path.join(_ROOT, "docs", "E2E_INTEGRATION_TEST_REPORT.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"\n  Report saved to: {report_path}")
    print()

    failed_count = sum(1 for r in results if not r.passed)
    raise SystemExit(1 if failed_count > 0 else 0)
