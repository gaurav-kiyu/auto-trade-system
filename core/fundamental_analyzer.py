"""
Fundamental Analysis Engine - Multi-dimension equity fundamental scoring.

Fetches fundamental data from Yahoo Finance, computes composite scores
across Value / Growth / Quality / Momentum dimensions, and caches
snapshots in SQLite for offline screening.

Scoring methodology
-------------------
Each dimension is scored 0-100, then blended by weight:

  VALUE (30%):  P/E (low=good), P/B (low=good), Div Yield (high=good)
  GROWTH (25%): Earnings growth, Revenue growth proxy
  QUALITY (25%): ROE, Debt/Equity, Operating margins, Current ratio
  MOMENTUM (20%): 52-week performance relative to index

Usage
-----
    from core.fundamental_analyzer import FundamentalAnalyzer

    fa = FundamentalAnalyzer()
    report = fa.analyze("RELIANCE.NS")
    print(report.composite_score, report.verdict)

    # Screen multiple symbols
    results = fa.screen(["RELIANCE.NS", "TCS.NS", "HDFCBANK.NS"])
    for r in sorted(results, key=lambda x: x.composite_score, reverse=True):
        print(f"{r.symbol}: {r.composite_score:.1f} - {r.verdict}")
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from core.db_utils import get_connection

_log = logging.getLogger(__name__)

# ── Scoring weights ──────────────────────────────────────────────────────
DEFAULT_WEIGHTS: dict[str, float] = {
    "value": 0.30,
    "growth": 0.25,
    "quality": 0.25,
    "momentum": 0.20,
}

# Scoring thresholds (per dimension sub-metric)
PE_HIGH_SCORE_THRESHOLD = 15.0   # P/E <= this → max score
PE_LOW_SCORE_THRESHOLD = 30.0    # P/E >= this → min score
PB_HIGH_SCORE_THRESHOLD = 2.0    # P/B <= this → max score
PB_LOW_SCORE_THRESHOLD = 5.0     # P/B >= this → min score
DY_HIGH_SCORE_THRESHOLD = 2.0    # Div yield >= this (%) → max score
DY_LOW_SCORE_THRESHOLD = 0.5     # Div yield <= this (%) → min score
DE_HIGH_SCORE_THRESHOLD = 30.0   # Debt/Equity <= this → max score
DE_LOW_SCORE_THRESHOLD = 80.0    # Debt/Equity >= this → min score
CR_HIGH_SCORE_THRESHOLD = 2.0    # Current ratio >= this → max score
CR_LOW_SCORE_THRESHOLD = 1.0     # Current ratio <= this → min score
OM_HIGH_SCORE_THRESHOLD = 0.20   # Operating margin >= 20% → max score
OM_LOW_SCORE_THRESHOLD = 0.05    # Operating margin <= 5% → min score
ROE_HIGH_SCORE_THRESHOLD = 0.15  # ROE >= 15% → max score
ROE_LOW_SCORE_THRESHOLD = 0.05   # ROE <= 5% → min score
EG_HIGH_SCORE_THRESHOLD = 0.15   # Earnings growth >= 15% → max score
EG_LOW_SCORE_THRESHOLD = -0.05   # Earnings growth <= -5% → min score
MCAP_HIGH_SCORE_THRESHOLD = 5e11  # Market cap >= 50K Cr → max score
MCAP_LOW_SCORE_THRESHOLD = 5e9   # Market cap <= 500 Cr → min score


# ── Data models ──────────────────────────────────────────────────────────


@dataclass
class FundamentalData:
    """Raw fundamental data fetched for a symbol."""
    symbol: str
    name: str = ""
    sector: str = ""
    industry: str = ""
    market_cap: float = 0.0
    pe_ratio: float = 0.0
    forward_pe: float = 0.0
    pb_ratio: float = 0.0
    eps_ttm: float = 0.0
    eps_forward: float = 0.0
    book_value: float = 0.0
    dividend_yield: float = 0.0
    dividend_rate: float = 0.0
    payout_ratio: float = 0.0
    debt_to_equity: float = 0.0
    current_ratio: float = 0.0
    operating_margin: float = 0.0
    gross_margin: float = 0.0
    ebitda_margin: float = 0.0
    profit_margin: float = 0.0
    earnings_growth: float = 0.0
    revenue_growth: float = 0.0
    free_cashflow: float = 0.0
    operating_cashflow: float = 0.0
    promoter_holding: float = 0.0
    institutional_holding: float = 0.0
    shares_outstanding: float = 0.0
    face_value: float = 0.0
    week_52_high: float = 0.0
    week_52_low: float = 0.0
    current_price: float = 0.0
    fifty_day_avg: float = 0.0
    two_hundred_day_avg: float = 0.0
    beta: float = 0.0
    timestamp: datetime = field(default_factory=datetime.now)
    raw_fields: dict[str, Any] = field(default_factory=dict)

    @property
    def computed_roe(self) -> float:
        """Return on Equity = EPS / Book Value (as decimal)."""
        if self.book_value > 0 and self.eps_ttm > 0:
            return self.eps_ttm / self.book_value
        return 0.0

    @property
    def week_52_change_pct(self) -> float:
        """52-week price change percentage."""
        if self.week_52_low > 0 and self.current_price > 0:
            return (self.current_price - self.week_52_low) / self.week_52_low * 100
        return 0.0

    @property
    def is_large_cap(self) -> bool:
        """Market cap >= 20,000 Cr."""
        return self.market_cap >= 2e11

    @property
    def is_mid_cap(self) -> bool:
        """Market cap 5,000 - 20,000 Cr."""
        return 5e10 <= self.market_cap < 2e11

    @property
    def is_small_cap(self) -> bool:
        """Market cap < 5,000 Cr."""
        return 0 < self.market_cap < 5e10


@dataclass
class DimensionScore:
    """Score for a single fundamental dimension."""
    value: float = 0.0     # 0-100
    growth: float = 0.0    # 0-100
    quality: float = 0.0   # 0-100
    momentum: float = 0.0  # 0-100

    def __post_init__(self) -> None:
        for attr_name in ("value", "growth", "quality", "momentum"):
            v = getattr(self, attr_name)
            if v < 0 or v > 100:
                raise ValueError(f"{attr_name} score must be 0-100, got {v}")


@dataclass
class ScoreDetail:
    """Detailed breakdown of a single metric's contribution."""
    metric: str
    raw_value: float
    score: float       # 0-100 contribution
    weight: float      # within-dimension weight
    rationale: str = ""


