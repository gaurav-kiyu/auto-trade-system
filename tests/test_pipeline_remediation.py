"""
Regression tests for Phase 2.1 Live-Market Pipeline Remediation.

Covers:
1. Blocker A: Yahoo Cache Independence (per-symbol cache timestamps, no starvation).
2. Blocker B: OHLCV Quality Gate (drop ratio <= 15% accepted, drop ratio > 15% rejected).
3. Blocker C: ML Alert Gate (PAPER/SIGNAL_ONLY neutral 0.500 fallback permitted; LIVE/AUTO strictly blocked).
4. Safety Invariants: SL_PCT=0.88, BASE_CAPITAL=3000, EXECUTION_MODE in (PAPER, SIGNAL_ONLY), live_trading_lockout_enabled=True.
"""

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from core.all_nse_scanner import AllNSEScanner
import core.yf_data_provider as yf_mod
from index_app.domains.signal.evaluator import SignalEvaluator


# ==============================================================================
# BLOCKER A: Yahoo Cache Independence Tests
# ==============================================================================

class TestYahooCacheIndependence:
    """Verify that _yf_data_cache_ts is per-symbol and avoids cache starvation."""

    def setup_method(self):
        yf_mod.invalidate_cache()

    def teardown_method(self):
        yf_mod.invalidate_cache()

    def test_cache_ts_is_per_symbol_dict(self):
        """_yf_data_cache_ts must be a dictionary, not a single float."""
        assert isinstance(yf_mod._yf_data_cache_ts, dict)

    def test_symbols_have_independent_cache_timestamps(self):
        """Fetching symbol A must not update or freeze symbol B's timestamp."""
        dummy_df = pd.DataFrame({"Close": [100.0, 101.0]})

        with patch.object(yf_mod, "fetch_intraday_data", return_value=(dummy_df, dummy_df, dummy_df)) as mock_fetch:
            # 1. Fetch NIFTY
            res1 = yf_mod.fetch_intraday_data_cached("^NSEI")
            assert mock_fetch.call_count == 1
            assert "^NSEI" in yf_mod._yf_data_cache_ts
            nifty_ts = yf_mod._yf_data_cache_ts["^NSEI"]

            # Advance clock slightly
            time.sleep(0.01)

            # 2. Fetch BANKNIFTY
            res2 = yf_mod.fetch_intraday_data_cached("^NSEBANK")
            assert mock_fetch.call_count == 2
            assert "^NSEBANK" in yf_mod._yf_data_cache_ts
            banknifty_ts = yf_mod._yf_data_cache_ts["^NSEBANK"]

            # Timestamps must be tracked independently
            assert banknifty_ts > nifty_ts
            assert yf_mod._yf_data_cache_ts["^NSEI"] == nifty_ts

    def test_invalidate_cache_clears_both_dicts(self):
        """invalidate_cache must clear both _yf_data_cache and _yf_data_cache_ts."""
        dummy_df = pd.DataFrame({"Close": [100.0]})
        with patch.object(yf_mod, "fetch_intraday_data", return_value=(dummy_df, dummy_df, dummy_df)):
            yf_mod.fetch_intraday_data_cached("^NSEI")
            assert len(yf_mod._yf_data_cache) > 0
            assert len(yf_mod._yf_data_cache_ts) > 0

            yf_mod.invalidate_cache()
            assert len(yf_mod._yf_data_cache) == 0
            assert len(yf_mod._yf_data_cache_ts) == 0

    def test_symbol_re_fetches_when_its_own_ttl_expires(self):
        """A symbol is re-fetched only when its own TTL expires, independent of others."""
        dummy_df = pd.DataFrame({"Close": [100.0]})
        with patch.object(yf_mod, "fetch_intraday_data", return_value=(dummy_df, dummy_df, dummy_df)) as mock_fetch:
            yf_mod.fetch_intraday_data_cached("^NSEI")
            assert mock_fetch.call_count == 1

            # Artificially expire NIFTY's timestamp
            yf_mod._yf_data_cache_ts["^NSEI"] = time.time() - (yf_mod._YF_CACHE_TTL + 5)

            # Re-fetch NIFTY should call fetch_intraday_data again
            yf_mod.fetch_intraday_data_cached("^NSEI")
            assert mock_fetch.call_count == 2


# ==============================================================================
# BLOCKER B: OHLCV Drop Tolerance & Quality Gate Tests
# ==============================================================================

