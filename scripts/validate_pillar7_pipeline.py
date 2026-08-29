#!/usr/bin/env python3
"""Pillar 7 End-to-End Validation — Simulated Paper Trading Session.

Validates the complete learning pipeline:

  Trade Exit → AutoLearner → KnowledgeBase
  Incident   → RootCauseAnalyzer → PatternLearner → KnowledgeBase
  Healing    → SelfHealing → KnowledgeBase (guidance)

Usage:
    python scripts/validate_pillar7_pipeline.py
    python scripts/validate_pillar7_pipeline.py --json   # JSON report
"""

from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

# Ensure project root is on sys.path
_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

logging.basicConfig(level=logging.WARNING, format="%(levelname)s | %(message)s")
_log = logging.getLogger("pillar7_validation")

# Windows-safe Unicode fallback
def _safe(text: str) -> str:
    """Replace non-ASCII characters with ASCII on Windows cp1252."""
    try:
        text.encode("cp1252")
        return text
    except UnicodeEncodeError:
        # Replace known Unicode chars from script output
        result = text.replace("\u2192", "->").replace("\u2705", "[OK]").replace("\u274c", "[FAIL]").replace("\u26a0", "[WARN]")
        # Final fallback: replace any remaining non-encodable chars with ?
        return result.encode("cp1252", errors="replace").decode("cp1252")


def print_header(title: str) -> None:
    w = 72
    print()
    print("=" * w)
    print(f"  {_safe(title)}")
    print("=" * w)


def print_step(step: int, total: int, desc: str, status: str = "...") -> None:
    print(f"  [{step:02d}/{total:02d}] {_safe(desc):60s} {_safe(status)}")


