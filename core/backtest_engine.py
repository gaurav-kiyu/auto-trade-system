from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from .strategy_engine import StrategyEngine


__all__ = [
    "BacktestConfig",
    "BacktestEngine",
    "BacktestReport",
    "BacktestTrade",
    "CsvReplaySource",
    "ReplayConfig",
    "ReplayEngine",
    "ReplaySignal",
]

@dataclass(frozen=True)
class ReplayConfig:
    datetime_column: str = "Datetime"
    open_column: str = "Open"
    high_column: str = "High"
    low_column: str = "Low"
    close_column: str = "Close"
    volume_column: str = "Volume"
    base_interval: str = "1min"
    frame_intervals: tuple[str, ...] = ("1min", "5min", "15min")
    warmup_bars: int = 20


@dataclass(frozen=True)
class BacktestConfig:
    initial_capital: float = 5000.0
    trade_size: int = 1
    signal_entry_buffer: int = 0
    fallback_stop_pct: float = 0.01
    fallback_target_pct: float = 0.02
    max_bars_in_trade: int = 20
    commission_per_trade: float = 0.0
    slippage_pct: float = 0.0
    cooldown_bars: int = 0


@dataclass(frozen=True)
class ReplaySignal:
    timestamp: str
    score: float
    threshold: float
    direction: str
    strength: str
    regime: str


@dataclass(frozen=True)
class BacktestTrade:
    entry_time: str
    exit_time: str
    direction: str
    entry_price: float
    exit_price: float
    qty: int
    gross_pnl: float
    net_pnl: float
    exit_reason: str
    bars_held: int
    signal_score: float
    signal_threshold: float


@dataclass(frozen=True)
class BacktestReport:
    name: str
    initial_capital: float
    ending_capital: float
    trades: list[BacktestTrade]
    total_trades: int
    wins: int
    losses: int
    win_rate: float
    net_pnl: float
    max_drawdown: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "initial_capital": self.initial_capital,
            "ending_capital": self.ending_capital,
            "total_trades": self.total_trades,
            "wins": self.wins,
            "losses": self.losses,
            "win_rate": self.win_rate,
            "net_pnl": self.net_pnl,
            "max_drawdown": self.max_drawdown,
            "trades": [asdict(trade) for trade in self.trades],
        }


class CsvReplaySource:
    def __init__(self, csv_path: str | Path, config: ReplayConfig | None = None) -> None:
        self._csv_path = Path(csv_path)
        self._config = config or ReplayConfig()

    def load(self) -> pd.DataFrame:
        df = pd.read_csv(self._csv_path)
        cfg = self._config
        renamed = {
            cfg.datetime_column: "Datetime",
            cfg.open_column: "Open",
            cfg.high_column: "High",
            cfg.low_column: "Low",
            cfg.close_column: "Close",
            cfg.volume_column: "Volume",
        }
        df = df.rename(columns=renamed)
        missing = [name for name in ("Datetime", "Open", "High", "Low", "Close", "Volume") if name not in df.columns]
        if missing:
            raise ValueError(f"Replay CSV missing columns: {', '.join(missing)}")
        df["Datetime"] = pd.to_datetime(df["Datetime"])
        df = df.sort_values("Datetime").set_index("Datetime")
        for col in ("Open", "High", "Low", "Close", "Volume"):
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.dropna(subset=["Open", "High", "Low", "Close"]).copy()
        return df


class ReplayEngine:
    def __init__(self, strategy_engine: StrategyEngine, replay_config: ReplayConfig | None = None) -> None:
        self._strategy_engine = strategy_engine
        self._cfg = replay_config or ReplayConfig()

    def _build_frames(self, base_df: pd.DataFrame, upto: int) -> dict[str, pd.DataFrame]:
        window = base_df.iloc[: upto + 1].copy()
        frames: dict[str, pd.DataFrame] = {"1m": window.copy()}
        agg = {
            "Open": "first",
            "High": "max",
            "Low": "min",
            "Close": "last",
            "Volume": "sum",
        }
        interval_map = {"1min": "1min", "5min": "5min", "15min": "15min", "1m": "1min", "5m": "5min", "15m": "15min"}
        for interval in self._cfg.frame_intervals:
            key = "1m" if interval in ("1min", "1m") else ("5m" if interval in ("5min", "5m") else ("15m" if interval in ("15min", "15m") else interval))
            if key == "1m":
                frames[key] = window.copy()
                continue
            rule = interval_map.get(interval, interval)
            rs = window.resample(rule, label="right", closed="right").agg(agg).dropna(subset=["Open", "High", "Low", "Close"])
            frames[key] = rs
        return frames

    def run(self, name: str, base_df: pd.DataFrame, vix: float = 0.0) -> list[ReplaySignal]:
        out: list[ReplaySignal] = []
        warmup = max(1, int(self._cfg.warmup_bars))
        for idx in range(warmup, len(base_df)):
            frames = self._build_frames(base_df, idx)
            sig = self._strategy_engine.generate_signal(name, frames, vix=vix)
            if not sig:
                continue
            snapshot = self._strategy_engine.snapshot(name, sig)
            out.append(
                ReplaySignal(
                    timestamp=str(base_df.index[idx]),
                    score=snapshot.score,
                    threshold=snapshot.threshold,
                    direction=snapshot.direction,
                    strength=snapshot.strength,
                    regime=snapshot.regime,
                )
            )
        return out


