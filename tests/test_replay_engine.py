"""Tests for core/execution/replay_engine.py - Session Replay Engine.

Covers:
- ReplaySession dataclass fields and defaults
- ReplayState dataclass fields and defaults
- ReplayEngine init and storage initialization
- create_session, load_session, list_sessions
- start_replay, pause_replay, resume_replay, stop_replay
- step_forward, step_backward, seek_to_time
- set_speed, get_state, get_current_session
- replay_events_in_range, replay_order_lifecycle
- get_session_events, _persist_session
- get_replay_engine singleton
"""
from __future__ import annotations

import threading
from unittest.mock import MagicMock, call, patch

import pytest

from core.execution.replay_engine import (
    ReplayEngine,
    ReplaySession,
    ReplayState,
    get_replay_engine,
)


class TestReplaySession:
    """ReplaySession dataclass defaults."""

    def test_default_fields(self):
        sess = ReplaySession(
            session_id="REPLAY-001",
            start_time="09:15",
            end_time="15:30",
            market_data_path="data/md.csv",
            events_path="data/ev.csv",
        )
        assert sess.session_id == "REPLAY-001"
        assert sess.start_time == "09:15"
        assert sess.end_time == "15:30"
        assert sess.market_data_path == "data/md.csv"
        assert sess.events_path == "data/ev.csv"
        assert sess.status == "PENDING"
        assert sess.created_at == ""


class TestReplayState:
    """ReplayState dataclass defaults."""

    def test_default_fields(self):
        rs = ReplayState(
            current_time="09:15",
            current_event_index=0,
            total_events=100,
            speed=1.0,
            is_paused=False,
        )
        assert rs.current_time == "09:15"
        assert rs.current_event_index == 0
        assert rs.total_events == 100
        assert rs.speed == 1.0
        assert rs.is_paused is False

    def test_fully_configured(self):
        rs = ReplayState(
            current_time="10:00",
            current_event_index=5,
            total_events=50,
            speed=2.5,
            is_paused=True,
        )
        assert rs.current_time == "10:00"
        assert rs.current_event_index == 5
        assert rs.total_events == 50
        assert rs.speed == 2.5
        assert rs.is_paused is True


class TestReplayEngineInit:
    """ReplayEngine construction and storage init."""

    @patch("core.execution.replay_engine.get_connection")
    def test_init_creates_table(self, mock_get_conn: MagicMock):
        mock_conn = MagicMock()
        mock_get_conn.return_value.__enter__.return_value = mock_conn
        engine = ReplayEngine()
        assert engine._sessions == {}
        assert engine._current_session is None
        assert engine._replay_state is None
        assert engine._lock is not None
        mock_conn.execute.assert_called_once()
        assert "CREATE TABLE IF NOT EXISTS replay_sessions" in mock_conn.execute.call_args[0][0]

    @patch("core.execution.replay_engine.get_connection")
    def test_init_storage_failure_logged(self, mock_get_conn: MagicMock):
        mock_get_conn.return_value.__enter__.side_effect = OSError("Disk full")
        # Should not raise
        engine = ReplayEngine()
        assert engine._sessions == {}

    @patch("core.execution.replay_engine.ReplayEngine._init_durable_storage")
    def test_inits_empty(self, mock_init):
        engine = ReplayEngine()
        assert engine._sessions == {}
        assert engine._current_session is None


