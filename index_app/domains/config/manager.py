"""Config Manager — runtime configuration lifecycle for ``index_trader.py``.

Provides ``ConfigManager`` which wraps a ``dict[str, Any]`` config and
handles hot-reload, key access with defaults, and optional validation
callbacks.  Thread-safe via ``RLock``.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable

log = logging.getLogger(__name__)

# Type alias for a config-change observer
ConfigObserver = Callable[[str, Any, Any], None]  # key, old_value, new_value


class ConfigManager:
    """Thread-safe wrapper around a configuration dictionary.

    Parameters
    ----------
    initial_cfg:
        Initial config dict (e.g. loaded by ``ConfigLoader``).
    name:
        Optional label used in log messages to identify this manager.

    Thread safety
    -------------
    All public methods acquire ``_lock`` (``RLock``) so the manager is safe to
    share across threads.
    """

    def __init__(self, initial_cfg: dict[str, Any] | None = None, name: str = "") -> None:
        self._cfg: dict[str, Any] = dict(initial_cfg) if initial_cfg else {}
        self._name = name or "config-manager"
        self._lock = threading.RLock()
        self._observers: list[ConfigObserver] = []

    # ── Read ──────────────────────────────────────────────────────────────────

    def get(self, key: str, default: Any = None) -> Any:
        """Return the value for *key*, or *default* if absent."""
        with self._lock:
            return self._cfg.get(key, default)

    def get_int(self, key: str, default: int = 0) -> int:
        """Return the value for *key* coerced to ``int``."""
        return int(self.get(key, default))

    def get_float(self, key: str, default: float = 0.0) -> float:
        """Return the value for *key* coerced to ``float``."""
        return float(self.get(key, default))

    def get_bool(self, key: str, default: bool = False) -> bool:
        """Return the value for *key* coerced to ``bool``."""
        return bool(self.get(key, default))

    def get_str(self, key: str, default: str = "") -> str:
        """Return the value for *key* coerced to ``str``."""
        return str(self.get(key, default))

    def all(self) -> dict[str, Any]:
        """Return a shallow copy of the full configuration dict."""
        with self._lock:
            return dict(self._cfg)

    def keys(self) -> set[str]:
        """Return the set of all keys."""
        with self._lock:
            return set(self._cfg.keys())

    # ── Write ─────────────────────────────────────────────────────────────────

    def update(self, cfg: dict[str, Any]) -> None:
        """Merge *cfg* into the current configuration and notify observers."""
        with self._lock:
            for key, value in cfg.items():
                old = self._cfg.get(key, _SENTINEL)
                self._cfg[key] = value
                if old is not _SENTINEL:
                    self._notify(key, old, value)
            log.debug("[%s] config updated (%d keys merged)", self._name, len(cfg))

    def set(self, key: str, value: Any) -> None:
        """Set a single key and notify observers."""
        with self._lock:
            old = self._cfg.get(key, _SENTINEL)
            self._cfg[key] = value
            if old is not _SENTINEL:
                self._notify(key, old, value)

    def replace(self, cfg: dict[str, Any]) -> None:
        """Replace the entire configuration and notify observers."""
        with self._lock:
            old_cfg = dict(self._cfg)
            self._cfg = dict(cfg)
            # Notify for all keys that existed in both or changed
            all_keys = set(old_cfg) | set(cfg)
            for key in sorted(all_keys):
                old_val = old_cfg.get(key, _SENTINEL)
                new_val = cfg.get(key, _SENTINEL)
                if old_val is not _SENTINEL and new_val is not _SENTINEL:
                    if old_val != new_val:
                        self._notify(key, old_val, new_val)

    # ── Observers ─────────────────────────────────────────────────────────────

    def observe(self, observer: ConfigObserver) -> Callable[[], None]:
        """Register an observer callback.

        Returns a callable that removes the observer when invoked.
        """
        with self._lock:
            self._observers.append(observer)
        # Return a removal function
        def _remove() -> None:
            with self._lock:
                if observer in self._observers:
                    self._observers.remove(observer)
        return _remove

    # ── Hot-reload ────────────────────────────────────────────────────────────

    def hot_reload(self, new_cfg: dict[str, Any]) -> dict[str, Any]:
        """Hot-reload configuration.

        Replaces the current config, logs the change, and returns a status dict.
        """
        keys_before = len(self._cfg)
        self.replace(new_cfg)
        log.info("[%s] hot-reload: %d keys → %d keys", self._name, keys_before, len(new_cfg))
        return {"status": "ok", "keys_before": keys_before, "keys_after": len(new_cfg)}

    # ── Internal ──────────────────────────────────────────────────────────────

    def _notify(self, key: str, old: Any, new: Any) -> None:
        """Notify all observers about a config change."""
        for obs in self._observers:
            try:
                obs(key, old, new)
            except (ValueError, TypeError, KeyError, AttributeError, IndexError, OSError) as exc:
                log.warning("[%s] observer failed for key '%s': %s", self._name, key, exc)

    def __repr__(self) -> str:
        return f"<ConfigManager '{self._name}' keys={len(self._cfg)}>"


# Internal sentinel to distinguish "key absent" from "value is None"
_SENTINEL = object()


__all__ = [
    "ConfigManager",
    "ConfigObserver",
]
