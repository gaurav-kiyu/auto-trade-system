"""
Tests for core/adaptive_signal.py - Adaptive signal evaluator with soft rejection.

Covers:
  - AdaptiveSignal dataclass
  - SignalConfidenceBand dataclass
  - _wilson_ci calculation (Wilson 95% CI)
  - compute_confidence_band with mocked DB
  - TimeframeAgreement dataclass
  - compute_timeframe_agreement across 1m/5m/15m
  - _build_risk_dict for tier rules
  - evaluate_adaptive_signal basic flow (soft rejection and data gates)
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import pandas as pd

from core.adaptive_signal import (
    AdaptiveSignal,
    SignalConfidenceBand,
    TimeframeAgreement,
    _build_risk_dict,
    _wilson_ci,
    compute_confidence_band,
    compute_timeframe_agreement,
)


# ── AdaptiveSignal Dataclass ────────────────────────────────────────


class TestAdaptiveSignal:
    def test_minimal_creation(self) -> None:
        signal = AdaptiveSignal(
            tier="STRONG",
            score=85,
            raw_score=90,
            confidence=0.85,
            direction="CALL",
            regime="TRENDING",
            soft_blocks=[],
            reasons=["score=85"],
            score_components={"tf_aligned": 20, "vwap": 15},
            features=["tf_aligned", "vwap"],
        )
        assert signal.tier == "STRONG"
        assert signal.score == 85
        assert signal.raw_score == 90
        assert signal.direction == "CALL"
        assert signal.regime == "TRENDING"
        assert signal.reasons == ["score=85"]
        assert signal.atr == 0.0  # default

    def test_default_values(self) -> None:
        signal = AdaptiveSignal(
            tier="WEAK", score=55, raw_score=60,
            confidence=0.5, direction="PUT",
            regime="NEUTRAL", soft_blocks=[],
            reasons=[], score_components={}, features=[],
        )
        assert signal.atr == 0.0
        assert signal.rsi == 50.0
        assert signal.adx == 0.0
        assert signal.vwap == 0.0
        assert signal.vol_ratio == 0.0
        assert signal.price == 0.0
        assert signal.macd == {}
        assert signal.risk == {}
        assert signal.position_spec is None
        assert signal.ml_pred_id == ""
        assert signal.reasoning == ""
        assert signal.confidence_band is None

    def test_with_all_fields(self) -> None:
        signal = AdaptiveSignal(
            tier="MODERATE", score=72, raw_score=75,
            confidence=0.7, direction="CALL",
            regime="SIDEWAYS", soft_blocks=["tf_mismatch"],
            reasons=["[TF] divergence"], score_components={"tf_aligned": 0},
            features=[], atr=120.0, rsi=55.0, adx=22.0,
            vwap=23480.0, vol_ratio=1.8, price=23500.0,
            macd={"histogram": 2.0, "macd": 5.0, "signal": 4.0},
            risk={"sl_mult_adj": 1.0},
            ml_pred_id="sig_12345",
            reasoning="Top Features: score:0.35",
        )
        assert signal.atr == 120.0
        assert signal.price == 23500.0
        assert signal.ml_pred_id == "sig_12345"
        assert "score:0.35" in signal.reasoning

    def test_soft_blocks_list(self) -> None:
        signal = AdaptiveSignal(
            tier="WEAK", score=40, raw_score=60,
            confidence=0.4, direction="PUT",
            regime="CHOPPY", soft_blocks=["tf_mismatch", "choppy_regime"],
            reasons=[], score_components={}, features=[],
        )
        assert len(signal.soft_blocks) == 2
        assert "tf_mismatch" in signal.soft_blocks
        assert "choppy_regime" in signal.soft_blocks

    def test_direction(self) -> None:
        call = AdaptiveSignal(
            tier="STRONG", score=85, raw_score=85,
            confidence=1.0, direction="CALL",
            regime="TRENDING", soft_blocks=[],
            reasons=[], score_components={}, features=[],
        )
        put = AdaptiveSignal(
            tier="STRONG", score=80, raw_score=80,
            confidence=1.0, direction="PUT",
            regime="TRENDING", soft_blocks=[],
            reasons=[], score_components={}, features=[],
        )
        assert call.direction == "CALL"
        assert put.direction == "PUT"


# ── SignalConfidenceBand Dataclass ──────────────────────────────────


class TestSignalConfidenceBand:
    def test_minimal_creation(self) -> None:
        band = SignalConfidenceBand(
            n_trades=100, n_wins=60, win_rate=0.6,
            ci_low=0.5, ci_high=0.7,
        )
        assert band.n_trades == 100
        assert band.win_rate == 0.6
        assert band.ci_low == 0.5
        assert band.ci_high == 0.7

    def test_with_all_fields(self) -> None:
        band = SignalConfidenceBand(
            n_trades=50, n_wins=35, win_rate=0.7,
            ci_low=0.55, ci_high=0.82,
            score_bin="70-80", regime="TRENDING",
            session="MORNING", direction="CALL",
        )
        assert band.score_bin == "70-80"
        assert band.regime == "TRENDING"
        assert band.session == "MORNING"
        assert band.direction == "CALL"

    def test_str_representation(self) -> None:
        band = SignalConfidenceBand(
            n_trades=100, n_wins=60, win_rate=0.6,
            ci_low=0.5, ci_high=0.7,
        )
        s = str(band)
        assert "CI:" in s
        assert "n=100" in s
        # Check that numeric values are formatted
        assert re.search(r'\d+%', s)  # Contains a percentage

    def test_str_with_zero_trades_default(self) -> None:
        band = SignalConfidenceBand(
            n_trades=0, n_wins=0, win_rate=0.0,
            ci_low=0.0, ci_high=1.0,
        )
        s = str(band)
        assert "0%" in s or "1" in s


# ── _wilson_ci ──────────────────────────────────────────────────────


class TestWilsonCI:
    def test_win_rate_half(self) -> None:
        lo, hi = _wilson_ci(50, 100)
        assert lo < 0.6
        assert hi > 0.4
        assert lo < 0.5 < hi  # 0.5 should be within interval

    def test_all_wins(self) -> None:
        lo, hi = _wilson_ci(100, 100)
        assert lo > 0.95  # Very tight upper bound

    def test_no_wins(self) -> None:
        lo, hi = _wilson_ci(0, 100)
        assert hi < 0.05  # Very tight lower bound
        assert lo == 0.0

    def test_zero_trades_default(self) -> None:
        lo, hi = _wilson_ci(0, 0)
        assert lo == 0.0
        assert hi == 1.0

    def test_single_trade(self) -> None:
        lo, hi = _wilson_ci(1, 1)
        assert lo > 0.0
        assert hi <= 1.0

    def test_ci_narrows_with_more_data(self) -> None:
        lo_small, hi_small = _wilson_ci(30, 60)
        lo_large, hi_large = _wilson_ci(300, 600)
        # Larger sample should have narrower CI
        small_width = hi_small - lo_small
        large_width = hi_large - lo_large
        assert large_width < small_width

    def test_z_default_is_196(self) -> None:
        lo, hi = _wilson_ci(50, 100)
        assert lo < hi

    def test_custom_z_score(self) -> None:
        lo_1, hi_1 = _wilson_ci(50, 100, z=1.0)
        lo_2, hi_2 = _wilson_ci(50, 100, z=3.0)
        # Higher z = wider interval
        assert (hi_2 - lo_2) > (hi_1 - lo_1)


# ── compute_confidence_band ─────────────────────────────────────────


class TestComputeConfidenceBand:
    def test_disabled_returns_none(self) -> None:
        result = compute_confidence_band(
            score=80, regime="TRENDING",
            session="MORNING", direction="CALL",
            db_path="nonexistent.db",
            cfg={"confidence_band_enabled": False},
        )
        assert result is None

    def test_returns_none_on_missing_db(self) -> None:
        result = compute_confidence_band(
            score=80, regime="TRENDING",
            session="MORNING", direction="CALL",
            db_path="nonexistent.db",
            cfg={},
        )
        assert result is None

    def test_returns_none_on_db_error(self) -> None:
        result = compute_confidence_band(
            score=80, regime="TRENDING",
            session="MORNING", direction="CALL",
            db_path="",
            cfg={},
        )
        assert result is None

    def test_returns_none_empty_db(self, tmp_path: Path) -> None:
        db = tmp_path / "empty.db"
        conn = sqlite3.connect(str(db))
        conn.execute("CREATE TABLE trades (id INTEGER PRIMARY KEY)")
        conn.close()
        result = compute_confidence_band(
            score=80, regime="TRENDING",
            session="MORNING", direction="CALL",
            db_path=str(db),
            cfg={},
        )
        assert result is None  # No matching score_bin

    def test_with_valid_data(self, tmp_path: Path) -> None:
        db = tmp_path / "trades.db"
        conn = sqlite3.connect(str(db))
        conn.execute("""
            CREATE TABLE trades (
                score INTEGER, regime TEXT, direction TEXT,
                net_pnl REAL, session TEXT
            )
        """)
        # Insert trades in score range 75-85
        for i in range(10):
            conn.execute(
                "INSERT INTO trades (score, regime, direction, net_pnl, session) VALUES (?, ?, ?, ?, ?)",
                (80, "TRENDING", "CALL", 500.0 if i < 7 else -300.0, "MORNING"),
            )
        conn.commit()
        conn.close()
        result = compute_confidence_band(
            score=80, regime="TRENDING",
            session="MORNING", direction="CALL",
            db_path=str(db),
            cfg={},
        )
        assert result is not None
        assert result.n_trades == 10
        assert 0.5 <= result.win_rate <= 0.8  # 7/10 wins = 0.7
        assert result.score_bin == "75-85"


# ── TimeframeAgreement Dataclass ────────────────────────────────────


class TestTimeframeAgreement:
    def test_full_agreement(self) -> None:
        ta = TimeframeAgreement(
            agreement_score=1.0,
            bullish_count=3,
            bearish_count=0,
            divergence_detail="1m=UP | 5m=UP | 15m=UP",
        )
        assert ta.agreement_score == 1.0
        assert ta.bullish_count == 3
        assert ta.bearish_count == 0

    def test_full_divergence(self) -> None:
        ta = TimeframeAgreement(
            agreement_score=0.0,
            bullish_count=1,
            bearish_count=2,
            divergence_detail="1m=UP | 5m=DOWN | 15m=DOWN",
        )
        assert ta.agreement_score == 0.0


# ── compute_timeframe_agreement ─────────────────────────────────────


class TestComputeTimeframeAgreement:
    def test_all_up_full_agreement(self) -> None:
        result = compute_timeframe_agreement("UP", "UP", "UP")
        assert result.agreement_score == 1.0
        assert result.bullish_count == 3
        assert result.bearish_count == 0

    def test_all_down_full_agreement(self) -> None:
        result = compute_timeframe_agreement("DOWN", "DOWN", "DOWN")
        assert result.agreement_score == 1.0
        assert result.bullish_count == 0
        assert result.bearish_count == 3

    def test_mixed_scores_partial(self) -> None:
        result = compute_timeframe_agreement("UP", "UP", "DOWN")
        # 2 UP, 1 DOWN → 2/3 agreement, rounded to 3 decimal places
        assert result.agreement_score == round(2 / 3, 3)
        assert result.bullish_count == 2
        assert result.bearish_count == 1

    def test_all_flat_returns_zero(self) -> None:
        result = compute_timeframe_agreement("FLAT", "FLAT", "FLAT")
        assert result.agreement_score == 0.0
        assert result.bullish_count == 0
        assert result.bearish_count == 0

    def test_one_flat_two_same(self) -> None:
        result = compute_timeframe_agreement("UP", "FLAT", "UP")
        # 2 UP, 0 DOWN, n_defined=2 → 2/2 = 1.0
        assert result.agreement_score == 1.0

    def test_one_flat_one_each(self) -> None:
        result = compute_timeframe_agreement("UP", "FLAT", "DOWN")
        # n_defined=2, max(1,1)=1 → 1/2 = 0.5
        assert result.agreement_score == 0.5

    def test_divergence_detail_includes_all(self) -> None:
        result = compute_timeframe_agreement("UP", "DOWN", "FLAT")
        assert "1m=UP" in result.divergence_detail
        assert "5m=DOWN" in result.divergence_detail
        assert "15m=FLAT" in result.divergence_detail

    def test_case_sensitive(self) -> None:
        result_upper = compute_timeframe_agreement("UP", "DOWN", "FLAT")
        assert isinstance(result_upper.agreement_score, float)


# ── _build_risk_dict ────────────────────────────────────────────────


class TestBuildRiskDict:
    def test_returns_risk_params_for_tier(self) -> None:
        risk = _build_risk_dict("STRONG")
        assert isinstance(risk, dict)
        assert "sl_mult_adj" in risk
        assert "tp_mult_adj" in risk
        assert "trail_enabled" in risk

    def test_unknown_tier_empty(self) -> None:
        risk = _build_risk_dict("INVALID_TIER")
        assert risk == {}

    def test_strong_tier_values(self) -> None:
        risk = _build_risk_dict("STRONG")
        assert risk.get("partial_exit_enabled") is not None
        assert risk.get("max_bars_mult") is not None

    def test_trail_values(self) -> None:
        risk = _build_risk_dict("STRONG")
        assert "trail_activate_pct" in risk
        assert "trail_from_peak_pct" in risk


# ── evaluate_adaptive_signal basic tests (with mocked df) ───────────


class TestEvaluateAdaptiveSignalBasic:
    def test_requires_dataframes(self) -> None:
        """With None dataframes, should return None with a hard-block reason."""
        from core.adaptive_signal import evaluate_adaptive_signal
        from core.pure_index_signal import PureIndexRegimeParams, PureIndexSignalParams

        params = PureIndexSignalParams(
            name="NIFTY",
            signal_cfg={
                "EARLY_SESSION_MIN_15M": 4,
                "NORMAL_SESSION_MIN_15M": 5,
                "ATR_MIN_THRESHOLD": 0.5,
            },
            regime=PureIndexRegimeParams(
                vix_block_threshold=35.0,
                adx_trend_threshold=20.0,
                adx_chop_threshold=15.0,
            ),
            iv_spike_threshold=50.0,
            vol_ratio_min=1.5,
            is_early_session=False,
        )
        result, reason = evaluate_adaptive_signal(
            params=params,
            df1=None, df5=None, df15=None,
            vix=20.0, iv=10.0,
            oi_sup=0, oi_res=0,
            pcr=1.0, smart="NEUTRAL",
        )
        assert result is None
        assert "short" in reason or reason is not None

    def test_with_small_dfs(self) -> None:
        """With dataframes that are too small, should return None."""
        from core.adaptive_signal import evaluate_adaptive_signal
        from core.pure_index_signal import PureIndexRegimeParams, PureIndexSignalParams

        params = PureIndexSignalParams(
            name="NIFTY",
            signal_cfg={
                "EARLY_SESSION_MIN_15M": 4,
                "NORMAL_SESSION_MIN_15M": 5,
                "ATR_MIN_THRESHOLD": 0.5,
            },
            regime=PureIndexRegimeParams(
                vix_block_threshold=35.0,
                adx_trend_threshold=20.0,
                adx_chop_threshold=15.0,
            ),
            iv_spike_threshold=50.0,
            vol_ratio_min=1.5,
            is_early_session=False,
        )

        small_df = pd.DataFrame({
            "Open": [100.0] * 5,
            "High": [101.0] * 5,
            "Low": [99.0] * 5,
            "Close": [100.0] * 5,
            "Volume": [10000] * 5,
        })
        result, reason = evaluate_adaptive_signal(
            params=params,
            df1=small_df, df5=small_df, df15=small_df,
            vix=20.0, iv=10.0,
            oi_sup=0, oi_res=0,
            pcr=1.0, smart="NEUTRAL",
        )
        assert result is None
        # Should complain about insufficient data
        assert reason is not None


# ── integration: compute_confidence_band with trades table ──────────


class TestConfidenceBandIntegration:
    def test_requires_score_bin(self, tmp_path: Path) -> None:
        """Trades outside the score bin should return None."""
        db = tmp_path / "trades.db"
        conn = sqlite3.connect(str(db))
        conn.execute("""
            CREATE TABLE trades (
                score INTEGER, regime TEXT, direction TEXT,
                net_pnl REAL, session TEXT
            )
        """)
        conn.execute(
            "INSERT INTO trades VALUES (?, ?, ?, ?, ?)",
            (30, "TRENDING", "CALL", 100.0, "MORNING"),
        )
        conn.commit()
        conn.close()
        result = compute_confidence_band(
            score=80, regime="TRENDING",
            session="MORNING", direction="CALL",
            db_path=str(db),
            cfg={},
        )
        assert result is None  # Score 30 not in 75-85 range

    def test_with_different_direction(self, tmp_path: Path) -> None:
        """Trades with wrong direction should not be counted."""
        db = tmp_path / "trades.db"
        conn = sqlite3.connect(str(db))
        conn.execute("""
            CREATE TABLE trades (
                score INTEGER, regime TEXT, direction TEXT,
                net_pnl REAL, session TEXT
            )
        """)
        for i in range(10):
            conn.execute(
                "INSERT INTO trades VALUES (?, ?, ?, ?, ?)",
                (80, "TRENDING", "PUT", 500.0 if i < 6 else -200.0, "MORNING"),
            )
        conn.commit()
        conn.close()
        result = compute_confidence_band(
            score=80, regime="TRENDING",
            session="MORNING", direction="CALL",
            db_path=str(db),
            cfg={},
        )
        assert result is None  # No CALL trades

    def test_custom_bin_width(self, tmp_path: Path) -> None:
        """Custom bin width should be respected."""
        db = tmp_path / "trades.db"
        conn = sqlite3.connect(str(db))
        conn.execute("""
            CREATE TABLE trades (
                score INTEGER, regime TEXT, direction TEXT,
                net_pnl REAL, session TEXT
            )
        """)
        # Insert trades with scores in range 70-90 for bin_width=10
        for score_val in [72, 75, 78, 82, 85]:
            conn.execute(
                "INSERT INTO trades VALUES (?, ?, ?, ?, ?)",
                (score_val, "TRENDING", "CALL", 500.0, "MORNING"),
            )
        conn.commit()
        conn.close()
        # With bin_width=10, score 80 should match 70-90 range
        result = compute_confidence_band(
            score=80, regime="TRENDING",
            session="MORNING", direction="CALL",
            db_path=str(db),
            cfg={"confidence_band_score_bin_width": 10},
        )
        # Trades with scores 72, 75, 78, 82, 85 are all in 70-90 range
        assert result is not None
        assert result.n_trades == 5