@dataclass
class ScreeningResult:
    """Complete screening result for one symbol."""
    symbol: str
    name: str
    sector: str
    current_price: float
    market_cap: float
    pe_ratio: float
    pb_ratio: float
    dividend_yield: float
    eps_ttm: float
    roe_pct: float
    debt_to_equity: float
    earnings_growth: float
    dimension_scores: DimensionScore
    composite_score: float
    details: list[ScoreDetail] = field(default_factory=list)
    raw_data: FundamentalData | None = None
    error: str = ""
    fetched_at: str = ""

    @property
    def verdict(self) -> str:
        """Qualitative assessment based on composite score."""
        if self.composite_score >= 75:
            return "STRONG_BUY"
        elif self.composite_score >= 60:
            return "BUY"
        elif self.composite_score >= 45:
            return "HOLD"
        elif self.composite_score >= 30:
            return "CAUTION"
        else:
            return "AVOID"

    @property
    def short_summary(self) -> str:
        """One-line summary of the screening result."""
        v = self.dimension_scores
        return (
            f"{self.symbol} ({self.name or '?'}): {self.verdict} "
            f"[V:{v.value:.0f} G:{v.growth:.0f} Q:{v.quality:.0f} M:{v.momentum:.0f}] "
            f"P/E={self.pe_ratio:.1f} ROE={self.roe_pct:.1f}%"
        )


# ── Scoring helpers ──────────────────────────────────────────────────────


def _score_inverse(value: float, high_good_threshold: float, low_good_threshold: float) -> float:
    """Score a metric where lower values are better (e.g. P/E, P/B, D/E).

    Args:
        value: The raw metric value.
        high_good_threshold: Value at or below which score is 100.
        low_good_threshold: Value at or above which score is 0.

    Returns:
        Score from 0-100.
    """
    if value <= 0:
        return 0.0
    if value <= high_good_threshold:
        return 100.0
    if value >= low_good_threshold:
        return 0.0
    # Linear interpolation between thresholds
    ratio = (value - high_good_threshold) / (low_good_threshold - high_good_threshold)
    return max(0.0, min(100.0, (1.0 - ratio) * 100.0))


def _score_direct(value: float, high_good_threshold: float, low_good_threshold: float) -> float:
    """Score a metric where higher values are better (e.g. Div Yield, ROE).

    Args:
        value: The raw metric value.
        high_good_threshold: Value at or above which score is 100.
        low_good_threshold: Value at or below which score is 0.

    Returns:
        Score from 0-100.
    """
    if value <= 0:
        return 0.0
    if value >= high_good_threshold:
        return 100.0
    if value <= low_good_threshold:
        return 0.0
    ratio = (value - low_good_threshold) / (high_good_threshold - low_good_threshold)
    return max(0.0, min(100.0, ratio * 100.0))


