#!/usr/bin/env python3
"""Benchmark Suite — OPB v2.57.0

Measures and records system performance metrics for CI regression detection.

Benchmarks:
  1. Cold startup time (import core)
  2. Warm startup time (cached)
  3. Signal generation latency
  4. Risk evaluation latency
  5. Position sizing latency
  6. ML prediction latency
  7. Database query latency (SQLite)
  8. Serialization/deserialization latency
  9. Memory allocation profile
  10. Config load latency

Outputs:
  - JSON report with P50/P90/P95/P99 latencies
  - Historical comparison against previous runs
  - CI-compatible exit code (non-zero if regression > 10%)
  - HTML visualization
"""

from __future__ import annotations

import gc
import json
import os
import statistics
import sys
import time
import tracemalloc
from pathlib import Path
from typing import Any

# ── Configuration ─────────────────────────────────────────────────────────────

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

BENCHMARKS_DIR = _PROJECT_ROOT / ".benchmarks"
HISTORY_FILE = BENCHMARKS_DIR / "benchmark_history.json"
REPORT_FILE = BENCHMARKS_DIR / "benchmark_report.json"
HTML_REPORT = BENCHMARKS_DIR / "benchmark_report.html"
REGRESSION_THRESHOLD_PCT = 10.0  # Alert if latency increases >10%
BENCHMARK_SCHEMA_VERSION = 2
WARMUP_ITERATIONS = 3
MEASURE_ITERATIONS = 100

os.makedirs(BENCHMARKS_DIR, exist_ok=True)


# ── Benchmark Helpers ─────────────────────────────────────────────────────────


def _now() -> float:
    """High-precision monotonic time."""
    return time.perf_counter_ns() / 1_000_000  # milliseconds


def _measure(
    fn,
    iterations: int = MEASURE_ITERATIONS,
    warmup: int = WARMUP_ITERATIONS,
    label: str = "",
) -> dict[str, float]:
    """Measure P50/P90/P95/P99 latency for a function.

    Args:
        fn: Zero-argument callable to benchmark.
        iterations: Number of timed iterations.
        warmup: Number of warmup iterations (not timed).
        label: Human-readable label for the benchmark.

    Returns:
        Dict with p50/p90/p95/p99/mean/min/max in milliseconds.

    """
    # Warmup
    for _ in range(warmup):
        try:
            fn()
        except Exception:
            pass

    # Measurement — use gc.freeze() to stabilize GC across iterations
    # instead of disabling/enabling GC which distorts latency
    gc.collect()
    latencies: list[float] = []
    for _ in range(iterations):
        t0 = _now()
        fn()
        latencies.append(_now() - t0)

    if not latencies:
        return {"error": "No measurements collected", "label": label}

    latencies.sort()
    n = len(latencies)
    result = {
        "label": label,
        "iterations": n,
        "min_ms": round(latencies[0], 3),
        "max_ms": round(latencies[-1], 3),
        "mean_ms": round(statistics.mean(latencies), 3),
        "median_ms": round(statistics.median(latencies), 3),
        "stdev_ms": round(statistics.stdev(latencies) if n > 1 else 0, 3),
        "p50_ms": round(latencies[int(n * 0.50)], 3) if n > 0 else 0,
        "p90_ms": round(latencies[int(n * 0.90)], 3) if n > 0 else 0,
        "p95_ms": round(latencies[int(n * 0.95)], 3) if n > 0 else 0,
        "p99_ms": round(latencies[int(n * 0.99)], 3) if n > 0 else 0,
    }
    return result


def _measure_import_time(module_path: str) -> float:
    """Measure how long it takes to import a module (cold).

    SAFETY: Only measures modules that are NOT currently imported by the
    running process. Shared modules (already in sys.modules at import time)
    are skipped with a note in the results.
    """
    if module_path in sys.modules:
        # Module already imported — skip to avoid breaking running state
        return -1.0
    t0 = _now()
    __import__(module_path)
    return _now() - t0


