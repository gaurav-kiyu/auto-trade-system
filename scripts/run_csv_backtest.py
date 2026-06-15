"""
CSV Backtest Replay Script
===========================
Loads historical 1m OHLCV data from a CSV file and runs the candle backtest engine.

Usage:
    python scripts/run_csv_backtest.py data/nifty_1m.csv
    python scripts/run_csv_backtest.py data/nifty_1m.csv --from 2025-10-01 --to 2025-12-31
    python scripts/run_csv_backtest.py data/nifty_1m.csv --symbol NIFTY --vix 14 --thr 60
    python scripts/run_csv_backtest.py data/nifty_1m.csv --sl 1.5 --tp 2.0 --put-force

CSV format:
    Datetime,Open,High,Low,Close,Volume
    2025-10-01 09:15:00,22400,22450,22380,22430,125000
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import timedelta
from pathlib import Path

import pandas as pd

# Add project root to path
_HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_HERE))


def load_csv(
    path: str,
    *,
    date_from: str | None = None,
    date_to: str | None = None,
) -> pd.DataFrame:
    """Load 1m OHLCV CSV and return a UTC-naive DatetimeIndexed DataFrame."""
    p = Path(path)
    if not p.exists():
        print(f"ERROR: File not found: {p}")
        sys.exit(1)

    # Read first line to detect datetime column name
    with open(p) as fh:
        header_line = fh.readline().strip()
    headers = [h.strip() for h in header_line.split(",")]

    parse_cols = False
    for dt_name in ("Datetime", "datetime", "Timestamp", "timestamp", "Date", "date"):
        if dt_name in headers:
            parse_cols = [dt_name]
            break

    df = pd.read_csv(
        p,
        parse_dates=parse_cols,
        dtype={h: float for h in headers if h.lower() in ("open", "high", "low", "close", "volume")},
        low_memory=False,
    )

    # Detect datetime column if not already found
    dt_col = None
    for col in ("Datetime", "datetime", "Timestamp", "timestamp", "Time", "time", "Date", "date"):
        if col in df.columns:
            dt_col = col
            break

    if dt_col is None and len(df.columns) > 0:
        dt_col = df.columns[0]
        if "date" not in dt_col.lower() and "time" not in dt_col.lower():
            print(f"ERROR: No datetime column found. Columns: {list(df.columns)}")
            sys.exit(1)

    if dt_col:
        df[dt_col] = pd.to_datetime(df[dt_col], errors="coerce")
        df = df.dropna(subset=[dt_col])
        df = df.set_index(dt_col)

    if df.index.tz is not None:
        df.index = df.index.tz_convert("UTC").tz_localize(None)
    else:
        df.index = df.index.tz_localize(None)

    # Ensure OHLCV columns
    col_map = {}
    for c in ("Open", "High", "Low", "Close", "Volume"):
        for variant in (c, c.lower(), c.upper()):
            if variant in df.columns:
                col_map[variant] = c
                break
    if col_map:
        df = df.rename(columns=col_map)

    missing = [c for c in ("Open", "High", "Low", "Close") if c not in df.columns]
    if missing:
        print(f"ERROR: Missing columns: {missing}. Got: {list(df.columns)}")
        sys.exit(1)

    if "Volume" not in df.columns:
        df["Volume"] = 0

    df = df[["Open", "High", "Low", "Close", "Volume"]]
    for c in ("Open", "High", "Low", "Close", "Volume"):
        df[c] = pd.to_numeric(df[c], errors="coerce")

    # Filter by date range
    if date_from:
        df = df[df.index >= pd.Timestamp(date_from)]
    if date_to:
        df = df[df.index <= pd.Timestamp(date_to) + timedelta(days=1)]

    df = df.sort_index()
    df = df[~df.index.duplicated(keep="last")]

    if df.empty:
        print(f"ERROR: No data after filtering. Range: {date_from} -> {date_to}")
        sys.exit(1)

    print(f"Loaded {len(df):,} bars from {df.index[0]} to {df.index[-1]}")
    return df


def run_backtest(
    df: pd.DataFrame,
    *,
    symbol: str = "NIFTY",
    threshold: int = 60,
    score_gap: int = 5,
    sl_atr_mult: float = 1.2,
    tp_atr_mult: float = 1.618,
    vix: float = 14.0,
    put_force: bool = False,
    use_option_model: bool = True,
    use_regime_rr: bool = True,
    initial_capital: float = 100_000.0,
    fee_per_lot: float = 40.0,
    verbose: bool = False,
) -> dict:
    """Run the candle backtest on the provided DataFrame."""
    # Load signal config
    import json as _json

    from core.candle_backtest import CandleBacktestConfig, CandleBacktestEngine
    from core.pure_index_signal import PureIndexRegimeParams
    from core.yf_bar_fetch import normalize_yfinance_ohlcv
    cfg_path = _HERE / "index_config.defaults.json"
    with open(cfg_path) as f:
        signal_cfg = _json.load(f)

    # Overlay config.json
    main_cfg = _HERE / "config.json"
    if main_cfg.exists():
        try:
            mc = _json.loads(main_cfg.read_text(encoding="utf-8"))
            for k in mc:
                signal_cfg[k] = mc[k]
        except (json.JSONDecodeError, OSError):
            pass

    # Normalize data
    df_norm = normalize_yfinance_ohlcv(df)

    # Regime params from config
    vix_block = float(signal_cfg.get("VIX_BLOCK_THRESHOLD", 25))
    adx_trend = float(signal_cfg.get("ADX_TREND_THRESHOLD", 25))
    adx_chop = float(signal_cfg.get("ADX_CHOP_THRESHOLD", 20))
    regime_params = PureIndexRegimeParams(
        vix_block_threshold=vix_block,
        adx_trend_threshold=adx_trend,
        adx_chop_threshold=adx_chop,
    )

    if put_force:
        # Monkey-patch to force PUT direction
        import core.candle_backtest as bt_mod
        _orig_execute = bt_mod.CandleBacktestEngine._execute_pending
        def _patched_execute(self, pending, row, idx, ts, cfg, capital):
            p2 = dict(pending)
            if p2["direction"] == "CALL":
                p2["direction"] = "PUT"
            return _orig_execute(self, p2, row, idx, ts, cfg, capital)
        bt_mod.CandleBacktestEngine._execute_pending = _patched_execute

    cfg = CandleBacktestConfig(
        initial_capital=initial_capital,
        strict_oi=False,
        base_ai_threshold=threshold,
        score_gap=score_gap,
        sl_atr_mult=sl_atr_mult,
        tp_atr_mult=tp_atr_mult,
        vix=vix,
        fee_per_lot=fee_per_lot,
        use_option_model=use_option_model,
        use_regime_rr=use_regime_rr,
    )

    iv_spike_threshold = float(signal_cfg.get("IV_SPIKE_THRESHOLD", 45.0))
    vol_ratio_min = float(signal_cfg.get("VOL_RATIO_MIN", 1.2))

    eng = CandleBacktestEngine(
        signal_cfg=signal_cfg,
        regime_params=regime_params,
        iv_spike_threshold=iv_spike_threshold,
        vol_ratio_min=vol_ratio_min,
        name=symbol,
    )

    result = eng.run(df_norm, cfg)
    m = result.metrics

    # Build report
    report = {
        "config": {
            "symbol": symbol,
            "period": f"{df_norm.index[0]} to {df_norm.index[-1]}",
            "bars": len(df_norm),
            "threshold": threshold,
            "score_gap": score_gap,
            "sl_atr_mult": sl_atr_mult,
            "tp_atr_mult": tp_atr_mult,
            "vix": vix,
            "put_force": put_force,
            "option_model": use_option_model,
            "regime_rr": use_regime_rr,
            "initial_capital": initial_capital,
            "fee_per_lot": fee_per_lot,
        },
        "metrics": {
            "total_trades": m.total_trades,
            "win_rate": m.win_rate,
            "profit_factor": m.profit_factor,
            "expectancy": m.expectancy_per_trade,
            "max_drawdown_pct": m.max_drawdown_pct,
            "sharpe": m.sharpe_ratio,
            "calmar": m.calmar_ratio,
            "wins": m.wins,
            "losses": m.losses,
            "avg_win": m.avg_win,
            "avg_loss": m.avg_loss,
            "rr_ratio": m.rr_ratio,
            "call_trades": m.call_trades,
            "put_trades": m.put_trades,
            "call_win_rate": m.call_win_rate,
            "put_win_rate": m.put_win_rate,
        },
        "regime_breakdown": {
            r: {"trades": s.trades, "wins": s.wins, "gross_pnl": s.gross_pnl}
            for r, s in m.by_regime.items()
            if s.trades > 0
        },
        "score_breakdown": {
            lbl: {"trades": b.trades, "wins": b.wins, "gross_pnl": b.gross_pnl}
            for lbl, b in m.by_score.items()
            if b.trades > 0
        },
        "ending_capital": result.ending_capital,
        "trades": [],
    }

    for t in result.journal:
        report["trades"].append({
            "entry": t.entry_time,
            "exit": t.exit_time,
            "direction": t.direction,
            "pnl": t.net_pnl,
            "score": t.score,
            "rr": t.rr_achieved,
            "exit_reason": t.exit_reason,
            "bars_held": t.bars_held,
            "regime": t.regime,
        })

    return report


def print_report(report: dict, verbose: bool = False) -> None:
    """Print a human-readable report (ASCII-safe, no Unicode)."""
    cfg = report["config"]
    m = report["metrics"]

    print("=" * 70)
    print(f"  CSV BACKTEST REPORT  |  {cfg['symbol']}  |  {cfg['period']}")
    print("=" * 70)
    print(f"  Config: thr={cfg['threshold']}, gap={cfg['score_gap']}, "
          f"SL={cfg['sl_atr_mult']}x, TP={cfg['tp_atr_mult']}x")
    print(f"  VIX={cfg['vix']}, OptionModel={cfg['option_model']}, PUT-Force={cfg['put_force']}")
    print(f"  Bars: {cfg['bars']:,}  |  Capital: Rs {cfg['initial_capital']:,.0f}")
    print()

    print("  Core Metrics:")
    print(f"    Trades: {m['total_trades']}  |  Win Rate: {m['win_rate']}%  "
          f"|  PF: {m['profit_factor']}")
    print(f"    Expectancy: Rs {m['expectancy']:.2f}  |  Max DD: {m['max_drawdown_pct']}%")
    print(f"    Sharpe: {m['sharpe']}  |  Calmar: {m['calmar']}")
    print(f"    Avg Win: Rs {m['avg_win']:.2f}  |  Avg Loss: Rs {m['avg_loss']:.2f}  "
          f"|  RR: {m['rr_ratio']}")
    print(f"    Ending Capital: Rs {report['ending_capital']:,.2f}  "
          f"|  Return: {(report['ending_capital']/cfg['initial_capital']-1)*100:.2f}%")
    print()

    print("  Directional:")
    print(f"    CALL: {m['call_trades']} trades ({m['call_win_rate']}% WR)")
    print(f"    PUT:  {m['put_trades']} trades ({m['put_win_rate']}% WR)")
    print()

    if report["regime_breakdown"]:
        print("  Regime Breakdown:")
        for r, s in report["regime_breakdown"].items():
            wr = s["wins"] / s["trades"] * 100 if s["trades"] else 0
            print(f"    {r:15s}: {s['trades']:3d}t / {s['wins']:2d}w  "
                  f"WR={wr:.0f}%  PnL=Rs {s['gross_pnl']:.0f}")
        print()

    if verbose and report["trades"]:
        print(f"  Trade Log ({len(report['trades'])} trades):")
        for t in report["trades"]:
            print(f"    {t['entry']} -> {t['exit']}  |  {t['direction']:4s}  "
                  f"PnL={t['pnl']:+7.0f}  |  Scr={t['score']:2d}  "
                  f"RR={t['rr']:.2f}  |  {t['exit_reason']:12s}  "
                  f"Bars={t['bars_held']:2d}  |  {t['regime']}")
        print()

    profit = report["ending_capital"] - cfg["initial_capital"]
    if profit > 0:
        print(f"  [PROFIT] +Rs {profit:,.2f}")
    elif profit < 0:
        print(f"  [LOSS] -Rs {abs(profit):,.2f}")
    else:
        print("  [BREAK EVEN] Rs 0")


def main() -> None:
    p = argparse.ArgumentParser(
        description="CSV Backtest Replay -- Load 1m OHLCV data and run candle backtest",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/run_csv_backtest.py data/nifty_1m.csv
  python scripts/run_csv_backtest.py data/nifty_1m.csv --from 2025-10-01 --to 2025-12-31
  python scripts/run_csv_backtest.py data/nifty_1m.csv --put-force --sl 0.15 --tp 2.0
  python scripts/run_csv_backtest.py data/nifty_1m.csv --symbol BANKNIFTY --vix 16
  python scripts/run_csv_backtest.py data/nifty_1m.csv --json > results.json
        """,
    )
    p.add_argument("csv", type=str, help="Path to CSV file with 1m OHLCV data")
    p.add_argument("--from", dest="date_from", type=str, default=None,
                   help="Start date (YYYY-MM-DD)")
    p.add_argument("--to", dest="date_to", type=str, default=None,
                   help="End date (YYYY-MM-DD)")
    p.add_argument("--symbol", type=str, default="NIFTY", help="Index name (default: NIFTY)")
    p.add_argument("--thr", type=int, default=60, help="AI threshold (default: 60)")
    p.add_argument("--score-gap", type=int, default=5, help="Score gap (default: 5)")
    p.add_argument("--sl", type=float, default=1.2, help="SL ATR multiplier (default: 1.2)")
    p.add_argument("--tp", type=float, default=1.618, help="TP ATR multiplier (default: 1.618)")
    p.add_argument("--vix", type=float, default=14.0, help="VIX level (default: 14)")
    p.add_argument("--capital", type=float, default=100_000.0,
                   help="Initial capital (default: 100000)")
    p.add_argument("--fee", type=float, default=40.0,
                   help="Fee per lot round-trip (default: 40)")
    p.add_argument("--put-force", action="store_true",
                   help="Force all CALL signals to PUT direction")
    p.add_argument("--no-option-model", dest="option_model", action="store_false",
                   help="Use raw index-point P&L instead of option premium model")
    p.add_argument("--no-regime-rr", dest="regime_rr", action="store_false",
                   help="Disable regime-adaptive TP/SL")
    p.add_argument("--json", action="store_true", help="Output as JSON")
    p.add_argument("--verbose", "-v", action="store_true", help="Show trade log")

    args = p.parse_args()

    df = load_csv(args.csv, date_from=args.date_from, date_to=args.date_to)
    report = run_backtest(
        df,
        symbol=args.symbol,
        threshold=args.thr,
        score_gap=args.score_gap,
        sl_atr_mult=args.sl,
        tp_atr_mult=args.tp,
        vix=args.vix,
        put_force=args.put_force,
        use_option_model=args.option_model,
        use_regime_rr=args.regime_rr,
        initial_capital=args.capital,
        fee_per_lot=args.fee,
        verbose=args.verbose,
    )

    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print_report(report, verbose=args.verbose)


if __name__ == "__main__":
    main()
