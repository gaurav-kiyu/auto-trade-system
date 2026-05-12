"""Tests for core.python_runtime."""

from __future__ import annotations

import threading

from core.python_runtime import ensure_supported_python, register_graceful_shutdown_signals


def test_register_graceful_shutdown_signals_registers():
    ev = threading.Event()
    register_graceful_shutdown_signals(ev)
    assert ev.is_set() is False


def test_ensure_supported_python_does_not_exit_on_current_interpreter():
    ensure_supported_python()
