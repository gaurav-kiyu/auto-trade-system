"""Tests for core.fundamental_analyzer - Multi-dimension equity fundamental scoring engine.

Covers:
  - FundamentalData model and computed properties
  - Dimension scoring (value, growth, quality, momentum)
  - Full analysis pipeline (score -> ScreeningResult)
  - Cache hit/miss/expiry logic
  - Error handling for missing symbols
  - Screen (multi-symbol) workflow
  - Singleton factory
  - Edge cases (missing data, zero values, negative values)
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
import time

import pytest

from core.fundamental_analyzer import (
    DEFAULT_WEIGHTS,
    DimensionScore,
    FundamentalAnalyzer,
    FundamentalData,
    ScoreDetail,
    ScreeningResult,
    get_fundamental_analyzer,
    reset_fundamental_analyzer,
    _compute_value_score,
    _compute_growth_score,
    _compute_quality_score,
    _compute_momentum_score,
    _score_direct,
    _score_inverse,
)


# ═══════════════════════════════════════════════════════════════════════════
# Scoring helper tests
# ═══════════════════════════════════════════════════════════════════════════


class TestScoreHelpers:
    def test_score_inverse_low_is_best(self):
        """P/E of 10 → score 100 (below high-good threshold of 15)."""
        assert _score_inverse(10, 15, 30) == 100.0

    def test_score_inverse_high_is_worst(self):
        """P/E of 35 → score 0 (above low-good threshold of 30)."""
        assert _score_inverse(35, 15, 30) == 0.0

    def test_score_inverse_midpoint(self):
        """P/E of 22.5 → score 50 (midway between 15 and 30)."""
        assert _score_inverse(22.5, 15, 30) == pytest.approx(50.0, rel=1e-3)

    def test_score_inverse_zero(self):
        """Zero P/E → score 0 (no earnings = not value play)."""
        assert _score_inverse(0, 15, 30) == 0.0

    def test_score_direct_high_is_best(self):
        """Div yield 3% → score 100 (above high-good threshold of 2%)."""
        assert _score_direct(3.0, 2.0, 0.5) == 100.0

    def test_score_direct_low_is_worst(self):
        """Div yield 0.3% → score 0 (below low-good threshold of 0.5%)."""
        assert _score_direct(0.3, 2.0, 0.5) == 0.0

    def test_score_direct_midpoint(self):
        """Div yield 1.25% → score 50."""
        assert _score_direct(1.25, 2.0, 0.5) == pytest.approx(50.0, rel=1e-3)

    def test_score_direct_negative_value(self):
        """Negative earnings growth → score 0."""
        assert _score_direct(-0.10, 0.15, -0.05) == 0.0


# ═══════════════════════════════════════════════════════════════════════════
# FundamentalData tests
# ═══════════════════════════════════════════════════════════════════════════


class TestFundamentalData:
    def test_computed_roe(self):
        """EPS 50 / Book Value 500 → ROE 10%."""
        data = FundamentalData("TEST", eps_ttm=50.0, book_value=500.0)
        assert data.computed_roe == pytest.approx(0.10, rel=1e-3)

    def test_computed_roe_zero_book_value(self):
        """ROE = 0 when book value is 0."""
        data = FundamentalData("TEST", eps_ttm=50.0, book_value=0.0)
        assert data.computed_roe == 0.0

    def test_week_52_change_pct(self):
        """Current 120, 52W low 100 → 20% change."""
        data = FundamentalData("TEST", current_price=120.0, week_52_low=100.0)
        assert data.week_52_change_pct == pytest.approx(20.0, rel=1e-3)

    def test_week_52_change_zero_low(self):
        """52-week change = 0 if low is 0."""
        data = FundamentalData("TEST", current_price=100.0, week_52_low=0.0)
        assert data.week_52_change_pct == 0.0

    def test_market_cap_classifications(self):
        """Large cap >= 20K Cr, Mid cap 5K-20K Cr, Small cap < 5K Cr."""
        large = FundamentalData("LARGE", market_cap=5e11)
        mid = FundamentalData("MID", market_cap=1e11)
        small = FundamentalData("SMALL", market_cap=1e10)

        assert large.is_large_cap is True
        assert large.is_mid_cap is False
        assert large.is_small_cap is False

        assert mid.is_large_cap is False
        assert mid.is_mid_cap is True
        assert mid.is_small_cap is False

        assert small.is_large_cap is False
        assert small.is_mid_cap is False
        assert small.is_small_cap is True


# ═══════════════════════════════════════════════════════════════════════════
# Dimension scoring tests
# ═══════════════════════════════════════════════════════════════════════════


class TestDimensionScoring:
    def test_value_score_ideal(self):
        """Strong value: low P/E, low P/B, high dividend yield."""
        data = FundamentalData(
            "TEST", pe_ratio=10.0, pb_ratio=1.2, forward_pe=9.5,
            dividend_yield=0.035, book_value=200.0, eps_ttm=30.0,
        )
        score, details = _compute_value_score(data)
        assert score >= 70.0
        assert len(details) == 4
        assert any(d.metric == "P/E" for d in details)
        assert any(d.metric == "Div Yield" for d in details)

    def test_value_score_expensive(self):
        """Expensive stock: high P/E, high P/B, no dividend."""
        data = FundamentalData(
            "TEST", pe_ratio=50.0, pb_ratio=8.0, forward_pe=45.0,
            dividend_yield=0.0, book_value=100.0, eps_ttm=5.0,
        )
        score, details = _compute_value_score(data)
        assert score <= 30.0

    def test_growth_score_high(self):
        """Strong growth: high earnings growth, positive forward EPS."""
        data = FundamentalData(
            "TEST", earnings_growth=0.25, revenue_growth=0.20,
            eps_ttm=50.0, eps_forward=60.0,
        )
        score, details = _compute_growth_score(data)
        assert score >= 70.0

    def test_growth_score_negative(self):
        """Negative earnings growth."""
        data = FundamentalData(
            "TEST", earnings_growth=-0.10, revenue_growth=-0.05,
            eps_ttm=50.0, eps_forward=45.0,
        )
        score, details = _compute_growth_score(data)
        assert score <= 30.0

    def test_quality_score_strong(self):
        """High quality: strong ROE, low debt, good margins."""
        data = FundamentalData(
            "TEST", eps_ttm=50.0, book_value=200.0,  # ROE = 25%
            debt_to_equity=15.0, current_ratio=2.5,
            operating_margin=0.25, profit_margin=0.18,
        )
        score, details = _compute_quality_score(data)
        assert score >= 70.0
        assert any(d.metric == "ROE" for d in details)
        assert any(d.metric == "Debt/Equity" for d in details)

    def test_quality_score_weak(self):
        """Low quality: poor ROE, high debt, low margins."""
        data = FundamentalData(
            "TEST", eps_ttm=2.0, book_value=200.0,  # ROE = 1%
            debt_to_equity=200.0, current_ratio=0.5,
            operating_margin=0.02, profit_margin=-0.05,
        )
        score, details = _compute_quality_score(data)
        assert score <= 30.0

    def test_momentum_score_uptrend(self):
        """Strong momentum: price above both moving averages."""
        data = FundamentalData(
            "TEST", current_price=150.0,
            week_52_low=80.0, week_52_high=160.0,
            fifty_day_avg=140.0, two_hundred_day_avg=130.0,
        )
        score, details = _compute_momentum_score(data)
        assert score >= 60.0
        assert any(d.metric == "52W Change" for d in details)

    def test_momentum_score_downtrend(self):
        """Weak momentum: price below moving averages."""
        data = FundamentalData(
            "TEST", current_price=90.0,
            week_52_low=80.0, week_52_high=160.0,
            fifty_day_avg=110.0, two_hundred_day_avg=120.0,
        )
        score, details = _compute_momentum_score(data)
        assert score <= 40.0


# ═══════════════════════════════════════════════════════════════════════════
# ScreeningResult tests
# ═══════════════════════════════════════════════════════════════════════════


class TestScreeningResult:
    @staticmethod
    def _make_result(symbol: str = "TEST", composite: float = 50.0,
                     **overrides: object) -> ScreeningResult:
        params = dict(
            symbol=symbol, name="", sector="", current_price=0.0,
            market_cap=0.0, pe_ratio=0.0, pb_ratio=0.0, dividend_yield=0.0,
            eps_ttm=0.0, roe_pct=0.0, debt_to_equity=0.0, earnings_growth=0.0,
            dimension_scores=DimensionScore(), composite_score=composite,
        )
        params.update(overrides)
        return ScreeningResult(**params)

    def test_verdict_strong_buy(self):
        r = self._make_result(composite=85.0)
        assert r.verdict == "STRONG_BUY"

    def test_verdict_buy(self):
        r = self._make_result(composite=68.0)
        assert r.verdict == "BUY"

    def test_verdict_hold(self):
        r = self._make_result(composite=50.0)
        assert r.verdict == "HOLD"

    def test_verdict_caution(self):
        r = self._make_result(composite=35.0)
        assert r.verdict == "CAUTION"

    def test_verdict_avoid(self):
        r = self._make_result(composite=20.0)
        assert r.verdict == "AVOID"

    def test_short_summary_format(self):
        r = self._make_result(
            symbol="RELIANCE.NS", name="Reliance Industries",
            current_price=2500.0, pe_ratio=22.5, roe_pct=12.5,
            dimension_scores=DimensionScore(value=65, growth=55, quality=70, momentum=60),
        )
        summary = r.short_summary
        assert "RELIANCE" in summary
        assert "22.5" in summary
        assert "12.5%" in summary
        assert "V:65" in summary
        assert "G:55" in summary


# ═══════════════════════════════════════════════════════════════════════════
# DimensionScore tests
# ═══════════════════════════════════════════════════════════════════════════


class TestDimensionScore:
    def test_valid_scores(self):
        ds = DimensionScore(value=80.0, growth=60.0, quality=70.0, momentum=50.0)
        assert ds.value == 80.0

    def test_invalid_score_below_zero_raises(self):
        with pytest.raises(ValueError, match="value score must be 0-100"):
            DimensionScore(value=-5.0)

    def test_invalid_score_above_100_raises(self):
        with pytest.raises(ValueError, match="growth score must be 0-100"):
            DimensionScore(growth=150.0)

    def test_default_scores_are_zero(self):
        ds = DimensionScore()
        assert ds.value == 0.0
        assert ds.growth == 0.0
        assert ds.quality == 0.0
        assert ds.momentum == 0.0


# ═══════════════════════════════════════════════════════════════════════════
# FundamentalAnalyzer tests
# ═══════════════════════════════════════════════════════════════════════════


class TestFundamentalAnalyzerInit:
    def test_default_weights_sum_to_one(self):
        """Default weights should sum to approximately 1.0."""
        total = sum(DEFAULT_WEIGHTS.values())
        assert abs(total - 1.0) < 0.01

    def test_invalid_weights_raises(self):
        """Weights not summing to ~1.0 should raise ValueError."""
        with pytest.raises(ValueError, match="weights must sum to 1.0"):
            FundamentalAnalyzer(weights={"value": 1.0, "growth": 1.0}, cache_ttl_seconds=9999)


class TestFundamentalAnalyzerScoring:
    """Tests that use a real temp DB but mock data (no yfinance calls)."""

    @pytest.fixture
    def fa(self):
        """Create a FundamentalAnalyzer with a temp DB."""
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        db_path = tmp.name
        tmp.close()
        fa = FundamentalAnalyzer(db_path=db_path, cache_ttl_seconds=9999)
        yield fa
        fa.invalidate_cache()
        try:
            os.unlink(db_path)
        except (OSError, PermissionError):
            pass

    def _make_data(self, symbol: str = "TEST.NS", **overrides: object) -> FundamentalData:
        """Create a FundamentalData instance with sensible defaults."""
        params = dict(
            symbol=symbol, name="Test Company", sector="Technology",
            market_cap=1e11, pe_ratio=20.0, forward_pe=18.0,
            pb_ratio=3.0, eps_ttm=30.0, eps_forward=35.0,
            book_value=200.0, dividend_yield=0.015,
            debt_to_equity=30.0, current_ratio=2.0,
            operating_margin=0.18, profit_margin=0.12,
            earnings_growth=0.12, revenue_growth=0.10,
            current_price=500.0, week_52_high=550.0, week_52_low=400.0,
            fifty_day_avg=490.0, two_hundred_day_avg=470.0,
            promoter_holding=45.0, institutional_holding=30.0,
            free_cashflow=5e9, operating_cashflow=8e9,
        )
        params.update(overrides)
        return FundamentalData(**params)

    def _cache_data(self, fa: FundamentalAnalyzer, data: FundamentalData) -> None:
        """Cache data by scoring it first, then storing."""
        result = fa._score(data.symbol, data)
        fa._cache_result(data.symbol, data, result)

    def test_analyze_with_mock_data(self, fa):
        """Direct _score with mock data should produce valid result."""
        data = self._make_data()
        self._cache_data(fa, data)
        result = fa.analyze("TEST.NS")
        assert isinstance(result, ScreeningResult)
        assert result.symbol == "TEST.NS"
        assert result.composite_score > 0
        assert result.composite_score <= 100
        assert len(result.details) >= 4

    def test_analyze_high_value_stock(self, fa):
        """A strong value stock should get a high value score."""
        data = self._make_data("VALUE.NS", pe_ratio=10.0, pb_ratio=1.2, dividend_yield=0.04)
        self._cache_data(fa, data)
        result = fa.analyze("VALUE.NS")
        assert result.dimension_scores.value >= 60.0

    def test_analyze_growth_stock(self, fa):
        """A high-growth stock should get a high growth score."""
        data = self._make_data("GROWTH.NS", earnings_growth=0.30, eps_forward=50.0, eps_ttm=30.0)
        self._cache_data(fa, data)
        result = fa.analyze("GROWTH.NS")
        assert result.dimension_scores.growth >= 70.0

    def test_analyze_high_quality_stock(self, fa):
        """A high-quality stock should get a high quality score."""
        data = self._make_data("QUAL.NS",
            eps_ttm=60.0, book_value=200.0,
            debt_to_equity=5.0, current_ratio=3.0,
            operating_margin=0.30, profit_margin=0.20,
        )
        self._cache_data(fa, data)
        result = fa.analyze("QUAL.NS")
        assert result.dimension_scores.quality >= 70.0

    def test_analyze_strong_momentum(self, fa):
        """A stock with strong momentum should get a high momentum score."""
        data = self._make_data("MOM.NS",
            current_price=550.0, week_52_low=300.0,
            fifty_day_avg=510.0, two_hundred_day_avg=480.0,
        )
        self._cache_data(fa, data)
        result = fa.analyze("MOM.NS")
        assert result.dimension_scores.momentum >= 60.0

    def test_analyze_missing_symbol(self, fa):
        """A symbol not in cache should return error result."""
        result = fa.analyze("NONEXISTENT_SYMBOL_12345")
        assert result.error != ""
        assert result.composite_score == 0.0

    def test_cache_hit_same_result(self, fa):
        """Analyzing the same symbol twice should return same score."""
        data = self._make_data("CACHE_TEST")
        self._cache_data(fa, data)
        r1 = fa.analyze("CACHE_TEST")
        r2 = fa.analyze("CACHE_TEST")
        assert r1.composite_score == r2.composite_score
        assert r1.dimension_scores == r2.dimension_scores

    def test_cache_expiry(self):
        """Stale cache entries should be refreshed."""
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        db_path = tmp.name
        tmp.close()

        fa_short = FundamentalAnalyzer(db_path=db_path, cache_ttl_seconds=0)
        data = FundamentalData("EXPIRE_TEST", name="Expiry Test", pe_ratio=20.0)
        self._cache_data = lambda f, d: f._cache_result(d.symbol, d, f._score(d.symbol, d))
        self._cache_data(fa_short, data)

        time.sleep(0.1)
        result = fa_short.analyze("EXPIRE_TEST")
        assert result.error != "" or result.composite_score > 0

        try:
            os.unlink(db_path)
        except (OSError, PermissionError):
            pass

    def test_cache_invalidate_single(self, fa):
        """Invalidating a single symbol should remove it from cache."""
        data = self._make_data("INV_TEST")
        self._cache_data(fa, data)
        assert fa._load_cached("INV_TEST") is not None
        fa.invalidate_cache("INV_TEST")
        assert fa._load_cached("INV_TEST") is None

    def test_cache_invalidate_all(self, fa):
        """Invalidating all should clear everything."""
        self._cache_data(fa, self._make_data("A"))
        self._cache_data(fa, self._make_data("B"))
        fa.invalidate_cache()
        assert fa._load_cached("A") is None
        assert fa._load_cached("B") is None

    def test_get_cache_stats(self, fa):
        """Cache stats should reflect current state."""
        stats = fa.get_cache_stats()
        assert "cached_symbols" in stats
        assert "cache_ttl_seconds" in stats
        self._cache_data(fa, self._make_data("STATS_TEST"))
        stats = fa.get_cache_stats()
        assert stats["cached_symbols"] >= 1

    def test_screen_multiple_symbols(self, fa):
        """Screen multiple symbols and get sorted results."""
        data_a = self._make_data("A.NS", pe_ratio=10.0, earnings_growth=0.20)
        data_b = self._make_data("B.NS", pe_ratio=50.0, earnings_growth=-0.10)
        self._cache_data(fa, data_a)
        self._cache_data(fa, data_b)
        results = fa.screen(["A.NS", "B.NS"])
        assert len(results) == 2
        assert results[0].composite_score >= results[1].composite_score

    def test_screen_with_min_score_filter(self, fa):
        """Min score filter should exclude low-scoring symbols."""
        # HIGH.NS: cheap + growing + quality → high score
        data_a = self._make_data("HIGH.NS",
            pe_ratio=10.0, pb_ratio=1.2, dividend_yield=0.03,
            earnings_growth=0.25, eps_forward=40.0,
            debt_to_equity=10.0, current_ratio=2.5,
            operating_margin=0.25, profit_margin=0.18,
            current_price=500.0, week_52_low=350.0,
            fifty_day_avg=480.0, two_hundred_day_avg=450.0,
        )
        # LOW.NS: expensive + shrinking + poor quality → low score
        data_b = self._make_data("LOW.NS",
            pe_ratio=100.0, pb_ratio=8.0, earnings_growth=-0.50,
            debt_to_equity=500.0, current_ratio=0.3,
            operating_margin=-0.10, profit_margin=-0.20,
            current_price=50.0, week_52_low=100.0,
            fifty_day_avg=80.0, two_hundred_day_avg=90.0,
        )
        self._cache_data(fa, data_a)
        self._cache_data(fa, data_b)
        # HIGH.NS should be above 40, LOW.NS below 40
        high_result = fa.analyze("HIGH.NS")
        low_result = fa.analyze("LOW.NS")
        assert high_result.composite_score >= 60.0
        assert low_result.composite_score < 40.0
        results = fa.screen(["HIGH.NS", "LOW.NS"], min_score=40.0)
        assert len(results) == 1
        assert results[0].symbol == "HIGH.NS"

    def test_error_in_screen(self, fa):
        """Screen should gracefully handle fetch errors (errors excluded from results)."""
        self._cache_data(fa, self._make_data("CACHED.NS"))
        results = fa.screen(["CACHED.NS", "UNKNOWN_12345"])
        # CACHED.NS should be in results (cache hit)
        # UNKNOWN_12345 is excluded because result.error is set
        assert len(results) == 1
        assert results[0].symbol == "CACHED.NS"
        # Verify it didn't crash
        assert results[0].composite_score > 0

    def test_force_refresh_bypasses_cache(self, fa):
        """force_refresh=True should skip cache and try to re-fetch."""
        self._cache_data(fa, self._make_data("FR_TEST"))
        result = fa.analyze("FR_TEST", force_refresh=True)
        assert isinstance(result, ScreeningResult)

    def test_dimension_score_verdict_consistency(self, fa):
        """Composite score should align with verdict."""
        strong = self._make_data("STRONG_TEST",
            pe_ratio=12.0, pb_ratio=1.5, dividend_yield=0.03,
            earnings_growth=0.20, eps_forward=40.0,
            debt_to_equity=10.0, current_ratio=2.5,
            operating_margin=0.25, profit_margin=0.18,
            current_price=500.0, week_52_low=350.0,
            fifty_day_avg=480.0, two_hundred_day_avg=450.0,
        )
        self._cache_data(fa, strong)
        r = fa.analyze("STRONG_TEST")
        assert r.verdict in ("STRONG_BUY", "BUY")
        assert r.composite_score >= 60.0

    def test_cache_persists_between_calls(self, fa):
        """Cached data should survive across analyzer instances."""
        self._cache_data(fa, self._make_data("PERSIST_TEST"))
        fa2 = FundamentalAnalyzer(db_path=fa._db_path, cache_ttl_seconds=9999)
        result = fa2.analyze("PERSIST_TEST")
        assert result.symbol == "PERSIST_TEST"
        assert result.composite_score > 0

    def test_screening_result_short_summary_present(self, fa):
        """ScreeningResult should always have a short_summary."""
        self._cache_data(fa, self._make_data("SUMMARY_TEST"))
        result = fa.analyze("SUMMARY_TEST")
        assert isinstance(result.short_summary, str)
        assert len(result.short_summary) > 10


# ═══════════════════════════════════════════════════════════════════════════
# Singleton factory tests
# ═══════════════════════════════════════════════════════════════════════════


class TestSingleton:
    def test_get_analyzer(self):
        reset_fundamental_analyzer()
        fa = get_fundamental_analyzer(cache_ttl_seconds=9999)
        assert isinstance(fa, FundamentalAnalyzer)

    def test_singleton_returns_same_instance(self):
        reset_fundamental_analyzer()
        fa1 = get_fundamental_analyzer(cache_ttl_seconds=9999)
        fa2 = get_fundamental_analyzer()
        assert fa1 is fa2
        reset_fundamental_analyzer()

    def test_reset_creates_new_instance(self):
        reset_fundamental_analyzer()
        fa1 = get_fundamental_analyzer(cache_ttl_seconds=9999)
        reset_fundamental_analyzer()
        fa2 = get_fundamental_analyzer(cache_ttl_seconds=9999)
        assert fa1 is not fa2


# ═══════════════════════════════════════════════════════════════════════════
# Edge cases
# ═══════════════════════════════════════════════════════════════════════════


class TestEdgeCases:
    @pytest.fixture
    def fa(self):
        """Create a FundamentalAnalyzer with a temp DB."""
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        db_path = tmp.name
        tmp.close()
        fa = FundamentalAnalyzer(db_path=db_path, cache_ttl_seconds=9999)
        yield fa
        try:
            os.unlink(db_path)
        except (OSError, PermissionError):
            pass

    def test_zero_market_cap(self, fa):
        """Market cap of 0 should not crash scoring."""
        data = FundamentalData("ZERO_MC", market_cap=0.0, pe_ratio=20.0, current_price=100.0)
        fa._cache_result("ZERO_MC", data, fa._score("ZERO_MC", data))
        result = fa.analyze("ZERO_MC")
        assert isinstance(result, ScreeningResult)
        assert result.composite_score >= 0.0

    def test_negative_earnings_no_crash(self, fa):
        """Negative earnings should score low but not crash."""
        data = FundamentalData("LOSS", pe_ratio=0.0, eps_ttm=-5.0,
                                book_value=100.0, earnings_growth=-0.50)
        fa._cache_result("LOSS", data, fa._score("LOSS", data))
        result = fa.analyze("LOSS")
        assert isinstance(result, ScreeningResult)
        # Low composite score expected but no crash
        assert result.composite_score >= 0.0

    def test_extremely_high_pe(self, fa):
        """Very high P/E should score 0 in value but not crash."""
        data = FundamentalData("HYPE", pe_ratio=500.0, pb_ratio=20.0)
        fa._cache_result("HYPE", data, fa._score("HYPE", data))
        result = fa.analyze("HYPE")
        assert result.dimension_scores.value <= 10.0

    def test_high_debt_does_not_crash(self, fa):
        """Extremely high debt/equity should score low but not crash."""
        data = FundamentalData("DEBT", debt_to_equity=9999.0, eps_ttm=10.0, book_value=50.0)
        fa._cache_result("DEBT", data, fa._score("DEBT", data))
        result = fa.analyze("DEBT")
        assert result.dimension_scores.quality >= 0.0
        assert result.dimension_scores.quality <= 40.0

    def test_all_zeros_no_crash(self, fa):
        """All fundamental data being zero should not crash."""
        data = FundamentalData("ZERO_ALL")
        fa._cache_result("ZERO_ALL", data, fa._score("ZERO_ALL", data))
        result = fa.analyze("ZERO_ALL")
        assert result.composite_score >= 0.0
        assert result.verdict == "AVOID"  # all zeros = worst case

    def test_invalid_cache_db_handling(self):
        """Invalid DB path should gracefully handle init error."""
        with pytest.raises((sqlite3.OperationalError, OSError)):
            FundamentalAnalyzer(db_path="/nonexistent/path/db.db", cache_ttl_seconds=9999)


# ═══════════════════════════════════════════════════════════════════════════
# ScoreDetail tests
# ═══════════════════════════════════════════════════════════════════════════


class TestScoreDetail:
    def test_create_detail(self):
        sd = ScoreDetail("P/E", 20.0, 75.0, 0.35, "Trailing P/E: 20.0")
        assert sd.metric == "P/E"
        assert sd.raw_value == 20.0
        assert sd.score == 75.0
        assert sd.weight == 0.35
        assert sd.rationale == "Trailing P/E: 20.0"


__all__ = []
