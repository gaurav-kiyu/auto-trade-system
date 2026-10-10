"""Regression Test Suite for Post-Market Remediation R1–R4.

Authority: OPB-FINAL-PHASE-GOVERNANCE-001
Program: v2.60 Phase D Forward Observation Quality & Outcome Integrity

Tests:
- R1: Futures Market-Data Resolution (No synthetic fallbacks, fail closed)
- R2: Derived Signal Governance (Cooldown, Burst Rate Limit, Daily Quota)
- R3: Candle-Based Outcome Observation (1m OHLC evaluation, High/Low barrier detection, same-bar ambiguity)
- R4: Analytics & G4 Metric Integrity (G4 schema pass, predictive validity separation, first-touch immutability)
"""

import datetime
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from core.all_nse_scanner import AllNSEScanner, ScannedStockSignal
from core.datetime_ist import now_ist
from core.futures_contract_resolver import (
    FuturesContractResolver,
    parse_canonical_symbol,
    resolve_futures_market_bar,
    resolve_futures_market_price,
)
from core.signals.forward_accumulation_reporter import (
    ForwardAccumulationReporter,
)
from core.signals.signal_forward_monitor import (
    SignalForwardMonitorService,
)
from core.signals.signal_outcome_dataset import (
    normalize_outcome_state,
)
from core.signals.signal_outcome_tracker import (
    OutcomeConfidence,
    SignalBar,
    SignalOutcomeTracker,
)

# ============================================================================
# R1 Tests: Futures Market-Data Resolution
# ============================================================================

def test_futures_symbol_parsing_canonical():
    """R1: Test decomposition of canonical futures symbols."""
    # Valid stock futures
    res1 = parse_canonical_symbol("DIXON26SEPFUT")
    assert res1 is not None
    assert res1["underlying"] == "DIXON"
    assert res1["expiry_year"] == 2026
    assert res1["expiry_month"] == 9
    assert res1["expiry_month_str"] == "SEP"
    assert res1["instrument_type"] == "FUTSTK"

    # Valid index futures
    res2 = parse_canonical_symbol("NIFTY26SEPFUT")
    assert res2 is not None
    assert res2["underlying"] == "NIFTY"
    assert res2["expiry_year"] == 2026
    assert res2["expiry_month"] == 9
    assert res2["instrument_type"] == "FUTIDX"

    # Valid Reliance futures
    res3 = parse_canonical_symbol("RELIANCE26OCTFUT")
    assert res3 is not None
    assert res3["underlying"] == "RELIANCE"
    assert res3["expiry_month"] == 10

    # Invalid symbols
    assert parse_canonical_symbol("AAPL") is None
    assert parse_canonical_symbol("DIXON") is None
    assert parse_canonical_symbol("NIFTY26FUT") is None
    assert parse_canonical_symbol("") is None
    assert parse_canonical_symbol(None) is None


def test_futures_missing_feed_fails_safely(caplog):
    """R1: When broker feed is missing/offline, resolve_futures_market_price fails closed and logs telemetry."""
    caplog.clear()
    price = resolve_futures_market_price("DIXON26SEPFUT", broker_adapter=None)
    assert price is None
    assert any("[FUTURES_FEED_UNAVAILABLE]" in record.message for record in caplog.records)

    bar = resolve_futures_market_bar("DIXON26SEPFUT", broker_adapter=None)
    assert bar is None


def test_futures_no_cash_price_fallback():
    """R1: Futures resolution never silently substitutes underlying spot cash price."""
    class MockDisconnectedAdapter:
        def get_ltp(self, symbol):
            # Returns None for futures contracts
            if "FUT" in symbol:
                return None
            return 14500.0  # Cash spot equity price

    adapter = MockDisconnectedAdapter()
    price = resolve_futures_market_price("DIXON26SEPFUT", broker_adapter=adapter)
    # Must be None, NEVER 14500.0
    assert price is None


def test_futures_with_mock_contract_feed():
    """R1: When valid contract data is supplied via broker adapter, quote is resolved nominally."""
    class MockConnectedBrokerAdapter:
        def get_futures_ltp(self, symbol):
            if symbol == "DIXON26SEPFUT":
                return 14750.50
            return None

    adapter = MockConnectedBrokerAdapter()
    price = resolve_futures_market_price("DIXON26SEPFUT", broker_adapter=adapter)
    assert price == 14750.50


# ============================================================================
# R2 Tests: Derived Signal Governance
# ============================================================================

@pytest.fixture
def test_scanner():
    """Construct an AllNSEScanner with isolated configuration and mocked credentials."""
    with patch.object(AllNSEScanner, "_reload_config_credentials", lambda self: None):
        cfg = {
            "EXECUTION_MODE": "SIGNAL_ONLY",
            "SIGNAL_DEDUP_COOLDOWN_SECS": 300,
            "MAX_ALERTS_PER_WINDOW": 5,
            "ALERT_RATE_WINDOW_SECS": 60,
            "MAX_ALERTS_PER_DAY": 10,
            "FUTURES_ENABLED": True,
            "MIN_SCORE_THRESHOLD": 70,
            "ALLOW_AFTER_HOURS_SCANNING": True,
        }
        scanner = AllNSEScanner(cfg=cfg)
        scanner._bot_token = ""
        scanner._email_enabled = False
        return scanner


def _make_parent_signal(symbol="RELIANCE", score=85, direction="CALL", price=3000.0):
    return ScannedStockSignal(
        symbol=symbol,
        company_name=f"{symbol} Ltd",
        series="EQ",
        direction=direction,
        score=score,
        raw_score=120,
        tier="STRONG",
        regime="TRENDING_BULL",
        price=price,
        rsi=62.0,
        adx=31.0,
        vwap=price - 10.0,
        confidence=0.88,
        ml_probability=0.72,
        score_components={},
        features={},
    )


