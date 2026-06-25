"""
Replay Engine - Item 8

Replay exact historical sessions tick by tick:
- Uses production logic unchanged
- Perfect for regression testing
- Incident replay
- Strategy debugging

Massive ROI for debugging and testing.
"""
from __future__ import annotations

import logging
import threading

from core.db_utils import get_connection
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from core.execution.event_system import TradingEvent, get_event_store
from core.time_provider import time_provider

_log = logging.getLogger(__name__)


@dataclass
class ReplaySession:
    """Replay session definition"""
    session_id: str
    start_time: str
    end_time: str
    market_data_path: str
    events_path: str
    status: str = "PENDING"
    created_at: str = ""


@dataclass
class ReplayState:
    """Current replay state"""
    current_time: str
    current_event_index: int
    total_events: int
    speed: float
    is_paused: bool


class ReplayEngine:
    """
    Session replay engine.
    Replays historical trading sessions for testing and debugging.
    """

    PERSISTENCE_PATH = "replay_sessions.db"

    def __init__(self):
        self._sessions: dict[str, ReplaySession] = {}
        self._current_session: ReplaySession | None = None
        self._replay_state: ReplayState | None = None
        self._lock = threading.RLock()
        self._market_data_callback: Callable | None = None
        self._event_callback: Callable | None = None
        self._init_durable_storage()

    def _init_durable_storage(self) -> None:
        """Initialize replay session storage"""
        try:
            with get_connection(self.PERSISTENCE_PATH) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS replay_sessions (
                        session_id TEXT PRIMARY KEY,
                        start_time TEXT,
                        end_time TEXT,
                        market_data_path TEXT,
                        events_path TEXT,
                        status TEXT,
                        created_at TEXT
                    )
                """)
                conn.commit()
            _log.info("ReplayEngine: Storage initialized")
        except Exception as e:
            _log.error(f"ReplayEngine: Failed to init storage: {e} (type: {type(e).__name__})")

    def create_session(
        self,
        start_time: str,
        end_time: str,
        market_data_path: str = "",
    ) -> ReplaySession:
        """Create a new replay session"""
        session_id = f"REPLAY-{int(time_provider.get_ts())}"

        session = ReplaySession(
            session_id=session_id,
            start_time=start_time,
            end_time=end_time,
            market_data_path=market_data_path,
            events_path="",
            created_at=time_provider.format_ts(),
        )

        self._sessions[session_id] = session
        self._persist_session(session)
        _log.info(f"Created replay session: {session_id}")

        return session

    def load_session(self, session_id: str) -> ReplaySession | None:
        """Load a replay session"""
        return self._sessions.get(session_id)

    def start_replay(
        self,
        session_id: str,
        speed: float = 1.0,
        on_market_data: Callable | None = None,
        on_event: Callable | None = None,
    ) -> bool:
        """Start replaying a session"""
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                _log.error(f"Session not found: {session_id}")
                return False

            self._current_session = session
            self._market_data_callback = on_market_data
            self._event_callback = on_event
            self._replay_state = ReplayState(
                current_time=session.start_time,
                current_event_index=0,
                total_events=0,
                speed=speed,
                is_paused=False,
            )

            session.status = "RUNNING"
            self._persist_session(session)
            _log.info(f"Started replay: {session_id} at speed {speed}x")
            return True

    def pause_replay(self) -> bool:
        """Pause current replay"""
        with self._lock:
            if self._replay_state:
                self._replay_state.is_paused = True
                if self._current_session:
                    self._current_session.status = "PAUSED"
                _log.info("Replay paused")
                return True
            return False

    def resume_replay(self) -> bool:
        """Resume paused replay"""
        with self._lock:
            if self._replay_state:
                self._replay_state.is_paused = False
                if self._current_session:
                    self._current_session.status = "RUNNING"
                _log.info("Replay resumed")
                return True
            return False

    def stop_replay(self) -> bool:
        """Stop current replay"""
        with self._lock:
            if self._current_session:
                self._current_session.status = "COMPLETED"
                self._persist_session(self._current_session)
                self._current_session = None
                self._replay_state = None
                _log.info("Replay stopped")
                return True
            return False

    def step_forward(self, steps: int = 1) -> bool:
        """Step forward N events"""
        with self._lock:
            if not self._replay_state or not self._current_session:
                return False

            self._replay_state.current_event_index += steps
            return True

    def step_backward(self, steps: int = 1) -> bool:
        """Step backward N events"""
        with self._lock:
            if not self._replay_state:
                return False

            self._replay_state.current_event_index = max(0, self._replay_state.current_event_index - steps)
            return True

    def seek_to_time(self, timestamp: str) -> bool:
        """Seek to specific timestamp"""
        with self._lock:
            if not self._current_session:
                return False

            self._replay_state.current_time = timestamp
            _log.info(f"Seeked to: {timestamp}")
            return True

    def replay_events_in_range(
        self,
        start_time: str,
        end_time: str,
        callback: Callable[[TradingEvent], None],
    ) -> int:
        """Replay all events in time range using event store"""
        event_store = get_event_store()
        events = event_store.get_events_in_range(start_time, end_time)

        for event in events:
            try:
                callback(event)
            except Exception as e:
                _log.error(f"Error in replay callback: {e} (type: {type(e).__name__})")

        _log.info(f"Replayed {len(events)} events from {start_time} to {end_time}")
        return len(events)

    def replay_order_lifecycle(self, client_order_id: str, callback: Callable[[TradingEvent], None]) -> int:
        """Replay full order lifecycle from events"""
        event_store = get_event_store()
        events = event_store.get_events_for_order(client_order_id)

        for event in events:
            try:
                callback(event)
            except Exception as e:
                _log.error(f"Error in order replay: {e} (type: {type(e).__name__})")

        _log.info(f"Replayed {len(events)} events for order {client_order_id}")
        return len(events)

    def set_speed(self, speed: float) -> bool:
        """Set replay speed"""
        with self._lock:
            if self._replay_state:
                self._replay_state.speed = max(0.1, min(100.0, speed))
                _log.info(f"Replay speed set to {self._replay_state.speed}x")
                return True
            return False

    def get_state(self) -> ReplayState | None:
        """Get current replay state"""
        return self._replay_state

    def get_current_session(self) -> ReplaySession | None:
        """Get current session"""
        return self._current_session

    def list_sessions(self) -> list[ReplaySession]:
        """List all replay sessions"""
        return list(self._sessions.values())

    def get_session_events(self, session_id: str) -> list[dict[str, Any]]:
        """Get events for a session"""
        session = self._sessions.get(session_id)
        if not session:
            return []

        event_store = get_event_store()
        events = event_store.get_events_in_range(session.start_time, session.end_time)

        return [e.to_dict() for e in events]

    def _persist_session(self, session: ReplaySession) -> None:
        """Persist session to DB"""
        try:
            with get_connection(self.PERSISTENCE_PATH) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO replay_sessions
                    (session_id, start_time, end_time, market_data_path, events_path, status, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    session.session_id,
                    session.start_time,
                    session.end_time,
                    session.market_data_path,
                    session.events_path,
                    session.status,
                    session.created_at,
                ))
                conn.commit()
        except Exception as e:
            _log.error(f"Failed to persist session: {e} (type: {type(e).__name__})")


_replay_engine: ReplayEngine | None = None
_engine_lock = threading.RLock()


def get_replay_engine() -> ReplayEngine:
    """Get singleton replay engine"""
    global _replay_engine
    with _engine_lock:
        if _replay_engine is None:
            _replay_engine = ReplayEngine()
        return _replay_engine


__all__ = [
    "ReplaySession",
    "ReplayState",
    "ReplayEngine",
    "get_replay_engine",
]