class TestCreateSession:
    """create_session() tests."""

    @patch("core.execution.replay_engine.get_connection")
    @patch("core.execution.replay_engine.time_provider")
    def test_creates_and_persists(self, mock_tp, mock_get_conn):
        mock_tp.get_ts.return_value = 1000.0
        mock_tp.format_ts.return_value = "2026-01-15T09:15:00"
        mock_conn = MagicMock()
        mock_get_conn.return_value.__enter__.return_value = mock_conn

        engine = ReplayEngine()
        sess = engine.create_session(
            start_time="09:15",
            end_time="15:30",
            market_data_path="data/md.csv",
        )
        assert sess.session_id == "REPLAY-1000"
        assert sess.start_time == "09:15"
        assert sess.end_time == "15:30"
        assert sess.market_data_path == "data/md.csv"
        assert sess.status == "PENDING"
        assert sess.created_at == "2026-01-15T09:15:00"
        assert engine._sessions["REPLAY-1000"] is sess
        # Persisted
        mock_conn.execute.assert_called()

    @patch("core.execution.replay_engine.get_connection")
    @patch("core.execution.replay_engine.time_provider")
    def test_store_path_defaults(self, mock_tp, mock_get_conn):
        mock_tp.get_ts.return_value = 2000.0
        mock_tp.format_ts.return_value = "2026-01-15T10:00:00"
        mock_conn = MagicMock()
        mock_get_conn.return_value.__enter__.return_value = mock_conn

        engine = ReplayEngine()
        sess = engine.create_session(start_time="10:00", end_time="11:00")
        assert sess.market_data_path == ""
        assert sess.events_path == ""

    @patch("core.execution.replay_engine.get_connection")
    @patch("core.execution.replay_engine.time_provider")
    def test_persist_failure_logged(self, mock_tp, mock_get_conn):
        mock_tp.get_ts.return_value = 3000.0
        mock_tp.format_ts.return_value = "2026-01-15T11:00:00"
        mock_conn = MagicMock()
        mock_conn.execute.side_effect = [None, OSError("DB locked")]
        mock_get_conn.return_value.__enter__.return_value = mock_conn

        engine = ReplayEngine()
        sess = engine.create_session(start_time="11:00", end_time="12:00")
        assert sess is not None
        assert sess.session_id == "REPLAY-3000"


class TestLoadSession:
    """load_session() and list_sessions()."""

    @patch("core.execution.replay_engine.get_connection")
    @patch("core.execution.replay_engine.time_provider")
    def test_load_existing(self, mock_tp, mock_get_conn):
        mock_tp.get_ts.return_value = 1.0
        mock_tp.format_ts.return_value = "T1"
        mock_conn = MagicMock()
        mock_get_conn.return_value.__enter__.return_value = mock_conn
        engine = ReplayEngine()
        sess = engine.create_session(start_time="09:15", end_time="15:30")
        loaded = engine.load_session(sess.session_id)
        assert loaded is sess

    @patch("core.execution.replay_engine.get_connection")
    @patch("core.execution.replay_engine.time_provider")
    def test_load_missing(self, mock_tp, mock_get_conn):
        mock_tp.get_ts.return_value = 2.0
        mock_tp.format_ts.return_value = "T2"
        mock_conn = MagicMock()
        mock_get_conn.return_value.__enter__.return_value = mock_conn
        engine = ReplayEngine()
        assert engine.load_session("NONEXISTENT") is None

    @patch("core.execution.replay_engine.get_connection")
    @patch("core.execution.replay_engine.time_provider")
    def test_list_sessions(self, mock_tp, mock_get_conn):
        mock_tp.get_ts.side_effect = [3.0, 4.0]  # Different IDs for each session
        mock_tp.format_ts.side_effect = ["T3", "T4"]
        mock_conn = MagicMock()
        mock_get_conn.return_value.__enter__.return_value = mock_conn
        engine = ReplayEngine()
        s1 = engine.create_session(start_time="09:15", end_time="10:00")
        s2 = engine.create_session(start_time="10:00", end_time="11:00")
        sessions = engine.list_sessions()
        assert len(sessions) == 2
        assert s1 in sessions
        assert s2 in sessions
        assert s1.session_id != s2.session_id