def test_derived_futures_obeys_cooldown(test_scanner):
    """R2: Derived futures signal within cooldown is suppressed with COOLDOWN_SUPPRESSED."""
    parent = _make_parent_signal("RELIANCE")
    resolver = FuturesContractResolver.get_instance()
    contract = resolver.resolve_current_contract("RELIANCE")
    assert contract is not None
    fut_symbol = contract.canonical_symbol

    # Pre-set alert time within cooldown
    test_scanner._last_alert_time[fut_symbol] = time.time() - 30.0  # 30s ago (< 300s)

    with patch("core.fno_universe.is_fno_symbol", return_value=True):
        test_scanner._dispatch_futures_alert_if_eligible(parent)

    state = test_scanner._evaluation_states.get(fut_symbol)
    assert state is not None
    assert state["state"] == "COOLDOWN_SUPPRESSED"


def test_derived_futures_obeys_burst_rate_limit(test_scanner):
    """R2: Derived futures signal is suppressed when window burst limit is exhausted."""
    parent = _make_parent_signal("RELIANCE")
    resolver = FuturesContractResolver.get_instance()
    contract = resolver.resolve_current_contract("RELIANCE")
    assert contract is not None
    fut_symbol = contract.canonical_symbol

    # Exhaust rate limit deque
    now = time.time()
    for _ in range(5):  # max is 5
        test_scanner._recent_dispatch_times.append(now)

    with patch("core.fno_universe.is_fno_symbol", return_value=True):
        test_scanner._dispatch_futures_alert_if_eligible(parent)

    state = test_scanner._evaluation_states.get(fut_symbol)
    assert state is not None
    assert state["state"] == "FILTERED"
    assert "Rate limit" in state["reason"]


def test_derived_futures_obeys_daily_signal_limit(test_scanner):
    """R2: Derived futures signal is blocked when daily signal limit is reached."""
    parent = _make_parent_signal("RELIANCE")
    resolver = FuturesContractResolver.get_instance()
    contract = resolver.resolve_current_contract("RELIANCE")
    assert contract is not None
    fut_symbol = contract.canonical_symbol

    with patch("core.fno_universe.is_fno_symbol", return_value=True), \
         patch("core.signals.signal_tracker.SignalTracker.get_instance") as mock_tracker:
        mock_tracker.return_value.count_generated_today.return_value = 10  # max is 10
        test_scanner._dispatch_futures_alert_if_eligible(parent)

    state = test_scanner._evaluation_states.get(fut_symbol)
    assert state is not None
    assert state["state"] == "FILTERED"
    assert "Daily signal limit reached" in state["reason"]


def test_derived_futures_dispatches_when_limits_allow(test_scanner):
    """R2: Derived futures signal qualifies and records alert time when all limits permit."""
    parent = _make_parent_signal("RELIANCE")
    resolver = FuturesContractResolver.get_instance()
    contract = resolver.resolve_current_contract("RELIANCE")
    assert contract is not None
    fut_symbol = contract.canonical_symbol

    with patch("core.fno_universe.is_fno_symbol", return_value=True), \
         patch("core.futures_contract_resolver.resolve_futures_market_price", return_value=3025.0), \
         patch("core.auth.user_signal_permissions.UserPermissionManager.get_instance") as mock_perm, \
         patch("core.signals.signal_tracker.SignalTracker.get_instance") as mock_tracker:


        mock_user = MagicMock(telegram_enabled=False, email_enabled=False)
        mock_perm.return_value.get_eligible_recipients.return_value = [mock_user]
        mock_tracker.return_value.count_generated_today.return_value = 2
        mock_tracker.return_value.record_generated_signal.return_value = "SIG_FUT_123"

        test_scanner._dispatch_futures_alert_if_eligible(parent)

    assert fut_symbol in test_scanner._last_alert_time
    assert (time.time() - test_scanner._last_alert_time[fut_symbol]) < 5.0


# ============================================================================
# R3 Tests: Candle-Based Outcome Observation
# ============================================================================

def test_candle_high_detects_t1_call():
    """R3: Intra-bar High touches T1 for CALL signal even if Close is below T1."""
    tracker = SignalOutcomeTracker.get_instance()
    signal = {
        "signal_id": "SIG_TEST_CALL_1",
        "symbol": "TESTSTOCK",
        "direction": "CALL",
        "status": "ACTIVE",
        "entry_price": 100.0,
        "stop_loss": 97.0,
        "target_1": 104.0,
        "target_2": 108.0,
        "category": "EQUITY_SWING_DELIVERY",
    }
    # Bar touches High 104.5 (> T1 104.0), Low 99.0 (> SL 97.0), Close 102.0 (< T1)
    bar = SignalBar(
        open=100.5,
        high=104.5,
        low=99.0,
        close=102.0,
        timestamp=now_ist().isoformat(),
    )
    res = tracker.evaluate_bar(signal, bar)
    assert res.hit_t1 is True
    assert res.hit_sl is False
    assert res.new_status == "TARGET_1_HIT"
    assert res.first_touch == "T1"
    assert res.outcome_confidence == OutcomeConfidence.EXACT_OBSERVATION.value


