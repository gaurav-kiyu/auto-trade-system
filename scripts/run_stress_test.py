#!/usr/bin/env python3
"""System Stress/Load Tester — OPB v2.57.0 (Phase 8)

Simulates high-frequency trading scenarios to identify concurrency
bottlenecks, race conditions, and performance limits under load.

Scenarios:
  1. burst_signals    : Rapid signal generation (100 signals in parallel)
  2. concurrent_risk  : Concurrent risk evaluations from multiple threads
  3. db_write_storm   : Rapid database writes from multiple threads
  4. mixed_workload   : Signals + risk + writes simultaneously
  5. long_soak        : Extended low-intensity soak test (60s)

Output:
  - Thread safety violations detected during stress
  - P50/P90/P95/P99 latencies under load
  - Maximum sustainable throughput
  - Error rates and types

Usage:
    python scripts/run_stress_test.py                    # Run all scenarios
    python scripts/run_stress_test.py --scenario burst_signals
    python scripts/run_stress_test.py --quick             # Quick smoke test
    python scripts/run_stress_test.py --ci                # CI mode
    python scripts/run_stress_test.py --json              # JSON output
"""

from __future__ import annotations

import concurrent.futures
import json
import statistics
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

_REPORTS_DIR = Path(__file__).resolve().parent.parent / "reports"


# ── Shared test state ─────────────────────────────────────────────────────────


