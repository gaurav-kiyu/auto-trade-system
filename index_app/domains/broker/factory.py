"""Broker Factory — extracted from index_trader.py ``_make_broker()``.

Provides ``BrokerFactory`` class and convenience functions for creating
broker adapter instances based on runtime configuration and execution mode.

Decouples broker selection logic from the trading orchestration monolith.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable

from core.datetime_ist import now_ist
from core.safety_state import is_hard_halted, is_shutting_down

log = logging.getLogger(__name__)


class BrokerFactory:
    """Creates broker adapter instances based on configuration.

    Responsibilities
    ----------------
    * Validate broker driver selection against execution mode flags.
    * Fall back to paper mode when real broker is unavailable or unsafe.
    * Delegate to ``core.adapters.broker_adapters.create_broker_adapter_with_runtime_context``
      for final adapter construction.

    Thread safety
    -------------
    Instances are stateless after construction — safe to share across threads.
    """

    def __init__(
        self,
        cfg: dict[str, Any],
        index_map: dict[str, Any],
        manual_signals_only: bool,
        broker_api_enabled: bool,
        paper_mode: bool,
        execution_mode: str,
        circuit_breaker: Any = None,
    ) -> None:
        self._cfg = cfg
        self._index_map = index_map
        self._manual_signals_only = manual_signals_only
        self._broker_api_enabled = broker_api_enabled
        self._paper_mode = paper_mode
        self._execution_mode = execution_mode
        self._circuit_breaker = circuit_breaker

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create_broker(
        self,
        *,
        now_fn: Callable[[], Any] | None = None,
        log_fn: Callable[[str], None] | None = None,
        send_fn: Callable[[str], None] | None = None,
    ) -> Any:
        """Create a broker adapter based on the current configuration.

        Parameters
        ----------
        now_fn:
            Function returning current IST datetime (defaults to ``core.datetime_ist.now_ist``).
        log_fn:
            Logging function (defaults to module logger).
        send_fn:
            Notification send function (defaults to no-op).

        Returns
        -------
        A ``BrokerAdapter`` wrapper around the chosen broker implementation.
        Falls back to ``PaperBrokerAdapter`` when real broker is unavailable.
        """
        from core.adapters.broker_adapters import BrokerAdapter, PaperBrokerAdapter

        _now_fn = now_fn or now_ist
        # Guard: log_fn may be a Logger instance instead of a callable
        if log_fn is None:
            _log_fn = lambda msg: log.info("%s", msg)
        elif callable(log_fn):
            _log_fn = log_fn
        else:
            _log_fn = lambda msg: log.info("%s", msg)
            log.warning("[BROKER_CFG] log_fn is not callable (type=%s), using default", type(log_fn).__name__)
        _send_fn = send_fn or (lambda msg, **kw: None)

        driver = str(self._cfg.get("BROKER_DRIVER", "PAPER")).upper()
        is_real_driver = driver not in ("PAPER", "SIM", "TEST", "")

        # ── Guard: Real driver + safe-mode flags = force paper ────────────────
        if is_real_driver and (self._manual_signals_only or not self._broker_api_enabled or self._paper_mode):
            _log_fn(
                f"[BROKER_CFG] BROKER_DRIVER={driver} but "
                f"MANUAL_SIGNALS_ONLY={self._manual_signals_only}, "
                f"BROKER_API_ENABLED={self._broker_api_enabled}, "
                f"PAPER_MODE={self._paper_mode} - forcing PAPER adapter"
            )
            return BrokerAdapter(PaperBrokerAdapter())

        # ── Guard: Manual / signal-only modes always use paper ────────────────
        if self._manual_signals_only or self._execution_mode.upper() in (
            "MANUAL", "MANUAL_ONLY", "SIGNAL_ONLY", "SIGNALS_ONLY",
        ):
            return BrokerAdapter(PaperBrokerAdapter())

        # ── Guard: Broker API disabled or paper mode ──────────────────────────
        if not (self._broker_api_enabled and not self._paper_mode):
            return BrokerAdapter(PaperBrokerAdapter())

        # ── Attempt real broker construction ──────────────────────────────────
        try:
            from core.adapters.broker_adapters import create_broker_adapter_with_runtime_context

            return create_broker_adapter_with_runtime_context(
                cfg=self._cfg,
                index_map=self._index_map,
                driver=driver,
                broker_api_enabled=self._broker_api_enabled,
                paper_mode=self._paper_mode,
                manual_signals_only=self._manual_signals_only,
                execution_mode=self._execution_mode,
                now_fn=_now_fn,
                log_fn=_log_fn,
                send_fn=_send_fn,
                shutdown_is_set_fn=is_shutting_down,
                hard_halt_is_set_fn=is_hard_halted,
                sleep_fn=lambda secs: time.sleep(secs),
                broker_wait_poll_sec=float(self._cfg.get("BROKER_WAIT_POLL_SEC", 1.0)),
                expiry_str_fn=lambda s: s,
                circuit_breaker=self._circuit_breaker,
            )
        except (ValueError, TypeError, OSError, ConnectionError) as exc:
            _log_fn(f"[BROKER] Real broker adapter construction FAILED: {exc} - FALLING BACK to paper mode")
            _send_fn(f"[BROKER] Real broker FAILED: {exc}. Falling back to paper mode.", critical=True)
            return BrokerAdapter(PaperBrokerAdapter())


# ==============================================================================
# Convenience function — direct replacement for inline _make_broker()
# ==============================================================================


def make_broker(
    cfg: dict[str, Any],
    index_map: dict[str, Any],
    *,
    manual_signals_only: bool = True,
    broker_api_enabled: bool = False,
    paper_mode: bool = True,
    execution_mode: str = "MANUAL",
    circuit_breaker: Any = None,
    now_fn: Callable[[], Any] | None = None,
    log_fn: Callable[[str], None] | None = None,
    send_fn: Callable[[str], None] | None = None,
) -> Any:
    """One-shot broker creation (replaces ``_make_broker()``).

    Parameters match the module-level globals in ``index_trader.py``.
    See ``BrokerFactory.create_broker()`` for details.
    """
    factory = BrokerFactory(
        cfg=cfg,
        index_map=index_map,
        manual_signals_only=manual_signals_only,
        broker_api_enabled=broker_api_enabled,
        paper_mode=paper_mode,
        execution_mode=execution_mode,
        circuit_breaker=circuit_breaker,
    )
    return factory.create_broker(now_fn=now_fn, log_fn=log_fn, send_fn=send_fn)


__all__ = [
    "BrokerFactory",
    "make_broker",
]