def test_candle_low_detects_sl_call():
    """R3: Intra-bar Low touches SL for CALL signal."""
    tracker = SignalOutcomeTracker.get_instance()
    signal = {
        "signal_id": "SIG_TEST_CALL_2",
        "symbol": "TESTSTOCK",
        "direction": "CALL",
        "status": "ACTIVE",
        "entry_price": 100.0,
        "stop_loss": 97.0,
        "target_1": 104.0,
        "target_2": 108.0,
        "category": "EQUITY_SWING_DELIVERY",
    }
    bar = SignalBar(
        open=99.0,
        high=100.0,
        low=96.5,  # <= SL 97.0
        close=98.0,
        timestamp=now_ist().isoformat(),
    )
    res = tracker.evaluate_bar(signal, bar)
    assert res.hit_sl is True
    assert res.hit_t1 is False
    assert res.new_status == "SL_HIT"
    assert res.first_touch == "SL"


def test_candle_put_inversion():
    """R3: For PUT direction, Low touches T1 and High touches SL."""
    tracker = SignalOutcomeTracker.get_instance()
    signal = {
        "signal_id": "SIG_TEST_PUT_1",
        "symbol": "TESTPUT",
        "direction": "PUT",
        "status": "ACTIVE",
        "entry_price": 100.0,
        "stop_loss": 103.0,
        "target_1": 96.0,
        "target_2": 92.0,
        "category": "STOCK_OPTIONS",
    }
    # Low drops to 95.5 (<= T1 96.0)
    bar_t1 = SignalBar(open=99.0, high=101.0, low=95.5, close=97.0, timestamp=now_ist().isoformat())
    res_t1 = tracker.evaluate_bar(signal, bar_t1)
    assert res_t1.hit_t1 is True
    assert res_t1.hit_sl is False
    assert res_t1.new_status == "TARGET_1_HIT"
    assert res_t1.first_touch == "T1"

    # High climbs to 103.5 (>= SL 103.0)
    bar_sl = SignalBar(open=100.0, high=103.5, low=99.0, close=102.0, timestamp=now_ist().isoformat())
    res_sl = tracker.evaluate_bar(signal, bar_sl)
    assert res_sl.hit_sl is True
    assert res_sl.hit_t1 is False
    assert res_sl.new_status == "SL_HIT"
    assert res_sl.first_touch == "SL"


def test_candle_same_bar_ambiguity():
    """R3: When High touches T1 AND Low touches SL in the same bar, quarantined as AMBIGUOUS with first_touch None."""
    tracker = SignalOutcomeTracker.get_instance()
    signal = {
        "signal_id": "SIG_TEST_AMBIG_1",
        "symbol": "TESTAMBIG",
        "direction": "CALL",
        "status": "ACTIVE",
        "entry_price": 100.0,
        "stop_loss": 97.0,
        "target_1": 104.0,
        "target_2": 108.0,
        "category": "EQUITY_SWING_DELIVERY",
    }
    # Wide bar touching both 105.0 (>= T1) and 95.0 (<= SL)
    bar = SignalBar(
        open=100.0,
        high=105.0,
        low=95.0,
        close=99.0,
        timestamp=now_ist().isoformat(),
    )
    res = tracker.evaluate_bar(signal, bar)
    assert res.hit_t1 is True
    assert res.hit_sl is True
    assert res.new_status == "AMBIGUOUS"
    assert res.first_touch is None
    assert res.outcome_confidence == OutcomeConfidence.AMBIGUOUS.value

    # Boundary verification: Deterministic SL touch sets first_touch == "SL" (not AMBIGUOUS)
    bar_sl_only = SignalBar(open=100.0, high=101.0, low=95.0, close=96.0, timestamp=now_ist().isoformat())
    res_sl = tracker.evaluate_bar(signal, bar_sl_only)
    assert res_sl.new_status != "AMBIGUOUS"
    assert res_sl.new_status == "SL_HIT"
    assert res_sl.first_touch == "SL"

    # Boundary verification: Deterministic T1 touch sets first_touch == "T1" (not AMBIGUOUS)
    bar_t1_only = SignalBar(open=100.0, high=105.0, low=98.0, close=104.5, timestamp=now_ist().isoformat())
    res_t1 = tracker.evaluate_bar(signal, bar_t1_only)
    assert res_t1.new_status != "AMBIGUOUS"
    assert res_t1.new_status == "TARGET_1_HIT"
    assert res_t1.first_touch == "T1"


def test_candle_stale_bar_fails_closed():
    """R3: Stale bars (>15m) are rejected with no-op when staleness checking is requested."""
    tracker = SignalOutcomeTracker.get_instance()
    signal = {
        "signal_id": "SIG_TEST_STALE_1",
        "symbol": "TESTSTALE",
        "direction": "CALL",
        "status": "ACTIVE",
        "entry_price": 100.0,
        "stop_loss": 97.0,
        "target_1": 104.0,
        "category": "EQUITY_SWING_DELIVERY",
    }
    # Bar is 30 minutes old
    now = now_ist()
    old_ts = (now - datetime.timedelta(minutes=30)).isoformat()
    bar = SignalBar(
        open=100.0,
        high=105.0,
        low=99.0,
        close=104.5,
        timestamp=old_ts,
    )
    res = tracker.evaluate_bar(signal, bar, current_time=now, check_staleness=True)
    # Stale bar must be rejected without barrier hit
    assert res.hit_t1 is False
    assert res.hit_sl is False
    assert res.new_status is None


# ============================================================================
# R4 Tests: Analytics & G4 Metric Integrity
# ============================================================================

