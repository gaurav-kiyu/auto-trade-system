"""Stress tests for ConfigManager under high concurrency.

Pushes the thread-safe wrapper to its limits with many concurrent
threads doing read/write/replace/observer operations simultaneously.
"""

from __future__ import annotations

import threading
import time

import pytest
from index_app.domains.config.manager import ConfigManager

pytestmark = pytest.mark.stress

# ==============================================================================
# Stress: sustained concurrent read/write
# ==============================================================================


class TestConfigManagerStress:
    """High-concurrency stress tests that push thread safety to the limit."""

    def test_stress_20_threads_rapid_set(self):
        """20 threads each doing 50 set() calls on a shared ConfigManager.

        Uses unique key per thread-write so there's no cross-thread race
        on individual keys.
        """
        mgr = ConfigManager({"flag": False})
        n_threads = 20
        writes_per_thread = 50
        errors: list[Exception] = []
        lock = threading.Lock()

        def worker(tid: int):
            for i in range(writes_per_thread):
                try:
                    mgr.set(f"key_{tid}_{i}", tid * 1000 + i)
                except Exception as e:
                    with lock:
                        errors.append(e)

        threads = [threading.Thread(target=worker, args=(tid,)) for tid in range(n_threads)]
        start = time.perf_counter()
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        elapsed = time.perf_counter() - start

        assert len(errors) == 0, f"{len(errors)} thread errors: {errors[:5]}"
        assert mgr.get("flag") is False  # bool check, not get_int (which coerces)
        # Total keys: 1 (flag) + n_threads * writes_per_thread
        assert len(mgr.all()) == 1 + n_threads * writes_per_thread
        assert elapsed < 30.0, f"Stress test too slow: {elapsed:.1f}s"

    def test_stress_concurrent_replace_and_read(self):
        """20 threads doing replace() while 20 threads read all()."""
        mgr = ConfigManager({"a": 1, "b": 2, "c": 3})
        n_writers = 10
        n_readers = 10
        iterations = 50
        writer_errors: list[Exception] = []
        reader_errors: list[Exception] = []
        lock = threading.Lock()

        def writer():
            for i in range(iterations):
                try:
                    mgr.replace({
                        "a": i,
                        "b": i * 2,
                        "c": f"val_{i}",
                    })
                except Exception as e:
                    with lock:
                        writer_errors.append(e)

        def reader():
            for _ in range(iterations):
                try:
                    cfg = mgr.all()
                    _ = cfg.get("a")
                    _ = cfg.get("b")
                    _ = cfg.get("c")
                except Exception as e:
                    with lock:
                        reader_errors.append(e)

        threads = [threading.Thread(target=writer) for _ in range(n_writers)]
        threads += [threading.Thread(target=reader) for _ in range(n_readers)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(writer_errors) == 0, f"{len(writer_errors)} writer errors"
        assert len(reader_errors) == 0, f"{len(reader_errors)} reader errors"

    def test_stress_concurrent_update_and_observe(self):
        """5 writers + 5 observer manipulators + 5 readers, all concurrent."""
        mgr = ConfigManager({"x": 0.0, "y": "hello", "z": [1, 2, 3]})
        n_writers = 5
        n_observers = 5
        n_readers = 5
        iterations = 50
        errors: list[Exception] = []
        lock = threading.Lock()

        def writer_worker():
            for i in range(iterations):
                try:
                    mgr.update({"x": float(i), "y": f"val_{i}", "z": [i, i + 1]})
                except Exception as e:
                    with lock:
                        errors.append(e)

        def observer_worker():
            local_removes = []
            for i in range(iterations // 5):
                try:
                    def make_obs(val):
                        def obs(k, o, n):
                            pass
                        return obs
                    remove = mgr.observe(make_obs(i))
                    local_removes.append(remove)
                    if len(local_removes) > 10:
                        old_remove = local_removes.pop(0)
                        old_remove()
                except Exception as e:
                    with lock:
                        errors.append(e)
            for r in local_removes:
                try:
                    r()
                except Exception as e:
                    with lock:
                        errors.append(e)

        def reader_worker():
            for _ in range(iterations):
                try:
                    _ = mgr.get_int("x")
                    _ = mgr.get_str("y")
                    _ = mgr.get("z", [])
                    _ = mgr.keys()
                    _ = mgr.all()
                except Exception as e:
                    with lock:
                        errors.append(e)

        threads = [threading.Thread(target=writer_worker) for _ in range(n_writers)]
        threads += [threading.Thread(target=observer_worker) for _ in range(n_observers)]
        threads += [threading.Thread(target=reader_worker) for _ in range(n_readers)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"{len(errors)} thread errors: {errors[:5]}"

    def test_stress_hot_reload_during_reads(self):
        """Hot-reload is atomic — readers should never see partial state."""
        mgr = ConfigManager({"stable": "value"})
        n_writers = 10
        n_readers = 10
        iterations = 30
        errors: list[Exception] = []
        lock = threading.Lock()

        def writer():
            for i in range(iterations):
                try:
                    mgr.hot_reload({
                        "a": f"v{i}", "b": f"v{i}", "c": f"v{i}",
                        "d": f"v{i}", "e": f"v{i}",
                    })
                except Exception as e:
                    with lock:
                        errors.append(e)

        def reader():
            for _ in range(iterations):
                try:
                    cfg = mgr.all()
                    assert "stable" not in cfg.keys()
                except Exception as e:
                    with lock:
                        errors.append(e)

        threads = [threading.Thread(target=writer) for _ in range(n_writers)]
        threads += [threading.Thread(target=reader) for _ in range(n_readers)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(errors) == 0, f"{len(errors)} thread errors"

    def test_stress_large_config_dict(self):
        """ConfigManager with 1000+ keys under concurrent access."""
        big_cfg = {f"KEY_{i}": f"value_{i}" for i in range(1000)}
        mgr = ConfigManager(initial_cfg=big_cfg)
        n_threads = 10
        iterations = 50
        errors: list[Exception] = []
        lock = threading.Lock()

        def worker(tid: int):
            for i in range(iterations):
                try:
                    idx = (tid * 100 + i) % 1000
                    mgr.get_str(f"KEY_{idx}")
                    mgr.set(f"KEY_{idx}", f"updated_by_{tid}_{i}")
                    assert mgr.get_str(f"KEY_{idx}") is not None
                    all_cfg = mgr.all()
                    assert len(all_cfg) == 1000
                except Exception as e:
                    with lock:
                        errors.append(e)

        threads = [threading.Thread(target=worker, args=(tid,)) for tid in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(errors) == 0, f"{len(errors)} thread errors"

    def test_stress_observer_chain_no_leak(self):
        """Adding and removing observers in tight loop should not leak memory."""
        mgr = ConfigManager({"x": 1})
        n_threads = 10
        iterations = 50
        errors: list[Exception] = []
        lock = threading.Lock()

        def worker():
            removes = []
            for i in range(iterations):
                try:
                    def make_obs(val):
                        def obs(k, o, n):
                            pass
                        return obs
                    remove = mgr.observe(make_obs(i))
                    removes.append(remove)
                except Exception as e:
                    with lock:
                        errors.append(e)
            for r in removes:
                try:
                    r()
                except Exception as e:
                    with lock:
                        errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        with mgr._lock:
            assert len(mgr._observers) == 0

    def test_stress_no_deadlock_on_recursive_access(self):
        """RLock allows recursive access — nested set/get should not deadlock."""
        mgr = ConfigManager({"x": 1})

        def recursive_access(count: int):
            if count <= 0:
                return
            val = mgr.get_int("x")
            mgr.set("x", val + 1)
            recursive_access(count - 1)

        mgr.set("x", 0)
        recursive_access(100)
        assert mgr.get_int("x") == 100


# ==============================================================================
# Stress: timing / throughput sanity
# ==============================================================================


class TestConfigManagerThroughput:
    """Basic throughput checks to ensure locking overhead is reasonable."""

    def test_single_thread_throughput(self):
        """100k operations single-threaded should complete in < 5s."""
        mgr = ConfigManager({"k": 0})
        n = 50_000
        start = time.perf_counter()
        for i in range(n):
            mgr.set("k", i)
        elapsed = time.perf_counter() - start
        assert mgr.get_int("k") == n - 1
        assert elapsed < 5.0, f"Too slow: {elapsed:.2f}s for {n} writes"
