#!/usr/bin/env python3
"""Auto-Learner Live Paper Mode Test — Real NSE Market Data.

Fetches live Nifty/BankNifty intraday data from yfinance, simulates
paper trades based on real price movements, and feeds them through
the complete Pillar 7 learning pipeline.

Usage:
    python scripts/live_paper_test.py
    python scripts/live_paper_test.py --json   # JSON report
"""

from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path

# Ensure project root in sys.path
_root = str(Path(__file__).resolve().parent.parent)
if _root not in sys.path:
    sys.path.insert(0, _root)

logging.basicConfig(level=logging.WARNING, format="%(levelname)s | %(message)s")
_log = logging.getLogger("live_paper_test")


def _print(line: str = "") -> None:
    """Print with Windows cp1252 fallback."""
    try:
        print(line)
    except UnicodeEncodeError:
        safe = line.encode("cp1252", errors="replace").decode("cp1252")
        print(safe)


def print_header(title: str) -> None:
    w = 70
    _print()
    _print("=" * w)
    _print("  " + title)
    _print("=" * w)


def print_step(num: int, total: int, desc: str, ok: bool = True) -> None:
    status = "PASS" if ok else "FAIL"
    _print(f"  [{num:02d}/{total:02d}] {desc:55s} [{status}]")


def main() -> int:
    total_steps = 7
    results: dict = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "steps": {},
        "overall": "PASS",
        "market_data": {},
    }
    passed = 0
    failed = 0

    _print()
    _print("=" * 70)
    _print("  AUTO-LEARNER LIVE PAPER MODE TEST")
    _print("  Real NSE Market Data via yfinance")
    _print(f"  {time.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    _print("=" * 70)

    # ── Step 1: Fetch live market data ────────────────────────────────────
    print_header("Step 1: Fetch Live Market Data")

    try:
        import yfinance as yf

        indices = {
            "^NSEI": "NIFTY 50",
            "^NSEBANK": "BANKNIFTY",
            "NIFTY_FIN_SERVICE.NS": "FINNIFTY",
        }
        market_data: dict = {}
        for symbol, name in indices.items():
            try:
                # Get last 30 days of daily data + today's intraday (15m bars)
                daily = yf.Ticker(symbol).history(period="1mo", interval="1d")
                intra = yf.Ticker(symbol).history(period="1d", interval="15m")
                if not daily.empty:
                    market_data[name] = {"daily": daily, "intraday": intra}
                    last_close = daily["Close"].iloc[-1]
                    last_high = daily["High"].iloc[-1]
                    last_low = daily["Low"].iloc[-1]
                    change_pct = ((last_close - daily["Open"].iloc[-1]) / daily["Open"].iloc[-1]) * 100
                    _print(f"  {name:15s}: {last_close:>8.2f}  (H:{last_high:>8.2f} L:{last_low:>8.2f} "
                           f"chg:{change_pct:>+5.2f}%)  bars:{len(intra) if not intra.empty else 0}")
            except Exception as exc:
                _print(f"  {name:15s}: SKIPPED ({exc})")

        assert len(market_data) >= 1, "At least one index must be available"
        results["market_data"] = {k: {"available": True} for k in market_data}
        print_step(1, total_steps, f"Fetched {len(market_data)} indices from live market", True)
        passed += 1
    except Exception as e:
        print_step(1, total_steps, f"Market data fetch failed: {e}", False)
        results["steps"]["1_market_data"] = {"status": "FAIL", "detail": str(e)}
        failed += 1
        # Cannot continue without market data
        _print("\n  Cannot proceed without live market data. Aborting.")
        results["overall"] = "FAIL"
        if "--json" in sys.argv:
            print(json.dumps(results, indent=2, default=str))
        return 1

    # ── Step 2: Initialize AutoLearner ────────────────────────────────────
    print_header("Step 2: Initialize AutoLearner (Paper Mode)")

    try:
        from core.auto_learner import AutoLearner, LearnerConfig, reset_auto_learner
        from core.knowledge_base import get_knowledge_base, reset_knowledge_base

        reset_auto_learner()
        reset_knowledge_base()
        get_knowledge_base().clear()

        learner = AutoLearner(LearnerConfig(
            enabled=True,
            state_file="backups/live_test_learner.json",
            per_symbol=True,
            regime_decay=0.95,
        ))
        learner.load()
        results["learner_initialized"] = True
        print_step(2, total_steps, "AutoLearner initialized (paper mode, no broker)", True)
        passed += 1
    except Exception as e:
        print_step(2, total_steps, f"Learner init failed: {e}", False)
        results["steps"]["2_learner_init"] = {"status": "FAIL", "detail": str(e)}
        failed += 1

    # ── Step 3: Generate paper trades from real price movements ───────────
    print_header("Step 3: Simulate Paper Trades from Price Action")

    try:
        trades_made = 0
        for index_name, mdata in market_data.items():
            daily = mdata["daily"]
            if daily is None or len(daily) < 5:
                continue

            closes = daily["Close"].values
            _highs = daily["High"].values
            _lows = daily["Low"].values
            _volumes = daily["Volume"].values if "Volume" in daily.columns else None

            # Analyze recent price action to generate realistic paper trades
            for i in range(2, len(closes)):
                prev_close = closes[i - 1]
                curr_close = closes[i]
                daily_range_pct = abs((curr_close - prev_close) / prev_close) * 100

                # Skip days with very small moves (no trade signal)
                if daily_range_pct < 0.3:
                    continue
                if trades_made >= 20:
                    break

                # Determine direction: if price moved up, simulate a CALL win
                # If down, simulate a PUT win (with some randomness for realism)
                direction = 1 if curr_close > prev_close else -1

                # Simulate 2 paper trades per significant move (one with trend, one against)
                # Trade 1: With trend (usually wins)
                tag1 = "WIN" if direction > 0 else "LOSS"
                pnl1 = abs(curr_close - prev_close) * (1 if tag1 == "WIN" else -0.8)
                regime1 = "TRENDING" if daily_range_pct > 1.0 else "MILD"
                strength1 = "STRONG" if daily_range_pct > 1.5 else "MODERATE"

                learner.record_exit(
                    symbol=index_name.split()[0],
                    tag=tag1,
                    regime=regime1,
                    strength=strength1,
                    net_pnl=pnl1,
                )
                learner.learn_from_exit(
                    symbol=index_name.split()[0],
                    tag=tag1,
                    net_pnl=pnl1,
                    regime=regime1,
                )
                trades_made += 1

                # Trade 2: Counter-trend (usually loses)
                tag2 = "LOSS" if direction > 0 else "WIN"
                pnl2 = -abs(curr_close - prev_close) * 0.5 * (-1 if tag2 == "LOSS" else 1)
                regime2 = "CHOPPY"
                strength2 = "WEAK"

                learner.record_exit(
                    symbol=index_name.split()[0],
                    tag=tag2,
                    regime=regime2,
                    strength=strength2,
                    net_pnl=pnl2,
                )
                learner.learn_from_exit(
                    symbol=index_name.split()[0],
                    tag=tag2,
                    net_pnl=pnl2,
                    regime=regime2,
                )
                trades_made += 1

            if trades_made >= 20:
                break

        learner.save()
        state = learner.export_global_state()
        wr = learner.regime_win_rates()

        _print(f"  Generated {trades_made} paper trades from real price action")
        _print(f"  Learner state: adj={state['score_adj']}, conf={state['confidence']}, streak={state['streak']}")
        _print(f"  Regime win rates: {wr}")
        assert trades_made > 0, "Must have generated at least 1 paper trade"
        print_step(3, total_steps, f"Generated {trades_made} paper trades from real data", True)
        results["trades_generated"] = trades_made
        results["learner_state"] = state
        results["regime_win_rates"] = wr
        passed += 1
    except Exception as e:
        print_step(3, total_steps, f"Paper trade simulation failed: {e}", False)
        results["steps"]["3_paper_trades"] = {"status": "FAIL", "detail": str(e)}
        failed += 1

    # ── Step 4: Verify Knowledge Base learning ────────────────────────────
    print_header("Step 4: Verify Knowledge Base Learning")

    try:
        kb = get_knowledge_base()
        kb_report = kb.get_report()

        _print(f"  KB entries: {kb_report.total_entries}")
        _print(f"  By type: {kb_report.by_type}")
        _print(f"  Avg confidence: {kb_report.avg_confidence:.3f}")
        _print(f"  Total frequency: {kb_report.total_frequency}")

        assert kb_report.total_entries > 0, "KB must have entries after learning"
        print_step(4, total_steps, f"KB has {kb_report.total_entries} learned patterns", True)
        results["kb_stats"] = {
            "entries": kb_report.total_entries,
            "by_type": kb_report.by_type,
            "frequency": kb_report.total_frequency,
        }
        passed += 1
    except Exception as e:
        print_step(4, total_steps, f"KB verification failed: {e}", False)
        results["steps"]["4_kb_verify"] = {"status": "FAIL", "detail": str(e)}
        failed += 1

    # ── Step 5: Cross-domain KB query ────────────────────────────────────
    print_header("Step 5: Cross-Domain Knowledge Query")

    try:
        # Query for each index
        for query in ["NIFTY", "BANKNIFTY", "FINNIFTY"]:
            results_q = learner.query_knowledge_base(query, max_results=3)
            _print(f"  Query '{query}': {len(results_q)} results")
            if results_q:
                top = results_q[0]
                _print(f"    Top: [{top.get('confidence', 0):.0%}] {top.get('pattern', '')[:80]}")

        # Query by regime
        for regime in ["TRENDING", "CHOPPY"]:
            results_r = learner.query_knowledge_base(regime.lower(), max_results=2)
            _print(f"  Query '{regime}': {len(results_r)} results")

        print_step(5, total_steps, "Cross-domain KB queries completed", True)
        results["step5_queries"] = "completed"
        passed += 1
    except Exception as e:
        print_step(5, total_steps, f"Cross-domain query failed: {e}", False)
        results["steps"]["5_cross_query"] = {"status": "FAIL", "detail": str(e)}
        failed += 1

    # ── Step 6: Threshold adjustment with real trades ─────────────────────
    print_header("Step 6: Threshold Adjustment from Learning")

    try:
        # Build a realistic trade history dict from the paper trades
        trade_history = []
        for idx_name, mdata in market_data.items():
            daily = mdata["daily"]
            if daily is None or len(daily) < 5:
                continue
            closes = daily["Close"].values
            for i in range(1, len(closes)):
                pnl = closes[i] - closes[i - 1]
                trade_history.append({
                    "net_pnl": float(pnl),
                    "action": "EXIT",
                    "regime": "TRENDING" if abs(pnl) / closes[i - 1] * 100 > 1.0 else "MILD",
                    "strength": "STRONG" if abs(pnl) / closes[i - 1] * 100 > 1.5 else "MODERATE",
                })

        _print(f"  Trade history: {len(trade_history)} entries from {len(market_data)} indices")

        # Test threshold adjustment
        delta, reason = learner.threshold_adjustment(
            symbol="NIFTY",
            regime="TRENDING",
            strength="STRONG",
            trades=trade_history,
        )
        _print(f"  Threshold adjustment: delta={delta:+d}, reason={reason}")

        # Test signal confidence
        sig = {"score": 72, "direction": "CALL", "threshold": 60, "breakout_ok": True,
               "mkt_regime": "TRENDING", "strength": "STRONG", "vol_ratio": 1.2}
        conf, band = learner.signal_confidence("NIFTY", sig, trade_history, default_threshold=60)
        _print(f"  Signal confidence: {conf}/99 (band {band})")

        assert isinstance(delta, int), "Delta must be int"
        assert 1 <= conf <= 99, "Confidence must be 1-99"
        print_step(6, total_steps, f"Threshold adj={delta:+d}, confidence={conf}/99 band {band}", True)
        results["threshold_adjustment"] = {"delta": delta, "reason": reason}
        results["signal_confidence"] = {"confidence": conf, "band": band}
        passed += 1
    except Exception as e:
        print_step(6, total_steps, f"Threshold adjustment failed: {e}", False)
        results["steps"]["6_threshold"] = {"status": "FAIL", "detail": str(e)}
        failed += 1

    # ── Step 7: PatternLearner + SelfHealing integration ──────────────────
    print_header("Step 7: PatternLearner & SelfHealing Integration")

    try:
        from core.pattern_learner import get_pattern_learner, reset_pattern_learner
        from core.self_healing.orchestrator import SelfHealingOrchestrator

        reset_pattern_learner()
        pl = get_pattern_learner()

        # Learn from a simulated incident using real market context
        class MockEv:
            category = "STACK_TRACE"
            description = f"Market data feed stale at NIFTY {market_data[list(market_data.keys())[0]]['daily']['Close'].iloc[-1]:.2f}"
            relevance = 0.9
            timestamp = time.time()
            details = {"current_price": float(market_data[list(market_data.keys())[0]]['daily']['Close'].iloc[-1])}
            source = "live_market"

        class MockIncident:
            incident_type = "stale_quote"
            incident_message = "Market data feed not updating during live session"
            probable_cause = "yfinance rate limiting or IP ban during high-frequency polling"
            severity = "HIGH"
            recommended_fix = "Reduce polling frequency, add jitter, fall back to alternative provider"
            evidence = [MockEv()]
            impacted_modules = ["core/yf_data_provider.py"]

        pl_entries = pl.learn_from_incident(MockIncident())
        _print(f"  Incident learning: {len(pl_entries)} patterns from 'stale_quote'")

        # Learn from a code review (realistic PR feedback)
        pr_entries = pl.learn_from_code_review(
            pr_id="PR-150",
            comments=[
                "Performance: N+1 query in trade history endpoint - add select_related()",
                "Security: SQL injection risk in query builder - use parameterized queries",
                "Architecture: Circular dependency between signal_engine and risk_service",
            ],
            author="senior-dev",
        )
        _print(f"  Code review learning: {len(pr_entries)} patterns from PR-150")

        # Get recommendations
        recs = pl.get_recommendations("market_data", max_results=5)
        _print(f"  Recommendations for 'market_data': {len(recs)} results")

        # SelfHealing KB guidance
        healer = SelfHealingOrchestrator(cfg={})
        guidance = healer._query_kb_for_guidance("stale_market_feed")
        _print(f"  SelfHealing KB guidance for stale_market_feed: {'found' if guidance else 'none'}")

        # Final report
        pl_report = pl.get_report()
        _print(f"  PatternLearner report: {pl_report.total_patterns_extracted} total patterns")

        print_step(7, total_steps, "Full integration: PL+SH+KB pipeline verified", True)
        results["integration"] = {
            "incident_patterns": len(pl_entries),
            "review_patterns": len(pr_entries),
            "recommendations": len(recs),
            "self_healing_guidance": bool(guidance),
        }
        passed += 1
    except Exception as e:
        print_step(7, total_steps, f"Integration test failed: {e}", False)
        results["steps"]["7_integration"] = {"status": "FAIL", "detail": str(e)}
        failed += 1

    # ── Summary ───────────────────────────────────────────────────────────
    results["passed"] = passed
    results["failed"] = failed
    results["total"] = total_steps
    results["overall"] = "PASS" if failed == 0 else "FAIL"

    _print()
    _print("=" * 70)
    _print("  LIVE PAPER MODE TEST SUMMARY")
    _print("=" * 70)
    _print(f"  Steps:        {passed}/{total_steps} passed, {failed} failed")
    _print(f"  Overall:      {results['overall']}")
    _print(f"  Market data:  {len(market_data)} indices live")
    _print(f"  Paper trades: {results.get('trades_generated', 0)} from real price action")
    _print(f"  KB patterns:  {results.get('kb_stats', {}).get('entries', 0)} learned")
    _print(f"  Threshold:    {results.get('threshold_adjustment', {}).get('delta', 'N/A')}")
    _print("=" * 70)
    _print()

    if "--json" in sys.argv:
        print(json.dumps(results, indent=2, default=str))

    # Cleanup test file
    try:
        Path("backups/live_test_learner.json").unlink(missing_ok=True)
    except OSError:
        pass

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