def test_first_touch_immutability_on_subsequent_timeout():
    """R4: When signal hits T1 and subsequently reaches calendar session close, first_touch remains T1 and normalizes to TARGET_FIRST."""
    # 1. State machine transition in tracker
    tracker = SignalOutcomeTracker.get_instance()
    signal_with_t1 = {
        "signal_id": "SIG_TEST_FT_1",
        "symbol": "TESTFT",
        "direction": "CALL",
        "status": "TARGET_1_HIT",
        "first_touch": "T1",
        "first_touch_at": "2026-09-28T10:15:00+05:30",
        "first_touch_price": 104.0,
        "outcome_confidence": "EXACT_OBSERVATION",
        "entry_price": 100.0,
        "stop_loss": 97.0,
        "target_1": 104.0,
        "target_2": 108.0,
        "created_date": "2026-09-28",
        "category": "STOCK_OPTIONS",
    }

    # At market close 15:35 IST
    close_time = datetime.datetime(2026, 9, 28, 15, 35, 0, tzinfo=now_ist().tzinfo)
    bar = SignalBar(open=103.0, high=103.5, low=102.5, close=103.0, timestamp=close_time.isoformat())

    eval_res = tracker.evaluate_bar(signal_with_t1, bar, current_time=close_time)
    assert eval_res.new_status == "EXPIRED"
    # First touch is preserved!
    assert eval_res.first_touch == "T1"

    # 2. Analytical normalization in dataset service
    normalized = normalize_outcome_state(
        first_touch=eval_res.first_touch,
        raw_status=eval_res.new_status,
        has_observations=True,
        is_valid=True,
    )
    # Must normalize to TARGET_FIRST, NOT TIMEOUT
    assert normalized == "TARGET_FIRST"


def test_g4_metric_dual_reporting():
    """R4: Test that G4 data quality gate reports schema/hygiene pass while separately exposing predictive usability metrics."""
    prod_db = Path("db/signals_history.db")
    if not prod_db.exists() or prod_db.stat().st_size < 500_000:
        pytest.skip(
            "Canonical historical production database db/signals_history.db (101 forward observations) "
            "not present in repository checkout (gitignored). Production database is intentionally external to CI."
        )

    SignalForwardMonitorService.reset_instance()
    try:
        service = SignalForwardMonitorService.get_instance(db_path=prod_db)
        dq = service.get_data_quality_summary()

        # G4 hygiene gate passes
        assert dq["dq_gate_passed"] is True
        assert dq["total_error_count"] == 0
        assert dq["data_quality_error_rate"] == 0.0

        # Predictive usability separation
        assert "predictive_usable_count" in dq
        assert "data_quality_affected_count" in dq
        assert "predictive_usable_percentage" in dq
        assert "data_quality_affected_percentage" in dq

        # In canonical cohort of 101: exactly 63 usable and 38 affected
        assert dq["total_observations"] == 101
        assert dq["predictive_usable_count"] == 63
        assert dq["data_quality_affected_count"] == 38
        assert dq["predictive_usable_percentage"] == 62.38
        assert dq["data_quality_affected_percentage"] == 37.62
    finally:
        SignalForwardMonitorService.reset_instance()


def test_data_quality_affected_quarantine_in_analytics():
    """R4: Affected records are distinguished without modifying historical cohort ground truth."""
    prod_db = Path("db/signals_history.db")
    if not prod_db.exists() or prod_db.stat().st_size < 500_000:
        pytest.skip(
            "Canonical historical production database db/signals_history.db (101 forward observations) "
            "not present in repository checkout (gitignored). Production database is intentionally external to CI."
        )

    SignalForwardMonitorService.reset_instance()
    try:
        service = SignalForwardMonitorService.get_instance(db_path=prod_db)
        summary = service.get_forward_summary()

        assert summary["total_registered"] == 101
        assert summary["predictive_usable_count"] == 63
        assert summary["data_quality_affected_count"] == 38

        # Verify daily report includes the new metrics
        reporter = ForwardAccumulationReporter(db_path=prod_db)
        report = reporter.generate_report()
        assert report.data_quality["predictive_usable_count"] == 63
        assert report.data_quality["data_quality_affected_count"] == 38

        md = reporter.render_markdown(report)
        assert "Predictive Usable" in md
        assert "DQ Affected" in md
    finally:
        SignalForwardMonitorService.reset_instance()


def test_scanner_passes_bar_lookup_fn(test_scanner):
    """R3: AllNSEScanner passes both price_lookup_fn and bar_lookup_fn to update_active_signal_outcomes."""
    with patch.object(test_scanner, "_market_session_is_open", return_value=True), \
         patch.object(test_scanner, "load_nse_universe", return_value=[]), \
         patch("core.signals.signal_tracker.SignalTracker.get_instance"), \
         patch("core.signals.signal_outcome_tracker.SignalOutcomeTracker.get_instance") as mock_tracker:

        # Populate a completed 1m bar
        sample_bar = SignalBar(
            open=100.0, high=105.0, low=99.0, close=104.0,
            timestamp=now_ist().isoformat()
        )
        test_scanner._latest_completed_bars["TCS"] = sample_bar

        test_scanner.scan_universe(symbols_limit=0, send_alerts=False)

        mock_tracker.return_value.update_active_signal_outcomes.assert_called_once()
        _, kwargs = mock_tracker.return_value.update_active_signal_outcomes.call_args
        assert "bar_lookup_fn" in kwargs
        assert "price_lookup_fn" in kwargs

        # Test that bar_lookup_fn returns the completed bar
        bar_lookup = kwargs["bar_lookup_fn"]
        retrieved_bar = bar_lookup("TCS")
        assert retrieved_bar == sample_bar


# ============================================================================
# Final Integration Verification (Checks 1–6)
# ============================================================================