class TestOHLCVDropTolerance:
    """Verify that SignalEvaluator accepts cleanable frames (drop <= 15%) and rejects invalid (drop > 15%)."""

    def _make_dummy_frame(self, n_rows=100, zero_volume_rows=0, invalid_ohlc_rows=0):
        times = pd.date_range("2026-09-18 09:15", periods=n_rows, freq="5min")
        close = np.linspace(100.0, 110.0, n_rows)
        high = close + 1.0
        low = close - 1.0
        open_ = close - 0.2
        volume = np.full(n_rows, 1000.0)

        if zero_volume_rows > 0:
            volume[:zero_volume_rows] = 0.0

        if invalid_ohlc_rows > 0:
            high[:invalid_ohlc_rows] = low[:invalid_ohlc_rows] - 10.0  # High < Low

        return pd.DataFrame({
            "Open": open_,
            "High": high,
            "Low": low,
            "Close": close,
            "Volume": volume,
        }, index=times)

    def test_drop_under_threshold_accepted(self):
        """Frame with 2 zero-volume rows out of 100 (2% <= 15%) is cleaned and accepted by evaluator."""
        evaluator = SignalEvaluator(cfg={})
        df = self._make_dummy_frame(n_rows=100, zero_volume_rows=2)

        mock_signal = MagicMock()
        mock_signal.score = 75
        mock_signal.tier = "MODERATE"
        mock_signal.direction = "CALL"

        with patch("index_app.domains.signal.evaluator._eval_v2", return_value=(mock_signal, "")):
            sig, reason = evaluator.evaluate(
                name="RELIANCE",
                frames={"df1m": df, "df5m": df, "df15m": df},
                vix=14.0,
            )
            assert sig is not None
            assert reason == ""

    def test_drop_over_threshold_rejected(self):
        """Frame with 20 zero-volume rows out of 100 (20% > 15%) is rejected by evaluator."""
        evaluator = SignalEvaluator(cfg={})
        df_excessive_drops = self._make_dummy_frame(n_rows=100, zero_volume_rows=20)
        df_clean = self._make_dummy_frame(n_rows=100, zero_volume_rows=0)

        sig, reason = evaluator.evaluate(
            name="RELIANCE",
            frames={"df1m": df_excessive_drops, "df5m": df_clean, "df15m": df_clean},
            vix=14.0,
        )
        assert sig is None
        assert "invalid_ohlcv" in reason

    def test_corrupted_ohlc_missing_column_rejected(self):
        """Frame missing required OHLC columns is strictly rejected by evaluator."""
        evaluator = SignalEvaluator(cfg={})
        df_corrupt = pd.DataFrame({"BadCol": [1, 2, 3]})
        df_clean = self._make_dummy_frame(n_rows=100, zero_volume_rows=0)

        sig, reason = evaluator.evaluate(
            name="RELIANCE",
            frames={"df1m": df_corrupt, "df5m": df_clean, "df15m": df_clean},
            vix=14.0,
        )
        assert sig is None
        assert "invalid_ohlcv" in reason

    def test_corrupted_ohlc_over_drop_threshold_rejected(self):
        """Frame with > 15% invalid OHLC rows (High < Low) is rejected by evaluator."""
        evaluator = SignalEvaluator(cfg={})
        df_corrupt = self._make_dummy_frame(n_rows=100, invalid_ohlc_rows=20)
        df_clean = self._make_dummy_frame(n_rows=100, zero_volume_rows=0)

        sig, reason = evaluator.evaluate(
            name="RELIANCE",
            frames={"df1m": df_corrupt, "df5m": df_clean, "df15m": df_clean},
            vix=14.0,
        )
        assert sig is None
        assert "invalid_ohlcv" in reason


# ==============================================================================
# BLOCKER C: ML Alert Gate Fallback Tests
# ==============================================================================

