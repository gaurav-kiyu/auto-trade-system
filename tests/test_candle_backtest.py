from __future__ import annotations

from pathlib import Path

from core.backtest_engine import CsvReplaySource, ReplayConfig
from core.candle_backtest import CandleBacktestConfig, run_candle_backtest
from core.pure_index_signal import PureIndexRegimeParams


ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"


def test_run_candle_backtest_on_fixture_csv():
    src = CsvReplaySource(FIXTURES / "replay_minute_bars.csv", ReplayConfig(warmup_bars=30))
    df = src.load()
    res = run_candle_backtest(
        df,
        signal_cfg={"VOL_RATIO_MIN": 0.01, "MACD_BONUS": 0, "STRONG_THRESHOLD": 85, "MODERATE_THRESHOLD": 70},
        regime_params=PureIndexRegimeParams(99.0, 5.0, 50.0),
        iv_spike_threshold=99.0,
        vol_ratio_min=0.01,
        backtest_cfg=CandleBacktestConfig(warmup_bars=30, base_ai_threshold=25, latency_bars=0, fee_per_lot=0.0, strict_oi=False),
        symbol="NIFTY",
    )
    assert res.ending_capital >= 0
    assert isinstance(res.equity_curve, list)
    assert res.metrics.total_trades >= 0