class BacktestEngine:
    def __init__(
        self,
        strategy_engine: StrategyEngine,
        replay_config: ReplayConfig | None = None,
        backtest_config: BacktestConfig | None = None,
    ) -> None:
        self._strategy_engine = strategy_engine
        self._replay_engine = ReplayEngine(strategy_engine, replay_config=replay_config)
        self._cfg = backtest_config or BacktestConfig()

    @staticmethod
    def _coerce_float(value: Any, default: float) -> float:
        try:
            return float(value)
        except (ValueError, TypeError):
            return float(default)

    def run(self, name: str, base_df: pd.DataFrame, vix: float = 0.0) -> BacktestReport:
        cfg = self._cfg
        trades: list[BacktestTrade] = []
        capital = float(cfg.initial_capital)
        peak_capital = capital
        max_drawdown = 0.0
        position: dict[str, Any] | None = None
        cooldown_until = -1
        warmup = max(1, int(self._replay_engine._cfg.warmup_bars))

        for idx in range(warmup, len(base_df)):
            row = base_df.iloc[idx]
            ts = str(base_df.index[idx])

            if position is not None:
                exit_price = None
                exit_reason = ""
                direction = str(position["direction"])
                stop_loss = float(position["stop_loss"])
                target = float(position["target"])
                held = idx - int(position["entry_idx"])
                if direction == "CALL":
                    if float(row["Low"]) <= stop_loss:
                        exit_price = stop_loss
                        exit_reason = "stop_loss"
                    elif float(row["High"]) >= target:
                        exit_price = target
                        exit_reason = "target"
                else:
                    if float(row["High"]) >= stop_loss:
                        exit_price = stop_loss
                        exit_reason = "stop_loss"
                    elif float(row["Low"]) <= target:
                        exit_price = target
                        exit_reason = "target"
                if exit_price is None and held >= int(cfg.max_bars_in_trade):
                    exit_price = float(row["Close"])
                    exit_reason = "time_exit"
                if exit_price is not None:
                    entry_price = float(position["entry_price"])
                    qty = int(position["qty"])
                    gross = (float(exit_price) - entry_price) * qty if direction == "CALL" else (entry_price - float(exit_price)) * qty
                    net = gross - float(cfg.commission_per_trade)
                    capital = round(capital + net, 2)
                    peak_capital = max(peak_capital, capital)
                    if peak_capital > 0:
                        max_drawdown = max(max_drawdown, round((peak_capital - capital) / peak_capital * 100, 2))
                    trades.append(
                        BacktestTrade(
                            entry_time=str(position["entry_time"]),
                            exit_time=ts,
                            direction=direction,
                            entry_price=round(entry_price, 4),
                            exit_price=round(float(exit_price), 4),
                            qty=qty,
                            gross_pnl=round(gross, 2),
                            net_pnl=round(net, 2),
                            exit_reason=exit_reason,
                            bars_held=held,
                            signal_score=float(position["score"]),
                            signal_threshold=float(position["threshold"]),
                        )
                    )
                    position = None
                    cooldown_until = idx + int(cfg.cooldown_bars)
                    continue

            if position is not None or idx < cooldown_until:
                continue

            frames = self._replay_engine._build_frames(base_df, idx)
            sig = self._strategy_engine.generate_signal(name, frames, vix=vix)
            if not sig:
                continue
            score = self._coerce_float(sig.get("score"), 0.0)
            threshold = self._coerce_float(sig.get("threshold"), 0.0)
            if score < threshold + float(cfg.signal_entry_buffer):
                continue
            direction = str(sig.get("direction") or "CALL").upper()
            close_px = float(row["Close"])
            slip_mult = 1.0 + float(cfg.slippage_pct) if direction == "CALL" else 1.0 - float(cfg.slippage_pct)
            entry_price = round(close_px * slip_mult, 4)
            stop_default = entry_price * (1.0 - float(cfg.fallback_stop_pct)) if direction == "CALL" else entry_price * (1.0 + float(cfg.fallback_stop_pct))
            target_default = entry_price * (1.0 + float(cfg.fallback_target_pct)) if direction == "CALL" else entry_price * (1.0 - float(cfg.fallback_target_pct))
            position = {
                "entry_idx": idx,
                "entry_time": ts,
                "entry_price": entry_price,
                "stop_loss": self._coerce_float(sig.get("stop_loss"), stop_default),
                "target": self._coerce_float(sig.get("tp2"), target_default),
                "direction": direction,
                "qty": int(sig.get("qty") or cfg.trade_size),
                "score": score,
                "threshold": threshold,
            }

        wins = len([t for t in trades if t.net_pnl >= 0])
        losses = len(trades) - wins
        net_pnl = round(sum(t.net_pnl for t in trades), 2)
        win_rate = round((wins / len(trades) * 100.0), 2) if trades else 0.0
        return BacktestReport(
            name=name,
            initial_capital=float(cfg.initial_capital),
            ending_capital=round(float(cfg.initial_capital) + net_pnl, 2),
            trades=trades,
            total_trades=len(trades),
            wins=wins,
            losses=losses,
            win_rate=win_rate,
            net_pnl=net_pnl,
            max_drawdown=max_drawdown,
        )