class TestStartReplay:
    """start_replay() tests."""

    @patch("core.execution.replay_engine.get_connection")
    @patch("core.execution.replay_engine.time_provider")
    def test_starts_successfully(self, mock_tp, mock_get_conn):
        mock_tp.get_ts.return_value = 10.0
        mock_tp.format_ts.return_value = "T10"
        mock_conn = MagicMock()
        mock_get_conn.return_value.__enter__.return_value = mock_conn
        engine = ReplayEngine()
        sess = engine.create_session(start_time="09:15", end_time="15:30")

        result = engine.start_replay(
            sess.session_id,
            speed=2.0,
            on_market_data=lambda x: None,
            on_event=lambda x: None,
        )
        assert result is True
        assert engine._current_session is sess
        assert engine._replay_state is not None
        assert engine._replay_state.current_time == "09:15"
        assert engine._replay_state.speed == 2.0
        assert engine._replay_state.is_paused is False
        assert sess.status == "RUNNING"

    @patch("core.execution.replay_engine.get_connection")
    @patch("core.execution.replay_engine.time_provider")
    def test_unknown_session(self, mock_tp, mock_get_conn):
        mock_tp.get_ts.return_value = 11.0
        mock_tp.format_ts.return_value = "T11"
        mock_conn = MagicMock()
        mock_get_conn.return_value.__enter__.return_value = mock_conn
        engine = ReplayEngine()
        result = engine.start_replay("NONEXISTENT")
        assert result is False

    @patch("core.execution.replay_engine.get_connection")
    @patch("core.execution.replay_engine.time_provider")
    def test_callbacks_stored(self, mock_tp, mock_get_conn):
        mock_tp.get_ts.return_value = 12.0
        mock_tp.format_ts.return_value = "T12"
        mock_conn = MagicMock()
        mock_get_conn.return_value.__enter__.return_value = mock_conn
        engine = ReplayEngine()
        sess = engine.create_session(start_time="09:15", end_time="15:30")
        md_cb = lambda x: None
        ev_cb = lambda x: None
        engine.start_replay(sess.session_id, on_market_data=md_cb, on_event=ev_cb)
        assert engine._market_data_callback is md_cb
        assert engine._event_callback is ev_cb


class TestPauseResumeStop:
    """pause_replay, resume_replay, stop_replay."""

    @patch("core.execution.replay_engine.get_connection")
    @patch("core.execution.replay_engine.time_provider")
    def test_pause_and_resume(self, mock_tp, mock_get_conn):
        mock_tp.get_ts.return_value = 20.0
        mock_tp.format_ts.return_value = "T20"
        mock_conn = MagicMock()
        mock_get_conn.return_value.__enter__.return_value = mock_conn
        engine = ReplayEngine()
        sess = engine.create_session(start_time="09:15", end_time="15:30")
        engine.start_replay(sess.session_id)

        assert engine.pause_replay() is True
        assert engine._replay_state.is_paused is True
        assert sess.status == "PAUSED"

        assert engine.resume_replay() is True
        assert engine._replay_state.is_paused is False
        assert sess.status == "RUNNING"

    @patch("core.execution.replay_engine.get_connection")
    @patch("core.execution.replay_engine.time_provider")
    def test_pause_when_not_running(self, mock_tp, mock_get_conn):
        mock_tp.get_ts.return_value = 21.0
        mock_tp.format_ts.return_value = "T21"
        mock_conn = MagicMock()
        mock_get_conn.return_value.__enter__.return_value = mock_conn
        engine = ReplayEngine()
        assert engine.pause_replay() is False
        assert engine.resume_replay() is False

    @patch("core.execution.replay_engine.get_connection")
    @patch("core.execution.replay_engine.time_provider")
    def test_stop_replay(self, mock_tp, mock_get_conn):
        mock_tp.get_ts.return_value = 30.0
        mock_tp.format_ts.return_value = "T30"
        mock_conn = MagicMock()
        mock_get_conn.return_value.__enter__.return_value = mock_conn
        engine = ReplayEngine()
        sess = engine.create_session(start_time="09:15", end_time="15:30")
        engine.start_replay(sess.session_id)

        assert engine.stop_replay() is True
        assert engine._current_session is None
        assert engine._replay_state is None
        assert sess.status == "COMPLETED"

    @patch("core.execution.replay_engine.get_connection")
    @patch("core.execution.replay_engine.time_provider")
    def test_stop_when_not_running(self, mock_tp, mock_get_conn):
        mock_tp.get_ts.return_value = 31.0
        mock_tp.format_ts.return_value = "T31"
        mock_conn = MagicMock()
        mock_get_conn.return_value.__enter__.return_value = mock_conn
        engine = ReplayEngine()
        assert engine.stop_replay() is False