class TestMLAlertGateFallback:
    """Verify that neutral 0.500 ML fallback is allowed in PAPER mode but blocked in LIVE mode."""

    def _make_mock_signal(self, score=75, tier="MODERATE", direction="CALL", ml_prob=0.5, ml_pred_id=""):
        sig = MagicMock()
        sig.score = score
        sig.raw_score = score
        sig.tier = tier
        sig.direction = direction
        sig.regime = "TRENDING_UP"
        sig.price = 2500.0
        sig.rsi = 55.0
        sig.adx = 26.0
        sig.vwap = 2490.0
        sig.confidence = 0.7
        sig.ml_probability = ml_prob
        sig.ml_pred_id = ml_pred_id
        sig.score_components = {"trend": 20}
        sig.reasons = []
        return sig

    def test_paper_mode_allows_neutral_05_fallback_when_model_unavailable(self):
        """In PAPER mode, when model is unavailable (ml_pred_id='', prob=0.5), signal passes ML gate."""
        scanner_cfg = {
            "ML_REQUIRED_FOR_ALERTS": True,
            "ML_ALERT_MIN_PROBABILITY": 0.65,
            "EXECUTION_MODE": "PAPER",
            "MIN_SCORE_THRESHOLD": 60,
            "INDEX_MIN_SCORE": 60,
        }
        with patch.object(AllNSEScanner, "_reload_config_credentials", lambda self: None):
            scanner = AllNSEScanner(cfg=scanner_cfg)

        mock_sig = self._make_mock_signal(ml_prob=0.5, ml_pred_id="")
        with patch.object(scanner._evaluator, "evaluate", return_value=(mock_sig, "")), \
             patch("yfinance.Ticker") as mock_ticker:
            times = pd.date_range(end=pd.Timestamp.now(tz="Asia/Kolkata"), periods=50, freq="5min")
            df = pd.DataFrame({"Open": 100.0, "High": 105.0, "Low": 95.0, "Close": 100.0, "Volume": 1000.0}, index=times)
            mock_ticker.return_value.history.return_value = df

            result = scanner.scan_single_stock({"symbol": "RELIANCE", "name": "Reliance Industries", "series": "EQ"})
            assert result is not None
            assert result.symbol == "RELIANCE"

    def test_live_mode_strictly_blocks_neutral_05_fallback(self):
        """In LIVE / AUTO mode, neutral 0.500 fallback is strictly blocked."""
        scanner_cfg = {
            "ML_REQUIRED_FOR_ALERTS": True,
            "ML_ALERT_MIN_PROBABILITY": 0.65,
            "EXECUTION_MODE": "AUTO",
            "MIN_SCORE_THRESHOLD": 60,
            "INDEX_MIN_SCORE": 60,
        }
        with patch.object(AllNSEScanner, "_reload_config_credentials", lambda self: None):
            scanner = AllNSEScanner(cfg=scanner_cfg)

        mock_sig = self._make_mock_signal(ml_prob=0.5, ml_pred_id="")
        with patch.object(scanner._evaluator, "evaluate", return_value=(mock_sig, "")), \
             patch("yfinance.Ticker") as mock_ticker:
            times = pd.date_range(end=pd.Timestamp.now(tz="Asia/Kolkata"), periods=50, freq="5min")
            df = pd.DataFrame({"Open": 100.0, "High": 105.0, "Low": 95.0, "Close": 100.0, "Volume": 1000.0}, index=times)
            mock_ticker.return_value.history.return_value = df

            result = scanner.scan_single_stock({"symbol": "RELIANCE", "name": "Reliance Industries", "series": "EQ"})
            assert result is None  # Blocked by strict ML gate in AUTO mode

    def test_genuinely_low_probability_blocked_even_in_paper_mode(self):
        """If model evaluated and produced prob < min (e.g. 0.40), blocked in all modes."""
        scanner_cfg = {
            "ML_REQUIRED_FOR_ALERTS": True,
            "ML_ALERT_MIN_PROBABILITY": 0.65,
            "EXECUTION_MODE": "PAPER",
            "MIN_SCORE_THRESHOLD": 60,
            "INDEX_MIN_SCORE": 60,
        }
        with patch.object(AllNSEScanner, "_reload_config_credentials", lambda self: None):
            scanner = AllNSEScanner(cfg=scanner_cfg)

        mock_sig = self._make_mock_signal(ml_prob=0.40, ml_pred_id="pred_123")
        with patch.object(scanner._evaluator, "evaluate", return_value=(mock_sig, "")), \
             patch("yfinance.Ticker") as mock_ticker:
            times = pd.date_range(end=pd.Timestamp.now(tz="Asia/Kolkata"), periods=50, freq="5min")
            df = pd.DataFrame({"Open": 100.0, "High": 105.0, "Low": 95.0, "Close": 100.0, "Volume": 1000.0}, index=times)
            mock_ticker.return_value.history.return_value = df

            result = scanner.scan_single_stock({"symbol": "RELIANCE", "name": "Reliance Industries", "series": "EQ"})
            assert result is None  # Genuinely low score must be suppressed


# ==============================================================================
# SAFETY INVARIANTS: Mandatory Runtime Verification
# ==============================================================================

