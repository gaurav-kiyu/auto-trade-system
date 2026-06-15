"""
Backtest benchmark comparison (Item 10 — v2.44).

Fetches buy-and-hold benchmark returns for strategy alpha measurement.
Results cached locally; fetch failures never block report generation.

Config keys
-----------
  benchmark_enabled         : bool   default true
  benchmark_symbol          : str    default "^NSEI"
  benchmark_risk_free_rate  : float  default 0.065  (6.5% India risk-free)
  benchmark_cache_hours     : int    default 24
"""
from __future__ import annotations

import json
import logging
import math
import time
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

_log = logging.getLogger(__name__)

_CACHE_DIR   = Path("data")
_CACHE_FILE  = _CACHE_DIR / "benchmark_cache.json"
_TRADING_DAYS_PER_YEAR = 252


@dataclass(frozen=True)
class BenchmarkReturn:
    symbol:               str
    start_date:           date
    end_date:             date
    total_return_pct:     float
    annualized_return_pct: float
    max_drawdown_pct:     float
    volatility_pct:       float   # annualised std dev of daily returns
    sharpe_ratio:         float
    data_source:          str     # "yahoo" | "cached" | "unavailable"


@dataclass(frozen=True)
class AlphaMetrics:
    alpha_pct:           float   # strategy_return - benchmark_return
    information_ratio:   float   # alpha / tracking_error (0.0 if unavailable)
    drawdown_ratio:      float   # strategy_max_dd / benchmark_max_dd (0.0 if 0)
    prob_outperform:     float   # fraction of MC simulations > benchmark (0.0 default)


def _annualise(total_return: float, n_days: int) -> float:
    """Convert total_return (fraction) to annualised % using trading-day convention."""
    if n_days <= 0:
        return 0.0
    years = n_days / _TRADING_DAYS_PER_YEAR
    try:
        return round(((1 + total_return) ** (1 / years) - 1) * 100, 2)
    except (ValueError, ZeroDivisionError):
        return 0.0


def _max_drawdown(closes: list[float]) -> float:
    """Maximum drawdown % from a list of close prices."""
    if len(closes) < 2:
        return 0.0
    peak = closes[0]
    mdd  = 0.0
    for c in closes:
        if c > peak:
            peak = c
        dd = (peak - c) / peak * 100.0 if peak > 0 else 0.0
        if dd > mdd:
            mdd = dd
    return round(mdd, 2)


def _volatility(closes: list[float]) -> float:
    """Annualised std dev of daily log returns in %."""
    if len(closes) < 2:
        return 0.0
    try:
        returns = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes)) if closes[i - 1] > 0]
        if not returns:
            return 0.0
        n   = len(returns)
        avg = sum(returns) / n
        var = sum((r - avg) ** 2 for r in returns) / max(n - 1, 1)
        return round(math.sqrt(var) * math.sqrt(_TRADING_DAYS_PER_YEAR) * 100, 2)
    except (ValueError, ZeroDivisionError, OverflowError):
        return 0.0


def _sharpe(total_return_pct: float, vol_pct: float, risk_free: float) -> float:
    if vol_pct <= 0:
        return 0.0
    return round((total_return_pct - risk_free * 100) / vol_pct, 3)


def _load_cache() -> dict:
    try:
        if _CACHE_FILE.exists():
            return json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        _log.debug("[BENCHMARK] non-critical error: %s", e)
    return {}


def _save_cache(data: dict) -> None:
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _CACHE_FILE.write_text(json.dumps(data, default=str, indent=2), encoding="utf-8")
    except (OSError, json.JSONDecodeError, TypeError) as exc:
        _log.debug("[BENCH] Cache write error: %s", exc)