def test_check1_futures_execution_path_wiring(tmp_path):
    """CHECK 1: Production execution-path wiring from FUTURES signal to resolver."""
    db_file = tmp_path / "test_check1.db"
    tracker = SignalOutcomeTracker(db_path=db_file)

    conn = tracker._get_conn()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS system_signals (
            signal_id TEXT PRIMARY KEY,
            timestamp TEXT NOT NULL,
            created_date TEXT NOT NULL,
            created_week TEXT NOT NULL,
            created_month TEXT NOT NULL,
            created_year TEXT NOT NULL,
            symbol TEXT NOT NULL,
            company_name TEXT,
            category TEXT NOT NULL,
            direction TEXT NOT NULL,
            score INTEGER NOT NULL,
            tier TEXT NOT NULL,
            entry_price REAL NOT NULL,
            stop_loss REAL NOT NULL,
            target_1 REAL NOT NULL,
            target_2 REAL NOT NULL,
            current_price REAL NOT NULL,
            status TEXT NOT NULL,
            pnl_pct REAL NOT NULL,
            channels_sent TEXT NOT NULL,
            first_touch TEXT DEFAULT '',
            first_touch_at TEXT DEFAULT '',
            first_touch_price REAL DEFAULT 0.0,
            outcome_confidence TEXT DEFAULT 'UNKNOWN'
        )
    """)
    now_str = now_ist().strftime("%Y-%m-%d %H:%M:%S")
    cur.execute("""
        INSERT INTO system_signals (
            signal_id, timestamp, created_date, created_week, created_month, created_year,
            symbol, company_name, category, direction, score, tier,
            entry_price, stop_loss, target_1, target_2, current_price, status, pnl_pct, channels_sent
        ) VALUES (
            'SIG-FUT-001', ?, '2026-09-29', 'W39', '09', '2026',
            'DIXON26SEPFUT', 'Dixon Futures', 'FUTURES', 'CALL', 85, 'STRONG',
            14500.0, 14000.0, 15000.0, 15500.0, 14500.0, 'ACTIVE', 0.0, 'TELEGRAM'
        )
    """, (now_str,))
    conn.commit()
    conn.close()

    # Mock broker adapter providing futures quotes/bars
    class MockFuturesBroker:
        def get_futures_bar(self, sym):
            if sym == "DIXON26SEPFUT":
                return SignalBar(
                    open=14600.0, high=15100.0, low=14500.0, close=15050.0,
                    timestamp=now_ist().isoformat()
                )
            return None
        def get_futures_ltp(self, sym):
            if sym == "DIXON26SEPFUT":
                return 15050.0
            return None

    mock_broker = MockFuturesBroker()
    with patch("core.futures_contract_resolver.resolve_futures_market_bar", side_effect=lambda s, **kw: mock_broker.get_futures_bar(s)), \
         patch("core.futures_contract_resolver.resolve_futures_market_price", side_effect=lambda s, **kw: mock_broker.get_futures_ltp(s)):

        # In scan_universe, latest_prices contains cash spot DIXON = 13500 (below SL)
        # but NOT DIXON26SEPFUT!
        res = tracker.update_active_signal_outcomes(
            price_lookup_fn=lambda s: {"DIXON": 13500.0}.get(s),
            bar_lookup_fn=lambda s: None
        )
        assert res["checked"] == 1
        assert res["resolved"] == 1

    # Verify signal resolved via futures bar (T1 hit at 15000), NEVER via cash spot (13500)
    conn = tracker._get_conn()
    cur = conn.cursor()
    cur.execute("SELECT status, first_touch, current_price FROM system_signals WHERE signal_id = 'SIG-FUT-001'")
    row = cur.fetchone()
    conn.close()

    assert row["status"] == "TARGET_1_HIT"
    assert row["first_touch"] == "T1"
    assert row["current_price"] == 15050.0


def test_check1_futures_never_substitutes_spot_cash_price(tmp_path):
    """CHECK 1: Prove cash spot price is NEVER substituted for futures contract."""
    db_file = tmp_path / "test_check1_spot.db"
    tracker = SignalOutcomeTracker(db_path=db_file)
    conn = tracker._get_conn()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS system_signals (
            signal_id TEXT PRIMARY KEY, timestamp TEXT NOT NULL, created_date TEXT NOT NULL,
            created_week TEXT NOT NULL, created_month TEXT NOT NULL, created_year TEXT NOT NULL,
            symbol TEXT NOT NULL, company_name TEXT, category TEXT NOT NULL, direction TEXT NOT NULL,
            score INTEGER NOT NULL, tier TEXT NOT NULL, entry_price REAL NOT NULL, stop_loss REAL NOT NULL,
            target_1 REAL NOT NULL, target_2 REAL NOT NULL, current_price REAL NOT NULL, status TEXT NOT NULL,
            pnl_pct REAL NOT NULL, channels_sent TEXT NOT NULL, first_touch TEXT DEFAULT '',
            first_touch_at TEXT DEFAULT '', first_touch_price REAL DEFAULT 0.0, outcome_confidence TEXT DEFAULT 'UNKNOWN'
        )
    """)
    now = now_ist()
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    created_date = now.strftime("%Y-%m-%d")
    created_week = f"W{now.isocalendar()[1]}"
    created_month = f"{now.month:02d}"
    created_year = str(now.year)
    cur.execute("""
        INSERT INTO system_signals (
            signal_id, timestamp, created_date, created_week, created_month, created_year,
            symbol, company_name, category, direction, score, tier,
            entry_price, stop_loss, target_1, target_2, current_price, status, pnl_pct, channels_sent
        ) VALUES (
            'SIG-FUT-002', ?, ?, ?, ?, ?,
            'DIXON26SEPFUT', 'Dixon Futures', 'FUTURES', 'CALL', 85, 'STRONG',
            14500.0, 14000.0, 15000.0, 15500.0, 14500.0, 'ACTIVE', 0.0, 'TELEGRAM'
        )
    """, (now_str, created_date, created_week, created_month, created_year))
    conn.commit()
    conn.close()

    # Cash spot price 13500.0 (would trigger SL_HIT if substituted!)
    # Futures resolver returns None (feed offline)
    res = tracker.update_active_signal_outcomes(
        price_lookup_fn=lambda s: {"DIXON": 13500.0}.get(s),
        bar_lookup_fn=lambda s: None
    )
    # Must NOT resolve
    assert res["resolved"] == 0

    conn = tracker._get_conn()
    cur = conn.cursor()
    cur.execute("SELECT status, first_touch, current_price FROM system_signals WHERE signal_id = 'SIG-FUT-002'")
    row = cur.fetchone()
    conn.close()

    assert row["status"] == "ACTIVE"
    assert row["first_touch"] == ""
    assert row["current_price"] == 14500.0