class TestSafetyInvariants:
    """Verify required safety invariants in json/config.json."""

    def test_safety_invariants_in_config(self):
        config_path = Path("json/config.json")
        assert config_path.exists(), "config.json must exist"

        with open(config_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)

        assert cfg.get("SL_PCT") == 0.88, f"SL_PCT must be 0.88, got {cfg.get('SL_PCT')}"
        assert cfg.get("BASE_CAPITAL") == 3000, f"BASE_CAPITAL must be 3000, got {cfg.get('BASE_CAPITAL')}"
        assert str(cfg.get("EXECUTION_MODE")).upper() in ("PAPER", "SIGNAL_ONLY"), (
            f"EXECUTION_MODE must be PAPER or SIGNAL_ONLY, got {cfg.get('EXECUTION_MODE')}"
        )
        assert cfg.get("SIGNAL_ONLY") is True, f"SIGNAL_ONLY must be True, got {cfg.get('SIGNAL_ONLY')}"
        assert cfg.get("full_auto_allowed") is False, f"full_auto_allowed must be False, got {cfg.get('full_auto_allowed')}"
        assert cfg.get("LIVE_TRADING_LOCKOUT") is True, f"LIVE_TRADING_LOCKOUT must be True, got {cfg.get('LIVE_TRADING_LOCKOUT')}"
        assert cfg.get("live_trading_lockout_enabled") is True, (
            f"live_trading_lockout_enabled must be True, got {cfg.get('live_trading_lockout_enabled')}"
        )
        assert cfg.get("telegram_allow_live_position_cmds") is False, (
            f"telegram_allow_live_position_cmds must be False, got {cfg.get('telegram_allow_live_position_cmds')}"
        )
        assert cfg.get("webhook_allow_live") is False, (
            f"webhook_allow_live must be False, got {cfg.get('webhook_allow_live')}"
        )


# ==============================================================================
# POST-PHASE-2.1 HARDENING TESTS (Holiday Gating & YF Last Close Cache TTL)
# ==============================================================================

class TestPostPhase21Hardening:
    """Verify Post-Phase-2.1 hardening fixes."""

    def test_market_session_holiday_gating(self):
        """_market_session_is_open and is_market_hours must block on weekday exchange holidays."""
        import datetime
        from core.all_nse_scanner import AllNSEScanner
        from core.market_scanner_daemon import is_market_hours

        scanner = AllNSEScanner()
        scanner._cfg = {"EXECUTION_MODE": "SIGNAL_ONLY", "ALLOW_AFTER_HOURS_SCANNING": False}

        # 2026-01-26 is Republic Day (Monday) - Official NSE Holiday
        # At 10:30 IST during trading hours:
        republic_day_dt = datetime.datetime(2026, 1, 26, 10, 30)

        with patch("core.all_nse_scanner.now_ist", return_value=republic_day_dt):
            assert scanner._market_session_is_open() is False, "Scanner must NOT be open on Republic Day"

        with patch("core.market_scanner_daemon.now_ist", return_value=republic_day_dt):
            assert is_market_hours(force_run=False) is False, "Market hours must be False on Republic Day"
            assert is_market_hours(force_run=True) is True, "force_run=True must override"

        # 2026-06-25 is Thursday (Normal trading day)
        normal_day_dt = datetime.datetime(2026, 6, 25, 10, 30)
        with patch("core.all_nse_scanner.now_ist", return_value=normal_day_dt):
            assert scanner._market_session_is_open() is True, "Scanner must be open on normal trading day"

    def test_last_close_cache_ttl_expiration(self):
        """fetch_last_close_summary must expire _last_close_cache when TTL has elapsed."""
        import time
        from unittest.mock import patch
        import core.yf_data_provider as yf_dp

        with yf_dp._last_close_cache_lock:
            yf_dp._last_close_cache.clear()
            yf_dp._last_close_cache["^NSEI"] = {"close": 24000.0, "change": 100.0, "pct": 0.42, "date": "17-Sep-2026"}
            yf_dp._last_close_cache_ts = time.time() - 301.0  # Expired > 300s

        index_map = {"NIFTY": {"yf": "^NSEI"}}
        mock_hist = pd.DataFrame(
            {"Close": [24500.0, 24600.0]},
            index=[pd.Timestamp("2026-09-17"), pd.Timestamp("2026-09-18")]
        )
        with patch("yfinance.Ticker") as mock_ticker:
            mock_ticker.return_value.history.return_value = mock_hist
            res = yf_dp.fetch_last_close_summary(index_map)
            assert "NIFTY" in res
            assert res["NIFTY"]["close"] == 24600.0, "Stale cached value must be replaced with fresh fetch"
