"""
Application State Manager.

Handles JSON-based state persistence for the trading bot.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

from core.datetime_ist import now_ist


class StatePersistenceManager:
    def __init__(self, file_path: str):
        self.file_path = Path(file_path)
        self._lock = threading.RLock()
        self._is_connected = False

    def connect(self) -> bool:
        try:
            with self._lock:
                self.file_path.parent.mkdir(parents=True, exist_ok=True)
                if not self.file_path.exists():
                    self._write_state({})
                self._is_connected = True
                return True
        except (OSError, PermissionError):
            return False

    def disconnect(self) -> None:
        with self._lock:
            self._is_connected = False

    def save_state(self, state: dict[str, Any]) -> bool:
        try:
            with self._lock:
                state_with_metadata = {
                    **state,
                    '_metadata': {
                        'saved_at': now_ist().isoformat(),
                        'version': '2.45'
                    }
                }
                self._write_state(state_with_metadata)
                return True
        except (OSError, TypeError, ValueError):
            return False

    def load_state(self) -> dict[str, Any] | None:
        try:
            with self._lock:
                if not self.file_path.exists():
                    return None
                with open(self.file_path, encoding='utf-8') as f:
                    state = json.load(f)
                if state and '_metadata' in state:
                    state_copy = state.copy()
                    del state_copy['_metadata']
                    return state_copy
                return state
        except (OSError, json.JSONDecodeError, KeyError):
            return None

    def delete_state(self) -> bool:
        try:
            with self._lock:
                if self.file_path.exists():
                    self.file_path.unlink()
                self._is_connected = False
                return True
        except (OSError, PermissionError):
            return False

    def health_check(self) -> dict[str, Any]:
        file_exists = self.file_path.exists()
        return {
            'status': 'healthy' if file_exists else 'unhealthy',
            'connected': self._is_connected,
            'backend': 'JSONFileAdapter'
        }

    def _write_state(self, state: dict[str, Any]) -> None:
        temp_path = self.file_path.with_suffix('.tmp')
        try:
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(state, f, indent=2, default=str, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_path, self.file_path)
        except (OSError, json.JSONDecodeError, TypeError):
            if temp_path.exists():
                temp_path.unlink(missing_ok=True)
            raise