def _compute_value_score(data: FundamentalData) -> tuple[float, list[ScoreDetail]]:
    """Compute Value dimension score (30% of composite)."""
    details: list[ScoreDetail] = []

    # P/E score (inverse - lower is better)
    pe_score = _score_inverse(data.pe_ratio, PE_HIGH_SCORE_THRESHOLD, PE_LOW_SCORE_THRESHOLD)
    details.append(ScoreDetail("P/E", data.pe_ratio, pe_score, 0.35,
                               f"Trailing P/E: {data.pe_ratio:.1f}"))

    # P/B score (inverse - lower is better)
    pb_score = _score_inverse(data.pb_ratio, PB_HIGH_SCORE_THRESHOLD, PB_LOW_SCORE_THRESHOLD)
    details.append(ScoreDetail("P/B", data.pb_ratio, pb_score, 0.30,
                               f"Price/Book: {data.pb_ratio:.1f}"))

    # Dividend yield score (direct - higher is better)
    dy_pct = data.dividend_yield * 100.0 if data.dividend_yield < 1.0 else data.dividend_yield
    dy_score = _score_direct(dy_pct, DY_HIGH_SCORE_THRESHOLD, DY_LOW_SCORE_THRESHOLD)
    details.append(ScoreDetail("Div Yield", dy_pct, dy_score, 0.20,
                               f"Dividend Yield: {dy_pct:.2f}%"))

    # Forward P/E (inverse, lower weight)
    fpe = data.forward_pe if data.forward_pe > 0 else data.pe_ratio
    fpe_score = _score_inverse(fpe, PE_HIGH_SCORE_THRESHOLD, PE_LOW_SCORE_THRESHOLD)
    details.append(ScoreDetail("Fwd P/E", fpe, fpe_score, 0.15,
                               f"Forward P/E: {fpe:.1f}"))

    # Weighted average
    total_weight = sum(d.weight for d in details)
    weighted = sum(d.score * d.weight for d in details) / total_weight if total_weight > 0 else 0.0
    return weighted, details


def _compute_growth_score(data: FundamentalData) -> tuple[float, list[ScoreDetail]]:
    """Compute Growth dimension score (25% of composite)."""
    details: list[ScoreDetail] = []

    # Earnings growth
    eg_score = _score_direct(data.earnings_growth, EG_HIGH_SCORE_THRESHOLD, EG_LOW_SCORE_THRESHOLD)
    details.append(ScoreDetail("Earnings Growth", data.earnings_growth, eg_score, 0.50,
                               f"Earnings growth: {data.earnings_growth*100:.1f}%"))

    # Revenue growth proxy (use earnings growth as proxy if no direct revenue growth)
    rg = data.revenue_growth if data.revenue_growth != 0 else data.earnings_growth
    rg_score = _score_direct(rg, EG_HIGH_SCORE_THRESHOLD, EG_LOW_SCORE_THRESHOLD)
    details.append(ScoreDetail("Revenue Growth", rg, rg_score, 0.30,
                               f"Revenue growth: {rg*100:.1f}%"))

    # Forward EPS vs TTM EPS growth
    eps_growth = (data.eps_forward - data.eps_ttm) / data.eps_ttm if data.eps_ttm > 0 else 0
    epsg_score = _score_direct(eps_growth, EG_HIGH_SCORE_THRESHOLD, EG_LOW_SCORE_THRESHOLD)
    details.append(ScoreDetail("EPS Growth (Fwd vs TTM)", eps_growth, epsg_score, 0.20,
                               f"EPS growth (fwd/ttm): {eps_growth*100:.1f}%"))

    total_weight = sum(d.weight for d in details)
    weighted = sum(d.score * d.weight for d in details) / total_weight if total_weight > 0 else 0.0
    return weighted, details


