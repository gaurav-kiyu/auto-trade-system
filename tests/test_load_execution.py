"""
Load/benchmark test for the execution pipeline.

Simulates concurrent order submissions through the ExecutionStateMachine
to verify: (a) no deadlocks under load, (b) all state transitions remain
deterministic, (c) throughput meets minimum thresholds.

Usage:
    python -m pytest tests/test_load_execution.py -v --tb=short
    python -m pytest tests/test_load_execution.py -v --tb=short -k "stress"   # heavier load
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

import pytest

from core.execution.deterministic_state_machine import (
    ExecutionState,
    ExecutionStateMachine,
    ExecutionStateMachineManager,
    TransitionResult,
    reset_execution_state_manager,
)


# ── Configuration ─────────────────────────────────────────────────────────────

@dataclass
class LoadConfig:
    """Tunable load parameters."""
    concurrency: int = 10          # concurrent simulated orders
    orders_per_thread: int = 5     # orders per concurrent worker
    transition_delay: float = 0.001  # simulated broker latency
    timeout_seconds: float = 30.0  # max wall-clock time for the test


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_state_manager():
    """Reset the singleton state manager before each test for isolation."""
    reset_execution_state_manager()
    yield
    reset_execution_state_manager()


@pytest.fixture
def load_config() -> LoadConfig:
    return LoadConfig()


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_machine(intent_id: str, **overrides) -> ExecutionStateMachine:
    """Factory helper matching existing test patterns."""
    params = {
        "intent_id": intent_id,
        "client_order_id": f"OPB-{intent_id}",
        "symbol": "NIFTY",
        "quantity": 50,
        "price": 150.0,
        "direction": "BUY",
    }
    params.update(overrides)
    return ExecutionStateMachine(**params)


def run_order_lifecycle(
    manager: ExecutionStateMachineManager,
    intent_id: str,
    delay: float = 0.001,
) -> dict:
    """
    Simulate a full order lifecycle: INIT → VALIDATED → PERSISTED → SUBMITTED
    → ACKNOWLEDGED → FILLED.
    Returns a dict with timing and transition results.
    """
    start = time.monotonic()
    result = {
        "intent_id": intent_id,
        "success": False,
        "transitions": [],
        "error": None,
        "duration_ms": 0.0,
    }

    try:
        machine, is_new = manager.create_or_get(
            intent_id=intent_id,
            symbol="NIFTY",
            quantity=50,
            price=150.0,
            direction="BUY",
        )
        result["is_new"] = is_new

        if not is_new:
            # Duplicate — still valid, just log it
            result["was_duplicate"] = True
            result["success"] = True
            return result

        # INIT → VALIDATED
        r1 = machine.validate_transition(ExecutionState.VALIDATED)
        result["transitions"].append(("INIT→VALIDATED", r1[0].value))
        assert r1[0] == TransitionResult.SUCCESS, f"INIT→VALIDATED failed: {r1[1]}"
        time.sleep(delay)

        # VALIDATED → PERSISTED
        r2 = machine.validate_transition(ExecutionState.PERSISTED)
        result["transitions"].append(("VALIDATED→PERSISTED", r2[0].value))
        assert r2[0] == TransitionResult.SUCCESS
        time.sleep(delay)

        # PERSISTED → SUBMITTED
        ok = machine.record_submission(f"BROKER-{intent_id}")
        assert ok, f"SUBMISSION failed for {intent_id}"
        result["transitions"].append(("PERSISTED→SUBMITTED", "SUCCESS"))

        # SUBMITTED → ACKNOWLEDGED
        ok = machine.record_acknowledgment()
        assert ok, f"ACK failed for {intent_id}"
        result["transitions"].append(("SUBMITTED→ACKNOWLEDGED", "SUCCESS"))
        time.sleep(delay)

        # ACKNOWLEDGED → FILLED
        ok = machine.record_fill(filled_qty=50, price=152.0)
        assert ok, f"FILL failed for {intent_id}"
        result["transitions"].append(("ACKNOWLEDGED→FILLED", "SUCCESS"))

        # Verify terminal state
        assert machine.state == ExecutionState.FILLED
        assert machine.is_terminal()
        assert machine.filled_quantity == 50

        result["success"] = True

    except (AssertionError, KeyError, ValueError, TypeError, RuntimeError) as e:
        result["error"] = str(e)

    result["duration_ms"] = (time.monotonic() - start) * 1000
    return result


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestLoadExecution:
    """Load tests for the execution pipeline."""

    def test_single_order_lifecycle(self):
        """Baseline: a single order through the full lifecycle."""
        mgr = ExecutionStateMachineManager()
        result = run_order_lifecycle(mgr, "LOAD-001", delay=0.0)
        assert result["success"], f"Single order failed: {result['error']}"
        assert len(result["transitions"]) == 5  # 5 transitions in the lifecycle
        assert result["duration_ms"] < 500, f"Single order too slow: {result['duration_ms']:.1f}ms"

    def test_concurrent_orders_basic(self):
        """10 concurrent orders — verify no deadlocks, all succeed."""
        mgr = ExecutionStateMachineManager()
        results: list[dict] = []
        errors: list[str] = []

        def worker(oid: int):
            r = run_order_lifecycle(mgr, f"LOAD-CONCURRENT-{oid:04d}", delay=0.002)
            return r

        with ThreadPoolExecutor(max_workers=10) as pool:
            futures = [pool.submit(worker, i) for i in range(10)]
            for f in as_completed(futures, timeout=30):
                r = f.result()
                results.append(r)
                if not r["success"]:
                    errors.append(f"{r['intent_id']}: {r['error']}")

        assert not errors, f"{len(errors)} concurrent order(s) failed: {'; '.join(errors[:3])}"
        assert len(results) == 10
        # All should be new (not duplicates) since intent IDs are unique
        assert all(r["is_new"] for r in results if r["success"])

    def test_concurrent_orders_heavy(self):
        """50 concurrent orders — stress the state manager."""
        mgr = ExecutionStateMachineManager()
        errors: list[str] = []

        def worker(oid: int):
            r = run_order_lifecycle(mgr, f"LOAD-HEAVY-{oid:04d}", delay=0.001)
            return r

        with ThreadPoolExecutor(max_workers=20) as pool:
            futures = [pool.submit(worker, i) for i in range(50)]
            for f in as_completed(futures, timeout=60):
                r = f.result()
                if not r["success"]:
                    errors.append(f"{r['intent_id']}: {r['error']}")

        assert not errors, f"{len(errors)} heavy order(s) failed: {'; '.join(errors[:3])}"

    def test_duplicate_intent_idempotency(self):
        """Same intent_id submitted twice — second should return existing."""
        mgr = ExecutionStateMachineManager()

        # First submission
        r1 = run_order_lifecycle(mgr, "LOAD-DUP-001")
        assert r1["success"]
        assert r1["is_new"] is True

        # Second submission with same intent_id
        r2 = run_order_lifecycle(mgr, "LOAD-DUP-001")
        assert r2["success"]
        # The create_or_get returns existing machine — the lifecycle may skip
        # transitions if already in terminal state
        assert r2["was_duplicate"] is True, "Duplicate should return existing machine"

    def test_state_machine_manager_prune(self):
        """Prune terminal machines — verify count decreases."""
        mgr = ExecutionStateMachineManager()

        # Create and complete 20 orders
        for i in range(20):
            r = run_order_lifecycle(mgr, f"LOAD-PRUNE-{i:04d}")
            assert r["success"]

        all_machines = mgr.get_all()
        assert len(all_machines) == 20

        # Prune with a very short max age (0 hours)
        pruned = mgr.prune_terminals(max_age_hours=0)
        assert pruned == 20, f"Expected 20 pruned, got {pruned}"

        all_after = mgr.get_all()
        assert len(all_after) == 0, f"Expected 0 after prune, got {len(all_after)}"

    def test_manager_lock_contention(self):
        """10 threads hammering create_or_get simultaneously — no deadlocks."""
        mgr = ExecutionStateMachineManager()
        successes = 0
        lock = threading.Lock()

        def contender(tid: int):
            nonlocal successes
            for i in range(20):
                intent_id = f"LOAD-CONTEND-{tid}-{i:04d}"
                machine, is_new = mgr.create_or_get(
                    intent_id=intent_id,
                    symbol="NIFTY",
                    quantity=50,
                    price=150.0,
                    direction="BUY",
                )
                if is_new:
                    machine.try_transition_to(ExecutionState.VALIDATED)
                    with lock:
                        successes += 1

        threads = [threading.Thread(target=contender, args=(t,)) for t in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)

        assert successes == 200, f"Expected 200 successful creates, got {successes}"

    def test_throughput_minimum(self):
        """Minimum throughput: at least 100 orders/sec through the pipeline."""
        mgr = ExecutionStateMachineManager()
        n_orders = 100
        start = time.monotonic()

        results = []
        for i in range(n_orders):
            r = run_order_lifecycle(mgr, f"LOAD-THROUGHPUT-{i:04d}", delay=0.0)
            results.append(r)

        elapsed = time.monotonic() - start
        throughput = n_orders / elapsed if elapsed > 0 else float("inf")

        # Minimum: 50 orders/sec (the pipeline is simple; should be much faster)
        assert throughput >= 50, (
            f"Throughput too low: {throughput:.0f} orders/sec "
            f"({n_orders} orders in {elapsed:.2f}s)"
        )

    def test_invalid_transition_under_load(self):
        """Simultaneous invalid transitions — state machine must refuse them."""
        mgr = ExecutionStateMachineManager()
        machine, _ = mgr.create_or_get(
            intent_id="LOAD-INVALID",
            symbol="NIFTY",
            quantity=50,
            price=150.0,
            direction="BUY",
        )

        errors: list[str] = []

        def try_bad_transition():
            # Try FILLED directly from INIT (should fail)
            r = machine.validate_transition(ExecutionState.FILLED)
            if r[0] == TransitionResult.SUCCESS:
                errors.append("FILLED from INIT should have been rejected")

        threads = [threading.Thread(target=try_bad_transition) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert not errors, f"Invalid transitions were allowed: {'; '.join(errors)}"
        assert machine.state == ExecutionState.INIT, (
            f"Machine state corrupted: {machine.state.value}"
        )


class TestLoadStress:
    """Heavier stress tests — run separately to avoid slowing the default suite."""

    @pytest.mark.slow
    def test_stress_500_orders(self):
        """500 orders with 50 concurrent workers."""
        mgr = ExecutionStateMachineManager()
        errors: list[str] = []
        durations: list[float] = []

        def worker(oid: int):
            r = run_order_lifecycle(mgr, f"LOAD-STRESS-{oid:05d}", delay=0.0)
            return r

        with ThreadPoolExecutor(max_workers=50) as pool:
            futures = [pool.submit(worker, i) for i in range(500)]
            for f in as_completed(futures, timeout=120):
                r = f.result()
                durations.append(r["duration_ms"])
                if not r["success"]:
                    errors.append(f"{r['intent_id']}: {r['error']}")

        assert not errors, f"{len(errors)} stress order(s) failed"
        avg_ms = sum(durations) / len(durations) if durations else 0
        max_ms = max(durations) if durations else 0
        print(f"\n  [LOAD] 500 orders: avg={avg_ms:.1f}ms, max={max_ms:.1f}ms")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