def test_check2_futures_missing_feed_fails_closed(tmp_path, caplog):
    """CHECK 2: Missing futures feed fails closed cleanly without exception, barrier hits, or price mutation."""
    caplog.clear()
    db_file = tmp_path / "test_check2.db"
    tracker = SignalOutcomeTracker(db_path=db_file)
    conn = tracker._get_conn()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS system_signals (
            signal_id TEXT PRIMARY KEY, timestamp TEXT NOT NULL, created_date TEXT NOT NULL,
            created_week TEXT NOT NULL, created_month TEXT NOT NULL, created_year TEXT NOT NULL,
            symbol TEXT NOT NULL, company_name TEXT, category TEXT NOT NULL, direction TEXT NOT NULL,
            score INTEGER NOT NULL, tier TEXT NOT NULL, entry_price REAL NOT NULL, stop_loss REAL NOT NULL,
            target_1 REAL NOT NULL, target_2 REAL NOT NULL, current_price REAL NOT NULL, status TEXT NOT NULL,
            pnl_pct REAL NOT NULL, channels_sent TEXT NOT NULL, first_touch TEXT DEFAULT '',
            first_touch_at TEXT DEFAULT '', first_touch_price REAL DEFAULT 0.0, outcome_confidence TEXT DEFAULT 'UNKNOWN'
        )
    """)
    now = now_ist()
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    created_date = now.strftime("%Y-%m-%d")
    created_week = f"W{now.isocalendar()[1]}"
    created_month = f"{now.month:02d}"
    created_year = str(now.year)
    cur.execute("""
        INSERT INTO system_signals (
            signal_id, timestamp, created_date, created_week, created_month, created_year,
            symbol, company_name, category, direction, score, tier,
            entry_price, stop_loss, target_1, target_2, current_price, status, pnl_pct, channels_sent
        ) VALUES (
            'SIG-FUT-003', ?, ?, ?, ?, ?,
            'DIXON26SEPFUT', 'Dixon Futures', 'FUTURES', 'CALL', 85, 'STRONG',
            14500.0, 14000.0, 15000.0, 15500.0, 14500.0, 'ACTIVE', 0.0, 'TELEGRAM'
        )
    """, (now_str, created_date, created_week, created_month, created_year))
    conn.commit()
    conn.close()

    # Resolver returns None (missing feed)
    res = tracker.update_active_signal_outcomes(price_lookup_fn=None, bar_lookup_fn=None)
    assert res["resolved"] == 0

    conn = tracker._get_conn()
    cur = conn.cursor()
    cur.execute("SELECT status, first_touch, current_price, pnl_pct FROM system_signals WHERE signal_id = 'SIG-FUT-003'")
    row = cur.fetchone()
    conn.close()

    assert row["status"] == "ACTIVE"
    assert row["first_touch"] == ""
    assert row["current_price"] == 14500.0
    assert row["pnl_pct"] == 0.0


def test_check3_completed_1m_candle_safety_invariant(test_scanner):
    """CHECK 3: Invariant proof: len(df1) < 2 records no SignalBar; len(df1) >= 2 records df1.iloc[-2]."""
    import pandas as pd
    now = now_ist()
    timestamps = [now - datetime.timedelta(minutes=i) for i in range(5, 0, -1)]

    # 1. Direct safety invariant test on the fail-closed logic:
    # len(df1) == 0 -> no bar
    df0 = pd.DataFrame()
    # len(df1) == 1 -> no bar
    df1_single = pd.DataFrame([{"Open": 100, "High": 105, "Low": 99, "Close": 104, "Volume": 100}], index=[now])
    # len(df1) == 2 -> df1.iloc[-2] recorded
    df1_pair = pd.DataFrame([
        {"Open": 100, "High": 105, "Low": 99, "Close": 104, "Volume": 100},  # iloc[-2]
        {"Open": 104, "High": 108, "Low": 103, "Close": 107, "Volume": 50},  # iloc[-1] forming
    ], index=[timestamps[0], timestamps[1]])

    def extract_bar_from_df(df):
        if len(df) >= 2:
            bar_row = df.iloc[-2]
            bar_idx = df.index[-2]
            ts_str = bar_idx.isoformat() if hasattr(bar_idx, "isoformat") else str(bar_idx)
            return SignalBar(
                open=float(bar_row["Open"]),
                high=float(bar_row["High"]),
                low=float(bar_row["Low"]),
                close=float(bar_row["Close"]),
                timestamp=ts_str,
                volume=float(bar_row.get("Volume", 0.0)),
            )
        return None

    assert extract_bar_from_df(df0) is None
    assert extract_bar_from_df(df1_single) is None
    bar_extracted = extract_bar_from_df(df1_pair)
    assert bar_extracted is not None
    assert bar_extracted.open == 100.0
    assert bar_extracted.close == 104.0  # From iloc[-2], NOT iloc[-1]

    # 2. Integration test in scan_single_stock with mock yfinance ticker
    df_valid = pd.DataFrame([
        {"Open": 3500.0, "High": 3510.0, "Low": 3495.0, "Close": 3505.0, "Volume": 1000},
        {"Open": 3505.0, "High": 3515.0, "Low": 3500.0, "Close": 3510.0, "Volume": 1100},
        {"Open": 3510.0, "High": 3520.0, "Low": 3505.0, "Close": 3515.0, "Volume": 1200},
        {"Open": 3515.0, "High": 3530.0, "Low": 3510.0, "Close": 3525.0, "Volume": 1500},  # iloc[-2]: completed
        {"Open": 3525.0, "High": 3535.0, "Low": 3520.0, "Close": 3530.0, "Volume": 300},   # iloc[-1]: forming
    ], index=timestamps)

    mock_ticker = MagicMock()
    mock_ticker.history.side_effect = lambda period, interval: df_valid if interval == "1m" else df_valid

    with patch("yfinance.Ticker", return_value=mock_ticker), \
         patch.object(test_scanner._evaluator, "evaluate", return_value=(None, "No setup")):
        test_scanner._latest_completed_bars.clear()
        test_scanner.scan_single_stock({"symbol": "TCS", "series": "EQ", "company_name": "TCS"})
        assert "TCS" in test_scanner._latest_completed_bars
        bar = test_scanner._latest_completed_bars["TCS"]
        # Must match iloc[-2] (Close: 3525.0, High: 3530.0), NOT forming iloc[-1] (Close: 3530.0)
        assert bar.close == 3525.0
        assert bar.high == 3530.0


def test_check4_candle_end_time_freshness_and_deduplication(tmp_path):
    """CHECK 4: Timestamp timezone handling, future-dated rejection, staleness, and deduplication."""
    tracker = SignalOutcomeTracker.get_instance()
    now = now_ist()
    signal = {
        "signal_id": "SIG_TEST_CHECK4",
        "symbol": "TCS",
        "direction": "CALL",
        "status": "ACTIVE",
        "entry_price": 100.0,
        "stop_loss": 97.0,
        "target_1": 104.0,
        "category": "EQUITY_SWING_DELIVERY",
    }

    # 1. Future-dated candle rejected (> 30s in future)
    future_time = now + datetime.timedelta(minutes=5)
    future_bar = SignalBar(open=100.0, high=105.0, low=99.0, close=104.0, timestamp=future_time.isoformat())
    res_future = tracker.evaluate_bar(signal, future_bar, current_time=now)
    assert res_future.hit_t1 is False
    assert res_future.new_status is None

    # 2. Stale candle rejected (> 15m in past when check_staleness=True)
    stale_time = now - datetime.timedelta(minutes=20)
    stale_bar = SignalBar(open=100.0, high=105.0, low=99.0, close=104.0, timestamp=stale_time.isoformat())
    res_stale = tracker.evaluate_bar(signal, stale_bar, current_time=now, check_staleness=True)
    assert res_stale.hit_t1 is False
    assert res_stale.new_status is None

    # 3. Valid fresh candle accepted
    fresh_time = now - datetime.timedelta(seconds=45)
    fresh_bar = SignalBar(open=100.0, high=105.0, low=99.0, close=104.0, timestamp=fresh_time.isoformat())
    res_fresh = tracker.evaluate_bar(signal, fresh_bar, current_time=now, check_staleness=True)
    assert res_fresh.hit_t1 is True
    assert res_fresh.new_status == "TARGET_1_HIT"

    # 4. Candle deduplication in update_active_signal_outcomes
    db_file = tmp_path / "test_check4_dedup.db"
    tracker_dedup = SignalOutcomeTracker(db_path=db_file)
    conn = tracker_dedup._get_conn()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS system_signals (
            signal_id TEXT PRIMARY KEY, timestamp TEXT NOT NULL, created_date TEXT NOT NULL,
            created_week TEXT NOT NULL, created_month TEXT NOT NULL, created_year TEXT NOT NULL,
            symbol TEXT NOT NULL, company_name TEXT, category TEXT NOT NULL, direction TEXT NOT NULL,
            score INTEGER NOT NULL, tier TEXT NOT NULL, entry_price REAL NOT NULL, stop_loss REAL NOT NULL,
            target_1 REAL NOT NULL, target_2 REAL NOT NULL, current_price REAL NOT NULL, status TEXT NOT NULL,
            pnl_pct REAL NOT NULL, channels_sent TEXT NOT NULL, first_touch TEXT DEFAULT '',
            first_touch_at TEXT DEFAULT '', first_touch_price REAL DEFAULT 0.0, outcome_confidence TEXT DEFAULT 'UNKNOWN'
        )
    """)
    now_str = now_ist().strftime("%Y-%m-%d %H:%M:%S")
    cur.execute("""
        INSERT INTO system_signals (
            signal_id, timestamp, created_date, created_week, created_month, created_year,
            symbol, company_name, category, direction, score, tier,
            entry_price, stop_loss, target_1, target_2, current_price, status, pnl_pct, channels_sent
        ) VALUES (
            'SIG-DEDUP-001', ?, '2026-09-29', 'W39', '09', '2026',
            'INFY', 'Infosys Ltd', 'LARGE_CAP_EQUITY', 'CALL', 85, 'STRONG',
            1800.0, 1750.0, 1850.0, 1900.0, 1800.0, 'ACTIVE', 0.0, 'TELEGRAM'
        )
    """, (now_str,))
    conn.commit()
    conn.close()

    identical_candle = SignalBar(
        open=1805.0, high=1815.0, low=1800.0, close=1810.0, timestamp=fresh_time.isoformat()
    )

    # First cycle evaluates the candle
    res1 = tracker_dedup.update_active_signal_outcomes(
        price_lookup_fn=None,
        bar_lookup_fn=lambda s: identical_candle if s == "INFY" else None
    )
    assert res1["checked"] == 1

    # Second cycle with the exact same candle timestamp is deduplicated
    res2 = tracker_dedup.update_active_signal_outcomes(
        price_lookup_fn=None,
        bar_lookup_fn=lambda s: identical_candle if s == "INFY" else None
    )
    assert res2["checked"] == 1
    # Check that ts_key is in _evaluated_candles
    assert f"SIG-DEDUP-001::{identical_candle.timestamp}" in tracker_dedup._evaluated_candles


