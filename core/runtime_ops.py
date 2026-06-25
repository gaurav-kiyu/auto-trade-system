"""Shared runtime helpers: circuit breaker, perf timings, manual kill-file check (index + stock)."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterable
from pathlib import Path


__all__ = [
    "CircuitBreaker",
    "PerfAccumulator",
    "check_manual_kill_switch",
]

class CircuitBreaker:
    """Rolling-window failure counter; trips and logs when threshold is hit."""

    def __init__(self, threshold: int, window_sec: float, log_fn: Callable[[str], None]) -> None:
        self._threshold = int(threshold)
        self._window = float(window_sec)
        self._log = log_fn
        self._lock = threading.RLock()
        self._failures: list[tuple[float, str]] = []
        self._tripped = False
        self._trip_ts = 0.0

    def record(self, source: str) -> None:
        now = time.time()
        with self._lock:
            self._failures.append((now, source))
            cutoff = now - self._window
            self._failures[:] = [f for f in self._failures if f[0] > cutoff]
            if len(self._failures) >= self._threshold and not self._tripped:
                self._tripped = True
                self._trip_ts = now
                self._log(
                    f"[CIRCUIT BREAKER] TRIPPED - {len(self._failures)} failures in {self._window}s from: "
                    f"{set(s for _, s in self._failures)}"
                )

    def ok(self) -> bool:
        if not self._tripped:
            return True
        now = time.time()
        with self._lock:
            cutoff = now - self._window
            self._failures[:] = [f for f in self._failures if f[0] > cutoff]
            if len(self._failures) < self._threshold // 2:
                self._tripped = False
                self._trip_ts = 0.0
                self._log("[CIRCUIT BREAKER] RECOVERED - failures subsided")
                return True
        return False

    def status(self) -> str:
        with self._lock:
            if self._tripped:
                return f"TRIPPED ({len(self._failures)} failures)"
        return "OK"


class PerfAccumulator:
    """Thread-safe stage → ms samples with trim/summary matching the trader scripts."""

    def __init__(self, initial_stages: Iterable[str] | None = None) -> None:
        self._lock = threading.RLock()
        if initial_stages:
            self._timings: dict[str, list[float]] = {k: [] for k in initial_stages}
        else:
            self._timings = {}

    def record(self, stage: str, elapsed_ms: float) -> None:
        with self._lock:
            q = self._timings.setdefault(stage, [])
            q.append(elapsed_ms)
            if len(q) > 200:
                del q[:100]

    def summary(self) -> str:
        with self._lock:
            parts: list[str] = []
            for stage, vals in self._timings.items():
                if not vals:
                    continue
                avg = sum(vals) / len(vals)
                mx = max(vals)
                sv = sorted(vals)
                n = len(sv)
                p95 = sv[int(0.95 * n)] if n >= 5 else mx
                p99 = sv[int(0.99 * n)] if n >= 20 else mx
                parts.append(f"{stage}:avg={round(avg)}ms,p95={round(p95)}ms,p99={round(p99)}ms,max={round(mx)}ms")
        return " | ".join(parts) if parts else "No data"

    def any_stage_len_over(self, n: int) -> bool:
        with self._lock:
            return any(len(v) > n for v in self._timings.values())

    def trim_queues_over(self, over: int = 100, keep_last: int = 50) -> None:
        with self._lock:
            for k in self._timings:
                if len(self._timings[k]) > over:
                    self._timings[k] = self._timings[k][-keep_last:]

    def clear_all_stages(self) -> None:
        with self._lock:
            self._timings.update({k: [] for k in self._timings})


def check_manual_kill_switch(
    kill_file: str | Path,
    *,
    halt_event: threading.Event,
    trip: Callable[[str], None],
) -> bool:
    """If kill file exists, call ``trip`` once until halt is set; return True if file exists."""
    p = Path(kill_file)
    if p.exists():
        if not halt_event.is_set():
            trip(f"Manual kill-switch file '{p}' detected")
        return True
    return False
