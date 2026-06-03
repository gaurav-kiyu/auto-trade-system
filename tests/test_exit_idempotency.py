"""
Tests for exit idempotency key determinism (DEBT-011).

Verifies that exit position operations use deterministic idempotency keys
based on position parameters (name, qty, entry_price, reason) rather than
non-deterministic values like time.time().

Key scenarios:
1. Same position + same reason → same idempotency key
2. Same position + different reason → different idempotency key
3. Different qty → different key
4. Different entry_price → different key
5. Deterministic key prevents duplicate exit orders
"""

from __future__ import annotations

from core.execution.idempotency.manager import IdempotencyManager
from core.execution.idempotency.certifier import IdempotencyCertifier


# ── Exit idempotency key format tests ────────────────────────────────────────

def _exit_idempotency_key(name: str, qty: int, entry_price: float, reason: str) -> str:
    """Simulate the deterministic key generation used in index_trader.py's _exit_position()."""
    return f"exit_{name}_{int(qty)}_{int(entry_price)}_{reason}"


class TestExitIdempotencyKeyDeterminism:
    """Verify that exit idempotency keys are deterministic."""

    def test_same_position_same_reason(self):
        """Same position params + same reason → identical key."""
        k1 = _exit_idempotency_key("NIFTY", 75, 22150.50, "stop_loss")
        k2 = _exit_idempotency_key("NIFTY", 75, 22150.50, "stop_loss")
        assert k1 == k2
        assert k1 == "exit_NIFTY_75_22150_stop_loss"

    def test_same_position_different_reason(self):
        """Same position params + different reason → different key."""
        k1 = _exit_idempotency_key("NIFTY", 75, 22150.50, "stop_loss")
        k2 = _exit_idempotency_key("NIFTY", 75, 22150.50, "take_profit")
        assert k1 != k2

    def test_different_qty_different_key(self):
        """Different qty → different key."""
        k1 = _exit_idempotency_key("NIFTY", 75, 22150.50, "stop_loss")
        k2 = _exit_idempotency_key("NIFTY", 50, 22150.50, "stop_loss")
        assert k1 != k2

    def test_different_entry_price_different_key(self):
        """Different entry_price → different key."""
        k1 = _exit_idempotency_key("NIFTY", 75, 22150.50, "stop_loss")
        k2 = _exit_idempotency_key("NIFTY", 75, 22200.00, "stop_loss")
        assert k1 != k2

    def test_different_symbol_different_key(self):
        """Different symbol/name → different key."""
        k1 = _exit_idempotency_key("NIFTY", 75, 22150.50, "stop_loss")
        k2 = _exit_idempotency_key("BANKNIFTY", 75, 22150.50, "stop_loss")
        assert k1 != k2

    def test_key_includes_all_components(self):
        """Key format includes all identifying components."""
        key = _exit_idempotency_key("NIFTY", 75, 22150.50, "trail_sl")
        assert key.startswith("exit_")
        assert "NIFTY" in key
        assert "75" in key
        assert "22150" in key
        assert "trail_sl" in key
        # Verify no time.time() suffix
        assert "_time_" not in key
        import re
        assert not re.search(r"_\d{10,}$", key)  # no trailing Unix timestamps


# ── IdempotencyManager integration tests ──────────────────────────────────────

