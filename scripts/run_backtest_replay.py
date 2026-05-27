from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX_IMPL = ROOT / "index_app" / "index_trader.py"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import BacktestConfig, BacktestEngine, CsvReplaySource, ReplayConfig, ReplayEngine, StrategyEngine


def _load_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _load_index_strategy(config_path: Path | None) -> StrategyEngine:
    if config_path:
        os.environ["OPBUYING_INDEX_CONFIG"] = str(config_path)
    argv_prev = sys.argv[:]
    sys.argv = ["index_app/index_trader.py", "--nogui"]
    try:
        spec = importlib.util.spec_from_file_location("index_backtest_module", INDEX_IMPL)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)
        return StrategyEngine(
            generate_signal_fn=module.generate_signal,
            top_signals_fn=module._get_top_signals,
            detect_regime_fn=module.detect_regime,
            detect_regime_and_adx_fn=module.detect_regime_and_adx,
        )
    finally:
        sys.argv = argv_prev


def _smoke_strategy() -> StrategyEngine:
    def _generate_signal(name: str, frames: dict, vix: float = 0.0):
        frame_1m = frames.get("1m")
        if frame_1m is None or len(frame_1m) < 20:
            return None
        close_now = float(frame_1m["Close"].iloc[-1])
        close_prev = float(frame_1m["Close"].iloc[-2])
        if close_now <= close_prev:
            return None
        return {
            "name": name,
            "score": 84,
            "threshold": 70,
            "direction": "CALL",
            "strength": "STRONG",
            "regime": "TRENDING",
            "price": close_now,
            "stop_loss": round(close_now - 0.7, 2),
            "tp2": round(close_now + 0.9, 2),
            "qty": 1,
        }

    return StrategyEngine(generate_signal_fn=_generate_signal)


def _backtest_config(cfg: dict) -> BacktestConfig:
    return BacktestConfig(
        initial_capital=float(cfg.get("BACKTEST_INITIAL_CAPITAL", cfg.get("BASE_CAPITAL", 5000))),
        trade_size=int(cfg.get("BACKTEST_TRADE_SIZE", 1)),
        signal_entry_buffer=int(cfg.get("BACKTEST_SIGNAL_BUFFER", 0)),
        fallback_stop_pct=float(cfg.get("BACKTEST_FALLBACK_STOP_PCT", 0.01)),
        fallback_target_pct=float(cfg.get("BACKTEST_FALLBACK_TARGET_PCT", 0.02)),
        max_bars_in_trade=int(cfg.get("BACKTEST_MAX_BARS_IN_TRADE", 20)),
        commission_per_trade=float(cfg.get("BACKTEST_COMMISSION_PER_TRADE", 0.0)),
        slippage_pct=float(cfg.get("BACKTEST_SLIPPAGE_PCT", 0.0)),
        cooldown_bars=int(cfg.get("BACKTEST_COOLDOWN_BARS", 0)),
    )


def _replay_config(cfg: dict) -> ReplayConfig:
    return ReplayConfig(
        datetime_column=str(cfg.get("REPLAY_DATETIME_COLUMN", "Datetime")),
        open_column=str(cfg.get("REPLAY_OPEN_COLUMN", "Open")),
        high_column=str(cfg.get("REPLAY_HIGH_COLUMN", "High")),
        low_column=str(cfg.get("REPLAY_LOW_COLUMN", "Low")),
        close_column=str(cfg.get("REPLAY_CLOSE_COLUMN", "Close")),
        volume_column=str(cfg.get("REPLAY_VOLUME_COLUMN", "Volume")),
        base_interval=str(cfg.get("REPLAY_BASE_INTERVAL", "1min")),
        frame_intervals=tuple(cfg.get("REPLAY_FRAME_INTERVALS", ["1min", "5min", "15min"])),
        warmup_bars=int(cfg.get("REPLAY_WARMUP_BARS", 20)),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run configurable replay/backtest against captured CSV data.")
    parser.add_argument("--mode", choices=("replay", "backtest"), default="backtest")
    parser.add_argument("--strategy", choices=("index", "smoke"), default="index")
    parser.add_argument("--csv", required=True, help="Path to replay CSV file.")
    parser.add_argument("--name", default="NIFTY", help="Instrument label to pass into the existing strategy.")
    parser.add_argument("--config", default="config.json", help="Config JSON path.")
    parser.add_argument("--report-file", help="Optional JSON report path.")
    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = ROOT / config_path
    cfg = _load_json(config_path)

    replay_cfg = _replay_config(cfg)
    strategy = _smoke_strategy() if args.strategy == "smoke" else _load_index_strategy(config_path if config_path.is_file() else None)
    source = CsvReplaySource(args.csv, config=replay_cfg)
    base_df = source.load()

    if args.mode == "replay":
        engine = ReplayEngine(strategy, replay_config=replay_cfg)
        signals = engine.run(args.name, base_df, vix=float(cfg.get("BACKTEST_FIXED_VIX", 0.0)))
        payload = {"mode": "replay", "name": args.name, "signals": [signal.__dict__ for signal in signals]}
        print(f"Replay signals: {len(signals)}")
    else:
        engine = BacktestEngine(strategy, replay_config=replay_cfg, backtest_config=_backtest_config(cfg))
        report = engine.run(args.name, base_df, vix=float(cfg.get("BACKTEST_FIXED_VIX", 0.0)))
        payload = {"mode": "backtest", **report.to_dict()}
        print(
            f"Backtest {report.name}: trades={report.total_trades} win_rate={report.win_rate:.2f}% "
            f"net_pnl={report.net_pnl:.2f} ending_capital={report.ending_capital:.2f}"
        )

    if args.report_file:
        out = Path(args.report_file)
        if not out.is_absolute():
            out = ROOT / out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"Report: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
