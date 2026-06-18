#!/usr/bin/env python3
"""
Comprehensive Backtest Suite - NIFTY / BANKNIFTY / FINNIFTY
=============================================================
Runs candle backtests with strict_oi=False (Yahoo Finance data has no OI coverage).
Saves structured JSON results for downstream use by reports.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (ValueError, OSError):
        pass

from core.candle_backtest import CandleBacktestConfig, run_candle_backtest
from core.pure_index_signal import PureIndexRegimeParams
from core.yf_bar_fetch import fetch_1m_bars_chunked_yfinance

SYMBOLS = {
    "NIFTY":     "^NSEI",
    "BANKNIFTY": "^NSEBANK",
    "FINNIFTY":  "NIFTY_FIN_SERVICE.NS",
}

BACKTEST_DAYS = 30  # Yahoo 1m max


def load_config() -> dict:
    defaults_path = ROOT / "index_config.defaults.json"
    if defaults_path.exists():
        return json.loads(defaults_path.read_text(encoding="utf-8"))
    return {}


def run_single_backtest(
    label: str,
    symbol_yf: str,
    signal_cfg: dict,
    json_out: dict,
) -> dict | None:
    print(f"\n{'='*60}")
    print(f"  BACKTEST: {label} ({symbol_yf})")
    print(f"{'='*60}")

    # Fetch data
    print(f"[{label}] Fetching {symbol_yf} {BACKTEST_DAYS}d 1m bars...")
    try:
        df = fetch_1m_bars_chunked_yfinance(symbol_yf, calendar_days=BACKTEST_DAYS)
    except (OSError, ValueError, TypeError, ConnectionError, RuntimeError) as e:
        print(f"[{label}] FETCH ERROR: {e}")
        return None

    if df is None or len(df) == 0:
        print(f"[{label}] No data returned.")
        return None

    bars = len(df)
    print(f"[{label}] Loaded {bars} bars  {df.index.min()} → {df.index.max()}")

    # Determine symbol for lot size
    if "NSEI" in symbol_yf or "NIFTY50" in symbol_yf:
        symbol = "NIFTY"
    elif "NSEBANK" in symbol_yf or "BANKNIFTY" in symbol_yf:
        symbol = "BANKNIFTY"
    elif "FIN" in symbol_yf:
        symbol = "FINNIFTY"
    else:
        symbol = label

    # Config
    thr = int(signal_cfg.get("AI_THRESHOLD", 65))
    gap = int(signal_cfg.get("SIGNAL_ENTRY_SCORE_GAP", 5))
    vix = float(signal_cfg.get("BACKTEST_VIX", 14.0))

    regime = PureIndexRegimeParams(
        vix_block_threshold=float(signal_cfg.get("VIX_BLOCK_THRESHOLD", 35)),
        adx_trend_threshold=float(signal_cfg.get("ADX_TREND_THRESHOLD", 20)),
        adx_chop_threshold=float(signal_cfg.get("ADX_CHOP_THRESHOLD", 14)),
    )

    base_cfg = CandleBacktestConfig(
        warmup_bars=35,
        base_ai_threshold=thr,
        score_gap=gap,
        latency_bars=1,
        slippage_pct=0.0005,
        spread_pct=0.0002,
        fee_per_lot=40.0,
        vix=vix,
        tp_atr_mult=float(signal_cfg.get("FIB_TP2_RATIO", 1.618)),
        sl_atr_mult=float(signal_cfg.get("ATR_SL_MULTIPLIER", 1.2)),
        use_option_model=True,
        dte=3,
        delta_scale=float(signal_cfg.get("OPTION_DELTA_SCALE", 1.5)),
        use_regime_rr=True,
        strict_oi=False,  # Yahoo data has no OI
    )

    # Run option model
    print(f"[{label}] Running option-model backtest... (threshold={thr}, gap={gap})")
    try:
        res = run_candle_backtest(
            df, signal_cfg=signal_cfg, regime_params=regime,
            iv_spike_threshold=float(signal_cfg.get("IV_SPIKE_THRESHOLD", 45)),
            vol_ratio_min=float(signal_cfg.get("VOL_RATIO_MIN", 1.2)),
            backtest_cfg=base_cfg, symbol=symbol,
        )
    except (ValueError, TypeError, KeyError, IndexError, RuntimeError, OSError) as e:
        print(f"[{label}] BACKTEST ERROR: {e}")
        json_out[label] = {"error": str(e)}
        return None

    m = res.metrics

    # Build structured result
    result = {
        "symbol": label,
        "data_bars": bars,
        "data_start": str(df.index.min()),
        "data_end": str(df.index.max()),
        "total_trades": m.total_trades,
        "wins": m.wins,
        "losses": m.losses,
        "win_rate": m.win_rate,
        "profit_factor": m.profit_factor,
        "expectancy_per_trade": m.expectancy_per_trade,
        "avg_win": m.avg_win,
        "avg_loss": m.avg_loss,
        "avg_pct_win": m.avg_pct_win,
        "avg_pct_loss": m.avg_pct_loss,
        "rr_ratio": m.rr_ratio,
        "avg_rr_achieved": m.avg_rr_achieved,
        "max_drawdown_pct": m.max_drawdown_pct,
        "sharpe_ratio": m.sharpe_ratio,
        "calmar_ratio": m.calmar_ratio,
        "ending_capital": res.ending_capital,
        "net_return_pct": ((res.ending_capital - base_cfg.initial_capital) / base_cfg.initial_capital) * 100,
        "call_trades": m.call_trades,
        "put_trades": m.put_trades,
        "call_win_rate": m.call_win_rate,
        "put_win_rate": m.put_win_rate,                "by_regime": {k: {"trades": v.trades, "wins": v.wins, "win_rate": v.win_rate, "avg_pnl": v.avg_pnl} for k, v in m.by_regime.items()},
                "by_score": {k: {"trades": v.trades, "wins": v.wins, "win_rate": v.win_rate, "gross_pnl": v.gross_pnl} for k, v in m.by_score.items()},
        "verdict": _verdict(m.win_rate, m.rr_ratio, m.profit_factor, m.sharpe_ratio),
    }

    # Print summary
    print(f"[{label}] Trades: {m.total_trades} ({m.wins}W / {m.losses}L) | "
          f"Win: {m.win_rate:.1f}% | PF: {m.profit_factor:.2f} | "
          f"RR: {m.rr_ratio:.2f} | Sharpe: {m.sharpe_ratio:.2f} | "
          f"MaxDD: {m.max_drawdown_pct:.2f}% | "
          f"Net: {result['net_return_pct']:+.1f}%")

    json_out[label] = result
    return result


def _verdict(win_rate, rr, pf, sharpe):
    if win_rate >= 60 and rr >= 1.5 and pf >= 1.5:
        return "STRONG EDGE"
    if win_rate >= 55 and pf >= 1.2:
        return "POSITIVE EDGE"
    if win_rate >= 50 and rr >= 1.2:
        return "MARGINAL EDGE"
    if pf < 1.0:
        return "NO EDGE"
    return "NEUTRAL"


def main() -> int:
    signal_cfg = load_config()
    json_out: dict = {}

    for label, yf_sym in SYMBOLS.items():
        t0 = time.time()
        run_single_backtest(label, yf_sym, signal_cfg, json_out)
        elapsed = time.time() - t0
        print(f"[{label}] Completed in {elapsed:.1f}s")

    # Structured summary
    output_path = ROOT / "reports/backtest_results.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(json_out, indent=2, default=str), encoding="utf-8")
    print(f"\n{'='*60}")
    print(f"  Results saved to: {output_path}")
    print(f"{'='*60}")

    # Summary table
    print(f"\n{'='*60}")
    print("  BACKTEST SUMMARY TABLE")
    print(f"{'='*60}")
    if json_out:
        print(f"  {'Index':<14} {'Trades':>6} {'Win%':>7} {'PF':>6} {'RR':>6} {'Sharpe':>7} {'MaxDD':>7} {'NetRet':>7}  Verdict")
        print(f"  {'-'*14} {'-'*6} {'-'*7} {'-'*6} {'-'*6} {'-'*7} {'-'*7} {'-'*7}  -------")
        for label in SYMBOLS:
            r = json_out.get(label)
            if r and "error" not in r:
                print(f"  {label:<14} {r['total_trades']:>6} {r['win_rate']:>6.1f}% "
                      f"{r['profit_factor']:>6.2f} {r['rr_ratio']:>6.2f} "
                      f"{r['sharpe_ratio']:>6.2f} {r['max_drawdown_pct']:>6.2f}% "
                      f"{r['net_return_pct']:>+6.1f}%  {r['verdict']}")
    print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