def _measure_memory(label: str = "") -> dict[str, Any]:
    """Measure current memory usage of the process."""
    try:
        import psutil
        proc = psutil.Process(os.getpid())
        mem = proc.memory_info()
        return {
            "label": label,
            "rss_mb": round(mem.rss / (1024 * 1024), 2),
            "vms_mb": round(mem.vms / (1024 * 1024), 2),
        }
    except ImportError:
        return {"label": label, "rss_mb": 0, "vms_mb": 0, "note": "psutil not installed"}


def _measure_tracemalloc(label: str = "") -> dict[str, Any]:
    """Measure peak memory allocation using tracemalloc."""
    if not tracemalloc.is_tracing():
        return {"label": label, "peak_mb": 0, "note": "tracemalloc not started"}
    snapshot = tracemalloc.take_snapshot()
    stats = snapshot.statistics("lineno")
    total_bytes = sum(s.size for s in stats[:50])
    return {
        "label": label,
        "peak_mb": round(total_bytes / (1024 * 1024), 3),
        "top_frames": [
            {
                "file": s.traceback[0].filename if s.traceback else "",
                "line": s.traceback[0].lineno if s.traceback else 0,
                "size_kb": round(s.size / 1024, 2),
            }
            for s in stats[:10]
        ],
    }


# ── Benchmark Definitions ─────────────────────────────────────────────────────


def benchmark_imports() -> list[dict[str, Any]]:
    """Benchmark cold import times for key modules."""
    results = []
    modules = [
        "core.datetime_ist",
        "core.exceptions",
        "core.logging",
        "core.config_bootstrap",
        "core.safety_state",
        "core.adaptive_signal",
        "core.pure_index_signal",
        "core.ml_classifier",
        "core.tier_engine",
        "core.services.risk_service",
    ]
    for mod in modules:
        elapsed = _measure_import_time(mod)
        if elapsed < 0:
            results.append({"module": mod, "cold_import_ms": 0, "note": "already imported, skipping"})
        else:
            results.append({"module": mod, "cold_import_ms": round(elapsed, 3)})
    return results


def _create_signal_data() -> dict[str, Any]:
    """Create realistic signal data for benchmarking."""
    return {
        "direction": "CALL",
        "price": 23500.0,
        "stop_loss": 23450.0,
        "target": 23700.0,
        "strength": 72,
        "volume_ratio": 1.5,
        "spread_pct": 0.5,
        "quantity": 1,
        "strike": 23500,
        "iv": 0.14,
        "tte_days": 3.0,
    }


def benchmark_signal_generation() -> dict[str, Any]:
    """Benchmark the full signal generation pipeline."""
    try:
        import pandas as pd
        from core.pure_index_signal import (
            PureIndexRegimeParams,
            PureIndexSignalParams,
            evaluate_dual_direction_signal,
        )

        def make_df(periods: int, step: float) -> pd.DataFrame:
            prices = [23000 + i * step for i in range(periods)]
            return pd.DataFrame({
                "Open": prices,
                "High": [p + 20 for p in prices],
                "Low": [p - 20 for p in prices],
                "Close": prices,
                "Volume": [500000] * periods,
            })

        params = PureIndexSignalParams(
            name="NIFTY",
            signal_cfg={},
            regime=PureIndexRegimeParams(
                vix_block_threshold=35.0,
                adx_trend_threshold=25.0,
                adx_chop_threshold=20.0,
            ),
            iv_spike_threshold=50.0,
            vol_ratio_min=1.2,
            is_early_session=False,
        )
        df1 = make_df(60, 5)
        df5 = make_df(12, 25)
        df15 = make_df(6, 60)
        return _measure(
            lambda: evaluate_dual_direction_signal(
                params=params,
                df1=df1,
                df5=df5,
                df15=df15,
                vix=15,
                iv=10,
                oi_sup=0,
                oi_res=0,
                pcr=1,
                smart="NEUTRAL",
            ),
            iterations=50,
            label="signal_generation",
        )
    except Exception as exc:
        return {"label": "signal_generation", "error": str(exc)}