def _compute_quality_score(data: FundamentalData) -> tuple[float, list[ScoreDetail]]:
    """Compute Quality dimension score (25% of composite)."""
    details: list[ScoreDetail] = []

    # ROE (computed as EPS / Book Value)
    roe = data.computed_roe
    roe_score = _score_direct(roe, ROE_HIGH_SCORE_THRESHOLD, ROE_LOW_SCORE_THRESHOLD)
    details.append(ScoreDetail("ROE", roe, roe_score, 0.25,
                               f"ROE (EPS/BV): {roe*100:.1f}%"))

    # Debt/Equity (inverse - lower is better, zero debt = ideal)
    de_val = data.debt_to_equity
    if de_val <= 0:
        de_score = 100.0
    else:
        de_score = _score_inverse(de_val, DE_HIGH_SCORE_THRESHOLD, DE_LOW_SCORE_THRESHOLD)
    details.append(ScoreDetail("Debt/Equity", data.debt_to_equity, de_score, 0.25,
                               f"D/E ratio: {data.debt_to_equity:.1f}"))

    # Operating margin
    om_score = _score_direct(data.operating_margin, OM_HIGH_SCORE_THRESHOLD, OM_LOW_SCORE_THRESHOLD)
    details.append(ScoreDetail("Op Margin", data.operating_margin, om_score, 0.20,
                               f"Operating margin: {data.operating_margin*100:.1f}%"))

    # Current ratio
    cr_score = _score_direct(data.current_ratio, CR_HIGH_SCORE_THRESHOLD, CR_LOW_SCORE_THRESHOLD)
    details.append(ScoreDetail("Current Ratio", data.current_ratio, cr_score, 0.15,
                               f"Current ratio: {data.current_ratio:.2f}"))

    # Profit margin
    pm_score = _score_direct(data.profit_margin, 0.15, -0.05)
    details.append(ScoreDetail("Profit Margin", data.profit_margin, pm_score, 0.15,
                               f"Profit margin: {data.profit_margin*100:.1f}%"))

    total_weight = sum(d.weight for d in details)
    weighted = sum(d.score * d.weight for d in details) / total_weight if total_weight > 0 else 0.0
    return weighted, details


def _compute_momentum_score(data: FundamentalData) -> tuple[float, list[ScoreDetail]]:
    """Compute Momentum dimension score (20% of composite)."""
    details: list[ScoreDetail] = []

    # 52-week price performance
    w52_change = data.week_52_change_pct
    # Normalize: 0% change → 50, +50% → 100, -50% → 0
    w52_score = max(0.0, min(100.0, 50.0 + w52_change))
    details.append(ScoreDetail("52W Change", w52_change, w52_score, 0.40,
                               f"52-week change: {w52_change:.1f}%"))

    # Price vs 200-day MA (trend strength)
    if data.two_hundred_day_avg > 0 and data.current_price > 0:
        vs_200 = (data.current_price - data.two_hundred_day_avg) / data.two_hundred_day_avg
        vs_200_score = max(0.0, min(100.0, 50.0 + vs_200 * 200.0))  # 5% above → 60, 5% below → 40
    else:
        vs_200 = 0.0
        vs_200_score = 50.0
    details.append(ScoreDetail("vs 200 DMA", vs_200, vs_200_score, 0.30,
                               f"Price vs 200DMA: {vs_200*100:.1f}%"))

    # Price vs 50-day MA (short-term momentum)
    if data.fifty_day_avg > 0 and data.current_price > 0:
        vs_50 = (data.current_price - data.fifty_day_avg) / data.fifty_day_avg
        vs_50_score = max(0.0, min(100.0, 50.0 + vs_50 * 200.0))
    else:
        vs_50 = 0.0
        vs_50_score = 50.0
    details.append(ScoreDetail("vs 50 DMA", vs_50, vs_50_score, 0.30,
                               f"Price vs 50DMA: {vs_50*100:.1f}%"))

    total_weight = sum(d.weight for d in details)
    weighted = sum(d.score * d.weight for d in details) / total_weight if total_weight > 0 else 0.0
    return weighted, details


# ── Main analyzer ────────────────────────────────────────────────────────