class TestStepSeekSpeed:
    """step_forward, step_backward, seek_to_time, set_speed."""

    @patch("core.execution.replay_engine.get_connection")
    @patch("core.execution.replay_engine.time_provider")
    def test_step_forward(self, mock_tp, mock_get_conn):
        mock_tp.get_ts.return_value = 40.0
        mock_tp.format_ts.return_value = "T40"
        mock_conn = MagicMock()
        mock_get_conn.return_value.__enter__.return_value = mock_conn
        engine = ReplayEngine()
        sess = engine.create_session(start_time="09:15", end_time="15:30")
        engine.start_replay(sess.session_id)
        assert engine._replay_state.current_event_index == 0

        assert engine.step_forward(5) is True
        assert engine._replay_state.current_event_index == 5

    @patch("core.execution.replay_engine.get_connection")
    @patch("core.execution.replay_engine.time_provider")
    def test_step_backward(self, mock_tp, mock_get_conn):
        mock_tp.get_ts.return_value = 41.0
        mock_tp.format_ts.return_value = "T41"
        mock_conn = MagicMock()
        mock_get_conn.return_value.__enter__.return_value = mock_conn
        engine = ReplayEngine()
        sess = engine.create_session(start_time="09:15", end_time="15:30")
        engine.start_replay(sess.session_id)
        engine.step_forward(10)
        assert engine.step_backward(3) is True
        assert engine._replay_state.current_event_index == 7

    @patch("core.execution.replay_engine.get_connection")
    @patch("core.execution.replay_engine.time_provider")
    def test_step_backward_clamps_at_zero(self, mock_tp, mock_get_conn):
        mock_tp.get_ts.return_value = 42.0
        mock_tp.format_ts.return_value = "T42"
        mock_conn = MagicMock()
        mock_get_conn.return_value.__enter__.return_value = mock_conn
        engine = ReplayEngine()
        sess = engine.create_session(start_time="09:15", end_time="15:30")
        engine.start_replay(sess.session_id)
        assert engine.step_backward(99) is True
        assert engine._replay_state.current_event_index == 0

    @patch("core.execution.replay_engine.get_connection")
    @patch("core.execution.replay_engine.time_provider")
    def test_step_no_replay(self, mock_tp, mock_get_conn):
        engine = ReplayEngine()
        assert engine.step_forward(1) is False
        assert engine.step_backward(1) is False

    @patch("core.execution.replay_engine.get_connection")
    @patch("core.execution.replay_engine.time_provider")
    def test_seek_to_time(self, mock_tp, mock_get_conn):
        mock_tp.get_ts.return_value = 50.0
        mock_tp.format_ts.return_value = "T50"
        mock_conn = MagicMock()
        mock_get_conn.return_value.__enter__.return_value = mock_conn
        engine = ReplayEngine()
        sess = engine.create_session(start_time="09:15", end_time="15:30")
        engine.start_replay(sess.session_id)
        assert engine.seek_to_time("12:00") is True
        assert engine._replay_state.current_time == "12:00"

    @patch("core.execution.replay_engine.get_connection")
    @patch("core.execution.replay_engine.time_provider")
    def test_seek_no_session(self, mock_tp, mock_get_conn):
        engine = ReplayEngine()
        assert engine.seek_to_time("12:00") is False

    @patch("core.execution.replay_engine.get_connection")
    @patch("core.execution.replay_engine.time_provider")
    def test_set_speed(self, mock_tp, mock_get_conn):
        mock_tp.get_ts.return_value = 60.0
        mock_tp.format_ts.return_value = "T60"
        mock_conn = MagicMock()
        mock_get_conn.return_value.__enter__.return_value = mock_conn
        engine = ReplayEngine()
        sess = engine.create_session(start_time="09:15", end_time="15:30")
        engine.start_replay(sess.session_id)
        assert engine.set_speed(5.0) is True
        assert engine._replay_state.speed == 5.0

    @patch("core.execution.replay_engine.get_connection")
    @patch("core.execution.replay_engine.time_provider")
    def test_speed_clamped(self, mock_tp, mock_get_conn):
        mock_tp.get_ts.return_value = 61.0
        mock_tp.format_ts.return_value = "T61"
        mock_conn = MagicMock()
        mock_get_conn.return_value.__enter__.return_value = mock_conn
        engine = ReplayEngine()
        sess = engine.create_session(start_time="09:15", end_time="15:30")
        engine.start_replay(sess.session_id)
        assert engine.set_speed(0.01) is True  # clamped to 0.1
        assert engine._replay_state.speed == 0.1
        assert engine.set_speed(999) is True  # clamped to 100.0
        assert engine._replay_state.speed == 100.0

    @patch("core.execution.replay_engine.get_connection")
    @patch("core.execution.replay_engine.time_provider")
    def test_set_speed_no_replay(self, mock_tp, mock_get_conn):
        engine = ReplayEngine()
        assert engine.set_speed(2.0) is False