def test_check5_target_sl_candle_six_cases():
    """CHECK 5: Verify all 6 target/SL candle barrier conditions."""
    tracker = SignalOutcomeTracker.get_instance()
    ts = now_ist().isoformat()

    # Case 1: CALL T1 Hit (High >= 103, Low > 98)
    call_sig = {"signal_id": "C1", "symbol": "S", "direction": "CALL", "entry_price": 100.0, "stop_loss": 98.0, "target_1": 103.0}
    b1 = SignalBar(open=100.5, high=103.5, low=100.2, close=103.1, timestamp=ts)
    r1 = tracker.evaluate_bar(call_sig, b1)
    assert r1.hit_t1 is True and r1.hit_sl is False and r1.new_status == "TARGET_1_HIT" and r1.first_touch == "T1"

    # Case 2: CALL SL Hit (Low <= 98, High < 103)
    b2 = SignalBar(open=100.2, high=100.8, low=97.5, close=98.0, timestamp=ts)
    r2 = tracker.evaluate_bar(call_sig, b2)
    assert r2.hit_sl is True and r2.hit_t1 is False and r2.new_status == "SL_HIT" and r2.first_touch == "SL"

    # Case 3: CALL Same-Bar Ambiguity (High >= 103 AND Low <= 98)
    b3 = SignalBar(open=100.0, high=103.5, low=97.5, close=101.0, timestamp=ts)
    r3 = tracker.evaluate_bar(call_sig, b3)
    assert r3.hit_t1 is True and r3.hit_sl is True and r3.new_status == "AMBIGUOUS" and r3.first_touch == "AMBIGUOUS_SAME_BAR"

    # Case 4: PUT T1 Hit (Low <= 97, High < 102)
    put_sig = {"signal_id": "P1", "symbol": "S", "direction": "PUT", "entry_price": 100.0, "stop_loss": 102.0, "target_1": 97.0}
    b4 = SignalBar(open=99.5, high=99.8, low=96.5, close=97.0, timestamp=ts)
    r4 = tracker.evaluate_bar(put_sig, b4)
    assert r4.hit_t1 is True and r4.hit_sl is False and r4.new_status == "TARGET_1_HIT" and r4.first_touch == "T1"

    # Case 5: PUT SL Hit (High >= 102, Low > 97)
    b5 = SignalBar(open=99.5, high=102.5, low=99.0, close=102.1, timestamp=ts)
    r5 = tracker.evaluate_bar(put_sig, b5)
    assert r5.hit_sl is True and r5.hit_t1 is False and r5.new_status == "SL_HIT" and r5.first_touch == "SL"

    # Case 6: PUT Same-Bar Ambiguity (Low <= 97 AND High >= 102)
    b6 = SignalBar(open=100.0, high=102.5, low=96.5, close=99.0, timestamp=ts)
    r6 = tracker.evaluate_bar(put_sig, b6)
    assert r6.hit_t1 is True and r6.hit_sl is True and r6.new_status == "AMBIGUOUS" and r6.first_touch == "AMBIGUOUS_SAME_BAR"


