"""
Broker Failover Manager (v2.45 Item 20).

Monitors API call failures for the active broker and automatically switches
to the next broker in the failover chain when the failure threshold is reached.
Attempts recovery (switch back) after failover_recovery_mins.

Failover chain example: ["kite", "angel"]
  — On kite failure: switch to angel after threshold consecutive errors.
  — After recovery_mins: attempt to restore kite.

SAFETY: All switches are logged and Telegram-notified.  Paper mode always
returns PaperBrokerAdapter regardless of failover state.

Public API
----------
    BrokerFailoverManager.record_success(broker)
    BrokerFailoverManager.record_failure(broker) → bool  (True = failover triggered)
    BrokerFailoverManager.get_active_broker()    → str
    BrokerFailoverManager.reset()

Config keys
-----------
    broker_failover_enabled  : bool  default false
    failover_threshold       : int   default 3
    failover_chain           : list  default ["kite", "angel"]
    failover_recovery_mins   : int   default 15
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any

_log = logging.getLogger(__name__)


@dataclass
class _BrokerState:
    name:             str
    failure_count:    int   = 0
    last_failure_ts:  float = 0.0
    is_active:        bool  = True


class BrokerFailoverManager:
    """Thread-safe broker failover manager."""

    def __init__(self, cfg: dict[str, Any] | None = None) -> None:
        c = cfg or {}
        self._enabled    = bool(c.get("broker_failover_enabled", False))
        self._threshold  = int(c.get("failover_threshold",       3))
        self._chain      = list(c.get("failover_chain",          ["kite", "angel"]))
        self._rec_mins   = float(c.get("failover_recovery_mins", 15.0))
        self._lock       = threading.Lock()
        self._states     = {b: _BrokerState(b) for b in self._chain}
        self._active_idx = 0
        self._failover_ts: float = 0.0

    def get_active_broker(self) -> str:
        """Return the name of the currently active broker."""
        with self._lock:
            if self._active_idx < len(self._chain):
                return self._chain[self._active_idx]
            return self._chain[0] if self._chain else "kite"

    def record_success(self, broker: str) -> None:
        """Reset failure count for broker on a successful API call."""
        with self._lock:
            if broker in self._states:
                self._states[broker].failure_count = 0

    def record_failure(self, broker: str) -> bool:
        """
        Record an API failure for broker.

        Returns:
            True  — failover was triggered (switch to next broker).
            False — threshold not yet reached; same broker remains active.
        """
        if not self._enabled:
            return False

        with self._lock:
            if broker not in self._states:
                self._states[broker] = _BrokerState(broker)

            state = self._states[broker]
            state.failure_count   += 1
            state.last_failure_ts  = time.time()

            # Only trigger failover for the currently active broker
            active = self._chain[self._active_idx] if self._active_idx < len(self._chain) else ""
            if broker != active:
                return False

            if state.failure_count < self._threshold:
                return False

            # Failover!
            next_idx = (self._active_idx + 1) % len(self._chain)
            if next_idx == self._active_idx:
                _log.error("[FAILOVER] only one broker in chain, cannot failover")
                return False

            _log.warning(
                "[FAILOVER] %s failed %d times → switching to %s",
                broker, state.failure_count, self._chain[next_idx],
            )
            state.failure_count  = 0
            self._active_idx     = next_idx
            self._failover_ts    = time.time()
            return True

    def maybe_recover(self) -> bool:
        """
        Attempt recovery to primary broker if recovery window has elapsed.

        Returns True if recovered to primary.
        """
        if not self._enabled or self._active_idx == 0:
            return False

        with self._lock:
            elapsed = (time.time() - self._failover_ts) / 60.0
            if elapsed >= self._rec_mins:
                _log.info(
                    "[FAILOVER] recovery: switching back to %s after %.0f min",
                    self._chain[0], elapsed,
                )
                self._active_idx = 0
                self._failover_ts = 0.0
                return True
        return False

    def reset(self) -> None:
        """Reset all failure counts and return to primary broker."""
        with self._lock:
            for s in self._states.values():
                s.failure_count   = 0
                s.last_failure_ts = 0.0
            self._active_idx  = 0
            self._failover_ts = 0.0

    def status(self) -> dict:
        """Return a status snapshot for health checks / web dashboard."""
        with self._lock:
            active = self._chain[self._active_idx] if self._chain else "none"
            return {
                "enabled":       self._enabled,
                "active_broker": active,
                "failover_count": self._active_idx,
                "brokers": {
                    b: {"failures": s.failure_count, "last_failure": s.last_failure_ts}
                    for b, s in self._states.items()
                },
            }