class TestGetState:
    """get_state() and get_current_session()."""

    @patch("core.execution.replay_engine.get_connection")
    @patch("core.execution.replay_engine.time_provider")
    def test_get_state(self, mock_tp, mock_get_conn):
        mock_tp.get_ts.return_value = 70.0
        mock_tp.format_ts.return_value = "T70"
        mock_conn = MagicMock()
        mock_get_conn.return_value.__enter__.return_value = mock_conn
        engine = ReplayEngine()
        assert engine.get_state() is None
        sess = engine.create_session(start_time="09:15", end_time="15:30")
        engine.start_replay(sess.session_id)
        state = engine.get_state()
        assert state is not None
        assert state.current_time == "09:15"

    @patch("core.execution.replay_engine.get_connection")
    @patch("core.execution.replay_engine.time_provider")
    def test_get_current_session(self, mock_tp, mock_get_conn):
        mock_tp.get_ts.return_value = 71.0
        mock_tp.format_ts.return_value = "T71"
        mock_conn = MagicMock()
        mock_get_conn.return_value.__enter__.return_value = mock_conn
        engine = ReplayEngine()
        assert engine.get_current_session() is None
        sess = engine.create_session(start_time="09:15", end_time="15:30")
        engine.start_replay(sess.session_id)
        assert engine.get_current_session() is sess
        engine.stop_replay()
        assert engine.get_current_session() is None