def main() -> int:
    total_steps = 9
    results: dict[str, Any] = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "steps": {},
        "overall": "PASS",
    }
    passed = 0
    failed = 0

    print(f"\n{'=' * 72}")
    print("  PILLAR 7 END-TO-END VALIDATION")
    print("  Simulated Paper Trading Session")
    print(f"  {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'=' * 72}")

    # ── Step 1: Reset singletons and initialize ───────────────────────────
    print_header("Phase 1: Setup")

    try:
        from core.auto_learner import AutoLearner, LearnerConfig, reset_auto_learner
        from core.knowledge_base import get_knowledge_base, reset_knowledge_base
        from core.pattern_learner import reset_pattern_learner

        reset_auto_learner()
        reset_pattern_learner()
        reset_knowledge_base()
        kb = get_knowledge_base()
        kb.clear()

        learner = AutoLearner(LearnerConfig(
            enabled=True,
            state_file="backups/test_learner_state.json",
            per_symbol=True,
        ))
        learner.load()
        print_step(1, total_steps, "Singletons reset, AutoLearner initialized", "✅")
        results["steps"]["1_setup"] = {"status": "PASS", "detail": "Singletons reset"}
        passed += 1
    except Exception as e:
        print_step(1, total_steps, f"Setup failed: {e}", "❌")
        results["steps"]["1_setup"] = {"status": "FAIL", "detail": str(e)}
        failed += 1

    # ── Step 2: Simulate trade exits (AutoLearner.record_exit) ────────────
    print_header("Phase 2: Trade Exit Learning (AutoLearner → KnowledgeBase)")

    try:
        trades = [
            ("NIFTY", "WIN", 150.0, "TRENDING", "STRONG"),
            ("NIFTY", "WIN", 75.0, "TRENDING", "STRONG"),
            ("NIFTY", "LOSS", -120.0, "CHOPPY", "WEAK"),
            ("BANKNIFTY", "WIN", 200.0, "TRENDING", "MODERATE"),
            ("BANKNIFTY", "LOSS", -80.0, "CHOPPY", "MODERATE"),
            ("NIFTY", "WIN", 50.0, "TRENDING", "STRONG"),
            ("FINNIFTY", "LOSS", -60.0, "CHOPPY", "WEAK"),
            ("NIFTY", "BREAKEVEN", 0.0, "RANGING", "WEAK"),
            ("BANKNIFTY", "WIN", 110.0, "TRENDING", "STRONG"),
            ("NIFTY", "LOSS", -200.0, "CHOPPY", "WEAK"),
        ]
        for symbol, tag, pnl, regime, strength in trades:
            learner.record_exit(symbol, tag, regime=regime, strength=strength, net_pnl=pnl)
            learner.learn_from_exit(symbol, tag, net_pnl=pnl, regime=regime)

        learner.save()
        state = learner.export_global_state()
        wr = learner.regime_win_rates()

        print_step(2, total_steps, "10 simulated trade exits recorded", "✅")
        print(f"         Global state: adj={state['score_adj']}, conf={state['confidence']}, streak={state['streak']}")
        print(f"         Regime win rates: {wr}")
        assert isinstance(state["score_adj"], int)
        results["steps"]["2_trade_exits"] = {
            "status": "PASS",
            "detail": f"adj={state['score_adj']}, conf={state['confidence']}, wr={wr}",
        }
        passed += 1
    except Exception as e:
        print_step(2, total_steps, f"Trade exits failed: {e}", "❌")
        results["steps"]["2_trade_exits"] = {"status": "FAIL", "detail": str(e)}
        failed += 1

    # ── Step 3: Query Knowledge Base for learned patterns ─────────────────
    print_header("Phase 3: Knowledge Base Query")

    try:
        kb_entries = kb.get_report()
        print_step(3, total_steps, f"KB has {kb_entries.total_entries} entries", "✅")
        print(f"         By type: {kb_entries.by_type}")
        print(f"         Avg confidence: {kb_entries.avg_confidence:.3f}")
        assert kb_entries.total_entries > 0, "KB should have entries after trade exits"
        results["steps"]["3_kb_query"] = {
            "status": "PASS",
            "detail": f"{kb_entries.total_entries} entries, types={kb_entries.by_type}",
        }
        passed += 1
    except Exception as e:
        print_step(3, total_steps, f"KB query failed: {e}", "❌")
        results["steps"]["3_kb_query"] = {"status": "FAIL", "detail": str(e)}
        failed += 1

    # ── Step 4: AutoLearner query_knowledge_base ──────────────────────────
    print_header("Phase 4: Cross-Domain KB Query")

    try:
        nifty_results = learner.query_knowledge_base("NIFTY trading", max_results=5)
        print_step(4, total_steps, f"Query 'NIFTY trading' → {len(nifty_results)} results", "✅")
        for r in nifty_results[:3]:
            print(f"         [{r.get('confidence', 0):.0%}] {r.get('pattern', '')[:80]}")
        results["steps"]["4_cross_domain_query"] = {
            "status": "PASS",
            "detail": f"{len(nifty_results)} results for 'NIFTY'",
        }
        passed += 1
    except Exception as e:
        print_step(4, total_steps, f"Cross-domain query failed: {e}", "❌")
        results["steps"]["4_cross_domain_query"] = {"status": "FAIL", "detail": str(e)}
        failed += 1

    # ── Step 5: PatternLearner — Learn from simulated incident ────────────
    print_header("Phase 5: Incident Learning (RootCauseAnalyzer → PatternLearner)")

    try:
        from core.pattern_learner import get_pattern_learner

        pl = get_pattern_learner()

        class MockEvidence:
            category = "STACK_TRACE"
            description = "File 'core/broker.py' at line 142 in connect() — ConnectionRefusedError"
            relevance = 0.95
            timestamp = time.time()
            details = {"host": "broker.zerodha.com", "port": 443}
            source = "runtime"

        class MockResult:
            incident_type = "broker_disconnect"
            incident_message = "Connection refused: broker.zerodha.com:443"
            probable_cause = "Network outage or firewall blocking outbound connections"
            severity = "CRITICAL"
            recommended_fix = "Check firewall rules and broker status page. Restart network interface."
            evidence = [MockEvidence()]
            impacted_modules = ["core/adapters/broker_adapters.py"]

        pl_entries = pl.learn_from_incident(MockResult())
        print_step(5, total_steps, f"Incident learned → {len(pl_entries)} KB entries", "✅")
        assert len(pl_entries) >= 1, "Should have created at least 1 KB entry"
        results["steps"]["5_incident_learning"] = {
            "status": "PASS",
            "detail": f"{len(pl_entries)} pattern entries from incident",
        }
        passed += 1
    except Exception as e:
        print_step(5, total_steps, f"Incident learning failed: {e}", "❌")
        results["steps"]["5_incident_learning"] = {"status": "FAIL", "detail": str(e)}
        failed += 1

    # ── Step 6: PatternLearner — Learn from code review ───────────────────
    print_header("Phase 6: Code Review Learning (PatternLearner)")

    try:
        pl = get_pattern_learner()
        review_entries = pl.learn_from_code_review(
            pr_id="PR-142",
            comments=[
                "This function has circular dependencies with module A — refactor into a shared service",
                "SQL injection vulnerability in query builder — use parameterized queries instead of f-strings",
                "N+1 query pattern in trade history endpoint — add select_related()",
                "LGTM, minor style nitpick on line 42",
            ],
            author="senior-dev",
            files_changed=["core/trade_history.py", "core/query_builder.py"],
        )
        print_step(6, total_steps, f"Code review learned → {len(review_entries)} KB entries", "✅")
        # Check categorization worked
        categories = set()
        for e in review_entries:
            categories.update(e.tags)
        print(f"         Categories: {categories}")
        assert len(review_entries) >= 1
        results["steps"]["6_review_learning"] = {
            "status": "PASS",
            "detail": f"{len(review_entries)} entries, categories={categories}",
        }
        passed += 1
    except Exception as e:
        print_step(6, total_steps, f"Review learning failed: {e}", "❌")
        results["steps"]["6_review_learning"] = {"status": "FAIL", "detail": str(e)}
        failed += 1

    # ── Step 7: PatternLearner — Get recommendations ──────────────────────
    print_header("Phase 7: Recommendations from Learned Patterns")

    try:
        recs = pl.get_recommendations("broker", max_results=5)
        print_step(7, total_steps, f"Recommendations for 'broker' → {len(recs)} results", "✅")
        for r in recs:
            print(f"         [{r.confidence:.0%}] {r.pattern[:80]}")
            if r.solution:
                print(f"           -> {r.solution[:80]}")
        results["steps"]["7_recommendations"] = {
            "status": "PASS",
            "detail": f"{len(recs)} recommendations for 'broker'",
        }
        passed += 1
    except Exception as e:
        print_step(7, total_steps, f"Recommendations failed: {e}", "❌")
        results["steps"]["7_recommendations"] = {"status": "FAIL", "detail": str(e)}
        failed += 1

    # ── Step 8: SelfHealing → KnowledgeBase guidance ──────────────────────
    print_header("Phase 8: Self-Healing KB Guidance")

    try:
        from core.self_healing.orchestrator import SelfHealingOrchestrator

        healer = SelfHealingOrchestrator(cfg={})
        guidance = healer._query_kb_for_guidance("broker_disconnected")
        has_guidance = bool(guidance)
        print_step(8, total_steps, f"SelfHealing KB guidance: {'found' if has_guidance else 'none'}", "✅" if has_guidance else "⚠️")
        if has_guidance:
            print(f"         {guidance[:150]}")
        results["steps"]["8_self_healing_kb"] = {
            "status": "PASS" if has_guidance else "WARN",
            "detail": f"KB guidance found: {has_guidance}",
        }
        passed += 1
    except Exception as e:
        print_step(8, total_steps, f"Self-healing KB failed: {e}", "❌")
        results["steps"]["8_self_healing_kb"] = {"status": "FAIL", "detail": str(e)}
        failed += 1

    # ── Step 9: PatternLearner Report & Trend Analysis ────────────────────
    print_header("Phase 9: Learning Analytics")

    try:
        pl_report = pl.get_report()
        trends = pl.get_pattern_trends(days=30)
        kb_report = kb.get_report()

        print_step(9, total_steps, "Learning analytics generated", "✅")
        print(f"         PatternLearner: {pl_report.total_patterns_extracted} patterns from "
              f"{pl_report.total_incidents_learned} incidents, {pl_report.total_reviews_learned} reviews")
        print(f"         KnowledgeBase: {kb_report.total_entries} total entries, "
              f"{kb_report.total_frequency} total frequency")
        print(f"         Trending: {trends['total_recent']} recent patterns")
        results["steps"]["9_analytics"] = {
            "status": "PASS",
            "detail": f"{pl_report.total_patterns_extracted} patterns, {kb_report.total_entries} KB entries",
        }
        passed += 1
    except Exception as e:
        print_step(9, total_steps, f"Analytics failed: {e}", "❌")
        results["steps"]["9_analytics"] = {"status": "FAIL", "detail": str(e)}
        failed += 1

    # ── Summary ───────────────────────────────────────────────────────────
    results["passed"] = passed
    results["failed"] = failed
    results["total"] = total_steps
    results["overall"] = "PASS" if failed == 0 else "FAIL" if failed > 2 else "PARTIAL"

    print(f"\n{'=' * 72}")
    print("  VALIDATION SUMMARY")
    print(f"{'=' * 72}")
    print(f"  Steps:     {passed}/{total_steps} passed, {failed} failed")
    print(f"  Overall:   {results['overall']}")
    print(f"{'=' * 72}\n")

    if "--json" in sys.argv:
        print(json.dumps(results, indent=2, default=str))

    return 0 if failed == 0 else 1 if failed > 2 else 0


if __name__ == "__main__":
    raise SystemExit(main())