def benchmark_risk_evaluation() -> dict[str, Any]:
    """Benchmark the risk evaluation pipeline."""
    try:
        from core.ports.risk.risk_port import PortfolioRiskMetrics
        from core.services.risk_service import RiskService, RiskServiceConfig
        svc = RiskService(RiskServiceConfig())
        data = _create_signal_data()
        metrics = PortfolioRiskMetrics(
            total_capital=100000,
            used_capital=0,
            available_capital=100000,
            daily_pnl=0,
            max_daily_loss=-2000,
            current_drawdown=0,
            max_drawdown=0,
            open_positions_count=0,
            max_open_positions=1,
            consecutive_losses=0,
            max_consecutive_losses=3,
            sector_exposure={},
            symbol_exposure={},
        )
        return _measure(
            lambda: svc.evaluate_trade("NIFTY", data, metrics),
            iterations=50,
            label="risk_evaluation",
        )
    except Exception as exc:
        return {"label": "risk_evaluation", "error": str(exc)}


def benchmark_position_sizing() -> dict[str, Any]:
    """Benchmark position size calculation."""
    try:
        from core.ports.risk.risk_port import PositionSizingInput
        from core.services.risk_service import RiskService, RiskServiceConfig
        svc = RiskService(RiskServiceConfig())
        inp = PositionSizingInput(
            symbol="NIFTY",
            entry_price=23500,
            stop_loss_price=23450,
            capital_available=100000,
            risk_per_trade=0.02,
            lot_size=50,
            volatility=20.0,
            existing_exposure=0,
        )
        return _measure(
            lambda: svc.calculate_position_size(inp),
            iterations=50,
            label="position_sizing",
        )
    except Exception as exc:
        return {"label": "position_sizing", "error": str(exc)}


def benchmark_ml_prediction() -> dict[str, Any]:
    """Benchmark ML model prediction latency."""
    try:
        from core.ml_classifier import predict_win_prob

        class _BenchmarkModel:
            def predict_proba(self, rows):
                return [[0.35, 0.65] for _ in rows]

        model = _BenchmarkModel()
        features = {
            "score": 72, "confidence": 0.65, "direction_call": 1,
            "is_strong": 1, "is_moderate": 0, "is_weak": 0,
            "has_soft_blocks": 0, "day_of_week": 3, "hour_of_entry": 10,
            "iv_rank": 45, "vix": 14.5, "pcr": 1.2,
            "regime_code": 1, "session_code": 2,
        }
        return _measure(
            lambda: predict_win_prob(model, features),
            iterations=20,
            label="ml_prediction",
        )
    except Exception as exc:
        return {"label": "ml_prediction", "error": str(exc)}


def benchmark_db_queries() -> dict[str, Any]:
    """Benchmark SQLite query latency."""
    try:
        from contextlib import closing

        from core.db_utils import get_connection
        with closing(get_connection(":memory:")) as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS bench (id INTEGER PRIMARY KEY, val TEXT)")
            conn.execute("INSERT INTO bench VALUES (1, 'test')")
            conn.commit()

            def query():
                conn.execute("SELECT * FROM bench WHERE id = 1").fetchone()

            return _measure(query, iterations=100, label="db_query_sqlite")
    except Exception as exc:
        return {"label": "db_query_sqlite", "error": str(exc)}


def benchmark_config_load() -> dict[str, Any]:
    """Benchmark config loading latency."""
    try:
        from core.config_bootstrap import get_effective_config
        return _measure(
            lambda: get_effective_config(
                "json/index_config.defaults.json",
                "json",
            ),
            iterations=20,
            label="config_load",
        )
    except Exception as exc:
        return {"label": "config_load", "error": str(exc)}