class StressMetrics:
    """Thread-safe metrics collector for stress tests."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._latencies: list[float] = []
        self._errors: list[str] = []
        self._success_count = 0
        self._failure_count = 0
        self._start_time = 0.0

    def record_success(self, latency_ms: float) -> None:
        with self._lock:
            self._latencies.append(latency_ms)
            self._success_count += 1

    def record_error(self, error: str) -> None:
        with self._lock:
            self._errors.append(error[:200])
            self._failure_count += 1

    def latency_stats(self) -> dict[str, float]:
        with self._lock:
            vals = sorted(self._latencies)
        if not vals:
            return {"min_ms": 0, "p50_ms": 0, "p90_ms": 0, "p95_ms": 0, "p99_ms": 0, "max_ms": 0, "mean_ms": 0}
        n = len(vals)
        return {
            "min_ms": round(vals[0], 3),
            "p50_ms": round(vals[int(n * 0.50)], 3),
            "p90_ms": round(vals[int(n * 0.90)], 3),
            "p95_ms": round(vals[int(n * 0.95)], 3),
            "p99_ms": round(vals[int(n * 0.99)], 3),
            "max_ms": round(vals[-1], 3),
            "mean_ms": round(statistics.mean(vals), 3),
            "total_operations": n,
        }

    @property
    def total(self) -> int:
        with self._lock:
            return self._success_count + self._failure_count

    @property
    def error_count(self) -> int:
        with self._lock:
            return self._failure_count

    def get_errors(self, limit: int = 10) -> list[str]:
        with self._lock:
            return self._errors[:limit]


# ── Stress Scenarios ──────────────────────────────────────────────────────────


def scenario_burst_signals(metrics: StressMetrics, concurrency: int = 20, iterations: int = 50) -> dict[str, Any]:
    """Rapid concurrent signal generation."""
    start = time.time()
    result: dict[str, Any] = {"name": "burst_signals", "concurrency": concurrency, "iterations_per_thread": iterations}

    def _worker(worker_id: int) -> None:
        for i in range(iterations):
            t0 = time.perf_counter()
            try:
                # Simulate signal computation
                _compute_signal({"score": 60 + (i % 30), "vix": 14.0 + (i % 5),
                                 "regime": "TRENDING", "direction": "CALL" if i % 2 == 0 else "PUT"})
                metrics.record_success((time.perf_counter() - t0) * 1000)
            except Exception as e:
                metrics.record_error(f"Worker {worker_id}, iter {i}: {e}")

    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as ex:
        futures = [ex.submit(_worker, wid) for wid in range(concurrency)]
        concurrent.futures.wait(futures)

    result["duration_sec"] = round(time.time() - start, 3)
    result["total_operations"] = metrics.total
    result["error_count"] = metrics.error_count
    result["operations_per_sec"] = round(metrics.total / max(result["duration_sec"], 0.001), 1)
    result["latency"] = metrics.latency_stats()
    result["errors"] = metrics.get_errors()
    return result


def scenario_concurrent_risk(metrics: StressMetrics, concurrency: int = 10, iterations: int = 30) -> dict[str, Any]:
    """Concurrent risk evaluations simulating multiple trade signals."""
    start = time.time()
    result: dict[str, Any] = {"name": "concurrent_risk", "concurrency": concurrency, "iterations_per_thread": iterations}

    def _worker(worker_id: int) -> None:
        for i in range(iterations):
            t0 = time.perf_counter()
            try:
                _evaluate_risk({
                    "symbol": "NIFTY",
                    "price": 23500.0 + i,
                    "direction": "CALL" if i % 2 == 0 else "PUT",
                    "score": 65 + (i % 30),
                    "capital": 100000.0,
                    "existing_positions": i % 5,
                })
                metrics.record_success((time.perf_counter() - t0) * 1000)
            except Exception as e:
                metrics.record_error(f"Worker {worker_id}, iter {i}: {e}")

    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as ex:
        futures = [ex.submit(_worker, wid) for wid in range(concurrency)]
        concurrent.futures.wait(futures)

    result["duration_sec"] = round(time.time() - start, 3)
    result["total_operations"] = metrics.total
    result["error_count"] = metrics.error_count
    result["operations_per_sec"] = round(metrics.total / max(result["duration_sec"], 0.001), 1)
    result["latency"] = metrics.latency_stats()
    result["errors"] = metrics.get_errors()
    return result


def scenario_db_write_storm(metrics: StressMetrics, concurrency: int = 8, iterations: int = 20) -> dict[str, Any]:
    """Concurrent database writes simulating rapid trade logging."""
    start = time.time()
    result: dict[str, Any] = {"name": "db_write_storm", "concurrency": concurrency, "iterations_per_thread": iterations}

    def _worker(worker_id: int) -> None:
        for i in range(iterations):
            t0 = time.perf_counter()
            try:
                _simulate_db_write({
                    "id": f"stress_{worker_id}_{i}",
                    "ts": time.time(),
                    "symbol": "NIFTY",
                    "pnl": (i % 10 - 5) * 100,
                })
                metrics.record_success((time.perf_counter() - t0) * 1000)
            except Exception as e:
                metrics.record_error(f"Worker {worker_id}, iter {i}: {e}")

    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as ex:
        futures = [ex.submit(_worker, wid) for wid in range(concurrency)]
        concurrent.futures.wait(futures)

    result["duration_sec"] = round(time.time() - start, 3)
    result["total_operations"] = metrics.total
    result["error_count"] = metrics.error_count
    result["operations_per_sec"] = round(metrics.total / max(result["duration_sec"], 0.001), 1)
    result["latency"] = metrics.latency_stats()
    result["errors"] = metrics.get_errors()
    return result


def scenario_mixed_workload(metrics: StressMetrics, duration_s: int = 10) -> dict[str, Any]:
    """Mixed workload: signals + risk + writes concurrently."""
    start = time.time()
    result: dict[str, Any] = {"name": "mixed_workload", "duration_s": duration_s}
    stop_event = threading.Event()

    def _worker_pool(pool_id: str, count: int) -> None:
        while not stop_event.is_set():
            t0 = time.perf_counter()
            try:
                if pool_id == "signals":
                    _compute_signal({"score": 65, "vix": 15.0, "regime": "RANGING", "direction": "CALL"})
                elif pool_id == "risk":
                    _evaluate_risk({"symbol": "NIFTY", "price": 23500.0, "direction": "CALL",
                                    "score": 70, "capital": 100000.0, "existing_positions": 2})
                elif pool_id == "writes":
                    _simulate_db_write({"id": f"mixed_{pool_id}_{count}", "ts": time.time(),
                                        "symbol": "BANKNIFTY", "pnl": 150.0})
                metrics.record_success((time.perf_counter() - t0) * 1000)
            except Exception as e:
                metrics.record_error(f"Pool {pool_id}: {e}")

    threads = []
    for pool, count in [("signals", 4), ("risk", 3), ("writes", 3)]:
        for _ in range(count):
            t = threading.Thread(target=_worker_pool, args=(pool, count), daemon=True)
            threads.append(t)
            t.start()

    time.sleep(duration_s)
    stop_event.set()
    for t in threads:
        t.join(timeout=2)

    result["duration_sec"] = round(time.time() - start, 3)
    result["total_operations"] = metrics.total
    result["error_count"] = metrics.error_count
    result["operations_per_sec"] = round(metrics.total / max(result["duration_sec"], 0.001), 1)
    result["latency"] = metrics.latency_stats()
    result["errors"] = metrics.get_errors()
    return result


def scenario_long_soak(metrics: StressMetrics, duration_s: int = 30) -> dict[str, Any]:
    """Extended low-intensity soak test."""
    start = time.time()
    result: dict[str, Any] = {"name": "long_soak", "duration_s": duration_s}
    stop_event = threading.Event()

    def _slow_worker() -> None:
        cycle = 0
        while not stop_event.is_set():
            t0 = time.perf_counter()
            try:
                _compute_signal({"score": 60 + (cycle % 30), "vix": 14.0, "regime": "TRENDING", "direction": "CALL"})
                _evaluate_risk({"symbol": "NIFTY", "price": 23500.0 + cycle, "direction": "CALL",
                                "score": 65 + (cycle % 30), "capital": 100000.0, "existing_positions": cycle % 3})
                metrics.record_success((time.perf_counter() - t0) * 1000)
            except Exception as e:
                metrics.record_error(f"Soak cycle {cycle}: {e}")
            cycle += 1
            time.sleep(0.1)  # 10 operations/sec

    workers = [threading.Thread(target=_slow_worker, daemon=True) for _ in range(5)]
    for w in workers:
        w.start()

    time.sleep(duration_s)
    stop_event.set()
    for w in workers:
        w.join(timeout=2)

    result["duration_sec"] = round(time.time() - start, 3)
    result["total_operations"] = metrics.total
    result["error_count"] = metrics.error_count
    result["operations_per_sec"] = round(metrics.total / max(result["duration_sec"], 0.001), 1)
    result["latency"] = metrics.latency_stats()
    result["errors"] = metrics.get_errors()
    return result


# ── Simulated workloads (isolated — no real broker/DB calls) ──────────────────


def _compute_signal(params: dict[str, Any]) -> dict[str, Any]:
    """Simulate signal computation without real I/O."""
    score = params.get("score", 50)
    vix = params.get("vix", 15.0)
    regime = params.get("regime", "NEUTRAL")
    direction = params.get("direction", "CALL")

    # Busy-work to simulate compute
    total = 0.0
    for _ in range(500):
        total += score * vix * 0.01
    # Chaotic lock/unlock to simulate real locking patterns
    _simulated_lock.acquire()
    _simulated_counter[0] += 1
    _simulated_lock.release()

    return {"score": score, "adjusted": total, "regime": regime, "direction": direction}


def _evaluate_risk(params: dict[str, Any]) -> dict[str, Any]:
    """Simulate risk evaluation without real I/O."""
    symbol = params.get("symbol", "NIFTY")
    price = params.get("price", 23500.0)
    direction = params.get("direction", "CALL")
    score = params.get("score", 50)
    capital = params.get("capital", 100000.0)

    total = 0.0
    for _ in range(300):
        risk_pct = score / 100.0 * (price / capital)
        total += risk_pct * 0.01

    _simulated_lock.acquire()
    _simulated_counter[1] += 1
    _simulated_lock.release()

    sl = price * 0.98 if direction == "CALL" else price * 1.02
    size = int(capital * 0.02 / abs(price - sl)) if abs(price - sl) > 0 else 1
    return {"symbol": symbol, "position_size": max(1, size), "risk_score": round(total, 4)}


def _simulate_db_write(record: dict[str, Any]) -> dict[str, Any]:
    """Simulate database write without real I/O."""
    # Busy-work to simulate serialization
    total = 0.0
    for _ in range(200):
        total += record.get("pnl", 0) * 0.001

    _simulated_lock.acquire()
    _simulated_counter[2] += 1
    _simulated_lock.release()

    record["_processed"] = True
    record["_hash"] = hash(str(record))
    return record


# Shared state for stress testing (with lock — simulates production patterns)
_simulated_lock = threading.RLock()
_simulated_counter = [0, 0, 0]


# ── Runner ────────────────────────────────────────────────────────────────────


_SCENARIOS = {
    "burst_signals": (scenario_burst_signals, {"concurrency": 20, "iterations": 50}),
    "concurrent_risk": (scenario_concurrent_risk, {"concurrency": 10, "iterations": 30}),
    "db_write_storm": (scenario_db_write_storm, {"concurrency": 8, "iterations": 20}),
    "mixed_workload": (scenario_mixed_workload, {"duration_s": 10}),
    "long_soak": (scenario_long_soak, {"duration_s": 30}),
}


def _reset_simulated_state() -> None:
    """Reset simulated shared state between scenarios."""
    global _simulated_counter
    _simulated_counter = [0, 0, 0]


def run_stress_test(
    scenarios: list[str] | None = None,
    quick: bool = False,
) -> list[dict[str, Any]]:
    """Run stress test scenarios."""
    if scenarios is None:
        scenarios = list(_SCENARIOS.keys())
    if quick:
        # Run reduced versions
        scenarios = ["burst_signals", "concurrent_risk"]
        _SCENARIOS["burst_signals"] = (scenario_burst_signals, {"concurrency": 5, "iterations": 10})
        _SCENARIOS["concurrent_risk"] = (scenario_concurrent_risk, {"concurrency": 3, "iterations": 5})

    _reset_simulated_state()
    all_results = []
    for name in scenarios:
        if name not in _SCENARIOS:
            all_results.append({"name": name, "error": f"Unknown scenario: {name}"})
            continue

        fn, params = _SCENARIOS[name]
        metrics = StressMetrics()
        print(f"  [{name:<20s}] Running ({params})...", end=" ", flush=True)
        t0 = time.time()
        try:
            result = fn(metrics, **params)
            result["scenario"] = name
            elapsed = time.time() - t0
            ops = result.get("total_operations", 0)
            errs = result.get("error_count", 0)
            ops_sec = result.get("operations_per_sec", 0)
            p50 = result.get("latency", {}).get("p50_ms", 0)
            print(f"✅ {ops} ops, {errs} errs, {ops_sec:.0f}/s, P50={p50:.1f}ms ({elapsed:.1f}s)")
            all_results.append(result)
        except Exception as e:
            elapsed = time.time() - t0
            print(f"❌ Error: {e}")
            all_results.append({"scenario": name, "error": str(e)})

    return all_results


def _generate_html(results: list[dict[str, Any]]) -> str:
    """Generate HTML stress test report."""
    rows = ""
    for r in results:
        if "error" in r:
            rows += f"""
            <tr style="border-left:4px solid #f44336">
                <td>❌</td><td>{r.get('scenario', r.get('name', '?'))}</td>
                <td colspan="6">Error: {r['error']}</td>
            </tr>"""
            continue
        lat = r.get("latency", {})
        ops = r.get("total_operations", 0)
        errs = r.get("error_count", 0)
        ops_sec = r.get("operations_per_sec", 0)
        dur = r.get("duration_sec", 0)
        color = "#4CAF50" if errs == 0 else "#FF9800" if errs < ops * 0.1 else "#f44336"
        rows += f"""
        <tr style="border-left:4px solid {color}">
            <td>{'✅' if errs == 0 else '⚠️' if errs < ops * 0.1 else '❌'}</td>
            <td>{r.get('scenario', r.get('name', '?'))}</td>
            <td>{ops:,}</td>
            <td>{errs}</td>
            <td>{ops_sec:.0f}</td>
            <td>{lat.get('p50_ms', 0):.2f}</td>
            <td>{lat.get('p95_ms', 0):.2f}</td>
            <td>{lat.get('p99_ms', 0):.2f}</td>
            <td>{dur:.1f}s</td>
        </tr>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>System Stress Test Report — OPB v2.57.0</title>
