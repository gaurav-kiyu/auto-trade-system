"""Shared process startup: graceful shutdown signals + supported CPython range (index + stock)."""

from __future__ import annotations

import signal
import sys
import threading


def register_graceful_shutdown_signals(shutdown_event: threading.Event) -> None:
    """SIGINT/SIGTERM set the event; register before blocking I/O (RCA-124 style)."""
    signal.signal(signal.SIGTERM, lambda s, f: shutdown_event.set())
    signal.signal(signal.SIGINT, lambda s, f: shutdown_event.set())


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
