"""Tests for core/signal_service.py -- SignalService class."""

import sys
from unittest.mock import MagicMock, patch

import pytest

from core.signal_service import (
    SignalService,
    get_signal_service,
    reset_signal_service,
)


@pytest.fixture(autouse=True)
def _reset():
    """Reset singleton and cache before each test."""
    reset_signal_service()

    yield


# ============================================================================
# Singleton
# ============================================================================


class TestSignalServiceSingleton:
    def test_get_signal_service_returns_same_instance(self):
        s1 = get_signal_service(cfg={"AI_THRESHOLD": 70})
        s2 = get_signal_service()
        assert s1 is s2

    def test_reset_signal_service_creates_new_instance(self):
        s1 = get_signal_service(cfg={"key": "val"})
        reset_signal_service()
        s2 = get_signal_service()
        assert s1 is not s2

    def test_default_cfg_is_empty_dict(self):
        svc = SignalService()
        assert svc._cfg == {}

    def test_cfg_passed_through_constructor(self):
        svc = SignalService(cfg={"AI_THRESHOLD": 80})
        assert svc._cfg["AI_THRESHOLD"] == 80

    def test_singleton_with_cfg(self):
        s1 = get_signal_service(cfg={"AI_THRESHOLD": 70})
        # second call ignores cfg (already created)
        s2 = get_signal_service(cfg={"AI_THRESHOLD": 99})
        assert s1._cfg["AI_THRESHOLD"] == 70
        assert s2._cfg["AI_THRESHOLD"] == 70


# ============================================================================
# validate_signal_pillars
# ============================================================================


class TestValidateSignalPillars:
    def test_valid_two_pillar_consensus(self):
        """Should pass when 2 independent pillars agree.
        
        Pillar 1 (Price/Momentum BULLISH) + Pillar 3 (Institutional Flow BULLISH)
        must both agree on direction for consensus.
        """
        svc = SignalService()
        ok, msg = svc.validate_signal_pillars(
            rsi=65.0,
            macd="bullish",
            adx=30.0,
            fii_net=500.0,
            dii_net=-200.0,
            gex=1e8,
        )
        assert ok is True
        assert "PILLAR_OK" in msg

    def test_single_pillar_fails(self):
        """Should fail with only 1 pillar."""
        svc = SignalService()
        ok, msg = svc.validate_signal_pillars(
            rsi=65.0,
            macd="bullish",
            adx=30.0,
        )
        assert ok is False
        assert "PILLAR_FAIL" in msg

    def test_all_pillars_present_bullish(self):
        """All 4 pillars present with BULLISH consensus should pass."""
        svc = SignalService()
        ok, msg = svc.validate_signal_pillars(
            rsi=60.0,
            macd="bullish",
            adx=30.0,
            # Pillar 2: options market
            iv_rank=0.6,
            oi_change=0.1,
            pcr=1.1,
            # Pillar 3: institutional flow (BULLISH)
            fii_net=500,
            dii_net=-200,
            gex=1e8,
            # Pillar 4: structural
            session_score=1.5,
        )
        assert ok is True
        assert "PILLAR_OK" in msg

    def test_pillar_fail_returns_reason(self):
        """Failure should include the reason in the message."""
        svc = SignalService()
        ok, msg = svc.validate_signal_pillars(
            rsi=65.0,
            macd="bullish",
            adx=30.0,
        )
        assert ok is False
        assert "have" in msg

    def test_no_data_returns_fail(self):
        """No data at all should return failure."""
        svc = SignalService()
        ok, msg = svc.validate_signal_pillars()
        assert ok is False
        assert "PILLAR_FAIL" in msg

    def test_bearish_direction_returned(self):
        """Consensus should identify bearish direction.
        
        Pillar 1 (Price/Momentum BEARISH) + Pillar 3 (Institutional Flow BEARISH).
        """
        svc = SignalService()
        ok, msg = svc.validate_signal_pillars(
            rsi=30.0,
            macd="bearish",
            adx=30.0,
            fii_net=-500.0,
            dii_net=200.0,
            gex=-1e8,
        )
        assert ok is True
        assert "BEARISH" in msg


