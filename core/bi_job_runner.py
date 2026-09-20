"""Background execution and caching engine for heavy BI, security, and architecture analysis.

Guarantees that synchronous, CPU-intensive AST parsing, git log extraction,
and dependency tree construction NEVER execute directly on the FastAPI asyncio
event loop, preventing event loop starvation and HTTP freezes.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import threading
import time
from collections.abc import Callable
from typing import Any

_log = logging.getLogger(__name__)


class BIJobRunner:
    """Thread-pool isolated executor with TTL caching for expensive analysis workloads."""

    _instance: BIJobRunner | None = None
    _lock = threading.Lock()

    def __init__(self, max_workers: int = 2) -> None:
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="bi_isolated_worker",
        )
        self._cache: dict[str, dict[str, Any]] = {}
        self._cache_lock = threading.Lock()
        self._running_jobs: dict[str, float] = {}

    @classmethod
    def get_instance(cls) -> BIJobRunner:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def get_cached(self, key: str, max_age: float = 300.0) -> Any | None:
        """Retrieve cached result if still within max_age seconds."""
        with self._cache_lock:
            entry = self._cache.get(key)
            if entry and (time.time() - entry["timestamp"]) <= max_age:
                return entry["data"]
        return None

    def set_cached(self, key: str, data: Any) -> None:
        """Store result in memory with current timestamp."""
        with self._cache_lock:
            self._cache[key] = {"data": data, "timestamp": time.time()}

    def clear_cache(self, key: str | None = None) -> None:
        """Clear specific key or entire cache."""
        with self._cache_lock:
            if key:
                self._cache.pop(key, None)
            else:
                self._cache.clear()

    async def execute_isolated(
        self,
        key: str,
        compute_fn: Callable[[], Any],
        max_age: float = 300.0,
        force_refresh: bool = False,
    ) -> Any:
        """Execute compute_fn in isolated thread pool with caching.

        Never blocks the calling asyncio event loop.
        """
        if not force_refresh:
            cached = self.get_cached(key, max_age=max_age)
            if cached is not None:
                return cached

        # Check if already running to prevent concurrent duplicate runs
        with self._cache_lock:
            is_running = key in self._running_jobs
            if not is_running:
                self._running_jobs[key] = time.time()

        loop = asyncio.get_running_loop()

        def _worker_wrapper() -> Any:
            try:
                t0 = time.perf_counter()
                result = compute_fn()
                elapsed = time.perf_counter() - t0
                _log.info("[BI-JOB] Completed '%s' in %.2fs (off-loop)", key, elapsed)
                self.set_cached(key, result)
                return result
            finally:
                with self._cache_lock:
                    self._running_jobs.pop(key, None)

        if is_running:
            # Another worker is already calculating this. Return stale data if available
            with self._cache_lock:
                stale = self._cache.get(key)
                if stale:
                    return stale["data"]

            # Wait for the running job to complete without spawning a second thread
            max_wait = 30.0
            waited = 0.0
            while waited < max_wait:
                await asyncio.sleep(0.5)
                waited += 0.5
                with self._cache_lock:
                    if key not in self._running_jobs:
                        cached = self._cache.get(key)
                        return cached["data"] if cached else None
            return None
        else:
            return await loop.run_in_executor(self._executor, _worker_wrapper)