class FundamentalAnalyzer:
    """Multi-dimension equity fundamental scoring engine.

    Fetches fundamental data from yfinance, computes composite scores
    across Value / Growth / Quality / Momentum dimensions, and caches
    results in an SQLite database.

    Args:
        db_path: Path to the fundamentals cache database.
        cache_ttl_seconds: How long a cached fundamental snapshot is valid.
        weights: Dimension weights (must sum to 1.0).
    """

    DEFAULT_DB = "fundamentals.db"

    def __init__(
        self,
        db_path: str | Path = DEFAULT_DB,
        *,
        cache_ttl_seconds: int = 86400,  # 24 hours
        weights: dict[str, float] | None = None,
    ) -> None:
        self._db_path = str(db_path)
        self._cache_ttl = cache_ttl_seconds
        self._weights = weights or dict(DEFAULT_WEIGHTS)
        self._lock = threading.RLock()

        # Validate weights sum to ~1.0
        total = sum(self._weights.values())
        if abs(total - 1.0) > 0.01:
            raise ValueError(f"Dimension weights must sum to 1.0, got {total:.3f}")

        self._init_db()

    # ── Public API ───────────────────────────────────────────────────────

    def set_weights(self, weights: dict[str, float]) -> None:
        """Update dimension weights at runtime.

        Args:
            weights: Dict with keys ``value``, ``growth``, ``quality``, ``momentum``.
                     Must sum to approximately 1.0.

        Raises:
            ValueError: If weights don't sum to ~1.0 or contain invalid keys.
        """
        valid_keys = {"value", "growth", "quality", "momentum"}
        if not set(weights.keys()).issubset(valid_keys):
            raise ValueError(f"Invalid weight keys: {set(weights.keys()) - valid_keys}")
        total = sum(weights.values())
        if abs(total - 1.0) > 0.01:
            raise ValueError(f"Dimension weights must sum to 1.0, got {total:.3f}")
        with self._lock:
            self._weights.update(weights)
        _log.info("[FA] Weights updated to: %s", self._weights)

    @property
    def current_weights(self) -> dict[str, float]:
        """Return a copy of the current dimension weights."""
        with self._lock:
            return dict(self._weights)

    def analyze(self, symbol: str, *, force_refresh: bool = False) -> ScreeningResult:
        """Fetch fundamentals and compute composite score for a single symbol.

        Args:
            symbol: Yahoo Finance symbol (e.g. ``RELIANCE.NS``, ``TCS.NS``).
            force_refresh: If True, bypass cache and re-fetch from yfinance.

        Returns:
            A ``ScreeningResult`` with detailed score breakdown.
        """
        # Check cache first
        if not force_refresh:
            cached = self._load_cached(symbol)
            if cached is not None:
                _log.debug("[FA] Using cached fundamentals for %s", symbol)
                return self._score(symbol, cached)

        # Fetch fresh data
        raw = self._fetch(symbol)
        if raw is None:
            return ScreeningResult(
                symbol=symbol,
                name="",
                sector="",
                current_price=0.0,
                market_cap=0.0,
                pe_ratio=0.0,
                pb_ratio=0.0,
                dividend_yield=0.0,
                eps_ttm=0.0,
                roe_pct=0.0,
                debt_to_equity=0.0,
                earnings_growth=0.0,
                dimension_scores=DimensionScore(),
                composite_score=0.0,
                error=f"Failed to fetch fundamental data for {symbol}",
            )

        # Score first, then cache the result (avoids double scoring)
        result = self._score(symbol, raw)
        self._cache_result(symbol, raw, result)
        return result

    def screen(
        self,
        symbols: list[str],
        *,
        force_refresh: bool = False,
        min_score: float = 0.0,
    ) -> list[ScreeningResult]:
        """Screen multiple symbols and return sorted results.

        Args:
            symbols: List of Yahoo Finance symbols.
            force_refresh: Bypass cache for all symbols.
            min_score: Minimum composite score to include (0-100).

        Returns:
            List of ``ScreeningResult`` sorted by composite score descending.
        """
        results: list[ScreeningResult] = []
        for symbol in symbols:
            try:
                result = self.analyze(symbol, force_refresh=force_refresh)
                if result.composite_score >= min_score and not result.error:
                    results.append(result)
            except (ValueError, TypeError, KeyError, AttributeError, ConnectionError, TimeoutError, OSError) as exc:
                _log.warning("[FA] Screen failed for %s: %s", symbol, exc)
                results.append(ScreeningResult(
                    symbol=symbol,
                    name="",
                    sector="",
                    current_price=0.0,
                    market_cap=0.0,
                    pe_ratio=0.0,
                    pb_ratio=0.0,
                    dividend_yield=0.0,
                    eps_ttm=0.0,
                    roe_pct=0.0,
                    debt_to_equity=0.0,
                    earnings_growth=0.0,
                    dimension_scores=DimensionScore(),
                    composite_score=0.0,
                    error=str(exc),
                ))

        results.sort(key=lambda r: r.composite_score, reverse=True)
        return results

    def get_cache_stats(self) -> dict[str, Any]:
        """Return cache statistics."""
        conn = get_connection(self._db_path)
        try:
            count = conn.execute("SELECT COUNT(*) FROM fundamental_cache").fetchone()[0]
            stale = conn.execute(
                "SELECT COUNT(*) FROM fundamental_cache "
                "WHERE fetched_at < datetime('now', ?)",
                (f"-{self._cache_ttl} seconds",),
            ).fetchone()[0]
            return {
                "db_path": self._db_path,
                "cache_ttl_seconds": self._cache_ttl,
                "cached_symbols": count,
                "stale_entries": stale,
            }
        finally:
            conn.close()

    def invalidate_cache(self, symbol: str | None = None) -> int:
        """Invalidate cached fundamental data.

        Args:
            symbol: If provided, invalidate only this symbol. If None, clear all.

        Returns:
            Number of invalidated entries.
        """
        conn = get_connection(self._db_path)
        try:
            if symbol:
                conn.execute("DELETE FROM fundamental_cache WHERE symbol = ?", (symbol,))
            else:
                conn.execute("DELETE FROM fundamental_cache")
            conn.commit()
            return conn.total_changes
        finally:
            conn.close()

    # ── Internal: Data Fetching ──────────────────────────────────────────

    def _fetch(self, symbol: str) -> FundamentalData | None:
        """Fetch fundamental data from yfinance for a symbol."""
        try:
            import yfinance as yf
        except ImportError:
            _log.error("[FA] yfinance not installed - cannot fetch fundamentals")
            return None

        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info
            if not info or not info.get("symbol"):
                _log.warning("[FA] No data returned for %s", symbol)
                return None

            # Map yfinance field names to our model
            data = FundamentalData(
                symbol=symbol,
                name=str(info.get("longName") or info.get("shortName") or info.get("symbol", "")),
                sector=str(info.get("sector", "")),
                industry=str(info.get("industry", "")),
                market_cap=float(info.get("marketCap", 0) or 0),
                pe_ratio=float(info.get("trailingPE", 0) or 0),
                forward_pe=float(info.get("forwardPE", 0) or 0),
                pb_ratio=float(info.get("priceToBook", 0) or 0),
                eps_ttm=float(info.get("trailingEps", 0) or 0 if info.get("trailingEps") else info.get("epsTrailingTwelveMonths", 0) or 0),
                eps_forward=float(info.get("forwardEps", 0) or 0),
                book_value=float(info.get("bookValue", 0) or 0),
                dividend_yield=float(info.get("dividendYield", 0) or 0),
                dividend_rate=float(info.get("dividendRate", 0) or 0),
                payout_ratio=float(info.get("payoutRatio", 0) or 0),
                debt_to_equity=float(info.get("debtToEquity", 0) or 0),
                current_ratio=float(info.get("currentRatio", 0) or 0),
                operating_margin=float(info.get("operatingMargins", 0) or 0),
                gross_margin=float(info.get("grossMargins", 0) or 0),
                ebitda_margin=float(info.get("ebitdaMargins", 0) or 0),
                profit_margin=float(info.get("profitMargins", 0) or 0),
                earnings_growth=float(info.get("earningsGrowth", 0) or 0),
                revenue_growth=float(info.get("revenueGrowth", 0) or 0),
                free_cashflow=float(info.get("freeCashflow", 0) or 0),
                operating_cashflow=float(info.get("operatingCashflow", 0) or 0),
                promoter_holding=float(info.get("heldPercentInsiders", 0) or 0) * 100,
                institutional_holding=float(info.get("heldPercentInstitutions", 0) or 0) * 100,
                shares_outstanding=float(info.get("sharesOutstanding", 0) or 0),
                face_value=float(info.get("faceValue", 0) or 0),
                week_52_high=float(info.get("fiftyTwoWeekHigh", 0) or 0),
                week_52_low=float(info.get("fiftyTwoWeekLow", 0) or 0),
                current_price=float(info.get("currentPrice", 0) or info.get("regularMarketPrice", 0) or 0),
                fifty_day_avg=float(info.get("fiftyDayAverage", 0) or 0),
                two_hundred_day_avg=float(info.get("twoHundredDayAverage", 0) or 0),
                beta=float(info.get("beta", 0) or 0),
                raw_fields=info,
            )
            return data

        except (ValueError, TypeError, KeyError, AttributeError, IndexError, ConnectionError, TimeoutError, OSError) as exc:
            _log.warning("[FA] Error fetching fundamentals for %s: %s", symbol, exc)
            return None
        except Exception as exc:
            _log.warning("[FA] Unexpected error fetching %s: %s", symbol, exc)
            return None

    # ── Internal: Scoring ────────────────────────────────────────────────

    def _score(self, symbol: str, data: FundamentalData) -> ScreeningResult:
        """Compute composite score from fundamental data."""
        value_score, value_details = _compute_value_score(data)
        growth_score, growth_details = _compute_growth_score(data)
        quality_score, quality_details = _compute_quality_score(data)
        momentum_score, momentum_details = _compute_momentum_score(data)

        dim_scores = DimensionScore(
            value=round(value_score, 1),
            growth=round(growth_score, 1),
            quality=round(quality_score, 1),
            momentum=round(momentum_score, 1),
        )

        composite = (
            value_score * self._weights.get("value", 0.30)
            + growth_score * self._weights.get("growth", 0.25)
            + quality_score * self._weights.get("quality", 0.25)
            + momentum_score * self._weights.get("momentum", 0.20)
        )

        all_details = value_details + growth_details + quality_details + momentum_details

        return ScreeningResult(
            symbol=symbol,
            name=data.name,
            sector=data.sector,
            current_price=data.current_price,
            market_cap=data.market_cap,
            pe_ratio=data.pe_ratio,
            pb_ratio=data.pb_ratio,
            dividend_yield=data.dividend_yield * 100 if data.dividend_yield < 1.0 else data.dividend_yield,
            eps_ttm=data.eps_ttm,
            roe_pct=data.computed_roe * 100,
            debt_to_equity=data.debt_to_equity,
            earnings_growth=data.earnings_growth,
            dimension_scores=dim_scores,
            composite_score=round(composite, 1),
            details=all_details,
            raw_data=data,
            fetched_at=datetime.now().isoformat(),
        )

    # ── Internal: DB Cache ───────────────────────────────────────────────

    def _init_db(self) -> None:
        """Create the fundamentals cache table if it doesn't exist."""
        conn = get_connection(self._db_path)
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS fundamental_cache (
                    symbol          TEXT PRIMARY KEY,
                    data_json       TEXT NOT NULL,
                    fetched_at      TEXT NOT NULL DEFAULT (datetime('now')),
                    pe_ratio        REAL DEFAULT 0.0,
                    pb_ratio        REAL DEFAULT 0.0,
                    market_cap      REAL DEFAULT 0.0,
                    eps_ttm         REAL DEFAULT 0.0,
                    dividend_yield  REAL DEFAULT 0.0,
                    debt_to_equity  REAL DEFAULT 0.0,
                    roe_pct         REAL DEFAULT 0.0,
                    composite_score REAL DEFAULT 0.0
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_fundamental_cache_composite
                ON fundamental_cache(composite_score DESC)
            """)
            conn.commit()
        finally:
            conn.close()

    def _cache_result(self, symbol: str, data: FundamentalData, result: ScreeningResult) -> None:
        """Store fundamental data and its computed score in the cache."""
        import json

        roe = data.computed_roe

        conn = get_connection(self._db_path)
        try:
            conn.execute(
                """
                INSERT OR REPLACE INTO fundamental_cache
                    (symbol, data_json, fetched_at, pe_ratio, pb_ratio,
                     market_cap, eps_ttm, dividend_yield, debt_to_equity,
                     roe_pct, composite_score)
                VALUES (?, ?, datetime('now'), ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    symbol,
                    json.dumps({
                        "name": data.name,
                        "sector": data.sector,
                        "industry": data.industry,
                        "pe_ratio": data.pe_ratio,
                        "pb_ratio": data.pb_ratio,
                        "market_cap": data.market_cap,
                        "eps_ttm": data.eps_ttm,
                        "dividend_yield": data.dividend_yield,
                        "debt_to_equity": data.debt_to_equity,
                        "current_price": data.current_price,
                        "forward_pe": data.forward_pe,
                        "eps_forward": data.eps_forward,
                        "book_value": data.book_value,
                        "dividend_rate": data.dividend_rate,
                        "payout_ratio": data.payout_ratio,
                        "current_ratio": data.current_ratio,
                        "operating_margin": data.operating_margin,
                        "gross_margin": data.gross_margin,
                        "ebitda_margin": data.ebitda_margin,
                        "profit_margin": data.profit_margin,
                        "earnings_growth": data.earnings_growth,
                        "revenue_growth": data.revenue_growth,
                        "free_cashflow": data.free_cashflow,
                        "operating_cashflow": data.operating_cashflow,
                        "promoter_holding": data.promoter_holding,
                        "institutional_holding": data.institutional_holding,
                        "shares_outstanding": data.shares_outstanding,
                        "face_value": data.face_value,
                        "week_52_high": data.week_52_high,
                        "week_52_low": data.week_52_low,
                        "fifty_day_avg": data.fifty_day_avg,
                        "two_hundred_day_avg": data.two_hundred_day_avg,
                        "beta": data.beta,
                    }),
                    data.pe_ratio,
                    data.pb_ratio,
                    data.market_cap,
                    data.eps_ttm,
                    data.dividend_yield,
                    data.debt_to_equity,
                    roe,
                    result.composite_score,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def _load_cached(self, symbol: str) -> FundamentalData | None:
        """Load fundamental data from cache if not stale."""
        import json

        conn = get_connection(self._db_path)
        try:
            row = conn.execute(
                """
                SELECT data_json, fetched_at FROM fundamental_cache
                WHERE symbol = ?
                  AND fetched_at > datetime('now', ?)
                """,
                (symbol, f"-{self._cache_ttl} seconds"),
            ).fetchone()

            if row is None:
                return None

            data_json, fetched_at = row
            d: dict[str, Any] = json.loads(data_json)

            return FundamentalData(
                symbol=symbol,
                name=d.get("name", ""),
                sector=d.get("sector", ""),
                industry=d.get("industry", ""),
                pe_ratio=d.get("pe_ratio", 0.0),
                pb_ratio=d.get("pb_ratio", 0.0),
                market_cap=d.get("market_cap", 0.0),
                eps_ttm=d.get("eps_ttm", 0.0),
                dividend_yield=d.get("dividend_yield", 0.0),
                debt_to_equity=d.get("debt_to_equity", 0.0),
                current_price=d.get("current_price", 0.0),
                forward_pe=d.get("forward_pe", 0.0),
                eps_forward=d.get("eps_forward", 0.0),
                book_value=d.get("book_value", 0.0),
                dividend_rate=d.get("dividend_rate", 0.0),
                payout_ratio=d.get("payout_ratio", 0.0),
                current_ratio=d.get("current_ratio", 0.0),
                operating_margin=d.get("operating_margin", 0.0),
                gross_margin=d.get("gross_margin", 0.0),
                ebitda_margin=d.get("ebitda_margin", 0.0),
                profit_margin=d.get("profit_margin", 0.0),
                earnings_growth=d.get("earnings_growth", 0.0),
                revenue_growth=d.get("revenue_growth", 0.0),
                free_cashflow=d.get("free_cashflow", 0.0),
                operating_cashflow=d.get("operating_cashflow", 0.0),
                promoter_holding=d.get("promoter_holding", 0.0),
                institutional_holding=d.get("institutional_holding", 0.0),
                shares_outstanding=d.get("shares_outstanding", 0.0),
                face_value=d.get("face_value", 0.0),
                week_52_high=d.get("week_52_high", 0.0),
                week_52_low=d.get("week_52_low", 0.0),
                fifty_day_avg=d.get("fifty_day_avg", 0.0),
                two_hundred_day_avg=d.get("two_hundred_day_avg", 0.0),
                beta=d.get("beta", 0.0),
                timestamp=datetime.fromisoformat(fetched_at) if fetched_at else datetime.now(),
                raw_fields=d,
            )
        finally:
            conn.close()


# ── Module-level singleton (one analyzer per process) ────────────────────

_analyzer: FundamentalAnalyzer | None = None
_analyzer_lock = threading.RLock()


def get_fundamental_analyzer(
    db_path: str | Path = FundamentalAnalyzer.DEFAULT_DB,
    *,
    cache_ttl_seconds: int = 86400,
    weights: dict[str, float] | None = None,
) -> FundamentalAnalyzer:
    """Get or create the singleton FundamentalAnalyzer instance.

    Args:
        db_path: Path to fundamentals cache database.
        cache_ttl_seconds: Cache TTL in seconds.
        weights: Optional dimension weights.

    Returns:
        The shared ``FundamentalAnalyzer`` instance.
    """
    global _analyzer
    if _analyzer is None:
        with _analyzer_lock:
            if _analyzer is None:
                _analyzer = FundamentalAnalyzer(
                    db_path=db_path,
                    cache_ttl_seconds=cache_ttl_seconds,
                    weights=weights,
                )
    return _analyzer


def reset_fundamental_analyzer() -> None:
    """Reset the singleton (useful for testing)."""
    global _analyzer
    with _analyzer_lock:
        _analyzer = None


__all__ = [
    "DEFAULT_WEIGHTS",
    "DimensionScore",
    "FundamentalAnalyzer",
    "FundamentalData",
    "ScoreDetail",
    "ScreeningResult",
    "get_fundamental_analyzer",
    "reset_fundamental_analyzer",
]