# ============================================================================
# generate_trading_signal
# ============================================================================


class TestGenerateTradingSignal:
    def test_basic_signal(self):
        """Should generate a signal dict with valid inputs."""
        svc = SignalService(cfg={"AI_THRESHOLD": 60})

        frames = {"df1m": None, "df5m": None, "df15m": None}

        # Patch the signal_engine module import and iv_rank/OI at the source
        with patch.dict(sys.modules, {"core.legacy.signal_engine": MagicMock()}):
            sys.modules["core.legacy.signal_engine"].build_full_signal = MagicMock(
                return_value={"signal": "BUY", "score": 75, "direction": "CALL"}
            )
            with patch("core.iv_rank.get_iv_rank", return_value=0.5):
                with patch("core.oi_snapshot_store.get_oi_at", return_value=0.05):
                    with patch("core.oi_snapshot_store.get_pcr_at", return_value=1.1):
                        result = svc.generate_trading_signal(
                            name="NIFTY", frames=frames, vix=15.0,
                        )

        assert result is not None
        assert result["signal"] == "BUY"
        assert result["score"] == 75

    def test_signal_without_oi_data(self):
        """Should work when OI data fetch fails."""
        svc = SignalService(cfg={"AI_THRESHOLD": 60})

        frames = {"df1m": None, "df5m": None, "df15m": None}

        with patch.dict(sys.modules, {"core.legacy.signal_engine": MagicMock()}):
            sys.modules["core.legacy.signal_engine"].build_full_signal = MagicMock(
                return_value={"signal": "SELL", "score": 30}
            )
            with patch("core.iv_rank.get_iv_rank", return_value=0.5):
                with patch("core.oi_snapshot_store.get_pcr_at", side_effect=ValueError("no data")):
                    result = svc.generate_trading_signal(
                        name="NIFTY", frames=frames,
                    )

        assert result is not None
        assert result["signal"] == "SELL"

    def test_signal_with_all_data(self):
        """Should include OI data when available."""
        svc = SignalService(cfg={"AI_THRESHOLD": 60})

        frames = {"df1m": None, "df5m": None, "df15m": None}

        with patch.dict(sys.modules, {"core.legacy.signal_engine": MagicMock()}):
            sys.modules["core.legacy.signal_engine"].build_full_signal = MagicMock(
                return_value={"signal": "BUY"}
            )
            with patch("core.iv_rank.get_iv_rank", return_value=0.5):
                with patch("core.oi_snapshot_store.get_oi_at", return_value=0.05):
                    with patch("core.oi_snapshot_store.get_pcr_at", return_value=1.1):
                        result = svc.generate_trading_signal(
                            name="BANKNIFTY", frames=frames, vix=14.0,
                        )

        assert result is not None

    def test_signal_custom_threshold(self):
        """Should use config threshold."""
        svc = SignalService(cfg={"AI_THRESHOLD": 85})

        frames = {"df1m": None, "df5m": None, "df15m": None}

        with patch.dict(sys.modules, {"core.legacy.signal_engine": MagicMock()}):
            mock_build = MagicMock(return_value={"signal": "BUY", "threshold": 85})
            sys.modules["core.legacy.signal_engine"].build_full_signal = mock_build
            with patch("core.iv_rank.get_iv_rank", return_value=0.5):
                with patch("core.oi_snapshot_store.get_oi_at", return_value=0.05):
                    with patch("core.oi_snapshot_store.get_pcr_at", return_value=1.1):
                        svc.generate_trading_signal(name="NIFTY", frames=frames)

            call_kwargs = mock_build.call_args[1] if mock_build.call_args else {}
            assert call_kwargs.get("threshold") == 85


# ============================================================================
# Static utility methods
# ============================================================================


class TestSignalUtilities:
    def test_get_signal_quality_report(self):
        assert SignalService.get_signal_quality_report() == "ok"

    def test_get_top_signals_default(self):
        assert SignalService.get_top_signals(5) == []