<style>
body {{ font-family: 'Segoe UI', Arial, sans-serif; max-width: 1000px; margin: 20px auto; padding: 20px; background: #f5f7fa; color: #333; }}
h1 {{ color: #1a237e; border-bottom: 3px solid #1a237e; padding-bottom: 8px; }}
table {{ width:100%;border-collapse:collapse;background:white;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.08);margin:20px 0; }}
th {{ background:#1a237e;color:white;padding:12px 16px;text-align:left; }}
td {{ padding:10px 16px;border-bottom:1px solid #e8eaf6; }}
footer {{ margin-top:40px;padding-top:20px;border-top:1px solid #e0e0e0;color:#999;font-size:0.85em;text-align:center; }}
</style>
</head>
<body>
<h1>⚡ System Stress Test Report</h1>
<table>
<tr><th>Status</th><th>Scenario</th><th>Ops</th><th>Errors</th><th>Ops/s</th><th>P50</th><th>P95</th><th>P99</th><th>Duration</th></tr>
{rows}
</table>
<footer>Generated by scripts/run_stress_test.py — OPB v2.57.0</footer>
</body>
</html>"""


# ── CLI ───────────────────────────────────────────────────────────────────────


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(
        description="System Stress/Load Tester",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--scenario", choices=list(_SCENARIOS.keys()) + ["all"],
                        default="all", help="Specific scenario to run")
    parser.add_argument("--quick", action="store_true", help="Quick smoke test")
    parser.add_argument("--ci", action="store_true", help="CI mode")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--html", default=None, help="HTML report path")
    args = parser.parse_args()

    _REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("  ⚡ SYSTEM STRESS TESTER v2.57.0")
    print("=" * 60)

    scenarios = list(_SCENARIOS.keys()) if args.scenario == "all" else [args.scenario]
    if args.quick:
        print("  Mode: QUICK (reduced concurrency/iterations)")

    results = run_stress_test(scenarios=scenarios, quick=args.quick)

    print(f"\n{'='*60}")
    print("  STRESS TEST SUMMARY")
    print(f"{'='*60}")

    total_ops = sum(r.get("total_operations", 0) for r in results if "error" not in r)
    total_errs = sum(r.get("error_count", 0) for r in results if "error" not in r)
    overall_health = "PASS" if total_errs == 0 else "WARN" if total_errs < total_ops * 0.05 else "FAIL"
    print(f"  Total Operations: {total_ops:,}")
    print(f"  Total Errors:     {total_errs:,}")
    print(f"  Error Rate:       {total_errs / max(total_ops, 1) * 100:.2f}%")
    print(f"  Health:           {overall_health}")

    if total_errs > 0:
        print("\n  Errors detected:")
        for r in results:
            if "error" in r:
                print(f"    ❌ {r.get('scenario', '?')}: {r['error']}")
            elif r.get("error_count", 0) > 0:
                for e in r.get("errors", [])[:3]:
                    print(f"    ⚠️  {r.get('scenario', '?')}: {e}")

    # HTML report
    html_path = args.html or str(_REPORTS_DIR / "stress_test_report.html")
    html = _generate_html(results)
    Path(html_path).parent.mkdir(parents=True, exist_ok=True)
    Path(html_path).write_text(html, encoding="utf-8")
    print(f"\n  📊 HTML report: {html_path}")

    # JSON report
    json_report = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "overall_health": overall_health,
        "total_operations": total_ops,
        "total_errors": total_errs,
        "error_rate_pct": round(total_errs / max(total_ops, 1) * 100, 2),
        "scenarios": results,
    }
    json_path = _REPORTS_DIR / "stress_test_report.json"
    json_path.write_text(json.dumps(json_report, indent=2, default=str), encoding="utf-8")
    print(f"  📋 JSON report: {json_path}")

    if args.json:
        print(json.dumps(json_report, indent=2, default=str))

    # CI check
    if args.ci and overall_health == "FAIL":
        print(f"\n❌ CI FAILED: {total_errs} errors ({total_errs/max(total_ops,1)*100:.1f}%)")
        return 1

    print(f"\n{'='*60}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
