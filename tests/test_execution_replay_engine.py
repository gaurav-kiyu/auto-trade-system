"""Tests for core/execution/replay_engine.py - Replay Engine."""

from __future__ import annotations

import itertools
from unittest.mock import patch

import pytest
from core.execution.replay_engine import (
    ReplayEngine,
    ReplaySession,
    ReplayState,
    get_replay_engine,
)
from core.time_provider import time_provider

_ts_counter = itertools.count(1000)


def _mock_get_ts():
    return next(_ts_counter)


class TestReplaySession:
    """ReplaySession dataclass coverage."""

    def test_defaults(self):
        s = ReplaySession(
            session_id="REPLAY-001",
            start_time="2026-01-01T09:00:00",
            end_time="2026-01-01T15:00:00",
            market_data_path="data.csv",
            events_path="events.json",
        )
        assert s.status == "PENDING"
        assert s.created_at == ""


class TestReplayState:
    """ReplayState dataclass coverage."""

    def test_values(self):
        s = ReplayState(
            current_time="09:00:00",
            current_event_index=0,
            total_events=100,
            speed=1.0,
            is_paused=False,
        )
        assert s.current_event_index == 0
        assert s.is_paused is False
        assert s.speed == 1.0


class TestReplayEngine:
    """ReplayEngine coverage."""

    @pytest.fixture
    def engine(self):
        with patch.object(time_provider, 'get_ts', create=True, side_effect=_mock_get_ts):
            yield ReplayEngine()

    def test_create_session(self, engine):
        session = engine.create_session(
            start_time="2026-01-01T09:00:00",
            end_time="2026-01-01T15:00:00",
            market_data_path="data.csv",
        )
        assert session.session_id.startswith("REPLAY-")
        assert session.status == "PENDING"

    def test_load_session(self, engine):
        session = engine.create_session(
            start_time="2026-01-01T09:00:00",
            end_time="2026-01-01T15:00:00",
        )
        loaded = engine.load_session(session.session_id)
        assert loaded is session

    def test_load_session_not_found(self, engine):
        result = engine.load_session("nonexistent")
        assert result is None

    def test_start_replay(self, engine):
        session = engine.create_session("09:00", "15:00")
        result = engine.start_replay(session.session_id, speed=1.0)
        assert result is True
        assert engine._current_session is not None
        assert engine._replay_state is not None
        assert engine._replay_state.current_time == "09:00"

    def test_start_replay_session_not_found(self, engine):
        result = engine.start_replay("nonexistent")
        assert result is False

    def test_pause_replay(self, engine):
        session = engine.create_session("09:00", "15:00")
        engine.start_replay(session.session_id)
        assert engine.pause_replay() is True
        assert engine._replay_state.is_paused is True

    def test_pause_replay_no_active_session(self, engine):
        assert engine.pause_replay() is False

    def test_resume_replay(self, engine):
        session = engine.create_session("09:00", "15:00")
        engine.start_replay(session.session_id)
        engine.pause_replay()
        assert engine.resume_replay() is True
        assert engine._replay_state.is_paused is False

    def test_resume_replay_no_active_session(self, engine):
        assert engine.resume_replay() is False

    def test_stop_replay(self, engine):
        session = engine.create_session("09:00", "15:00")
        engine.start_replay(session.session_id)
        assert engine.stop_replay() is True
        assert engine._current_session is None
        assert engine._replay_state is None

    def test_stop_replay_no_active_session(self, engine):
        assert engine.stop_replay() is False

    def test_step_forward(self, engine):
        session = engine.create_session("09:00", "15:00")
        engine.start_replay(session.session_id)
        assert engine.step_forward(3) is True
        assert engine._replay_state.current_event_index == 3

    def test_step_forward_no_active_session(self, engine):
        assert engine.step_forward() is False

    def test_step_backward(self, engine):
        session = engine.create_session("09:00", "15:00")
        engine.start_replay(session.session_id)
        engine.step_forward(5)
        assert engine.step_backward(2) is True
        assert engine._replay_state.current_event_index == 3

    def test_step_backward_no_active_session(self, engine):
        assert engine.step_backward() is False

    def test_step_backward_clamps_at_zero(self, engine):
        session = engine.create_session("09:00", "15:00")
        engine.start_replay(session.session_id)
        engine.step_backward(10)
        assert engine._replay_state.current_event_index == 0

    def test_seek_to_time(self, engine):
        session = engine.create_session("09:00", "15:00")
        engine.start_replay(session.session_id)
        assert engine.seek_to_time("12:00") is True
        assert engine._replay_state.current_time == "12:00"

    def test_seek_to_time_no_session(self, engine):
        assert engine.seek_to_time("12:00") is False

    def test_set_speed(self, engine):
        session = engine.create_session("09:00", "15:00")
        engine.start_replay(session.session_id)
        assert engine.set_speed(2.5) is True
        assert engine._replay_state.speed == 2.5

    def test_set_speed_no_session(self, engine):
        assert engine.set_speed(2.0) is False

    def test_set_speed_clamps_low(self, engine):
        session = engine.create_session("09:00", "15:00")
        engine.start_replay(session.session_id)
        engine.set_speed(0.01)
        assert engine._replay_state.speed == 0.1

    def test_set_speed_clamps_high(self, engine):
        session = engine.create_session("09:00", "15:00")
        engine.start_replay(session.session_id)
        engine.set_speed(200.0)
        assert engine._replay_state.speed == 100.0

    def test_get_state_no_session(self, engine):
        assert engine.get_state() is None

    def test_get_current_session(self, engine):
        session = engine.create_session("09:00", "15:00")
        engine.start_replay(session.session_id)
        current = engine.get_current_session()
        assert current is session

    def test_list_sessions(self, engine):
        engine.create_session("09:00", "15:00")
        engine.create_session("10:00", "16:00")
        sessions = engine.list_sessions()
        assert len(sessions) == 2

    def test_get_session_events_not_found(self, engine):
        events = engine.get_session_events("nonexistent")
        assert events == []


class TestGetReplayEngine:
    """Singleton get_replay_engine coverage."""

    def test_get_instance(self):
        engine = get_replay_engine()
        assert isinstance(engine, ReplayEngine)

    def test_singleton_behavior(self):
        e1 = get_replay_engine()
        e2 = get_replay_engine()
        assert e1 is e2