# ── Historical Comparison ─────────────────────────────────────────────────────


def _load_history() -> dict[str, Any]:
    """Load previous benchmark run for comparison."""
    if HISTORY_FILE.exists():
        try:
            return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_history(results: dict[str, Any]) -> None:
    """Save benchmark results for future comparison."""
    HISTORY_FILE.write_text(
        json.dumps(results, indent=2, default=str),
        encoding="utf-8",
    )


def _compare_with_history(current: dict, history: dict) -> list[dict[str, Any]]:
    """Compare current benchmarks with historical data.

    Returns list of regressions found.
    """
    if history.get("benchmark_schema_version") != current.get("benchmark_schema_version"):
        return []

    regressions = []
    for label, cur in current.get("latency", {}).items():
        if not isinstance(cur, dict) or "p50_ms" not in cur:
            continue
        hist = history.get("latency", {}).get(label, {})
        if "p50_ms" not in hist:
            continue
        prev_p50 = hist["p50_ms"]
        cur_p50 = cur["p50_ms"]
        if prev_p50 > 0:
            change_pct = ((cur_p50 - prev_p50) / prev_p50) * 100
            if change_pct > REGRESSION_THRESHOLD_PCT:
                regressions.append({
                    "benchmark": label,
                    "previous_p50_ms": prev_p50,
                    "current_p50_ms": cur_p50,
                    "change_pct": round(change_pct, 2),
                    "threshold_pct": REGRESSION_THRESHOLD_PCT,
                })
    return regressions


# ── HTML Report Generator ─────────────────────────────────────────────────────


