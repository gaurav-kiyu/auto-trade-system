"""Tests for benchmark history compatibility and regression detection."""

from scripts import run_benchmarks as benchmarks


def test_compare_with_history_rejects_incompatible_schema():
    current = {
        "benchmark_schema_version": 2,
        "latency": {
            "config_load": {"p50_ms": 10.0},
        },
    }
    history = {
        "benchmark_schema_version": 1,
        "latency": {
            "config_load": {"p50_ms": 1.0},
        },
    }

    assert benchmarks._compare_with_history(current, history) == []


def test_compare_with_history_detects_regression_for_matching_schema():
    current = {
        "benchmark_schema_version": 2,
        "latency": {
            "config_load": {"p50_ms": 11.1},
        },
    }
    history = {
        "benchmark_schema_version": 2,
        "latency": {
            "config_load": {"p50_ms": 10.0},
        },
    }

    regressions = benchmarks._compare_with_history(current, history)

    assert len(regressions) == 1
    assert regressions[0]["benchmark"] == "config_load"
    assert regressions[0]["change_pct"] == 11.0


def test_compare_with_history_ignores_change_at_threshold():
    current = {
        "benchmark_schema_version": 2,
        "latency": {
            "position_sizing": {"p50_ms": 11.0},
        },
    }
    history = {
        "benchmark_schema_version": 2,
        "latency": {
            "position_sizing": {"p50_ms": 10.0},
        },
    }

    assert benchmarks._compare_with_history(current, history) == []
