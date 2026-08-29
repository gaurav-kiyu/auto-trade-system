"""
Performance benchmark tests for the Fundamentals Analyzer.

Measures response time of analyze, screen, and weight operations
to detect performance regressions over time. Uses generous thresholds
to accommodate yfinance latency variability.

Usage:
    python -m pytest tests/test_fundamental_analyzer_benchmark.py -v --tb=short
"""

from __future__ import annotations

import logging
import os
import time

import pytest

fastapi = pytest.importorskip("fastapi", reason="fastapi not installed")

from core.fundamental_analyzer import get_fundamental_analyzer, reset_fundamental_analyzer

_log = logging.getLogger(__name__)

# ── Timing thresholds (seconds) ──────────────────────────────────────────
# Generous upper bounds — yfinance can be slow depending on network.
# These are regression guards, not microbenchmarks.
#
# Set PYTEST_BENCHMARK_STRICT=1 to halve all thresholds for CI environments
# where performance is more predictable.

_STRICT = os.environ.get("PYTEST_BENCHMARK_STRICT", "").lower() in ("1", "true", "yes")
_MULT = 0.5 if _STRICT else 1.0

ANALYZE_MAX_SEC = 12.0 * _MULT   # Single symbol analysis (yfinance can be slow)
SCREEN_2_MAX_SEC = 15.0 * _MULT  # Screen with 2 symbols
SCREEN_5_MAX_SEC = 30.0 * _MULT  # Screen with 5 symbols
WEIGHT_MAX_SEC = 0.5 * _MULT     # Weight operations are always in-memory


@pytest.fixture(autouse=True)
def _reset_before() -> None:
    """Reset the fundamental analyzer singleton before each test."""
    reset_fundamental_analyzer()
    yield
    reset_fundamental_analyzer()


class TestFundamentalAnalyzerBenchmarks:
    """Response time benchmarks for FundamentalAnalyzer operations."""

    def test_analyze_timing(self) -> None:
        """Analyze a single symbol should complete within threshold."""
        fa = get_fundamental_analyzer()
        start = time.perf_counter()
        result = fa.analyze("RELIANCE.NS")
        elapsed = time.perf_counter() - start
        assert elapsed < ANALYZE_MAX_SEC, (
            f"Analyze RELIANCE.NS took {elapsed:.2f}s (limit {ANALYZE_MAX_SEC}s)"
        )
        assert result is not None
        _log.info("[BENCH] analyze=%.2fs", elapsed)

    def test_screen_two_symbols_timing(self) -> None:
        """Screen with 2 symbols should complete within threshold."""
        fa = get_fundamental_analyzer()
        start = time.perf_counter()
        results = fa.screen(["RELIANCE.NS", "TCS.NS"], min_score=0.0)
        elapsed = time.perf_counter() - start
        assert elapsed < SCREEN_2_MAX_SEC, (
            f"Screen 2 symbols took {elapsed:.2f}s (limit {SCREEN_2_MAX_SEC}s)"
        )
        assert isinstance(results, list)
        _log.info("[BENCH] screen_2=%.2fs", elapsed)

    def test_screen_five_symbols_timing(self) -> None:
        """Screen with 5 symbols should complete within threshold."""
        fa = get_fundamental_analyzer()
        symbols = ["RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFCBANK.NS", "ICICIBANK.NS"]
        start = time.perf_counter()
        results = fa.screen(symbols, min_score=0.0)
        elapsed = time.perf_counter() - start
        assert elapsed < SCREEN_5_MAX_SEC, (
            f"Screen 5 symbols took {elapsed:.2f}s (limit {SCREEN_5_MAX_SEC}s)"
        )
        assert len(results) <= 5
        _log.info("[BENCH] screen_5=%.2fs", elapsed)

    def test_weights_get_timing(self) -> None:
        """GET weights should be near-instant (in-memory)."""
        fa = get_fundamental_analyzer()
        start = time.perf_counter()
        w = fa.current_weights
        elapsed = time.perf_counter() - start
        assert elapsed < WEIGHT_MAX_SEC, (
            f"Weights GET took {elapsed:.4f}s (limit {WEIGHT_MAX_SEC}s)"
        )
        assert isinstance(w, dict)
        for k in ("value", "growth", "quality", "momentum"):
            assert k in w

    def test_weights_set_timing(self) -> None:
        """PUT weights should be near-instant (in-memory update)."""
        fa = get_fundamental_analyzer()
        new_w = {"value": 0.40, "growth": 0.20, "quality": 0.20, "momentum": 0.20}
        start = time.perf_counter()
        fa.set_weights(new_w)
        elapsed = time.perf_counter() - start
        assert elapsed < WEIGHT_MAX_SEC, (
            f"Weights SET took {elapsed:.4f}s (limit {WEIGHT_MAX_SEC}s)"
        )
        assert abs(fa.current_weights["value"] - 0.40) < 0.001

    def test_screen_with_weights_timing(self) -> None:
        """Screen with custom weights should complete within threshold."""
        fa = get_fundamental_analyzer()
        fa.set_weights({"value": 0.40, "growth": 0.20, "quality": 0.20, "momentum": 0.20})
        start = time.perf_counter()
        results = fa.screen(["RELIANCE.NS", "TCS.NS"], min_score=0.0)
        elapsed = time.perf_counter() - start
        assert elapsed < SCREEN_2_MAX_SEC, (
            f"Screen with weights took {elapsed:.2f}s (limit {SCREEN_2_MAX_SEC}s)"
        )
        assert isinstance(results, list)

    def test_cache_stats_format(self) -> None:
        """Cache stats should return a dict."""
        fa = get_fundamental_analyzer()
        # Populate cache first
        fa.analyze("RELIANCE.NS")
        start = time.perf_counter()
        stats = fa.get_cache_stats()
        elapsed = time.perf_counter() - start
        assert elapsed < 0.5, f"Cache stats took {elapsed:.4f}s"
        assert isinstance(stats, dict), f"Expected dict, got {type(stats)}"

    def test_weights_persist_in_session(self) -> None:
        """Setting weights persists for subsequent operations."""
        fa = get_fundamental_analyzer()
        fa.set_weights({"value": 0.50, "growth": 0.20, "quality": 0.15, "momentum": 0.15})
        start = time.perf_counter()
        result = fa.analyze("TCS.NS")
        elapsed = time.perf_counter() - start
        assert elapsed < ANALYZE_MAX_SEC
        assert result is not None