def _generate_html(results: dict[str, Any]) -> str:
    """Generate an HTML visualization of benchmark results."""
    latency_rows = ""
    for label, data in results.get("latency", {}).items():
        if isinstance(data, dict) and "error" not in data:
            latency_rows += f"""
            <tr>
                <td>{data.get('label', label)}</td>
                <td>{data.get('p50_ms', 'N/A')}</td>
                <td>{data.get('p90_ms', 'N/A')}</td>
                <td>{data.get('p95_ms', 'N/A')}</td>
                <td>{data.get('p99_ms', 'N/A')}</td>
                <td>{data.get('mean_ms', 'N/A')}</td>
                <td>{data.get('min_ms', 'N/A')}</td>
                <td>{data.get('max_ms', 'N/A')}</td>
                <td>{data.get('iterations', 'N/A')}</td>
            </tr>"""
        elif isinstance(data, dict) and "error" in data:
            latency_rows += f"""
            <tr>
                <td>{label}</td>
                <td colspan="8" style="color:red;">ERROR: {data['error']}</td>
            </tr>"""

    import_rows = ""
    for mod in results.get("imports", []):
        import_rows += f"""
        <tr>
            <td>{mod.get('module', 'N/A')}</td>
            <td>{mod.get('cold_import_ms', 'N/A')} ms</td>
        </tr>"""

    memory_rows = ""
    for mem in results.get("memory", []):
        memory_rows += f"""
        <tr>
            <td>{mem.get('label', 'N/A')}</td>
            <td>{mem.get('rss_mb', 'N/A')} MB</td>
            <td>{mem.get('vms_mb', 'N/A')} MB</td>
        </tr>"""

    regressions = results.get("regressions", [])
    reg_rows = ""
    for r in regressions:
        color = "red" if r["change_pct"] > r["threshold_pct"] else "orange"
        reg_rows += f"""
        <tr style="color:{color};">
            <td>{r['benchmark']}</td>
            <td>{r['previous_p50_ms']} ms</td>
            <td>{r['current_p50_ms']} ms</td>
            <td>{r['change_pct']}%</td>
            <td>{'⚠️ REGRESSION' if r['change_pct'] > r['threshold_pct'] else 'OK'}</td>
        </tr>"""

    timestamp = results.get("timestamp", "N/A")
    commit = results.get("commit", "N/A")

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>OPB Benchmark Report — v2.57.0</title>
<style>
body {{ font-family: -apple-system, sans-serif; margin: 20px; background: #f5f5f5; }}
h1, h2, h3 {{ color: #333; }}
table {{ border-collapse: collapse; width: 100%; margin: 10px 0 20px; background: #fff; }}
th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
th {{ background: #4A90D9; color: white; }}
tr:nth-child(even) {{ background: #f9f9f9; }}
.summary {{ background: #e8f5e9; padding: 15px; border-radius: 5px; margin: 10px 0; }}
.regression {{ background: #ffebee; padding: 15px; border-radius: 5px; margin: 10px 0; }}
</style>
</head>
<body>
<h1>OPB Benchmark Report</h1>
<div class="summary">
<p><strong>Timestamp:</strong> {timestamp}</p>
<p><strong>Commit:</strong> {commit}</p>
<p><strong>Version:</strong> v2.57.0</p>
</div>

<h2>Latency Benchmarks (ms)</h2>
<table>
<tr><th>Benchmark</th><th>P50</th><th>P90</th><th>P95</th><th>P99</th><th>Mean</th><th>Min</th><th>Max</th><th>Iterations</th></tr>
{latency_rows}
</table>

<h2>Cold Import Times</h2>
<table>
<tr><th>Module</th><th>Time</th></tr>
{import_rows}
</table>

<h2>Memory Usage</h2>
<table>
<tr><th>Label</th><th>RSS</th><th>VMS</th></tr>
{memory_rows}
</table>

<h2>Regression Detection</h2>
{'<table><tr><th>Benchmark</th><th>Previous P50</th><th>Current P50</th><th>Change %</th><th>Status</th></tr>' + reg_rows + '</table>' if reg_rows else '<p>✅ No regressions detected compared to previous run.</p>'}

<h2>Memory Allocation</h2>
<table>
<tr><th>File</th><th>Line</th><th>Size KB</th></tr>
"""
    for alloc in results.get("tracemalloc", []):
        for frame in alloc.get("top_frames", []):
            html += f"<tr><td>{frame.get('file', 'N/A')}</td><td>{frame.get('line', 'N/A')}</td><td>{frame.get('size_kb', 'N/A')}</td></tr>"
    html += """
</table>
<p style="color:#888; margin-top:30px;">Generated by OPB Benchmark Suite v2.57.0</p>
</body>
</html>"""
    return html


# ── Main Runner ───────────────────────────────────────────────────────────────


def run_benchmarks(json_output: bool = False, html_output: bool = True, ci_mode: bool = False) -> dict[str, Any]:
    """Run all benchmarks and return results.

    Args:
        json_output: Print JSON report to stdout.
        html_output: Generate HTML report file.
        ci_mode: Exit with non-zero code if regressions found.

    Returns:
        Dict with all benchmark results.
    """
    print("=" * 60)
    print("  OPB BENCHMARK SUITE v2.57.0")
    print("=" * 60)


    results: dict[str, Any] = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S IST"),
        "version": "2.57.0",
        "benchmark_schema_version": BENCHMARK_SCHEMA_VERSION,
        "commit": os.environ.get("GIT_COMMIT", "local"),
        "python_version": sys.version,
    }

    # 1. Cold imports
    print("\n[1/6] Cold import benchmarks...")
    results["imports"] = benchmark_imports()
    for mod in results["imports"]:
        print(f"  {mod['module']:<40s} {mod['cold_import_ms']:>8.3f} ms")

    # 2. Latency benchmarks
    print("\n[2/6] Latency benchmarks...")
    latency = {}
    bench_fns = [
        ("signal_generation", benchmark_signal_generation),
        ("risk_evaluation", benchmark_risk_evaluation),
        ("position_sizing", benchmark_position_sizing),
        ("ml_prediction", benchmark_ml_prediction),
        ("db_query_sqlite", benchmark_db_queries),
        ("config_load", benchmark_config_load),
    ]
    for label, fn in bench_fns:
        result = fn()
        latency[label] = result
        if "error" not in result:
            print(f"  {label:<30s} P50={result.get('p50_ms', '?'):>8.3f} ms  "
                  f"P90={result.get('p90_ms', '?'):>8.3f} ms  "
                  f"P95={result.get('p95_ms', '?'):>8.3f} ms")
        else:
            print(f"  {label:<30s} ERROR: {result['error']}")
    results["latency"] = latency

    # Start memory tracing only after latency benchmarks so instrumentation
    # overhead does not contaminate latency measurements.
    if not tracemalloc.is_tracing():
        tracemalloc.start()
    _tracemalloc_started = tracemalloc.is_tracing()

    # 3. Memory usage
    print("\n[3/6] Memory usage...")
    results["memory"] = [_measure_memory("post_benchmark")]

    # 4. Allocation profile
    print("\n[4/6] Allocation profiling...")
    results["tracemalloc"] = [_measure_tracemalloc("peak_allocation")]

    # 5. Historical comparison
    print("\n[5/6] Historical comparison...")
    history = _load_history()
    if history:
        results["history_comparable"] = (
            history.get("benchmark_schema_version")
            == results.get("benchmark_schema_version")
        )
        results["history_comparison_reason"] = (
            "comparable"
            if results["history_comparable"]
            else "benchmark_schema_mismatch"
        )
        regressions = _compare_with_history(results, history)
        results["regressions"] = regressions
        results["history_file"] = str(HISTORY_FILE)
        if regressions:
            print(f"  ⚠️  {len(regressions)} regression(s) detected:")
            for r in regressions:
                print(f"    {r['benchmark']}: {r['previous_p50_ms']:.3f} → {r['current_p50_ms']:.3f} ms ({r['change_pct']:+.2f}%)")
        else:
            print("  ✅ No regressions detected")
    else:
        results["history_comparable"] = False
        results["history_comparison_reason"] = "no_previous_baseline"
        results["regressions"] = []
        print("  ℹ️  No previous benchmark data for comparison")

    # Save history
    _save_history(results)

    # 6. Generate reports
    print("\n[6/6] Generating reports...")
    if json_output:
        print(json.dumps(results, indent=2, default=str))

    if html_output:
        html = _generate_html(results)
        HTML_REPORT.write_text(html, encoding="utf-8")
        print(f"  HTML report: {HTML_REPORT}")

    REPORT_FILE.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    print(f"  JSON report: {REPORT_FILE}")

    if _tracemalloc_started and tracemalloc.is_tracing():
        tracemalloc.stop()
    print("\n" + "=" * 60)
    print("  BENCHMARK COMPLETE")
    print("=" * 60)

    return results


def main() -> int:
    """CLI entry point."""
    import argparse
    parser = argparse.ArgumentParser(description="OPB Benchmark Suite")
    parser.add_argument("--json", action="store_true", help="Output JSON to stdout")
    parser.add_argument("--no-html", action="store_true", help="Skip HTML report generation")
    parser.add_argument("--ci", action="store_true", help="CI mode: exit non-zero on regressions or benchmark errors")
    args = parser.parse_args()

    results = run_benchmarks(
        json_output=args.json,
        html_output=not args.no_html,
        ci_mode=args.ci,
    )

    benchmark_errors = [
        result
        for result in results.get("latency", {}).values()
        if isinstance(result, dict) and "error" in result
    ]
    if args.ci and benchmark_errors:
        print(f"\nCI FAILED: {len(benchmark_errors)} benchmark error(s) found")
        for result in benchmark_errors:
            print(f"    {result.get('label', 'unknown')}: {result.get('error')}")
        return 1

    if args.ci and results.get("regressions"):
        print(f"\nCI FAILED: {len(results['regressions'])} regression(s) found")
        return 1
    return 0

if __name__ == "__main__":
    sys.exit(main())
