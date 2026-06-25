"""
Compatibility interface for index_trader: a thin read-only API that exposes
signals, state export, and health-check endpoints for external tools.

This module is intended to be imported by legacy scripts that call functions
from `index_app.index_trader` and expects the same function names. The heavy
logic lives in DI-managed services registered in `index_app.index_trader._setup_di_container()`.

Public API:
- start_trader(): Start main trader loop (returns a controller object)
- get_state_snapshot(): Return current trader state (safe, read-only dict)
- generate_signal_snapshot(): Run a single scan and return signals
- health_check(): Return dict with health metrics

This shim will not perform writes or mutate config. It obtains service
instances from the DI container and calls read-only methods on them.
"""
from __future__ import annotations

from typing import Any

# Lazy import - resolved inside _ensure_initialized to break circular dependency


__all__ = [
    "generate_signal_snapshot",
    "get_state_snapshot",
    "health_check",
    "start_trader",
]

_container = None
_setup_di_container = None

# Ensure DI container is initialized lazily
_initialized = False


def _ensure_initialized() -> None:
    global _initialized, _container, _setup_di_container
    if not _initialized:
        from index_app.index_trader import container as _c, setup_di_container as _s
        _container = _c
        _setup_di_container = _s
        __setup_di_container()
        _initialized = True


def start_trader(*, paper: bool = True) -> Any:
    """Return a controller object that allows read-only interrogation.

    This does NOT start background threads or execute live orders. It returns
    an object exposing the public read-only methods of services for external
    monitoring or testing.
    """
    _ensure_initialized()
    # Build a lightweight controller exposing read-only methods
    exec_svc = _container.resolve("ExecutionPort")
    risk_svc = _container.resolve("RiskPort")
    persist = _container.resolve("PersistencePort")

    class Controller:
        def get_positions(self) -> list[dict[str, Any]]:
            return getattr(exec_svc, "list_positions", lambda: [])()

        def get_state(self) -> dict[str, Any]:
            return getattr(persist, "export_state", lambda: {})()

        def scan_signals(self) -> list[dict[str, Any]]:
            return getattr(exec_svc, "scan_and_score", lambda: [])()

        def health(self) -> dict[str, Any]:
            hb = {}
            for svc_name, svc in ("execution", exec_svc), ("risk", risk_svc):
                try:
                    hb[svc_name] = getattr(svc, "health_check", lambda: {"ok": True})()
                except Exception as e:
                    hb[svc_name] = {"ok": False, "error": str(e)}
            return hb

    return Controller()


def get_state_snapshot() -> dict[str, Any]:
    _ensure_initialized()
    persist = _container.resolve("PersistencePort")
    return getattr(persist, "export_state", lambda: {})()


def generate_signal_snapshot() -> list[dict[str, Any]]:
    _ensure_initialized()
    exec_svc = _container.resolve("ExecutionPort")
    return getattr(exec_svc, "scan_and_score", lambda: [])()


def health_check() -> dict[str, Any]:
    _ensure_initialized()
    return start_trader().health()
