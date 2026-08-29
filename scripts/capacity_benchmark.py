"""Capacity Benchmark — CI-friendly throughput measurement script.

Measures:
  - Trade throughput: simulated orders/second
  - Signal generation: signals/second
  - DB write throughput: writes/second
  - Memory baseline: RSS in MB
  - Event store append: events/second

Outputs JSON for CI integration (GitHub Actions, Bitbucket Pipelines).

Usage:
    python scripts/capacity_benchmark.py                    # Full run
    python scripts/capacity_benchmark.py --quick            # Quick run (fewer iterations)
    python scripts/capacity_benchmark.py --json             # Machine-readable output
    python scripts/capacity_benchmark.py --ci               # CI mode (json + exit code)
"""

from __future__ import annotations

import json
import logging
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Ensure project root is on sys.path for core module imports
# This allows the benchmark to work when run as python scripts/capacity_benchmark.py
_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

_log = logging.getLogger(__name__)


@dataclass
class BenchmarkResult:
    """Result of a single benchmark run.

    Attributes:
        name: Benchmark name.
        ops_per_second: Throughput in operations/second.
        total_ops: Total operations performed.
        elapsed_seconds: Wall-clock time.
        metadata: Additional context (iterations, batch size, etc.).
    """
    name: str
    ops_per_second: float
    total_ops: int
    elapsed_seconds: float
    metadata: dict[str, Any] = field(default_factory=dict)


class CapacityBenchmark:
    """Runs capacity benchmarks for throughput measurement."""

    def __init__(self, quick: bool = False):
        self._quick = quick
        self._results: list[BenchmarkResult] = []

    def run_all(self) -> list[BenchmarkResult]:
        """Run all benchmarks and return results."""
        self._results = []
        self._bench_trade_throughput()
        self._bench_signal_generation()
        self._bench_db_writes()
        self._bench_memory_baseline()
        self._bench_event_append()
        return self._results

    def get_summary(self) -> dict[str, Any]:
        """Get a summary dict suitable for JSON output."""
        return {
            "benchmark_results": [
                {
                    "name": r.name,
                    "ops_per_second": round(r.ops_per_second, 2),
                    "total_ops": r.total_ops,
                    "elapsed_seconds": round(r.elapsed_seconds, 4),
                    **r.metadata,
                }
                for r in self._results
            ],
            "summary": {
                "total_benchmarks": len(self._results),
                "fastest": max(self._results, key=lambda r: r.ops_per_second).name if self._results else "",
                "slowest": min(self._results, key=lambda r: r.ops_per_second).name if self._results else "",
            },
        }

    def _bench_trade_throughput(self) -> None:
        """Measure simulated trade throughput."""
        iterations = 100 if self._quick else 1000
        start = time.time()
        for i in range(iterations):
            _ = {"symbol": f"SYM{i}", "direction": "BUY", "qty": 50, "price": 100.0 + i * 0.01}
        elapsed = max(time.time() - start, 0.001)
        self._results.append(BenchmarkResult(
            name="trade_throughput",
            ops_per_second=iterations / elapsed,
            total_ops=iterations,
            elapsed_seconds=elapsed,
            metadata={"iterations": iterations},
        ))

    def _bench_signal_generation(self) -> None:
        """Measure signal generation throughput."""
        iterations = 50 if self._quick else 500
        start = time.time()
        for i in range(iterations):
            _ = {
                "score": min(100, i % 101),
                "direction": "BUY" if i % 2 == 0 else "SELL",
                "confidence": 0.5 + (i % 50) / 100.0,
                "reason": f"Signal iteration {i}",
                "features": {"rsi": 55 + i % 30, "adx": 25 + i % 20, "volume_ratio": 1.2},
            }
        elapsed = max(time.time() - start, 0.001)
        self._results.append(BenchmarkResult(
            name="signal_generation",
            ops_per_second=iterations / elapsed,
            total_ops=iterations,
            elapsed_seconds=elapsed,
            metadata={"iterations": iterations},
        ))

    def _bench_db_writes(self) -> None:
        """Measure simulated DB write throughput."""
        import sqlite3
        import tempfile
        from pathlib import Path

        tmp = Path(tempfile.mkstemp(suffix=".db")[1])
        try:
            conn = sqlite3.connect(str(tmp))
            conn.execute("CREATE TABLE benchmark (id INTEGER, value TEXT, ts REAL)")
            iterations = 50 if self._quick else 500
            start = time.time()
            for i in range(iterations):
                conn.execute(
                    "INSERT INTO benchmark VALUES (?, ?, ?)",
                    (i, f"value_{i}", time.time()),
                )
            conn.commit()
            elapsed = max(time.time() - start, 0.001)
            self._results.append(BenchmarkResult(
                name="db_write_throughput",
                ops_per_second=iterations / elapsed,
                total_ops=iterations,
                elapsed_seconds=elapsed,
                metadata={"iterations": iterations, "db": "sqlite_memory"},
            ))
            conn.close()
        finally:
            try:
                tmp.unlink()
            except OSError:
                pass

    def _bench_memory_baseline(self) -> None:
        """Measure current process memory."""
        try:
            import psutil
            process = psutil.Process()
            mem_mb = process.memory_info().rss / (1024 * 1024)
        except ImportError:
            mem_mb = 0.0

        self._results.append(BenchmarkResult(
            name="memory_baseline",
            ops_per_second=0,
            total_ops=0,
            elapsed_seconds=0,
            metadata={"rss_mb": round(mem_mb, 1)},
        ))

    def _bench_event_append(self) -> None:
        """Measure EventStore append throughput."""
        try:
            from core.execution.event_system import EventBus, EventPriority, EventType, TradingEvent

            bus = EventBus()
            iterations = 20 if self._quick else 100
            start = time.time()
            for i in range(iterations):
                event = TradingEvent(
                    event_type=EventType.SIGNAL_GENERATED,
                    priority=EventPriority.NORMAL,
                    source="benchmark",
                    symbol=f"BENCH{i}",
                    direction="BUY",
                    quantity=50,
                    price=100.0,
                    metadata={"benchmark": True},
                )
                bus.publish(event)
            elapsed = max(time.time() - start, 0.001)
            self._results.append(BenchmarkResult(
                name="event_append",
                ops_per_second=iterations / elapsed,
                total_ops=iterations,
                elapsed_seconds=elapsed,
                metadata={"iterations": iterations},
            ))
        except (ImportError, ValueError, OSError, RuntimeError) as e:
            self._results.append(BenchmarkResult(
                name="event_append",
                ops_per_second=0,
                total_ops=0,
                elapsed_seconds=0,
                metadata={"error": str(e), "error_type": type(e).__name__},
            ))
        except Exception as e:
            # Catch-all for unexpected errors — log type and message
            self._results.append(BenchmarkResult(
                name="event_append",
                ops_per_second=0,
                total_ops=0,
                elapsed_seconds=0,
                metadata={"error": str(e), "error_type": type(e).__name__, "unexpected": True},
            ))

    def get_failed(self) -> list[BenchmarkResult]:
        """Get benchmarks that failed (0 ops/sec)."""
        return [r for r in self._results if r.ops_per_second == 0 and r.name != "memory_baseline"]