def fetch_benchmark(
    symbol:       str,
    start_date:   date,
    end_date:     date,
    risk_free_rate: float = 0.065,
    cache_hours:  int   = 24,
) -> BenchmarkReturn | None:
    """
    Fetch buy-and-hold return for `symbol` from Yahoo Finance.
    Results cached for `cache_hours`. Returns None on any failure.
    """
    cache_key = f"{symbol}_{start_date}_{end_date}"
    ttl_secs  = cache_hours * 3600

    cache = _load_cache()
    entry = cache.get(cache_key, {})
    if entry and (time.time() - float(entry.get("fetched_at", 0))) < ttl_secs:
        try:
            return BenchmarkReturn(**{k: v for k, v in entry.items() if k != "fetched_at"})
        except (TypeError, ValueError, KeyError) as e:
            _log.debug("[BENCHMARK] non-critical error: %s", e)

    try:
        import yfinance as yf  # already in requirements
        ticker = yf.Ticker(symbol)
        df     = ticker.history(
            start=start_date.isoformat(),
            end=(end_date + timedelta(days=1)).isoformat(),
            interval="1d",
        )
        if df is None or df.empty:
            _log.warning("[BENCH] Empty history for %s %s→%s", symbol, start_date, end_date)
            return None

        closes = [float(c) for c in df["Close"].dropna().tolist() if c > 0]
        if len(closes) < 2:
            return None

        total_ret  = (closes[-1] / closes[0]) - 1.0
        n_days     = len(closes)
        ann_ret    = _annualise(total_ret, n_days)
        mdd        = _max_drawdown(closes)
        vol        = _volatility(closes)
        sharpe     = _sharpe(round(total_ret * 100, 2), vol, risk_free_rate)

        result = BenchmarkReturn(
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            total_return_pct=round(total_ret * 100, 2),
            annualized_return_pct=ann_ret,
            max_drawdown_pct=mdd,
            volatility_pct=vol,
            sharpe_ratio=sharpe,
            data_source="yahoo",
        )

        # Persist cache
        entry_data = {
            "symbol": symbol, "start_date": str(start_date), "end_date": str(end_date),
            "total_return_pct": result.total_return_pct,
            "annualized_return_pct": result.annualized_return_pct,
            "max_drawdown_pct": result.max_drawdown_pct,
            "volatility_pct": result.volatility_pct,
            "sharpe_ratio": result.sharpe_ratio,
            "data_source": "cached",
            "fetched_at": time.time(),
        }
        cache[cache_key] = entry_data
        _save_cache(cache)

        return result

    except (ImportError, ValueError, TypeError, OSError, ConnectionError, KeyError, IndexError) as exc:
        _log.warning("[BENCH] Fetch failed for %s: %s", symbol, exc)
        return None


def compute_alpha_metrics(
    strategy_return_pct:  float,
    strategy_max_dd_pct:  float,
    benchmark:            BenchmarkReturn | None,
    mc_pnls:              list[float] | None = None,
    benchmark_total_pnl:  float = 0.0,
) -> AlphaMetrics:
    """
    Compute alpha and related metrics vs benchmark.
    mc_pnls: list of Monte Carlo final P&L values (for prob_outperform).
    """
    if benchmark is None:
        return AlphaMetrics(0.0, 0.0, 0.0, 0.0)

    alpha = round(strategy_return_pct - benchmark.total_return_pct, 2)

    drawdown_ratio = 0.0
    if benchmark.max_drawdown_pct > 0:
        drawdown_ratio = round(strategy_max_dd_pct / benchmark.max_drawdown_pct, 3)

    prob_outperform = 0.0
    if mc_pnls and benchmark_total_pnl != 0:
        beating = sum(1 for p in mc_pnls if p > benchmark_total_pnl)
        prob_outperform = round(beating / len(mc_pnls), 4)

    # Information ratio: alpha / tracking_error (simplified)
    ir = 0.0
    if benchmark.volatility_pct > 0 and strategy_return_pct != benchmark.total_return_pct:
        ir = round(alpha / benchmark.volatility_pct, 3)

    return AlphaMetrics(
        alpha_pct=alpha,
        information_ratio=ir,
        drawdown_ratio=drawdown_ratio,
        prob_outperform=prob_outperform,
    )


def format_benchmark_table(
    strategy_return_pct: float,
    strategy_max_dd_pct: float,
    strategy_sharpe:     float,
    benchmark:           BenchmarkReturn | None,
    period_days:         int,
) -> str:
    """Return a plain-text benchmark comparison table for Telegram/logs."""
    if benchmark is None:
        return "Benchmark: unavailable (Yahoo fetch failed)"

    alpha = strategy_return_pct - benchmark.total_return_pct
    lines = [
        f"Benchmark Comparison ({period_days}d) vs {benchmark.symbol}",
        f"  Strategy return : {strategy_return_pct:+.1f}%",
        f"  Benchmark return: {benchmark.total_return_pct:+.1f}%",
        f"  Alpha           : {alpha:+.1f}%",
        f"  Strategy Sharpe : {strategy_sharpe:.2f}",
        f"  Benchmark Sharpe: {benchmark.sharpe_ratio:.2f}",
        f"  Strategy Max DD : -{strategy_max_dd_pct:.1f}%",
        f"  Benchmark Max DD: -{benchmark.max_drawdown_pct:.1f}%",
    ]
    return "\n".join(lines)
