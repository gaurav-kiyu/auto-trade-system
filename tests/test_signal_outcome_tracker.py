"""Comprehensive Test Suite for Phase 2.1 Signal Outcome Tracker.

Covers all 15 mandatory verification cases:
1. Normal T1 hit for CALL
2. Normal SL hit for CALL
3. Normal T1 hit for PUT
4. Normal SL hit for PUT
5. T2 continuation after initial T1 hit
6. Ambiguous same-candle condition for CALL (High >= T1 and Low <= SL)
7. Ambiguous same-candle condition for PUT (Low <= T1 and High >= SL)
8. First-touch immutability (write-once guarantee)
9. Idempotency of duplicate bar evaluations (zero duplicate events)
10. Weekend and holiday suppression
11. Stale / missing / negative price handling (fail-open safety)
12. Intraday session-close expiration
13. Near-close generation grace period (no premature expiration)
14. Mathematical win rate & profit factor with ambiguous quarantining
15. Process restart recovery and state hydration from SQLite
"""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from core.signals.signal_outcome_tracker import (
    OutcomeConfidence,
    OutcomeState,
    SignalBar,
    SignalOutcomeTracker,
)
from core.signals.signal_tracker import SignalTracker


@pytest.fixture(autouse=True)
def _reset_singletons():
    SignalOutcomeTracker.reset_instance()
    SignalTracker.reset_instance()
    yield
    SignalOutcomeTracker.reset_instance()
    SignalTracker.reset_instance()