def test_check6_r2_governance_suppression_never_calls_tracker(test_scanner):
    """CHECK 6: Suppressed alerts (cooldown, rate limit, quota) NEVER call tracker.record_generated_signal()."""
    parent = _make_parent_signal("RELIANCE")
    resolver = FuturesContractResolver.get_instance()
    contract = resolver.resolve_current_contract("RELIANCE")
    assert contract is not None
    fut_symbol = contract.canonical_symbol

    with patch("core.fno_universe.is_fno_symbol", return_value=True), \
         patch("core.signals.signal_tracker.SignalTracker.get_instance") as mock_tracker:

        # 1. Cooldown suppression
        test_scanner._last_alert_time[fut_symbol] = time.time() - 10.0
        test_scanner._dispatch_futures_alert_if_eligible(parent)
        mock_tracker.return_value.record_generated_signal.assert_not_called()

        # 2. Window burst rate limit suppression
        test_scanner._last_alert_time.clear()
        now = time.time()
        for _ in range(5):
            test_scanner._recent_dispatch_times.append(now)
        test_scanner._dispatch_futures_alert_if_eligible(parent)
        mock_tracker.return_value.record_generated_signal.assert_not_called()

        # 3. Daily quota suppression
        test_scanner._recent_dispatch_times.clear()
        mock_tracker.return_value.count_generated_today.return_value = 10
        test_scanner._dispatch_futures_alert_if_eligible(parent)
        mock_tracker.return_value.record_generated_signal.assert_not_called()
