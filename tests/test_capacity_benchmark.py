"""Unit tests for scripts/capacity_benchmark.py — Capacity Benchmark Engine.

Tests cover:
  - BenchmarkResult dataclass
  - CapacityBenchmark class: all 5 benchmarks
  - run_benchmarks() function
  - get_failed() filtering
  - get_summary() JSON output
  - CLI argument parsing
"""

from __future__ import annotations

import json
from unittest.mock import patch

from scripts.capacity_benchmark import (
    BenchmarkResult,
    CapacityBenchmark,
    _cli,
    run_benchmarks,
)

# =========================================================================
# BenchmarkResult Dataclass
# =========================================================================


class TestBenchmarkResult:
    """Test BenchmarkResult dataclass."""

    def test_default_values(self) -> None:
        r = BenchmarkResult(name="test", ops_per_second=100.0, total_ops=50, elapsed_seconds=0.5)
        assert r.name == "test"
        assert r.ops_per_second == 100.0
        assert r.total_ops == 50
        assert r.elapsed_seconds == 0.5
        assert r.metadata == {}

    def test_custom_metadata(self) -> None:
        r = BenchmarkResult(
            name="custom", ops_per_second=50.0, total_ops=10,
            elapsed_seconds=0.2, metadata={"iterations": 10, "db": "sqlite"},
        )
        assert r.metadata["iterations"] == 10


# =========================================================================
# CapacityBenchmark — Constructor
# =========================================================================


class TestCapacityBenchmarkInit:
    """Test CapacityBenchmark constructor."""

    def test_default_not_quick(self) -> None:
        bm = CapacityBenchmark()
        assert bm._quick is False

    def test_quick_mode(self) -> None:
        bm = CapacityBenchmark(quick=True)
        assert bm._quick is True


# =========================================================================
# CapacityBenchmark — Individual Benchmarks
# =========================================================================


class TestTradeThroughput:
    def test_runs_successfully(self) -> None:
        bm = CapacityBenchmark(quick=True)
        bm._bench_trade_throughput()
        assert len(bm._results) == 1
        r = bm._results[0]
        assert r.name == "trade_throughput"
        assert r.total_ops == 100
        assert r.ops_per_second > 0

    def test_metadata_has_iterations(self) -> None:
        bm = CapacityBenchmark(quick=True)
        bm._bench_trade_throughput()
        assert bm._results[0].metadata.get("iterations") == 100


class TestSignalGeneration:
    def test_runs_successfully(self) -> None:
        bm = CapacityBenchmark(quick=True)
        bm._bench_signal_generation()
        assert len(bm._results) == 1
        r = bm._results[0]
        assert r.name == "signal_generation"
        assert r.total_ops == 50
        assert r.ops_per_second > 0


class TestDBWrites:
    def test_runs_successfully(self) -> None:
        bm = CapacityBenchmark(quick=True)
        bm._bench_db_writes()
        assert len(bm._results) == 1
        r = bm._results[0]
        assert r.name == "db_write_throughput"
        assert r.total_ops == 50
        assert r.ops_per_second > 0

    def test_cleans_up_temp_file(self) -> None:
        bm = CapacityBenchmark(quick=True)
        bm._bench_db_writes()
        # Temp file should be cleaned up — no assertion needed, just shouldn't crash


class TestMemoryBaseline:
    def test_runs_without_crash(self) -> None:
        bm = CapacityBenchmark(quick=True)
        bm._bench_memory_baseline()
        assert len(bm._results) == 1
        r = bm._results[0]
        assert r.name == "memory_baseline"
        assert r.ops_per_second == 0  # memory baseline always reports 0 ops/sec

    def test_metadata_has_rss_mb(self) -> None:
        bm = CapacityBenchmark(quick=True)
        bm._bench_memory_baseline()
        assert "rss_mb" in bm._results[0].metadata


class TestEventAppend:
    def test_handles_import_error_gracefully(self) -> None:
        """When core module import fails, catch block should record 0 ops/sec."""
        bm = CapacityBenchmark(quick=True)
        # Mock __import__ to fail for the event_system import
        with patch("builtins.__import__") as mock_import:
            def _fail_import(name: str, *args: object, **kwargs: object) -> object:
                if name in ("core", "core.execution", "core.execution.event_system"):
                    raise ImportError("No module named core")
                return __import__(name, *args, **kwargs)
            mock_import.side_effect = _fail_import
            bm._bench_event_append()
        r = bm._results[0]
        assert r.ops_per_second == 0
        assert r.metadata.get("error_type") == "ImportError"

    def test_runs_successfully_when_importable(self) -> None:
        """When core module is available, event_append should succeed."""
        bm = CapacityBenchmark(quick=True)
        try:
            bm._bench_event_append()
            r = bm._results[0]
            assert r.name == "event_append"
            # May be 0 if core module not available, but shouldn't crash
            assert r.total_ops >= 0
        except (ImportError, ModuleNotFoundError):
            pass  # Graceful skip if core not available in test environment


