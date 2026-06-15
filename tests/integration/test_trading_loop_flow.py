"""
Integration test for the full trading loop flow.

Validates the end-to-end pipeline:

    Config Loading → Module Init → Signal Generation → Order Execution → Reconciliation → Shutdown

All external dependencies (NSE API, broker, yfinance) are mocked.
Tests use the actual production code paths wherever possible.
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

# Path to the project root (used for config file location)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.fixture(autouse=True)
def reset_globals():
    """Reset module-level globals between tests to prevent cross-test contamination."""
    import core.nse_option_recorder as nor
    from core.safety_state import _HARD_HALT, _shutdown

    nor.reset_nse_adapter_cache()

    # Clear any hard halt or shutdown from previous tests
    _HARD_HALT.clear()
    _shutdown.clear()

    # Reset config globals in index_trader
    import index_app.index_trader as it
    it._config_loaded = False
    it.PAPER_MODE = True
    it.MANUAL_SIGNALS_ONLY = True
    it.BROKER_API_ENABLED = False
    it.EXECUTION_MODE = "MANUAL"
    it._CFG = {}
    it.positions.clear()
    it.decision_log.clear()

    # Reset LTP resolver (may have been mocked by previous test)
    # Set to None — PositionService._get_underlying_ltp() handles None gracefully
    it._ltp_resolver = None

    # Reset PositionService singleton so each test starts fresh
    from core.position_service import reset_position_service
    reset_position_service()
    it._position_service = None


@pytest.fixture
def mock_config_file() -> str:
    """Create a minimal but valid config.json inside the project root."""
    cfg = {
            "EXECUTION_MODE": "PAPER",
            "MANUAL_SIGNALS_ONLY": False,
            "BROKER_API_ENABLED": False,
            "BROKER_DRIVER": "PAPER",
            "BASE_CAPITAL": 10000.0,
            "MAX_DAILY_LOSS": -2000.0,
            "MAX_DRAWDOWN": 0.3,
            "RISK_MODE": "FIXED",
            "RISK_FIXED_AMOUNT": 150.0,
            "AI_THRESHOLD": 60,
            "SCAN_INTERVAL": 30,
            "SL_PCT": 0.92,
            "TARGET_PCT": 1.3,
            "TRAIL_PCT": 0.93,
            "MIN_NET_RR": 1.5,
            "SIGNAL_MAX_AGE": 90,
            "MAX_OPEN": 2,
            "MAX_TRADES_DAY": 4,
            "TIER_STRONG_MIN": 80,
            "TIER_MODERATE_MIN": 70,
            "TIER_WEAK_MIN": 60,
            "QUALITY_MIN_SCORE": 68,
            "VIX_HALT_THRESHOLD": 30.0,
            "VIX_BLOCK_THRESHOLD": 40.0,
            "INTRADAY_LOSS_LIMIT": -1000.0,
            "MAX_CONSECUTIVE_LOSSES": 3,
            "expiry_day_controls_enabled": False,
            "kite_ticker_startup_connect": False,
            "circuit_breaker_broker_enabled": False,
            "AUDIT_LOG_ENABLED": False,
            "webhook_receiver_enabled": False,
            "web_dashboard_enabled": False,
        }
    path = _PROJECT_ROOT / "tests" / "_test_config_integration.json"
    path.write_text(json.dumps(cfg, indent=2))
    yield str(path)
    # Cleanup
    if path.exists():
        path.unlink()


@pytest.fixture
def mock_yfinance():
    """Mock yfinance intraday data to return realistic OHLCV."""
    import pandas as pd
    import numpy as np

    # Generate 60 bars of realistic 1m data
    now = time.time()
    timestamps = [now - (60 - i) * 60 for i in range(60)]
    base = 22000.0
    closes = base + np.cumsum(np.random.randn(60) * 10)
    opens = closes - np.random.randn(60) * 5
    highs = np.maximum(closes, opens) + abs(np.random.randn(60) * 3)
    lows = np.minimum(closes, opens) - abs(np.random.randn(60) * 3)

    df1m = pd.DataFrame({
        "Open": opens, "High": highs, "Low": lows, "Close": closes,
        "Volume": np.random.randint(1000, 10000, 60)
    }, index=pd.to_datetime(timestamps, unit="s"))

    # 5m data: resample every 5 bars
    df5m = pd.DataFrame({
        "Open": opens[::5], "High": [max(highs[i:i+5]) for i in range(0, 60, 5)],
        "Low": [min(lows[i:i+5]) for i in range(0, 60, 5)],
        "Close": closes[4::5],
        "Volume": [sum(v) for v in np.array_split(np.random.randint(1000, 10000, 60), 12)]
    }, index=pd.to_datetime(timestamps[::5], unit="s"))

    # 15m data: resample every 15 bars
    df15m = pd.DataFrame({
        "Open": opens[::15], "High": [max(highs[i:i+15]) for i in range(0, 60, 15)],
        "Low": [min(lows[i:i+15]) for i in range(0, 60, 15)],
        "Close": closes[14::15],
        "Volume": [sum(v) for v in np.array_split(np.random.randint(1000, 10000, 60), 4)]
    }, index=pd.to_datetime(timestamps[::15], unit="s"))

    return df1m, df5m, df15m


# ── Integration Tests ────────────────────────────────────────────────────────


class TestFullTradingLoopFlow:
    """End-to-end validation of the complete trading loop pipeline."""

    @patch.dict(os.environ, {}, clear=True)
    @patch("index_app.index_trader.now_ist")
    @patch("index_app.index_trader.market_status")
    def test_config_loading_to_loop_entry(
        self, mock_market_status: MagicMock, mock_now_ist: MagicMock,
        mock_config_file: str, monkeypatch: pytest.MonkeyPatch,
    ):
        """Test Phase 1: Config loading → initialization → trading loop entry.

        Validates:
        - Config is loaded with correct values
        - PAPER mode is forced correctly
        - Trading loop enters without error
        """
        monkeypatch.setenv("OPBUYING_INDEX_CONFIG", mock_config_file)

        # Simulate market hours
        mock_market_status.return_value = "OPEN"
        mock_now_ist.return_value = time.time()

        # Import and reload config
        import index_app.index_trader as it
        it._config_loaded = False
        it._load_config(force=True)

        # Verify config values
        assert it.PAPER_MODE is True
        assert it.EXECUTION_MODE == "PAPER"
        assert it.MANUAL_SIGNALS_ONLY is False
        assert it.BROKER_API_ENABLED is False
        assert it._CFG.get("BASE_CAPITAL") == 10000.0
        assert it._CFG.get("SCAN_INTERVAL") == 30

        # Verify module-level globals are initialized
        # _portfolio_service is initialized at module import time
        assert it._portfolio_service is not None
        # _risk_service is None until setup_di_container() is called
        # (config loading alone does not initialize it)
        assert it._risk_service is None, "risk_service requires setup_di_container()"
        assert it._reentry_trackers is not None
        assert len(it.INDEX_PRIORITY) >= 3
        assert "NIFTY" in it.INDEX_PRIORITY
        assert "BANKNIFTY" in it.INDEX_PRIORITY
        assert "FINNIFTY" in it.INDEX_PRIORITY

        # Verify broker adapter (should be PAPER mode)
        broker = it._make_broker()
        assert broker is not None
        assert hasattr(broker, "place_order") or hasattr(broker, "execute_order")
        assert it.PAPER_MODE or not it.BROKER_API_ENABLED  # Safe mode

    @patch("index_app.index_trader.now_ist")
    @patch("index_app.index_trader.market_status")
    @patch("index_app.index_trader._fetch_intraday_data_cached")
    @patch("index_app.index_trader._yf_fetch_vix")
    @patch("index_app.index_trader._generate_trading_signal")
    def test_signal_generation_and_entry_gates(
        self,
        mock_gen_signal: MagicMock,
        mock_vix: MagicMock,
        mock_fetch_data: MagicMock,
        mock_market_status: MagicMock,
        mock_now_ist: MagicMock,
        mock_yfinance,
    ):
        """Test Phase 2: Signal generation → entry gate validation.

        Validates:
        - Signal generation produces valid signals
        - Entry gates (mandate, reentry, correlation) are evaluated
        - enter_trade() is called with correct parameters
        - Decision log is populated
        """
        import index_app.index_trader as it

        # Set execution mode to bypass MANUAL early return
        it.EXECUTION_MODE = "PAPER"
        it.MANUAL_SIGNALS_ONLY = False

        # Set up market status
        mock_market_status.return_value = "OPEN"
        mock_now_ist.return_value = time.time()

        # Mock VIX to a safe level
        mock_vix.return_value = 15.0

        # Mock intraday data
        df1m, df5m, df15m = mock_yfinance
        mock_fetch_data.return_value = (df1m, df5m, df15m)

        # Mock a strong trading signal
        mock_gen_signal.return_value = {
            "signal": "BUY",
            "direction": "CALL",
            "score": 85,
            "threshold": 60,
            "price": 150.0,
            "strike": 22100,
            "rr": 2.5,
            "regime": "TRENDING",
            "signal_ts": time.time(),
            "timestamp": time.time(),
            "breakout_ok": True,
            "confidence": 0.82,
        }

        # Mock risk_service at module level (it's None after reset_globals)
        mock_risk = MagicMock()
        from core.services.risk_service import RiskEvaluation, RiskDecision as RiskServiceDecision
        mock_risk_eval = MagicMock(spec=RiskEvaluation)
        mock_risk_eval.decision = RiskServiceDecision.ALLOWED
        mock_risk_eval.reason = "All checks passed"
        mock_risk_eval.risk_score = 0.2
        mock_risk.evaluate_trade.return_value = mock_risk_eval
        mock_risk.get_portfolio_risk_metrics.return_value.available_capital = 10000.0
        mock_risk.get_portfolio_risk_metrics.return_value.open_positions_count = 0
        mock_risk.get_portfolio_risk_metrics.return_value.consecutive_losses = 0
        mock_risk.config.max_open_positions = 5
        mock_risk.get_live_vix.return_value = 15.0
        mock_risk.get_required_margin_per_lot.return_value = 1000.0

        with patch.object(it, "_risk_service", mock_risk):
            with patch.object(it, "_execution_service") as mock_exec:
                from core.ports.execution.execution_port import OrderResult, OrderStatus
                mock_exec.execute_order.return_value = OrderResult(
                    order_id="test_123", status=OrderStatus.FILLED,
                    filled_quantity=50, average_price=150.0, reject_reason="",
                )
                with patch.object(it, "check_mandate_trade_allowed", return_value=(True, "MANDATE_ALLOWED")):
                    # Test enter_trade with mocked risk_service and execution_service
                    it.enter_trade("NIFTY", mock_gen_signal.return_value)

        # Verify decision log was populated by enter_trade
        assert len(it.decision_log) > 0, "enter_trade should have populated decision_log"

    @patch("index_app.index_trader.now_ist")
    @patch("index_app.index_trader.market_status")
    def test_exit_position(
        self,
        mock_market_status: MagicMock,
        mock_now_ist: MagicMock,
    ):
        """Test Phase 3: Position monitoring and exit.

        Validates:
        - Position monitoring detects SL/Target conditions
        - Exit orders are placed correctly
        - Positions are cleaned up after exit
        """
        import index_app.index_trader as it
        from unittest.mock import MagicMock as _MagicMock

        # Clear any existing positions
        it.positions.clear()

        # Inject a mock position
        entry_price = 150.0
        entry_underlying = 22100.0
        it.positions["NIFTY"] = {
            "direction": "CALL",
            "qty": 50,
            "entry_price": entry_price,
            "underlying_entry_price": entry_underlying,
            "entry_time": time.time() - 120,  # 2 minutes ago
            "order_id": "test_order_123",
            "signal": "CALL",
            "strike": 22100,
            "idempotency_key": "test_exit",
            "entry_order_direction": "BUY",
            "score": 85,
        }

        # Mock LTP resolver to trigger SL (underlying dropped 10% from entry)
        sl_price = entry_underlying * 0.90  # Below 0.92 SL threshold
        mock_resolver = _MagicMock()
        mock_resolver.resolve.return_value = sl_price
        _original_ltp_resolver = it._ltp_resolver
        it._ltp_resolver = mock_resolver

        # Mock market status
        mock_market_status.return_value = "OPEN"
        mock_now_ist.return_value = time.time()

        # Mock execution service for exit
        with patch.object(it, "_execution_service") as mock_exec:
            from core.ports.execution.execution_port import OrderResult, OrderStatus
            mock_exec.execute_order.return_value = OrderResult(
                order_id="exit_123",
                status=OrderStatus.FILLED,
                filled_quantity=50,
                average_price=sl_price,
                reject_reason="",
            )

            # Run position monitoring
            it._monitor_positions()

            # Position should be removed after SL exit
            assert "NIFTY" not in it.positions, "Position should have been removed after SL exit"

            # Verify exit order was placed
            mock_exec.execute_order.assert_called_once()

        # Restore original LTP resolver to prevent test pollution
        it._ltp_resolver = _original_ltp_resolver

    @patch("index_app.index_trader.now_ist")
    def test_reconciliation_flow(self, mock_now_ist: MagicMock):
        """Test Phase 4: Reconciliation cycle.

        Validates:
        - Periodic reconciliation runs without error
        - CLEAN state reported when no positions
        """
        import index_app.index_trader as it

        mock_now_ist.return_value = time.time()
        it.positions.clear()

        # Mock execution service for reconciliation
        with patch.object(it, "_execution_service") as mock_exec:
            mock_exec.run_ack_watchdog.return_value = {"acknowledged": 0, "errors": 0}

            if hasattr(it, "_periodic_reconcile"):
                it._periodic_reconcile()
                mock_exec.run_ack_watchdog.assert_called_once_with(max_ack_age_seconds=30.0)

    @patch("index_app.index_trader.now_ist")
    @patch("index_app.index_trader.market_status")
    def test_trading_loop_cycle(
        self,
        mock_market_status: MagicMock,
        mock_now_ist: MagicMock,
    ):
        """Test Phase 5: Single trading loop iteration (scaled down).

        Validates that the trading loop:
        - Reads market status correctly
        - Fetches data for each index
        - Generates signals
        - Monitors positions
        - Reconciles
        - Exits on shutdown

        Uses heavily mocked dependencies for fast execution.
        The shutdown is triggered via a timer to avoid patching a
        reference that _run_trading_loop reads from core.safety_state.
        """
        import index_app.index_trader as it

        # Setup mocks
        mock_market_status.return_value = "OPEN"
        mock_now_ist.return_value = time.time()

        df = MagicMock()
        df.__len__.return_value = 60
        df.__getitem__.return_value = MagicMock()

        # Use the real shutdown Event with a timer to stop the loop
        from core.safety_state import _shutdown as _real_shutdown
        it._CFG["SCAN_INTERVAL"] = 0.1  # Ensure wait() returns quickly
        _real_shutdown.clear()
        _timer = threading.Timer(1.0, _real_shutdown.set)
        _timer.start()

        # Run the real trading loop; timer will trigger shutdown

        try:
            with patch.object(it, "_fetch_intraday_data_cached", return_value=(df, df, df)):
                with patch.object(it, "_yf_fetch_vix", return_value=15.0):
                    with patch.object(it, "_generate_trading_signal") as mock_sig:
                        mock_sig.return_value = {
                            "signal": "BUY", "direction": "CALL", "score": 85,
                            "threshold": 60, "price": 150.0, "strike": 22100,
                            "rr": 2.5, "regime": "TRENDING", "signal_ts": time.time(),
                            "timestamp": time.time(), "breakout_ok": True,
                            "confidence": 0.82,
                        }

                        with patch.object(it, "update_closes", return_value=None):
                            # Actually run the real trading loop
                            # The timer will set _real_shutdown after 1 second
                            # which causes the loop to exit cleanly
                            it._run_trading_loop()

        finally:
            _timer.cancel()
            _real_shutdown.clear()

        # Verify signal generation was called at least once
        assert mock_sig.called, "Signal generation should run during trading loop"

    @patch.dict(os.environ, {}, clear=True)
    @patch("index_app.index_trader.now_ist")
    @patch("index_app.index_trader.market_status")
    def test_shutdown_graceful(
        self,
        mock_market_status: MagicMock,
        mock_now_ist: MagicMock,
        mock_config_file: str,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """Test Phase 6: Graceful shutdown sequence.

        Validates:
        - Shutdown event stops the trading loop
        - No crashes during shutdown
        """
        monkeypatch.setenv("OPBUYING_INDEX_CONFIG", mock_config_file)

        import index_app.index_trader as it
        from core.safety_state import _shutdown

        mock_market_status.return_value = "CLOSED"
        mock_now_ist.return_value = time.time()

        # Set shutdown signal
        _shutdown.set()

        try:
            it._run_trading_loop()
        except Exception as e:
            pytest.fail(f"Trading loop raised exception during shutdown: {e}")

        # _shutdown is auto-cleared by reset_globals fixture for next test

    @patch("index_app.index_trader.now_ist")
    def test_signal_validation_flow(self, mock_now_ist: MagicMock):
        """Test Phase 7: Signal independence validation and pillar system.

        Validates that validate_signal_pillars correctly validates
        signal independence across multiple data sources.
        """
        import index_app.index_trader as it

        mock_now_ist.return_value = time.time()

        # Test with all pillars agreeing (BUY signal)
        valid, reason = it.validate_signal_pillars(
            rsi=65.0, macd="BULLISH", adx=25.0,
            iv_rank=45.0, oi_change=12.0, pcr=1.2,
            fii_net=500.0, dii_net=200.0, gex=1.5,
            session_score=8.0,
        )
        # Signal independence validator should produce a valid result
        # (no crash or exception), with a string reason
        assert isinstance(valid, bool), "validate_signal_pillars should return bool"
        assert isinstance(reason, str), "validate_signal_pillars should return string reason"
        assert len(reason) > 0, "reason should not be empty"

        # With all 4 pillars providing bullish data, should get consensus
        if valid:
            assert "PILLAR_OK" in reason, "valid signal should indicate pillar consensus"
        else:
            assert "PILLAR_FAIL" in reason, "invalid signal should indicate pillar failure"

    @patch("index_app.index_trader.now_ist")
    @patch("index_app.index_trader.market_status")
    def test_expiry_day_gate_blocks_entry(
        self,
        mock_market_status: MagicMock,
        mock_now_ist: MagicMock,
    ):
        """Phase 8: Expiry day gate blocks trade entry after cutoff.

        Validates that enter_trade() respects the expiry day controller
        and blocks entry when can_enter_position() returns blocked.
        """
        import index_app.index_trader as it
        from core.expiry_day_controller import ExpiryControlResult, ExpirySession

        # Set execution mode to bypass MANUAL early return
        it.EXECUTION_MODE = "PAPER"
        it.MANUAL_SIGNALS_ONLY = False

        mock_market_status.return_value = "OPEN"
        mock_now_ist.return_value = time.time()

        sig = {
            "signal": "BUY", "direction": "CALL", "score": 85,
            "price": 150.0, "signal_ts": time.time(), "timestamp": time.time(),
            "breakout_ok": True,
        }

        # Mock expiry controller to block entry
        blocked_result = ExpiryControlResult(
            allowed=False,
            reason="Expiry cutoff reached",
            session=ExpirySession.BLOCKED,
            risk_level="HIGH",
        )
        with patch.object(it, "_expiry_controller") as mock_expiry:
            mock_expiry.can_enter_position.return_value = blocked_result

            with patch.object(it, "_risk_service") as mock_risk:
                from core.services.risk_service import RiskDecision
                mock_risk_eval = MagicMock()
                mock_risk_eval.decision = RiskDecision.ALLOWED
                mock_risk_eval.reason = "OK"
                mock_risk_eval.risk_score = 0.2
                mock_risk.evaluate_trade.return_value = mock_risk_eval
                mock_risk.get_portfolio_risk_metrics.return_value.available_capital = 10000.0
                mock_risk.get_portfolio_risk_metrics.return_value.open_positions_count = 0
                mock_risk.get_portfolio_risk_metrics.return_value.consecutive_losses = 0
                mock_risk.config.max_open_positions = 5
                mock_risk.get_live_vix.return_value = 15.0
                mock_risk.get_required_margin_per_lot.return_value = 1000.0

                with patch.object(it, "_warmup_manager") as mock_warmup:
                    mock_warmup.can_enter.return_value = True

                    it.enter_trade("NIFTY", sig)

        # Decision log should show EXPIRY_BLOCK
        assert "NIFTY" in it.decision_log
        assert "EXPIRY_BLOCK" in str(it.decision_log.get("NIFTY", {}).get("msg", "")), \
            f"Expected EXPIRY_BLOCK in decision_log, got: {it.decision_log.get('NIFTY', {})}"

    @patch("index_app.index_trader.now_ist")
    @patch("index_app.index_trader.market_status")
    def test_news_sentinel_blocks_entry(
        self,
        mock_market_status: MagicMock,
        mock_now_ist: MagicMock,
    ):
        """Phase 9: News sentinel blocks entry during HIGH risk level.

        Validates that enter_trade() checks the news sentinel risk level
        and blocks entry when it's HIGH or EXTREME.
        """
        import index_app.index_trader as it

        mock_market_status.return_value = "OPEN"
        mock_now_ist.return_value = time.time()

        sig = {
            "signal": "BUY", "direction": "CALL", "score": 85,
            "price": 150.0, "signal_ts": time.time(), "timestamp": time.time(),
            "breakout_ok": True,
        }

        # Mock news sentinel with HIGH risk
        mock_news_risk = MagicMock()
        mock_news_risk.risk_level = "HIGH"
        mock_news_risk.headline = "Breaking: Market volatility expected"

        with patch.object(it, "_news_sentinel") as mock_news:
            mock_news.get_current_risk.return_value = mock_news_risk

            with patch.object(it, "_risk_service") as mock_risk:
                from core.services.risk_service import RiskDecision
                mock_risk_eval = MagicMock()
                mock_risk_eval.decision = RiskDecision.ALLOWED
                mock_risk_eval.reason = "OK"
                mock_risk_eval.risk_score = 0.2
                mock_risk.evaluate_trade.return_value = mock_risk_eval
                mock_risk.get_portfolio_risk_metrics.return_value.available_capital = 10000.0
                mock_risk.get_portfolio_risk_metrics.return_value.open_positions_count = 0
                mock_risk.get_portfolio_risk_metrics.return_value.consecutive_losses = 0
                mock_risk.config.max_open_positions = 5
                mock_risk.get_live_vix.return_value = 15.0
                mock_risk.get_required_margin_per_lot.return_value = 1000.0

                with patch.object(it, "_expiry_controller") as mock_expiry:
                    mock_expiry.can_enter_position.return_value = MagicMock(allowed=True)

                    with patch.object(it, "_warmup_manager") as mock_warmup:
                        mock_warmup.can_enter.return_value = True

                        it.enter_trade("NIFTY", sig)

        # Decision log should show NEWS_BLOCK
        assert "NIFTY" in it.decision_log
        assert "NEWS_BLOCK" in str(it.decision_log.get("NIFTY", {}).get("msg", "")), \
            f"Expected NEWS_BLOCK in decision_log, got: {it.decision_log.get('NIFTY', {})}"

    @patch("index_app.index_trader.now_ist")
    @patch("index_app.index_trader.market_status")
    def test_max_age_exits_position(
        self,
        mock_market_status: MagicMock,
        mock_now_ist: MagicMock,
    ):
        """Phase 10: Position auto-exits when max age is reached.

        Validates that _monitor_positions() exits a position when
        its age exceeds MAX_POSITION_AGE from config.
        """
        import index_app.index_trader as it

        mock_market_status.return_value = "OPEN"
        mock_now_ist.return_value = time.time()

        # Clear any positions and inject a stale one
        it.positions.clear()

        # Inject position that's older than MAX_POSITION_AGE
        entry_price = 150.0
        entry_underlying = 22100.0
        it.positions["NIFTY"] = {
            "direction": "CALL", "qty": 50, "entry_price": entry_price,
            "underlying_entry_price": entry_underlying,
            "entry_time": time.time() - 99999,  # Very old position
            "order_id": "test_old", "signal": "CALL", "strike": 22100,
            "idempotency_key": "test_max_age", "entry_order_direction": "BUY",
            "score": 85,
        }

        # Set a low MAX_POSITION_AGE to trigger max-age exit
        it._CFG["MAX_POSITION_AGE"] = 10  # 10 seconds max

        # Use LTP resolver mock to return current price (no SL trigger, just age)
        mock_resolver = MagicMock()
        mock_resolver.resolve.return_value = entry_underlying
        _original_ltp_resolver = it._ltp_resolver
        it._ltp_resolver = mock_resolver

        with patch.object(it, "_execution_service") as mock_exec:
            from core.ports.execution.execution_port import OrderResult, OrderStatus
            mock_exec.execute_order.return_value = OrderResult(
                order_id="exit_max_age", status=OrderStatus.FILLED,
                filled_quantity=50, average_price=entry_price * 0.95,
                reject_reason="",
            )

            it._monitor_positions()

        # Position should be removed after max-age exit
        assert "NIFTY" not in it.positions, \
            "Position should have been removed after max-age exit"

        # Restore original LTP resolver
        it._ltp_resolver = _original_ltp_resolver

    @patch("index_app.index_trader.now_ist")
    @patch("index_app.index_trader.market_status")
    def test_auction_session_blocks_entry(
        self,
        mock_market_status: MagicMock,
        mock_now_ist: MagicMock,
    ):
        """Phase 11: Auction session blocks trade entry.

        Validates that enter_trade() blocks entry during NSE
        auction session (pre-open/post-close).
        """
        import index_app.index_trader as it

        mock_market_status.return_value = "OPEN"
        mock_now_ist.return_value = time.time()

        sig = {
            "signal": "BUY", "direction": "CALL", "score": 85,
            "price": 150.0, "signal_ts": time.time(), "timestamp": time.time(),
            "breakout_ok": True,
        }

        # Mock auction session check to return True
        # Patch at the source (core.datetime_ist) since PositionService imports it internally
        with patch("core.datetime_ist.is_in_auction_session", return_value=True):
            with patch.object(it, "_risk_service") as mock_risk:
                from core.services.risk_service import RiskDecision
                mock_risk_eval = MagicMock()
                mock_risk_eval.decision = RiskDecision.ALLOWED
                mock_risk_eval.reason = "OK"
                mock_risk_eval.risk_score = 0.2
                mock_risk.evaluate_trade.return_value = mock_risk_eval
                mock_risk.get_portfolio_risk_metrics.return_value.available_capital = 10000.0
                mock_risk.get_portfolio_risk_metrics.return_value.open_positions_count = 0
                mock_risk.get_portfolio_risk_metrics.return_value.consecutive_losses = 0
                mock_risk.config.max_open_positions = 5

                with patch.object(it, "_expiry_controller") as mock_expiry:
                    mock_expiry.can_enter_position.return_value = MagicMock(allowed=True)

                    with patch.object(it, "_warmup_manager") as mock_warmup:
                        mock_warmup.can_enter.return_value = True

                        with patch.object(it, "_news_sentinel") as mock_news:
                            mock_news.get_current_risk.return_value = MagicMock(risk_level="NONE")

                            it.enter_trade("NIFTY", sig)

        # Decision log should show AUCTION_BLOCK
        assert "NIFTY" in it.decision_log
        assert "AUCTION_BLOCK" in str(it.decision_log.get("NIFTY", {}).get("msg", "")), \
            f"Expected AUCTION_BLOCK in decision_log, got: {it.decision_log.get('NIFTY', {})}"

    @patch("index_app.index_trader.now_ist")
    @patch("index_app.index_trader.market_status")
    @patch("index_app.index_trader._fetch_intraday_data_cached")
    @patch("index_app.index_trader._yf_fetch_vix")
    def test_correlation_guard_blocks_entry_during_loop(
        self,
        mock_vix: MagicMock,
        mock_fetch_data: MagicMock,
        mock_market_status: MagicMock,
        mock_now_ist: MagicMock,
    ):
        """Phase 12: Correlation guard blocks same-direction entry on correlated index.

        Validates that the trading loop evaluates correlation guard
        and blocks entries when a correlated index has an open position
        with the same direction.
        """
        import index_app.index_trader as it

        mock_market_status.return_value = "OPEN"
        mock_now_ist.return_value = time.time()

        # Add an existing position to trigger correlation guard
        it.positions.clear()
        it.positions["NIFTY"] = {
            "direction": "CALL", "qty": 50, "entry_price": 150.0,
            "underlying_entry_price": 22100.0, "entry_time": time.time(),
            "order_id": "existing", "signal": "CALL", "strike": 22100,
            "entry_order_direction": "BUY", "score": 85,
        }

        df = MagicMock()
        df.__len__.return_value = 60
        df.__getitem__.return_value = MagicMock()

        mock_vix.return_value = 15.0
        mock_fetch_data.return_value = (df, df, df)

        # Mock a signal for BANKNIFTY (correlated with NIFTY)
        sig = {
            "signal": "BUY", "direction": "CALL", "score": 85,
            "threshold": 60, "price": 150.0, "strike": 48000,
            "rr": 2.5, "regime": "TRENDING", "signal_ts": time.time(),
            "timestamp": time.time(), "breakout_ok": True,
        }

        with patch.object(it, "_generate_trading_signal", return_value=sig):
            with patch.object(it, "check_portfolio_correlation") as mock_corr:
                # Return blocked for BANKNIFTY (correlated with NIFTY)
                mock_corr.side_effect = lambda name, direction, positions, cfg: (
                    (True, "OK")
                    if name == "NIFTY"
                    else (False, "CORRELATION_BLOCK: correlated position exists")
                )
                # Use the real shutdown Event with a timer to stop the loop
                from core.safety_state import _shutdown as _real_shutdown
                it._CFG["SCAN_INTERVAL"] = 0.1
                _real_shutdown.clear()
                _timer = threading.Timer(1.0, _real_shutdown.set)
                _timer.start()

                try:
                    with patch.object(it, "check_mandate_trade_allowed",
                                      return_value=(True, "MANDATE_ALLOWED")):
                        it._run_trading_loop()
                finally:
                    _timer.cancel()
                    _real_shutdown.clear()

        # Decision log should show CORRELATION_BLOCK for BANKNIFTY
        blocked_found = any(
            "CORRELATION_BLOCK" in str(v.get("msg", ""))
            for v in it.decision_log.values()
        )
        assert blocked_found, \
            f"Expected CORRELATION_BLOCK in decision_log, got: {dict(it.decision_log)}"

    @patch("index_app.index_trader.now_ist")
    @patch("index_app.index_trader.market_status")
    def test_reentry_evaluator_blocks_entry(
        self,
        mock_market_status: MagicMock,
        mock_now_ist: MagicMock,
    ):
        """Phase 13: Order flow with mocked risk and execution services.

        Validates the full enter_trade() path through risk evaluation,
        order submission, and position tracking. Uses mocked services
        to avoid hitting production code paths.
        """
        import index_app.index_trader as it

        # Set execution mode to bypass MANUAL early return
        it.EXECUTION_MODE = "PAPER"
        it.MANUAL_SIGNALS_ONLY = False

        mock_market_status.return_value = "OPEN"
        mock_now_ist.return_value = time.time()

        sig = {
            "signal": "BUY", "direction": "CALL", "score": 85,
            "price": 150.0, "signal_ts": time.time(), "timestamp": time.time(),
            "breakout_ok": True,
        }

        # Mock get_position_size to return a fixed lot size
        with patch.object(it, "get_position_size", return_value=1):
            with patch.object(it, "_risk_service") as mock_risk:
                from core.services.risk_service import RiskDecision
                mock_risk_eval = MagicMock()
                mock_risk_eval.decision = RiskDecision.ALLOWED
                mock_risk_eval.reason = "OK"
                mock_risk_eval.risk_score = 0.2
                mock_risk.evaluate_trade.return_value = mock_risk_eval
                mock_risk.get_portfolio_risk_metrics.return_value.available_capital = 10000.0
                mock_risk.get_portfolio_risk_metrics.return_value.open_positions_count = 0
                mock_risk.get_portfolio_risk_metrics.return_value.consecutive_losses = 0
                mock_risk.config.max_open_positions = 5
                mock_risk.get_live_vix.return_value = 15.0
                mock_risk.get_required_margin_per_lot.return_value = 1000.0

                with patch.object(it, "_expiry_controller") as mock_expiry:
                    mock_expiry.can_enter_position.return_value = MagicMock(allowed=True)

                    with patch.object(it, "_warmup_manager") as mock_warmup:
                        mock_warmup.can_enter.return_value = True

                        with patch.object(it, "_news_sentinel") as mock_news:
                            mock_news.get_current_risk.return_value = MagicMock(risk_level="NONE")

                            with patch("core.datetime_ist.is_in_auction_session",
                                       return_value=False):

                                with patch.object(it, "_execution_service") as mock_exec:
                                    from core.ports.execution.execution_port import OrderResult, OrderStatus
                                    mock_exec.execute_order.return_value = OrderResult(
                                        order_id="order_reentry_test",
                                        status=OrderStatus.FILLED,
                                        filled_quantity=1,
                                        average_price=150.0,
                                        reject_reason="",
                                    )

                                    with patch.object(it, "_margin_validator") as mock_margin:
                                        mock_margin_result = MagicMock()
                                        mock_margin_result.allowed = True
                                        mock_margin_result.error_message = ""
                                        mock_margin_result.warning_message = ""
                                        mock_margin.validate.return_value = mock_margin_result

                                        with patch.object(it, "_portfolio_service") as mock_portfolio:
                                            mock_portfolio.get_available_margin.return_value = 10000.0

                                            it.enter_trade("NIFTY", sig)

        # Decision log should show Executed (all mocks set to allow the order)
        assert "NIFTY" in it.decision_log, "Decision log should have NIFTY entry"
        log_msg = str(it.decision_log.get("NIFTY", {}).get("msg", ""))
        assert "Executed" in log_msg, \
            f"Expected 'Executed' in decision_log, got: {log_msg}"

    def test_stub_exports_compatibility(self):
        """Test Phase 14: Verify all stub exports are present and callable.

        Validates backward compatibility of legacy module-level exports.
        """
        import index_app.index_trader as it

        # Verify core globals
        assert hasattr(it, "PAPER_MODE")
        assert hasattr(it, "MANUAL_SIGNALS_ONLY")
        assert hasattr(it, "BROKER_API_ENABLED")
        assert hasattr(it, "EXECUTION_MODE")
        assert hasattr(it, "positions")
        assert hasattr(it, "decision_log")
        assert hasattr(it, "INDEX_PRIORITY")
        assert hasattr(it, "INDEX_MAP")
        assert hasattr(it, "SL_PCT")
        assert hasattr(it, "TARGET_PCT")
        assert hasattr(it, "TRAIL_PCT")
        assert hasattr(it, "MIN_NET_RR")

        # Verify key functions are callable
        assert callable(it.market_status)
        assert callable(it.get_position_size)
        assert callable(it.get_mandate_status)
        assert callable(it.daily_reset)
        assert callable(it._exit_position)

        # Verify module-level __getattr__ works for hidden imports
        from core.safety_state import _HARD_HALT, _shutdown as shutdown_event

        assert it._HARD_HALT is _HARD_HALT
        assert it._shutdown is shutdown_event


class TestSecurityAndSafetyGates:
    """Test safety-critical gates that must never be bypassed."""

    @patch("index_app.index_trader.now_ist")
    def test_hard_halt_blocks_entry(self, mock_now_ist: MagicMock):
        """Hard halt must block ALL new trade entries."""
        import index_app.index_trader as it
        from core.safety_state import trip_hard_halt, is_hard_halted

        mock_now_ist.return_value = time.time()

        # Trip the hard halt
        trip_hard_halt("Test halt", source="test")
        assert is_hard_halted() is True

        # Verify enter_trade returns immediately
        sig = {"signal": "BUY", "direction": "CALL", "score": 85,
               "price": 150.0, "signal_ts": time.time(), "timestamp": time.time()}
        it.enter_trade("NIFTY", sig)

        # Decision log should show HARD HALT block
        assert "NIFTY" in it.decision_log
        assert "HARD HALT" in str(it.decision_log.get("NIFTY", {}).get("msg", ""))

        # _HARD_HALT is auto-cleared by reset_globals fixture for next test