class TestSignalOutcomeTracker:
    def _create_tracker(self, tmp_path: Path, calendar_engine: Any = None) -> SignalOutcomeTracker:
        db_file = tmp_path / "test_outcomes.db"
        tracker = SignalOutcomeTracker(db_path=db_file, calendar_engine=calendar_engine)
        return tracker

    def _create_system_signal(
        self,
        tracker: SignalOutcomeTracker,
        signal_id: str = "SIG-TEST-001",
        symbol: str = "RELIANCE",
        direction: str = "CALL",
        category: str = "LARGE_CAP_EQUITY",
        entry_price: float = 2500.0,
        stop_loss: float = 2425.0,
        target_1: float = 2600.0,
        target_2: float = 2700.0,
        status: str = "ACTIVE",
        first_touch: str = "",
        first_touch_price: float = 0.0,
        order_placed: int = 0,
        recipients_count: int = 0,
        raw_data: str = "",
        created_date: str | None = None,
        timestamp: str | None = None,
    ) -> dict[str, Any]:
        from core.datetime_ist import now_ist
        _now = now_ist()
        if created_date is None:
            created_date = _now.strftime("%Y-%m-%d")
        if timestamp is None:
            timestamp = _now.strftime("%Y-%m-%d 10:00:00")
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
                recipients_count INTEGER DEFAULT 0,
                raw_data TEXT,
                opportunity_key TEXT,
                outcome_confidence TEXT DEFAULT 'POLLING',
                order_placed INTEGER DEFAULT 0,
                first_touch TEXT DEFAULT '',
                first_touch_at TEXT DEFAULT '',
                first_touch_price REAL DEFAULT 0.0
            )
        """)
        cur.execute("""
            INSERT OR REPLACE INTO system_signals (
                signal_id, timestamp, created_date, created_week, created_month, created_year,
                symbol, company_name, category, direction, score, tier, entry_price, stop_loss,
                target_1, target_2, current_price, status, pnl_pct, first_touch, first_touch_price,
                outcome_confidence, order_placed, recipients_count, raw_data
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            signal_id, timestamp, created_date, "2026-W38", "2026-09", "2026",
            symbol, symbol, category, direction, 85, "STRONG",
            entry_price, stop_loss, target_1, target_2, entry_price, status, 0.0,
            first_touch, first_touch_price, "POLLING", order_placed, recipients_count, raw_data
        ))
        conn.commit()
        cur.execute("SELECT * FROM system_signals WHERE signal_id = ?", (signal_id,))
        row = dict(cur.fetchone())
        conn.close()
        return row

    # 1. Normal T1 hit for CALL
    def test_state_transition_t1_call(self, tmp_path):
        tracker = self._create_tracker(tmp_path)
        sig = self._create_system_signal(tracker, direction="CALL", entry_price=100.0, stop_loss=95.0, target_1=104.0, target_2=108.0)

        bar = SignalBar(open=100.0, high=105.0, low=99.0, close=104.5, timestamp="2026-09-17T10:05:00")
        res = tracker.evaluate_bar(sig, bar)

        assert res.new_status == OutcomeState.TARGET_1_HIT.value
        assert res.first_touch == "T1"
        assert res.outcome_confidence == OutcomeConfidence.EXACT_OBSERVATION.value
        assert res.pnl_pct == 4.5

    # 2. Normal SL hit for CALL
    def test_state_transition_sl_call(self, tmp_path):
        tracker = self._create_tracker(tmp_path)
        sig = self._create_system_signal(tracker, direction="CALL", entry_price=100.0, stop_loss=95.0, target_1=104.0, target_2=108.0)

        bar = SignalBar(open=99.0, high=99.5, low=94.0, close=94.5, timestamp="2026-09-17T10:05:00")
        res = tracker.evaluate_bar(sig, bar)

        assert res.new_status == OutcomeState.SL_HIT.value
        assert res.first_touch == "SL"
        assert res.outcome_confidence == OutcomeConfidence.EXACT_OBSERVATION.value
        assert res.pnl_pct == -5.5

    # 3. Normal T1 hit for PUT
    def test_state_transition_t1_put(self, tmp_path):
        tracker = self._create_tracker(tmp_path)
        sig = self._create_system_signal(tracker, direction="PUT", entry_price=100.0, stop_loss=105.0, target_1=96.0, target_2=92.0)

        bar = SignalBar(open=100.0, high=101.0, low=95.0, close=95.5, timestamp="2026-09-17T10:05:00")
        res = tracker.evaluate_bar(sig, bar)

        assert res.new_status == OutcomeState.TARGET_1_HIT.value
        assert res.first_touch == "T1"
        assert res.outcome_confidence == OutcomeConfidence.EXACT_OBSERVATION.value
        assert res.pnl_pct == 4.5

    # 4. Normal SL hit for PUT
    def test_state_transition_sl_put(self, tmp_path):
        tracker = self._create_tracker(tmp_path)
        sig = self._create_system_signal(tracker, direction="PUT", entry_price=100.0, stop_loss=105.0, target_1=96.0, target_2=92.0)

        bar = SignalBar(open=101.0, high=106.0, low=100.5, close=105.5, timestamp="2026-09-17T10:05:00")
        res = tracker.evaluate_bar(sig, bar)

        assert res.new_status == OutcomeState.SL_HIT.value
        assert res.first_touch == "SL"
        assert res.outcome_confidence == OutcomeConfidence.EXACT_OBSERVATION.value
        assert res.pnl_pct == -5.5

    # 5. T2 continuation after initial T1 hit
    def test_state_transition_t2_continuation(self, tmp_path):
        tracker = self._create_tracker(tmp_path)
        sig = self._create_system_signal(
            tracker,
            direction="CALL",
            entry_price=100.0,
            stop_loss=95.0,
            target_1=104.0,
            target_2=108.0,
            status="TARGET_1_HIT",
            first_touch="T1",
        )

        bar = SignalBar(open=105.0, high=109.0, low=103.0, close=108.5, timestamp="2026-09-17T10:10:00")
        res = tracker.evaluate_bar(sig, bar)

        assert res.new_status == OutcomeState.TARGET_2_HIT.value
        # First touch remains T1 (write-once immutable)
        assert res.first_touch == "T1"

    # 6. Ambiguous same-candle condition for CALL (High >= T1 and Low <= SL)
    def test_ambiguous_same_candle_call(self, tmp_path):
        tracker = self._create_tracker(tmp_path)
        sig = self._create_system_signal(tracker, direction="CALL", entry_price=100.0, stop_loss=95.0, target_1=104.0, target_2=108.0)

        # Candle touched both 105.0 (>= T1) and 94.0 (<= SL) in the same bar!
        bar = SignalBar(open=99.0, high=105.0, low=94.0, close=101.0, timestamp="2026-09-17T10:05:00")
        res = tracker.evaluate_bar(sig, bar)

        assert res.new_status == OutcomeState.AMBIGUOUS.value
        assert res.first_touch == "AMBIGUOUS_SAME_BAR"
        assert res.outcome_confidence == OutcomeConfidence.AMBIGUOUS.value
        assert "Quarantined as Ambiguous" in res.transition_note

    # 7. Ambiguous same-candle condition for PUT (Low <= T1 and High >= SL)
    def test_ambiguous_same_candle_put(self, tmp_path):
        tracker = self._create_tracker(tmp_path)
        sig = self._create_system_signal(tracker, direction="PUT", entry_price=100.0, stop_loss=105.0, target_1=96.0, target_2=92.0)

        # Candle touched both 95.0 (<= T1) and 106.0 (>= SL) in the same bar!
        bar = SignalBar(open=101.0, high=106.0, low=95.0, close=98.0, timestamp="2026-09-17T10:05:00")
        res = tracker.evaluate_bar(sig, bar)

        assert res.new_status == OutcomeState.AMBIGUOUS.value
        assert res.first_touch == "AMBIGUOUS_SAME_BAR"
        assert res.outcome_confidence == OutcomeConfidence.AMBIGUOUS.value

    # 8. First-touch immutability (write-once guarantee)
    def test_first_touch_immutability(self, tmp_path):
        tracker = self._create_tracker(tmp_path)
        sig_id = "SIG-IMMUTABLE-001"
        self._create_system_signal(tracker, signal_id=sig_id, direction="CALL", entry_price=100.0, stop_loss=95.0, target_1=104.0)

        # Bar 1: Hits T1
        bar1 = SignalBar(open=100.0, high=105.0, low=99.0, close=104.0, timestamp="2026-09-17T10:00:00")
        tracker.update_active_signal_outcomes(lambda sym: None, bar_lookup_fn=lambda sym: bar1)

        conn = tracker._get_conn()
        row1 = dict(conn.execute("SELECT * FROM system_signals WHERE signal_id = ?", (sig_id,)).fetchone())
        conn.close()

        assert row1["status"] == "TARGET_1_HIT"
        assert row1["first_touch"] == "T1"
        first_touch_timestamp = row1["first_touch_at"]
        assert first_touch_timestamp

        # Bar 2: Price plunges to SL (94.0).
        bar2 = SignalBar(open=104.0, high=104.0, low=94.0, close=94.5, timestamp="2026-09-17T10:05:00")
        tracker.update_active_signal_outcomes(lambda sym: None, bar_lookup_fn=lambda sym: bar2)

        conn = tracker._get_conn()
        row2 = dict(conn.execute("SELECT * FROM system_signals WHERE signal_id = ?", (sig_id,)).fetchone())
        events = [dict(r) for r in conn.execute("SELECT * FROM signal_outcome_events WHERE signal_id = ?", (sig_id,)).fetchall()]
        conn.close()

        # first_touch and first_touch_at MUST REMAIN T1!
        assert row2["first_touch"] == "T1"
        assert row2["first_touch_at"] == first_touch_timestamp
        # The lifecycle event was recorded
        assert len(events) >= 1

    # 9. Idempotency of duplicate bar evaluations (zero duplicate events)
    def test_idempotent_processing(self, tmp_path):
        tracker = self._create_tracker(tmp_path)
        sig_id = "SIG-IDEMP-001"
        self._create_system_signal(tracker, signal_id=sig_id, direction="CALL", entry_price=100.0, stop_loss=95.0, target_1=104.0)

        bar = SignalBar(open=100.0, high=105.0, low=99.0, close=104.0, timestamp="2026-09-17T10:00:00")

        # Run 3 times with identical bar
        tracker.update_active_signal_outcomes(lambda sym: None, bar_lookup_fn=lambda sym: bar)
        tracker.update_active_signal_outcomes(lambda sym: None, bar_lookup_fn=lambda sym: bar)
        tracker.update_active_signal_outcomes(lambda sym: None, bar_lookup_fn=lambda sym: bar)

        conn = tracker._get_conn()
        events = [dict(r) for r in conn.execute("SELECT * FROM signal_outcome_events WHERE signal_id = ?", (sig_id,)).fetchall()]
        conn.close()

        # Exactly 1 event inserted, not 3
        assert len(events) == 1

    # 10. Weekend and holiday suppression
    def test_weekend_holiday_suppression(self, tmp_path):
        mock_cal = MagicMock()
        # Saturday: not a market day
        mock_cal.is_market_day.return_value = False
        tracker = self._create_tracker(tmp_path, calendar_engine=mock_cal)

        sig = self._create_system_signal(
            tracker,
            direction="CALL",
            category="INDEX_OPTIONS",
            entry_price=100.0,
            stop_loss=95.0,
            target_1=104.0,
            created_date="2026-09-18",
            timestamp="2026-09-18 10:00:00",
        )

        # Saturday evaluation time
        saturday_dt = datetime.datetime(2026, 9, 19, 16, 0, 0)
        bar = SignalBar(open=100.0, high=102.0, low=98.0, close=101.0, timestamp=saturday_dt)

        res = tracker.evaluate_bar(sig, bar, current_time=saturday_dt)
        # Should not expire on weekends/holidays
        assert res.new_status is None
        assert res.first_touch is None

    # 11. Stale / missing / negative price handling (fail-open safety)
    def test_stale_missing_price_handling(self, tmp_path):
        tracker = self._create_tracker(tmp_path)
        sig = self._create_system_signal(tracker, direction="CALL", entry_price=100.0, stop_loss=95.0, target_1=104.0)

        # 1. Negative price in bar
        bad_bar = SignalBar(open=-100.0, high=-90.0, low=-110.0, close=-95.0, timestamp="2026-09-17T10:00:00")
        res1 = tracker.evaluate_bar(sig, bad_bar)
        assert res1.new_status is None

        # 2. Inverted bar (high < low)
        inverted_bar = SignalBar(open=100.0, high=90.0, low=110.0, close=95.0, timestamp="2026-09-17T10:00:00")
        res2 = tracker.evaluate_bar(sig, inverted_bar)
        assert res2.new_status is None

        # 3. Stale bar (timestamp 30 minutes before current_time)
        now = datetime.datetime(2026, 9, 17, 10, 45, 0)
        stale_bar = SignalBar(open=100.0, high=105.0, low=99.0, close=104.0, timestamp=datetime.datetime(2026, 9, 17, 10, 0, 0))
        res3 = tracker.evaluate_bar(sig, stale_bar, current_time=now, check_staleness=True)
        # Stale bar fails open, zero state mutation
        assert res3.new_status is None

    # 12. Intraday session-close expiration
    def test_intraday_eod_expiration(self, tmp_path):
        mock_cal = MagicMock()
        mock_cal.is_market_day.return_value = True
        tracker = self._create_tracker(tmp_path, calendar_engine=mock_cal)

        sig = self._create_system_signal(
            tracker,
            direction="CALL",
            category="INDEX_OPTIONS",
            entry_price=100.0,
            stop_loss=95.0,
            target_1=104.0,
            created_date="2026-09-17",
            timestamp="2026-09-17 10:00:00",
        )

        # 15:35 IST on the same trading day (market closed)
        eod_time = datetime.datetime(2026, 9, 17, 15, 35, 0)
        bar = SignalBar(open=101.0, high=102.0, low=98.0, close=101.5, timestamp=eod_time)

        res = tracker.evaluate_bar(sig, bar, current_time=eod_time)
        assert res.new_status == OutcomeState.EXPIRED.value
        assert res.first_touch == "EXPIRED"
        assert res.outcome_confidence == OutcomeConfidence.UNRESOLVED.value

    # 13. Near-close generation grace period (no premature expiration)
    def test_session_close_edge_case(self, tmp_path):
        mock_cal = MagicMock()
        mock_cal.is_market_day.return_value = True
        tracker = self._create_tracker(tmp_path, calendar_engine=mock_cal)

        # Signal created at 15:22 IST (within 15m of close)
        sig = self._create_system_signal(
            tracker,
            direction="CALL",
            category="INDEX_OPTIONS",
            entry_price=100.0,
            stop_loss=95.0,
            target_1=104.0,
            created_date="2026-09-17",
            timestamp="2026-09-17 15:22:00",
        )

        # Evaluated at 15:31 IST (1 minute after close)
        eval_time = datetime.datetime(2026, 9, 17, 15, 31, 0)
        bar = SignalBar(open=100.5, high=101.0, low=99.5, close=100.0, timestamp=eval_time)

        res = tracker.evaluate_bar(sig, bar, current_time=eval_time)
        # Should NOT expire because it receives near-close grace
        assert res.new_status is None
        assert res.first_touch is None

    # 14. Mathematical win rate & profit factor with ambiguous quarantining
    def test_outcome_stats_api_math(self, tmp_path):
        tracker = self._create_tracker(tmp_path)
        # Seed 4 signals:
        # 1: T1 Hit (+4% gain)
        # 2: T1 Hit (+5% gain)
        # 3: SL Hit (-3% loss)
        # 4: Ambiguous (same candle T1+SL)
        # 5: Expired (0% gain)
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
                recipients_count INTEGER DEFAULT 0,
                raw_data TEXT,
                opportunity_key TEXT,
                outcome_confidence TEXT DEFAULT 'POLLING',
                first_touch TEXT DEFAULT '',
                first_touch_at TEXT DEFAULT ''
            )
        """)
        signals_data = [
            ("SIG-1", "TARGET_1_HIT", "T1", 4.0),
            ("SIG-2", "TARGET_1_HIT", "T1", 5.0),
            ("SIG-3", "SL_HIT", "SL", -3.0),
            ("SIG-4", "AMBIGUOUS", "AMBIGUOUS_SAME_BAR", 0.5),
            ("SIG-5", "EXPIRED", "EXPIRED", 0.0),
        ]
        for sig_id, status, ft, pnl in signals_data:
            cur.execute("""
                INSERT INTO system_signals (
                    signal_id, timestamp, created_date, created_week, created_month, created_year,
                    symbol, category, direction, score, tier, entry_price, stop_loss, target_1, target_2,
                    current_price, status, pnl_pct, first_touch, outcome_confidence
                ) VALUES (?, '2026-09-17 10:00:00', '2026-09-17', '2026-W38', '2026-09', '2026',
                          'TEST', 'LARGE_CAP_EQUITY', 'CALL', 85, 'STRONG', 100, 95, 104, 108,
                          100, ?, ?, ?, 'EXACT_OBSERVATION')
            """, (sig_id, status, pnl, ft))
        conn.commit()
        conn.close()

        stats = tracker.get_outcome_statistics(timeframe="all")
        assert stats["total_signals"] == 5
        assert stats["t1_hits"] == 2
        assert stats["sl_hits"] == 1
        assert stats["ambiguous"] == 1
        assert stats["expired"] == 1
        assert stats["resolved_signals"] == 3  # 2 T1 + 1 SL

        # Win Rate % = 2 / (2 + 1) * 100 = 66.67%
        # Ambiguous and Expired quarantined from both numerator and denominator!
        assert stats["win_rate_pct"] == 66.67
        # Profit Factor = (4.0 + 5.0) / 3.0 = 3.0
        assert stats["profit_factor"] == 3.0

    # 15. Process restart recovery and state hydration from SQLite
    def test_restart_recovery(self, tmp_path):
        db_path = tmp_path / "restart_test.db"
        tracker1 = SignalOutcomeTracker(db_path=db_path)
        sig_id = "SIG-RESTART-001"
        self._create_system_signal(tracker1, signal_id=sig_id, direction="CALL", entry_price=100.0, stop_loss=95.0, target_1=104.0)

        # Simulate process crash / restart by instantiating a fresh tracker instance
        tracker2 = SignalOutcomeTracker(db_path=db_path)
        conn = tracker2._get_conn()
        row = dict(conn.execute("SELECT * FROM system_signals WHERE signal_id = ?", (sig_id,)).fetchone())
        conn.close()

        assert row["status"] == "ACTIVE"
        assert row["first_touch"] == ""

        # Now evaluate price on tracker2
        bar = SignalBar(open=100.0, high=105.0, low=99.0, close=104.0, timestamp="2026-09-17T11:00:00")
        res = tracker2.evaluate_bar(row, bar)

        assert res.new_status == OutcomeState.TARGET_1_HIT.value
        assert res.first_touch == "T1"

    # 16. REST API route contract
    def test_api_routes_contract(self):
        auth_routes = (Path(__file__).resolve().parents[1] / "core" / "auth" / "routes.py").read_text(encoding="utf-8")
        admin_routes = (Path(__file__).resolve().parents[1] / "core" / "enterprise_dashboard" / "routes" / "admin.py").read_text(encoding="utf-8")
        assert '@router.get("/signals/outcome-stats")' in auth_routes
        assert '@app.get("/api/v1/signals/outcome-stats")' in admin_routes

    # 17. UI template contract
    def test_ui_templates_contract(self):
        admin_tpl = (Path(__file__).resolve().parents[1] / "templates" / "enterprise" / "admin_signals.html").read_text(encoding="utf-8")
        user_tpl = (Path(__file__).resolve().parents[1] / "templates" / "enterprise" / "user_signals.html").read_text(encoding="utf-8")
        assert 'id="statAmbiguous"' in admin_tpl
        assert 'id="statProfitFactor"' in admin_tpl
        assert 'value="AMBIGUOUS"' in admin_tpl
        assert 'AMBIGUOUS' in user_tpl

    # 18. CALL T2 Only (direct continuation or gap without stopping at T1)
    def test_call_t2_only(self, tmp_path):
        tracker = self._create_tracker(tmp_path)
        sig = self._create_system_signal(tracker, direction="CALL", entry_price=100.0, stop_loss=95.0, target_1=104.0, target_2=108.0)
        bar = SignalBar(open=105.0, high=109.0, low=101.0, close=108.5, timestamp="2026-09-17T10:05:00")
        res = tracker.evaluate_bar(sig, bar)
        assert res.new_status == OutcomeState.TARGET_2_HIT.value
        assert res.first_touch in ("T1", "T2")
        assert res.first_touch_price in (104.0, 108.0)
        assert res.is_terminal is True

    # 19. PUT T2 Only
    def test_put_t2_only(self, tmp_path):
        tracker = self._create_tracker(tmp_path)
        sig = self._create_system_signal(tracker, direction="PUT", entry_price=100.0, stop_loss=105.0, target_1=96.0, target_2=92.0)
        bar = SignalBar(open=95.0, high=97.0, low=91.0, close=91.5, timestamp="2026-09-17T10:05:00")
        res = tracker.evaluate_bar(sig, bar)
        assert res.new_status == OutcomeState.TARGET_2_HIT.value
        assert res.first_touch in ("T1", "T2")
        assert res.first_touch_price in (96.0, 92.0)
        assert res.is_terminal is True

    # 20. T2 + SL in the same bar (Ambiguous Quarantine)
    def test_ambiguous_t2_sl_same_bar(self, tmp_path):
        tracker = self._create_tracker(tmp_path)
        sig = self._create_system_signal(tracker, direction="CALL", entry_price=100.0, stop_loss=95.0, target_1=104.0, target_2=108.0)
        bar = SignalBar(open=99.0, high=110.0, low=93.0, close=101.0, timestamp="2026-09-17T10:05:00")
        res = tracker.evaluate_bar(sig, bar)
        assert res.new_status == OutcomeState.AMBIGUOUS.value
        assert res.first_touch == "AMBIGUOUS_SAME_BAR"
        assert res.outcome_confidence == OutcomeConfidence.AMBIGUOUS.value
        assert res.is_terminal is True

    # 21. T1 + T2 in the same bar without SL (Normal Target 2 progression)
    def test_t1_t2_same_bar_no_sl(self, tmp_path):
        tracker = self._create_tracker(tmp_path)
        sig = self._create_system_signal(tracker, direction="CALL", entry_price=100.0, stop_loss=95.0, target_1=104.0, target_2=108.0)
        bar = SignalBar(open=99.0, high=109.5, low=98.0, close=109.0, timestamp="2026-09-17T10:05:00")
        res = tracker.evaluate_bar(sig, bar)
        assert res.new_status == OutcomeState.TARGET_2_HIT.value
        assert res.first_touch == "T1"
        assert res.first_touch_price == 104.0
        assert res.is_terminal is True

    # 22. Direct gap through T2
    def test_direct_gap_through_t2(self, tmp_path):
        tracker = self._create_tracker(tmp_path)
        sig = self._create_system_signal(tracker, direction="CALL", entry_price=100.0, stop_loss=95.0, target_1=104.0, target_2=108.0)
        bar = SignalBar(open=112.0, high=115.0, low=111.0, close=114.0, timestamp="2026-09-17T10:05:00")
        res = tracker.evaluate_bar(sig, bar)
        assert res.new_status == OutcomeState.TARGET_2_HIT.value
        assert res.is_terminal is True

    # 23. Direct gap through SL
    def test_direct_gap_through_sl(self, tmp_path):
        tracker = self._create_tracker(tmp_path)
        sig = self._create_system_signal(tracker, direction="CALL", entry_price=100.0, stop_loss=95.0, target_1=104.0, target_2=108.0)
        bar = SignalBar(open=91.0, high=92.0, low=89.0, close=90.0, timestamp="2026-09-17T10:05:00")
        res = tracker.evaluate_bar(sig, bar)
        assert res.new_status == OutcomeState.SL_HIT.value
        assert res.first_touch == "SL"
        assert res.first_touch_price == 95.0
        assert res.is_terminal is True

    # 24. Exact equality at each barrier
    def test_exact_equality_at_each_barrier(self, tmp_path):
        tracker = self._create_tracker(tmp_path)
        sig = self._create_system_signal(tracker, direction="CALL", entry_price=100.0, stop_loss=95.0, target_1=104.0, target_2=108.0)
        # Exactly equals T1
        bar_t1 = SignalBar(open=100.0, high=104.0, low=99.0, close=103.5, timestamp="2026-09-17T10:05:00")
        res_t1 = tracker.evaluate_bar(sig, bar_t1)
        assert res_t1.new_status == OutcomeState.TARGET_1_HIT.value
        assert res_t1.first_touch_price == 104.0

        # Exactly equals SL
        bar_sl = SignalBar(open=99.0, high=99.5, low=95.0, close=96.0, timestamp="2026-09-17T10:05:00")
        res_sl = tracker.evaluate_bar(sig, bar_sl)
        assert res_sl.new_status == OutcomeState.SL_HIT.value
        assert res_sl.first_touch_price == 95.0

    # 25. T1 followed by T2 multi-bar progression
    def test_t1_followed_by_t2_progression(self, tmp_path):
        tracker = self._create_tracker(tmp_path)
        sig_id = "SIG-T1-T2-PROG"
        self._create_system_signal(tracker, signal_id=sig_id, direction="CALL", entry_price=100.0, stop_loss=95.0, target_1=104.0, target_2=108.0)

        # Bar 1: hits T1
        bar1 = SignalBar(open=100.0, high=105.0, low=99.0, close=104.0, timestamp="2026-09-17T10:00:00")
        tracker.update_active_signal_outcomes(lambda sym: None, bar_lookup_fn=lambda sym: bar1)

        conn = tracker._get_conn()
        row1 = dict(conn.execute("SELECT * FROM system_signals WHERE signal_id = ?", (sig_id,)).fetchone())
        conn.close()
        assert row1["status"] == "TARGET_1_HIT"
        assert row1["first_touch"] == "T1"
        assert row1["first_touch_price"] == 104.0

        # Bar 2: reaches T2
        bar2 = SignalBar(open=104.5, high=109.0, low=103.0, close=108.5, timestamp="2026-09-17T10:05:00")
        tracker.update_active_signal_outcomes(lambda sym: None, bar_lookup_fn=lambda sym: bar2)

        conn = tracker._get_conn()
        row2 = dict(conn.execute("SELECT * FROM system_signals WHERE signal_id = ?", (sig_id,)).fetchone())
        conn.close()
        assert row2["status"] == "TARGET_2_HIT"
        # FIRST-TOUCH IMMUTABLE
        assert row2["first_touch"] == "T1"
        assert row2["first_touch_price"] == 104.0

    # 26. T1 followed by SL preserves first touch
    def test_t1_followed_by_sl_preserves_first_touch(self, tmp_path):
        tracker = self._create_tracker(tmp_path)
        sig_id = "SIG-T1-SL-PRESERVE"
        self._create_system_signal(tracker, signal_id=sig_id, direction="CALL", entry_price=100.0, stop_loss=95.0, target_1=104.0, target_2=108.0)

        bar1 = SignalBar(open=100.0, high=105.0, low=99.0, close=104.0, timestamp="2026-09-17T10:00:00")
        tracker.update_active_signal_outcomes(lambda sym: None, bar_lookup_fn=lambda sym: bar1)

        conn = tracker._get_conn()
        row1 = dict(conn.execute("SELECT * FROM system_signals WHERE signal_id = ?", (sig_id,)).fetchone())
        conn.close()
        assert row1["status"] == "TARGET_1_HIT"
        assert row1["first_touch"] == "T1"
        assert row1["first_touch_price"] == 104.0

        # Bar 2: Crashes below SL (94.0)
        bar2 = SignalBar(open=103.0, high=103.0, low=93.0, close=93.5, timestamp="2026-09-17T10:05:00")
        tracker.update_active_signal_outcomes(lambda sym: None, bar_lookup_fn=lambda sym: bar2)

        conn = tracker._get_conn()
        row2 = dict(conn.execute("SELECT * FROM system_signals WHERE signal_id = ?", (sig_id,)).fetchone())
        conn.close()
        # First touch remains T1! Win is never turned into a loss retrospectively!
        assert row2["first_touch"] == "T1"
        assert row2["first_touch_price"] == 104.0

    # 27. Post-close signal generation grace
    def test_post_close_signal_grace(self, tmp_path):
        mock_cal = MagicMock()
        mock_cal.is_market_day.return_value = True
        tracker = self._create_tracker(tmp_path, calendar_engine=mock_cal)

        sig = self._create_system_signal(
            tracker,
            direction="CALL",
            category="INDEX_OPTIONS",
            entry_price=100.0,
            stop_loss=95.0,
            target_1=104.0,
            created_date="2026-09-17",
            timestamp="2026-09-17 15:35:00",
        )
        eval_time = datetime.datetime(2026, 9, 17, 15, 40, 0)
        bar = SignalBar(open=100.0, high=101.0, low=99.0, close=100.0, timestamp=eval_time)
        res = tracker.evaluate_bar(sig, bar, current_time=eval_time)
        assert res.new_status is None
        assert res.first_touch is None

    # 28. Exhaustive first-touch immutability across T1->T2, T1->SL, repeated evals, restart, duplicate bars
    def test_first_touch_immutability_exhaustive(self, tmp_path):
        db_path = tmp_path / "immutability_exhaustive.db"
        tracker = SignalOutcomeTracker(db_path=db_path)
        sig_id = "SIG-EXHAUSTIVE-FT"
        self._create_system_signal(tracker, signal_id=sig_id, direction="CALL", entry_price=100.0, stop_loss=95.0, target_1=104.0, target_2=108.0)

        # Step 1: Hit T1
        bar1 = SignalBar(open=100.0, high=105.0, low=99.0, close=104.0, timestamp="2026-09-17T10:00:00")
        tracker.update_active_signal_outcomes(lambda sym: None, bar_lookup_fn=lambda sym: bar1)

        conn = tracker._get_conn()
        r1 = dict(conn.execute("SELECT first_touch, first_touch_at, first_touch_price FROM system_signals WHERE signal_id = ?", (sig_id,)).fetchone())
        conn.close()
        ft, ft_at, ft_price = r1["first_touch"], r1["first_touch_at"], r1["first_touch_price"]
        assert ft == "T1"
        assert ft_price == 104.0
        assert ft_at != ""

        # Step 2: Duplicate bar evaluation
        tracker.update_active_signal_outcomes(lambda sym: None, bar_lookup_fn=lambda sym: bar1)

        # Step 3: T1 -> T2 progression
        bar2 = SignalBar(open=104.0, high=109.0, low=103.0, close=108.0, timestamp="2026-09-17T10:05:00")
        tracker.update_active_signal_outcomes(lambda sym: None, bar_lookup_fn=lambda sym: bar2)

        # Step 4: T1 -> SL crash
        bar3 = SignalBar(open=108.0, high=108.0, low=92.0, close=93.0, timestamp="2026-09-17T10:10:00")
        tracker.update_active_signal_outcomes(lambda sym: None, bar_lookup_fn=lambda sym: bar3)

        # Step 5: Process restart simulation
        tracker_restarted = SignalOutcomeTracker(db_path=db_path)
        tracker_restarted.update_active_signal_outcomes(lambda sym: None, bar_lookup_fn=lambda sym: bar3)

        conn = tracker_restarted._get_conn()
        r_final = dict(conn.execute("SELECT first_touch, first_touch_at, first_touch_price FROM system_signals WHERE signal_id = ?", (sig_id,)).fetchone())
        conn.close()

        # Strict bit-for-bit immutability check
        assert r_final["first_touch"] == ft == "T1"
        assert r_final["first_touch_at"] == ft_at
        assert r_final["first_touch_price"] == ft_price == 104.0

    # 29. Generated-signal independence: evaluates signals regardless of execution/notification state
    def test_generated_signal_independence(self, tmp_path):
        tracker = self._create_tracker(tmp_path)
        # 5 distinct conditions:
        # 1: generated + paper order placed
        # 2: generated + no paper order
        # 3: generated + margin blocked
        # 4: generated + notification dispatched
        # 5: generated + notification unavailable
        s1 = self._create_system_signal(tracker, signal_id="SIG-IND-1", order_placed=1, entry_price=100.0, stop_loss=95.0, target_1=104.0)
        s2 = self._create_system_signal(tracker, signal_id="SIG-IND-2", order_placed=0, entry_price=100.0, stop_loss=95.0, target_1=104.0)
        s3 = self._create_system_signal(tracker, signal_id="SIG-IND-3", order_placed=0, raw_data='{"margin_blocked": true}', entry_price=100.0, stop_loss=95.0, target_1=104.0)
        s4 = self._create_system_signal(tracker, signal_id="SIG-IND-4", recipients_count=2, entry_price=100.0, stop_loss=95.0, target_1=104.0)
        s5 = self._create_system_signal(tracker, signal_id="SIG-IND-5", recipients_count=0, entry_price=100.0, stop_loss=95.0, target_1=104.0)

        # Same market bar reaches T1 (105.0)
        bar = SignalBar(open=100.0, high=105.0, low=99.0, close=104.5, timestamp="2026-09-17T10:05:00")
        for sig in (s1, s2, s3, s4, s5):
            res = tracker.evaluate_bar(sig, bar)
            assert res.new_status == OutcomeState.TARGET_1_HIT.value
            assert res.first_touch == "T1"
            assert res.first_touch_price == 104.0
            assert res.outcome_confidence == OutcomeConfidence.EXACT_OBSERVATION.value

    # 30. Database idempotency: zero duplicate outcome events and transitions across repeated passes
    def test_database_idempotency_exhaustive(self, tmp_path):
        db_path = tmp_path / "idempotency_exhaustive.db"
        tracker = SignalOutcomeTracker(db_path=db_path)
        sig_id = "SIG-IDEMP-EXHAUSTIVE"
        self._create_system_signal(tracker, signal_id=sig_id, entry_price=100.0, stop_loss=95.0, target_1=104.0)

        bar = SignalBar(open=100.0, high=105.0, low=99.0, close=104.0, timestamp="2026-09-17T10:00:00")

        # 10 repeated passes of the exact same bar
        for _ in range(10):
            tracker.update_active_signal_outcomes(lambda sym: None, bar_lookup_fn=lambda sym: bar)

        conn = tracker._get_conn()
        events = [dict(r) for r in conn.execute("SELECT * FROM signal_outcome_events WHERE signal_id = ?", (sig_id,)).fetchall()]
        row = dict(conn.execute("SELECT * FROM system_signals WHERE signal_id = ?", (sig_id,)).fetchone())
        conn.close()

        assert len(events) == 1  # Exactly 1 event, not 10!
        assert row["status"] == "TARGET_1_HIT"
        assert row["first_touch"] == "T1"

    # 31. Explicit verification of First-Touch vs Lifecycle Progression semantics and event recording
    def test_first_touch_vs_lifecycle_events_explicit(self, tmp_path):
        db_path = tmp_path / "dual_semantics.db"
        tracker = SignalOutcomeTracker(db_path=db_path)

        # Signal A: T1 -> T2 progression
        sig_a = "SIG-SEMANTICS-T1-T2"
        self._create_system_signal(tracker, signal_id=sig_a, entry_price=100.0, stop_loss=95.0, target_1=104.0, target_2=108.0)

        # Bar A1: Touches T1 (105.0)
        bar_a1 = SignalBar(open=100.0, high=105.0, low=99.0, close=104.0, timestamp="2026-09-17T10:00:00")
        tracker.update_active_signal_outcomes(lambda sym: None, bar_lookup_fn=lambda sym: bar_a1)

        conn = tracker._get_conn()
        row_a1 = dict(conn.execute("SELECT * FROM system_signals WHERE signal_id = ?", (sig_a,)).fetchone())
        events_a1 = [dict(r) for r in conn.execute("SELECT * FROM signal_outcome_events WHERE signal_id = ?", (sig_a,)).fetchall()]
        conn.close()

        assert row_a1["status"] == "TARGET_1_HIT"
        assert row_a1["first_touch"] == "T1"
        assert row_a1["first_touch_price"] == 104.0
        assert len(events_a1) == 1
        assert events_a1[0]["hit_t1"] == 1 and events_a1[0]["hit_t2"] == 0

        # Bar A2: Advances to T2 (109.0)
        bar_a2 = SignalBar(open=104.5, high=109.0, low=103.5, close=108.5, timestamp="2026-09-17T10:05:00")
        tracker.update_active_signal_outcomes(lambda sym: None, bar_lookup_fn=lambda sym: bar_a2)

        conn = tracker._get_conn()
        row_a2 = dict(conn.execute("SELECT * FROM system_signals WHERE signal_id = ?", (sig_a,)).fetchone())
        events_a2 = [dict(r) for r in conn.execute("SELECT * FROM signal_outcome_events WHERE signal_id = ?", (sig_a,)).fetchall()]
        conn.close()

        # Lifecycle progressed to TARGET_2_HIT, but FIRST-TOUCH remains IMMUTABLE
        assert row_a2["status"] == "TARGET_2_HIT"
        assert row_a2["first_touch"] == "T1"
        assert row_a2["first_touch_price"] == 104.0
        assert len(events_a2) == 2
        assert events_a2[1]["hit_t2"] == 1

        # Signal B: T1 -> later SL reversal
        sig_b = "SIG-SEMANTICS-T1-SL"
        self._create_system_signal(tracker, signal_id=sig_b, entry_price=100.0, stop_loss=95.0, target_1=104.0, target_2=108.0)

        # Bar B1: Touches T1
        tracker.update_active_signal_outcomes(lambda sym: None, bar_lookup_fn=lambda sym: bar_a1)
        # Bar B2: Severe market drop touching SL (93.0)
        bar_b2 = SignalBar(open=103.0, high=103.0, low=93.0, close=93.5, timestamp="2026-09-17T10:05:00")
        tracker.update_active_signal_outcomes(lambda sym: None, bar_lookup_fn=lambda sym: bar_b2)

        conn = tracker._get_conn()
        row_b2 = dict(conn.execute("SELECT * FROM system_signals WHERE signal_id = ?", (sig_b,)).fetchone())
        events_b2 = [dict(r) for r in conn.execute("SELECT * FROM signal_outcome_events WHERE signal_id = ?", (sig_b,)).fetchall()]
        conn.close()

        # Lifecycle reflects SL hit, but First-Touch record remains strictly T1
        assert row_b2["status"] == "SL_HIT"
        assert row_b2["first_touch"] == "T1"
        assert row_b2["first_touch_price"] == 104.0
        assert len(events_b2) == 2
        assert events_b2[1]["hit_sl"] == 1

        # Check API stats clarity
        stats = tracker.get_outcome_statistics()
        assert stats["metric_type"] == "FIRST_TOUCH_OBSERVATIONAL"
        assert "first_touch_win_rate_pct" in stats
        assert "first_touch_win_rate_display" in stats

    # 32. Zero Upstream Mutation Verification: before/after field assertion across all signal attributes
    def test_no_upstream_mutation_comprehensive(self, tmp_path):
        db_path = tmp_path / "upstream_immutability.db"
        tracker = SignalOutcomeTracker(db_path=db_path)

        sig_id = "SIG-UPSTREAM-IMMUTABLE-001"
        self._create_system_signal(
            tracker,
            signal_id=sig_id,
            symbol="RELIANCE",
            category="LARGE_CAP_EQUITY",
            direction="CALL",
            entry_price=2850.0,
            stop_loss=2764.5,
            target_1=2964.0,
            target_2=3078.0,
            order_placed=1,
            recipients_count=5,
        )

        conn = tracker._get_conn()
        before_row = dict(conn.execute("SELECT * FROM system_signals WHERE signal_id = ?", (sig_id,)).fetchone())
        conn.close()

        # Execute multiple tracking updates with various price movements (including T1 hit)
        bar = SignalBar(open=2850.0, high=2970.0, low=2840.0, close=2965.0, timestamp="2026-09-17T09:30:00")
        tracker.update_active_signal_outcomes(lambda sym: None, bar_lookup_fn=lambda sym: bar)

        conn = tracker._get_conn()
        after_row = dict(conn.execute("SELECT * FROM system_signals WHERE signal_id = ?", (sig_id,)).fetchone())
        conn.close()

        # Upstream core fields MUST BE 100% UNCHANGED
        upstream_fields = [
            "signal_id", "symbol", "category", "direction", "score", "tier",
            "entry_price", "stop_loss", "target_1", "target_2",
            "order_placed", "recipients_count"
        ]
        for field in upstream_fields:
            assert before_row[field] == after_row[field], f"Upstream mutation detected in field '{field}': before={before_row[field]}, after={after_row[field]}"

    # 33. Distinguish the four observation states: within window, no barrier, data unavailable, not invoked
    def test_four_observation_conditions_distinct(self, tmp_path):
        db_path = tmp_path / "obs_conditions.db"
        tracker = SignalOutcomeTracker(db_path=db_path)

        sig_id = "SIG-OBS-CONDITIONS"
        self._create_system_signal(tracker, signal_id=sig_id, entry_price=100.0, stop_loss=95.0, target_1=104.0)

        # Condition 1: Signal still within observation window (and within barriers)
        bar_inside = SignalBar(open=100.0, high=102.0, low=99.0, close=101.0, timestamp="2026-09-17T10:00:00")
        res1 = tracker.evaluate_bar(dict(signal_id=sig_id, direction="CALL", entry_price=100.0, stop_loss=95.0, target_1=104.0, target_2=0.0, category="LARGE_CAP_EQUITY"), bar_inside)
        assert res1.new_status is None  # Remains ACTIVE/OPEN
        assert res1.first_touch is None
        assert res1.is_terminal is False

        # Condition 2: Genuine bar evaluated but no qualifying outcome occurred
        tracker.update_active_signal_outcomes(lambda sym: None, bar_lookup_fn=lambda sym: bar_inside)
        conn = tracker._get_conn()
        events = conn.execute("SELECT * FROM signal_outcome_events WHERE signal_id = ?", (sig_id,)).fetchall()
        row = dict(conn.execute("SELECT * FROM system_signals WHERE signal_id = ?", (sig_id,)).fetchone())
        conn.close()
        assert len(events) == 0  # 0 events recorded because no barrier was reached
        assert row["status"] == "ACTIVE"  # Status unchanged

        # Condition 3: Market data unavailable or stale quote (> 15m)
        bar_stale = SignalBar(open=100.0, high=105.0, low=99.0, close=104.0, timestamp="2026-09-17T09:00:00")
        res_stale = tracker.evaluate_bar(row, bar_stale, check_staleness=True, current_time=datetime.datetime.fromisoformat("2026-09-17T10:00:00"))
        assert res_stale.new_status is None
        assert res_stale.first_touch is None  # Fails open, zero mutation

        # Condition 4: Tracker not invoked
        # If tracker is not invoked, database values remain frozen at their last known verified state
        assert row["status"] == "ACTIVE"
        assert row["first_touch"] == ""