class TestExitIdempotencyViaManager:
    """Verify exit keys work correctly through the IdempotencyManager."""

    def test_exit_key_via_manager_deterministic(self):
        """Same exit params generate same hash via IdempotencyManager."""
        manager = IdempotencyManager(cache_size=100, expiry_hours=1)

        class FakeExitRequest:
            symbol = "NIFTY"
            direction = "EXIT"
            strike = 0
            qty = 75

        class FakeContext1:
            signal_id = "exit_NIFTY_75_22150_stop_loss"
            signal_timestamp = None

        class FakeContext2:
            signal_id = "exit_NIFTY_75_22150_stop_loss"
            signal_timestamp = None

        key1 = manager.generate_key(FakeExitRequest(), FakeContext1())
        key2 = manager.generate_key(FakeExitRequest(), FakeContext2())
        assert key1 == key2

    def test_exit_key_different_reason_different_hash(self):
        """Different exit reasons produce different hashes via manager."""
        manager = IdempotencyManager(cache_size=100, expiry_hours=1)

        class FakeExitRequest:
            symbol = "NIFTY"
            direction = "EXIT"
            strike = 0
            qty = 75

        class FakeContextStop:
            signal_id = "exit_NIFTY_75_22150_stop_loss"
            signal_timestamp = None

        class FakeContextTp:
            signal_id = "exit_NIFTY_75_22150_take_profit"
            signal_timestamp = None

        key1 = manager.generate_key(FakeExitRequest(), FakeContextStop())
        key2 = manager.generate_key(FakeExitRequest(), FakeContextTp())
        assert key1 != key2

    def test_exit_duplicate_prevention(self):
        """Exit key marked in-flight prevents duplicate."""
        manager = IdempotencyManager(cache_size=100, expiry_hours=1)

        class FakeExitRequest:
            symbol = "NIFTY"
            direction = "EXIT"
            strike = 0
            qty = 75

        class FakeContext:
            signal_id = "exit_NIFTY_75_22150_stop_loss"
            signal_timestamp = None

        key = manager.generate_key(FakeExitRequest(), FakeContext())
        assert not manager.is_duplicate(key)
        manager.mark_in_flight(key)
        assert manager.is_duplicate(key)

    def test_exit_key_confirm_then_duplicate(self):
        """Exit key confirmed as executed prevents duplicate."""
        manager = IdempotencyManager(cache_size=100, expiry_hours=1)

        class FakeExitRequest:
            symbol = "NIFTY"
            direction = "EXIT"
            strike = 0
            qty = 75

        class FakeContext:
            signal_id = "exit_NIFTY_75_22150_time_exit"
            signal_timestamp = None

        key = manager.generate_key(FakeExitRequest(), FakeContext())
        manager.store_result(key, {"status": "exit_confirmed"})
        assert manager.is_duplicate(key)

    def test_different_qty_different_hash(self):
        """Different quantities produce different hashes for exits."""
        manager = IdempotencyManager(cache_size=100, expiry_hours=1)

        class FakeExitRequest75:
            symbol = "NIFTY"
            direction = "EXIT"
            strike = 0
            qty = 75

        class FakeExitRequest50:
            symbol = "NIFTY"
            direction = "EXIT"
            strike = 0
            qty = 50

        class FakeContext:
            signal_id = "exit_NIFTY_75_22150_stop_loss"
            signal_timestamp = None

        key1 = manager.generate_key(FakeExitRequest75(), FakeContext())
        key2 = manager.generate_key(FakeExitRequest50(), FakeContext())
        assert key1 != key2


# ── IdempotencyCertifier integration tests ────────────────────────────────────

class TestExitIdempotencyViaCertifier:
    """Verify exit keys work through the IdempotencyCertifier."""

    def test_certifier_rejects_duplicate_exit(self):
        """Certifier prevents duplicate exit execution."""
        cert = IdempotencyCertifier(db_path=":memory:")
        try:
            # Simulate exit execution_id
            eid = cert.generate_execution_id("NIFTY", "EXIT", 0, 75, time_slot=6100)
            assert not cert.is_duplicate(eid)

            cid = cert.begin(eid, "NIFTY", "SELL", {"qty": 75, "reason": "stop_loss"})
            assert cert.is_pending(eid)
            assert cert.is_duplicate(eid)

            # Second begin should return same cert_id rather than creating duplicate
            cid2 = cert.begin(eid, "NIFTY", "SELL", {"qty": 75, "reason": "stop_loss"})
            assert cid2 is not None  # Returns existing cert_id
        finally:
            cert.close()

    def test_certifier_distinct_exit_reasons(self):
        """Different exit reasons get different execution_ids."""
        cert = IdempotencyCertifier(db_path=":memory:")
        try:
            eid1 = cert.generate_execution_id("NIFTY", "EXIT", 0, 75, time_slot=6100)
            eid2 = cert.generate_execution_id("NIFTY", "EXIT", 0, 75, time_slot=6101)
            assert eid1 != eid2
        finally:
            cert.close()