class TestReplayEvents:
    """replay_events_in_range() and replay_order_lifecycle()."""

    @patch("core.execution.replay_engine.get_connection")
    @patch("core.execution.replay_engine.get_event_store")
    def test_replay_events_in_range(self, mock_get_es, mock_get_conn):
        mock_conn = MagicMock()
        mock_get_conn.return_value.__enter__.return_value = mock_conn
        mock_store = MagicMock()
        mock_get_es.return_value = mock_store
        event_a = MagicMock()
        event_b = MagicMock()
        mock_store.get_events_in_range.return_value = [event_a, event_b]

        engine = ReplayEngine()
        callback = MagicMock()
        count = engine.replay_events_in_range("09:15", "15:30", callback)
        assert count == 2
        callback.assert_has_calls([call(event_a), call(event_b)])

    @patch("core.execution.replay_engine.get_connection")
    @patch("core.execution.replay_engine.get_event_store")
    def test_replay_events_empty(self, mock_get_es, mock_get_conn):
        mock_conn = MagicMock()
        mock_get_conn.return_value.__enter__.return_value = mock_conn
        mock_store = MagicMock()
        mock_get_es.return_value = mock_store
        mock_store.get_events_in_range.return_value = []

        engine = ReplayEngine()
        count = engine.replay_events_in_range("09:15", "15:30", lambda x: None)
        assert count == 0

    @patch("core.execution.replay_engine.get_connection")
    @patch("core.execution.replay_engine.get_event_store")
    def test_replay_events_callback_error(self, mock_get_es, mock_get_conn):
        mock_conn = MagicMock()
        mock_get_conn.return_value.__enter__.return_value = mock_conn
        mock_store = MagicMock()
        mock_get_es.return_value = mock_store
        event_a = MagicMock()
        mock_store.get_events_in_range.return_value = [event_a]

        engine = ReplayEngine()
        bad_cb = MagicMock(side_effect=ValueError("boom"))
        count = engine.replay_events_in_range("09:15", "15:30", bad_cb)
        assert count == 1  # Error logged, count still returned

    @patch("core.execution.replay_engine.get_connection")
    @patch("core.execution.replay_engine.get_event_store")
    def test_replay_order_lifecycle(self, mock_get_es, mock_get_conn):
        mock_conn = MagicMock()
        mock_get_conn.return_value.__enter__.return_value = mock_conn
        mock_store = MagicMock()
        mock_get_es.return_value = mock_store
        event_a = MagicMock()
        mock_store.get_events_for_order.return_value = [event_a]

        engine = ReplayEngine()
        callback = MagicMock()
        count = engine.replay_order_lifecycle("order-123", callback)
        assert count == 1
        callback.assert_called_once_with(event_a)
        mock_store.get_events_for_order.assert_called_once_with("order-123")


class TestGetSessionEvents:
    """get_session_events()."""

    @patch("core.execution.replay_engine.get_connection")
    @patch("core.execution.replay_engine.get_event_store")
    @patch("core.execution.replay_engine.time_provider")
    def test_get_session_events(self, mock_tp, mock_get_es, mock_get_conn):
        mock_tp.get_ts.return_value = 80.0
        mock_tp.format_ts.return_value = "T80"
        mock_conn = MagicMock()
        mock_get_conn.return_value.__enter__.return_value = mock_conn
        mock_store = MagicMock()
        mock_get_es.return_value = mock_store
        event_a = MagicMock()
        event_a.to_dict.return_value = {"id": "evt-1"}
        mock_store.get_events_in_range.return_value = [event_a]

        engine = ReplayEngine()
        sess = engine.create_session(start_time="09:15", end_time="15:30")
        events = engine.get_session_events(sess.session_id)
        assert len(events) == 1
        assert events[0]["id"] == "evt-1"

    @patch("core.execution.replay_engine.get_connection")
    @patch("core.execution.replay_engine.get_event_store")
    @patch("core.execution.replay_engine.time_provider")
    def test_get_session_events_unknown(self, mock_tp, mock_get_es, mock_get_conn):
        mock_tp.get_ts.return_value = 81.0
        mock_tp.format_ts.return_value = "T81"
        mock_conn = MagicMock()
        mock_get_conn.return_value.__enter__.return_value = mock_conn

        engine = ReplayEngine()
        events = engine.get_session_events("NONEXISTENT")
        assert events == []


class TestGetReplayEngine:
    """get_replay_engine singleton."""

    @patch("core.execution.replay_engine.get_connection")
    def test_singleton(self, mock_get_conn):
        mock_conn = MagicMock()
        mock_get_conn.return_value.__enter__.return_value = mock_conn
        engine1 = get_replay_engine()
        engine2 = get_replay_engine()
        assert engine1 is engine2
        assert isinstance(engine1, ReplayEngine)

    @patch("core.execution.replay_engine.get_connection")
    def test_reset_singleton_after_stop(self, mock_get_conn):
        mock_conn = MagicMock()
        mock_get_conn.return_value.__enter__.return_value = mock_conn
        engine1 = get_replay_engine()
        engine1.stop_replay()
        engine2 = get_replay_engine()
        assert engine2 is engine1  # singleton persists