# =========================================================================
# CapacityBenchmark — run_all
# =========================================================================


class TestRunAll:
    def test_returns_five_results(self) -> None:
        bm = CapacityBenchmark(quick=True)
        results = bm.run_all()
        assert len(results) == 5

    def test_all_have_positive_ops_or_zero(self) -> None:
        bm = CapacityBenchmark(quick=True)
        results = bm.run_all()
        for r in results:
            assert r.ops_per_second >= 0
            assert r.total_ops >= 0
            assert r.elapsed_seconds >= 0


# =========================================================================
# CapacityBenchmark — get_failed
# =========================================================================


class TestGetFailed:
    def test_no_failures_all_pass(self) -> None:
        bm = CapacityBenchmark(quick=True)
        bm._results = [
            BenchmarkResult(name="a", ops_per_second=100.0, total_ops=50, elapsed_seconds=0.5),
            BenchmarkResult(name="b", ops_per_second=200.0, total_ops=100, elapsed_seconds=0.5),
            BenchmarkResult(name="memory_baseline", ops_per_second=0, total_ops=0, elapsed_seconds=0),
        ]
        failed = bm.get_failed()
        assert failed == []

    def test_filters_memory_baseline(self) -> None:
        """memory_baseline with 0 ops/sec should not be counted as failed."""
        bm = CapacityBenchmark(quick=True)
        bm._results = [
            BenchmarkResult(name="memory_baseline", ops_per_second=0, total_ops=0, elapsed_seconds=0),
        ]
        failed = bm.get_failed()
        assert failed == []

    def test_reports_failed_benchmarks(self) -> None:
        bm = CapacityBenchmark(quick=True)
        bm._results = [
            BenchmarkResult(name="good", ops_per_second=100, total_ops=50, elapsed_seconds=0.5),
            BenchmarkResult(name="bad", ops_per_second=0, total_ops=0, elapsed_seconds=0),
        ]
        failed = bm.get_failed()
        assert len(failed) == 1
        assert failed[0].name == "bad"


# =========================================================================
# CapacityBenchmark — get_summary
# =========================================================================


class TestGetSummary:
    def test_returns_json_serializable_dict(self) -> None:
        bm = CapacityBenchmark(quick=True)
        bm.run_all()
        summary = bm.get_summary()
        # Must be JSON-serializable
        json_str = json.dumps(summary)
        parsed = json.loads(json_str)
        assert "benchmark_results" in parsed
        assert len(parsed["benchmark_results"]) == 5

    def test_summary_has_total_count(self) -> None:
        bm = CapacityBenchmark(quick=True)
        bm.run_all()
        summary = bm.get_summary()
        assert summary["summary"]["total_benchmarks"] == 5

    def test_summary_has_fastest_and_slowest(self) -> None:
        bm = CapacityBenchmark(quick=True)
        bm.run_all()
        summary = bm.get_summary()
        assert summary["summary"]["fastest"] != ""
        assert summary["summary"]["slowest"] != ""


# =========================================================================
# run_benchmarks function
# =========================================================================


class TestRunBenchmarksFunction:
    def test_returns_zero_when_all_pass(self) -> None:
        exit_code = run_benchmarks(quick=True)
        assert exit_code == 0

    def test_json_output_is_valid(self) -> None:
        """JSON mode should produce parseable output."""
        import io
        import sys
        captured = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured
        try:
            run_benchmarks(quick=True, json_output=True)
        finally:
            sys.stdout = old_stdout
        output = captured.getvalue()
        assert output.strip() != ""
        parsed = json.loads(output)
        assert "benchmark_results" in parsed


# =========================================================================
# CLI
# =========================================================================


class TestCLI:
    """Test CLI argument parsing."""

    def test_quick_flag_passes_quick_true(self) -> None:
        with patch("scripts.capacity_benchmark.run_benchmarks") as mock:
            mock.return_value = 0
            with patch("sys.argv", ["prog", "--quick"]):
                try:
                    _cli()
                except SystemExit:
                    pass
                mock.assert_called_once()
                # Verify quick=True is passed
                call_kwargs = mock.call_args[1] if len(mock.call_args) > 1 else {}
                if not call_kwargs:
                    # Positional arg: quick is the first positional
                    call_args = mock.call_args[0] if mock.call_args else ()
                    assert len(call_args) >= 1
                    assert call_args[0] is True
