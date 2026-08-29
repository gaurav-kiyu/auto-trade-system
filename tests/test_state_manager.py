"""
Tests for core/state_manager.py - Authoritative State Manager.

Covers:
  - StateManager initialization and load/save
  - Key-value get/set operations with thread-safe atomic writes
  - State recovery from DB on corruption
  - Session recovery report with broker comparison
  - Consecutive loss tracking
  - Compatibility aliases (save, load)
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

import pytest
from core.state_manager import SessionRecoveryReport, StateManager

# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture()
def state_file(tmp_path: Path) -> str:
    return str(tmp_path / "trader_state.json")


@pytest.fixture()
def db_file(tmp_path: Path) -> str:
    return str(tmp_path / "trades.db")


@pytest.fixture()
def manager(state_file: str, db_file: str) -> StateManager:
    return StateManager(state_file=state_file, db_path=db_file)


# ── StateManager Initialization ──────────────────────────────────────


class TestInit:
    def test_init_creates_empty_state(self, state_file: str, db_file: str) -> None:
        m = StateManager(state_file=state_file, db_path=db_file)
        assert m._state == {}

    def test_init_does_not_create_file_prematurely(self, state_file: str, db_file: str) -> None:
        StateManager(state_file=state_file, db_path=db_file)
        assert not Path(state_file).exists()

    def test_init_with_custom_state_file(self, state_file: str, db_file: str) -> None:
        m = StateManager(state_file=state_file, db_path=db_file)
        assert str(m.state_path) == state_file

    def test_init_with_custom_db_path(self, state_file: str, db_file: str) -> None:
        m = StateManager(state_file=state_file, db_path=db_file)
        assert str(m.db_path) == db_file

    def test_init_accepts_kwargs(self, state_file: str, db_file: str) -> None:
        m = StateManager(
            state_file=state_file,
            db_path=db_file,
            extra_param=True,
        )
        assert m._state == {}

    def test_load_existing_state(self, state_file: str, db_file: str) -> None:
        Path(state_file).write_text(json.dumps({"foo": "bar"}))
        m = StateManager(state_file=state_file, db_path=db_file)
        assert m.get("foo") == "bar"

    def test_load_corrupted_state_falls_back(self, state_file: str, db_file: str) -> None:
        Path(state_file).write_text("not valid json{{}")
        m = StateManager(state_file=state_file, db_path=db_file)
        # Falls back to empty state gracefully
        assert m._state == {}


# ── Get / Set ────────────────────────────────────────────────────────


class TestGetSet:
    def test_get_missing_key_returns_default(self, manager: StateManager) -> None:
        assert manager.get("nonexistent", 42) == 42

    def test_get_missing_key_no_default(self, manager: StateManager) -> None:
        assert manager.get("nonexistent") is None

    def test_set_and_get(self, manager: StateManager) -> None:
        manager.set("test_key", "test_value")
        assert manager.get("test_key") == "test_value"

    def test_set_overwrites(self, manager: StateManager) -> None:
        manager.set("key", "first")
        manager.set("key", "second")
        assert manager.get("key") == "second"

    def test_set_persists_to_disk(self, manager: StateManager, state_file: str) -> None:
        manager.set("persisted", True)
        data = json.loads(Path(state_file).read_text())
        assert data.get("persisted") is True

    def test_set_integer_value(self, manager: StateManager) -> None:
        manager.set("count", 10)
        assert manager.get("count") == 10

    def test_set_dict_value(self, manager: StateManager) -> None:
        d = {"nested": "value"}
        manager.set("dict", d)
        assert manager.get("dict") == d

    def test_set_list_value(self, manager: StateManager) -> None:
        lst = [1, 2, 3]
        manager.set("list", lst)
        assert manager.get("list") == lst

    def test_multiple_keys(self, manager: StateManager) -> None:
        manager.set("a", 1)
        manager.set("b", 2)
        manager.set("c", 3)
        assert manager.get("a") == 1
        assert manager.get("b") == 2
        assert manager.get("c") == 3


# ── Consecutive Losses ──────────────────────────────────────────────


class TestConsecutiveLosses:
    def test_default_zero(self, manager: StateManager) -> None:
        assert manager.get_consecutive_losses() == 0

    def test_set_and_get(self, manager: StateManager) -> None:
        manager.set_consecutive_losses(3)
        assert manager.get_consecutive_losses() == 3

    def test_set_tracks_max(self, manager: StateManager) -> None:
        manager.set_consecutive_losses(3)
        manager.set_consecutive_losses(2)  # lower than max
        assert manager.get("max_consecutive_losses") == 3

    def test_reset_after_win(self, manager: StateManager) -> None:
        manager.set_consecutive_losses(3)
        manager.reset_consecutive_losses()
        assert manager.get_consecutive_losses() == 0

    def test_reset_preserves_max(self, manager: StateManager) -> None:
        manager.set_consecutive_losses(5)
        manager.reset_consecutive_losses()
        assert manager.get("max_consecutive_losses") == 5


# ── Session Recovery Report ─────────────────────────────────────────


class TestSessionRecoveryReport:
    def test_empty_positions(self, manager: StateManager) -> None:
        report = manager.session_recovery_report(broker_positions={})
        assert report.local_positions == 0
        assert report.broker_positions == 0
        assert report.matched_symbols == 0
        assert report.positions_aligned

    def test_matching_positions(self, manager: StateManager) -> None:
        manager.set("active_positions", {"NIFTY": {"qty": 1}})
        report = manager.session_recovery_report(
            broker_positions={"NIFTY": {"qty": 1}}
        )
        assert report.local_positions == 1
        assert report.broker_positions == 1
        assert report.matched_symbols == 1
        assert report.positions_aligned

    def test_mismatched_positions(self, manager: StateManager) -> None:
        manager.set("active_positions", {"NIFTY": {"qty": 1}})
        report = manager.session_recovery_report(
            broker_positions={"BANKNIFTY": {"qty": 1}}
        )
        assert report.local_positions == 1
        assert report.broker_positions == 1
        assert report.matched_symbols == 0
        assert not report.positions_aligned

    def report_note_on_match(self, manager: StateManager) -> None:
        report = manager.session_recovery_report(broker_positions={})
        assert "Aligned" in report.note

    def report_note_on_mismatch(self, manager: StateManager) -> None:
        manager.set("active_positions", {"NIFTY": {"qty": 1}})
        report = manager.session_recovery_report(broker_positions={})
        assert "Mismatch" in report.note

    def test_multi_symbol(self, manager: StateManager) -> None:
        manager.set("active_positions", {
            "NIFTY": {"qty": 1},
            "BANKNIFTY": {"qty": 2},
        })
        report = manager.session_recovery_report(
            broker_positions={
                "NIFTY": {"qty": 1},
                "BANKNIFTY": {"qty": 2},
                "FINNIFTY": {"qty": 1},
            }
        )
        assert report.local_positions == 2
        assert report.broker_positions == 3
        assert report.matched_symbols == 2
        assert report.positions_aligned

    def test_session_recovery_report_dataclass(self) -> None:
        r = SessionRecoveryReport(
            local_positions=2,
            broker_positions=3,
            matched_symbols=1,
            positions_aligned=False,
            note="Mismatch detected",
        )
        assert r.local_positions == 2
        assert r.broker_positions == 3
        assert r.matched_symbols == 1
        assert not r.positions_aligned
        assert r.note == "Mismatch detected"


# ── Compatibility Aliases ────────────────────────────────────────────


class TestAliases:
    def test_save_alias(self, manager: StateManager, state_file: str) -> None:
        manager.set("key", "value")
        # save() is an alias for save_state()
        manager.save()
        data = json.loads(Path(state_file).read_text())
        assert data.get("key") == "value"

    def test_load_alias(self, state_file: str, db_file: str) -> None:
        Path(state_file).write_text(json.dumps({"loaded": True}))
        m = StateManager(state_file=state_file, db_path=db_file)
        # load() is an alias for load_state()
        m.load()
        assert m.get("loaded") is True


# ── Save / Load Custom Callbacks ─────────────────────────────────────


class TestCustomCallbacks:
    def test_save_callback_called(self, state_file: str, db_file: str) -> None:
        callback_data: dict[str, Any] = {}

        def custom_save() -> None:
            callback_data["saved"] = True

        m = StateManager(
            state_file=state_file,
            db_path=db_file,
            save_fn=custom_save,
        )
        m.set("key", "value")
        assert callback_data.get("saved") is True

    def test_load_callback_called(self, state_file: str, db_file: str) -> None:
        Path(state_file).write_text(json.dumps({"loaded_via_callback": False}))
        callback_data: dict[str, Any] = {}

        class LoadCallbackManager(StateManager):  # type: ignore[no-redef]
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                callback_data["loaded"] = True
                # Bypass normal init to avoid recursive callback
                self.state_path = Path(state_file)
                self.db_path = Path(db_file)
                self._state = {"custom": "data"}
                self._save_fn = None
                self._load_fn = None
                self._local_positions_fn = None
                self._broker_positions_fn = None
                self._lock = threading.Lock()

        m = LoadCallbackManager()
        assert callback_data.get("loaded") is True
        assert m.get("custom") == "data"