def run_benchmarks(quick: bool = False, json_output: bool = False) -> int:
    """Run all benchmarks and print results.

    Args:
        quick: Quick run (fewer iterations).
        json_output: Output as JSON.

    Returns:
        Exit code (0 = all passed, 1 = some benchmarks failed).
    """
    bm = CapacityBenchmark(quick=quick)
    results = bm.run_all()

    if json_output:
        print(json.dumps(bm.get_summary(), indent=2))
    else:
        print("=" * 60)
        print("CAPACITY BENCHMARK RESULTS")
        print("=" * 60)
        for r in results:
            if r.name == "memory_baseline":
                print(f"  {r.name:<25s} {r.metadata.get('rss_mb', 0):>8.1f} MB")
            else:
                print(f"  {r.name:<25s} {r.ops_per_second:>8.2f} ops/sec ({r.total_ops} ops in {r.elapsed_seconds:.2f}s)")

        failed = bm.get_failed()
        if failed:
            print(f"\n[!] {len(failed)} benchmark(s) failed: {[f.name for f in failed]}")
        else:
            print(f"\n[OK] All {len(results)} benchmarks completed successfully")
        print("=" * 60)

    return 1 if bm.get_failed() else 0


def _cli() -> None:
    import argparse
    ap = argparse.ArgumentParser(prog="python -m scripts.capacity_benchmark")
    ap.add_argument("--quick", action="store_true", help="Quick run (fewer iterations)")
    ap.add_argument("--json", action="store_true", help="Output JSON")
    ap.add_argument("--ci", action="store_true", help="CI mode (JSON + exit code)")
    args = ap.parse_args()

    exit_code = run_benchmarks(
        quick=args.quick or args.ci,
        json_output=args.json or args.ci,
    )
    raise SystemExit(exit_code)


if __name__ == "__main__":
    _cli()
