"""Shared process startup: graceful shutdown signals + supported CPython range (index + stock)."""

from __future__ import annotations

import atexit
import logging
import signal
import sys
import threading
from collections.abc import Callable

log = logging.getLogger(__name__)

_shutdown_callbacks: list[Callable[[], None]] = []
_shutdown_in_progress = False
_shutdown_lock = threading.Lock()


def _reset_shutdown_state_for_testing() -> None:
    """Reset module-level shutdown state (test helper only)."""
    global _shutdown_callbacks, _shutdown_in_progress
    _shutdown_callbacks = []
    _shutdown_in_progress = False


def register_graceful_shutdown_signals(shutdown_event: threading.Event) -> None:
    """SIGINT/SIGTERM set the event AND execute shutdown callbacks asynchronously.

    Calls execute_shutdown() via a daemon thread to avoid deadlock: the signal
    handler runs in the interrupted thread's context and may try to acquire
    locks held by that thread. A fresh daemon thread has no such conflict.
    Also relies on the atexit-registered execute_shutdown() (see
    setup_graceful_shutdown) which runs on normal interpreter exit.
    """
    def _signal_handler(s, f):
        if not shutdown_event.is_set():
            shutdown_event.set()
            threading.Thread(target=execute_shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)


def register_shutdown_callback(cb: Callable[[], None]) -> None:
    """Register a callback to be invoked during graceful shutdown.

    Callbacks are invoked in LIFO order. Common uses:
      - flush TradeJournal thread pool
      - save trader state
      - close database connections
    """
    _shutdown_callbacks.append(cb)


def execute_shutdown() -> None:
    """Execute all registered shutdown callbacks exactly once (thread-safe)."""
    global _shutdown_in_progress
    with _shutdown_lock:
        if _shutdown_in_progress:
            return
        _shutdown_in_progress = True

    log.info("Graceful shutdown: flushing %d registered callbacks...", len(_shutdown_callbacks))
    for cb in reversed(_shutdown_callbacks):
        try:
            cb()
        except Exception as e:
            log.error("Shutdown callback failed: %s: %s", getattr(cb, "__name__", "?"), e)
    log.info("Graceful shutdown complete.")


def setup_graceful_shutdown(shutdown_event: threading.Event | None = None) -> threading.Event:
    """One-call setup: register signals + atexit handler.

    Returns the shutdown Event that gets set on SIGTERM/SIGINT.
    """
    if shutdown_event is None:
        shutdown_event = threading.Event()

    register_graceful_shutdown_signals(shutdown_event)
    atexit.register(execute_shutdown)
    return shutdown_event


def ensure_supported_python(
    low: tuple[int, int] = (3, 10),
    high_exclusive: tuple[int, int] = (3, 20),
) -> None:
    """Exit if interpreter is outside [low, high_exclusive). Default: 3.10 through 3.19."""
    vi = sys.version_info
    if not (low <= (vi.major, vi.minor) < high_exclusive):
        hi_minor = high_exclusive[1] - 1
        print(
            f"[ERROR] Python {low[0]}.{low[1]}–{high_exclusive[0]}.{hi_minor} supported. "
            f"Found:{vi.major}.{vi.minor}"
        )
        print("Install: pyenv install 3.12.7 && pyenv local 3.12.7")
        sys.exit(1)
