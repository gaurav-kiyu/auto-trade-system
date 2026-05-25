"""
Failure Injection Test Utilities

Simulate various failure scenarios:
- ACK timeout
- Partial fill
- Malformed broker payload
- Stale quote
- DB write fail
- Broker disconnect/reconnect

Usage:
    with FailureInjector.inject("ack_timeout"):
        # Test code here
    
    # Or register specific failures
    fi = FailureInjector()
    fi.register_failure("partial_fill", probability=0.5)
"""
from __future__ import annotations

import random
import threading
import time
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any

import pytest


class FailureType(Enum):
    """Types of failures that can be injected."""
    ACK_TIMEOUT = auto()
    PARTIAL_FILL = auto()
    MALFORMED_PAYLOAD = auto()
    STALE_QUOTE = auto()
    DB_WRITE_FAIL = auto()
    BROKER_DISCONNECT = auto()
    BROKER_RECONNECT_DELAY = auto()
    INVALID_ORDER_STATE = auto()
    PRICE_ERROR = auto()


@dataclass
class FailureScenario:
    """Configuration for a failure scenario."""
    failure_type: FailureType
    probability: float  # 0-1
    delay_ms: int = 0
    error_message: str = "Injected failure"
    custom_data: dict[str, Any] = field(default_factory=dict)


class FailureInjector:
    """
    Configurable failure injection for testing.
    Can be used as context manager or registered for probabilistic injection.
    """

    _instance: FailureInjector | None = None
    _lock = threading.Lock()

    def __init__(self):
        self._enabled = False
        self._scenarios: dict[FailureType, FailureScenario] = {}
        self._callbacks: dict[FailureType, Callable] = {}
        self._injection_count: dict[FailureType, int] = {}

    @classmethod
    def get_instance(cls) -> FailureInjector:
        """Get singleton instance."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def enable(self) -> None:
        """Enable failure injection."""
        self._enabled = True

    def disable(self) -> None:
        """Disable failure injection."""
        self._enabled = False

    def register_scenario(self, scenario: FailureScenario) -> None:
        """Register a failure scenario."""
        self._scenarios[scenario.failure_type] = scenario
        self._injection_count[scenario.failure_type] = 0

    def register_callback(self, failure_type: FailureType, callback: Callable) -> None:
        """Register callback for a specific failure type."""
        self._callbacks[failure_type] = callback

    def should_inject(self, failure_type: FailureType) -> bool:
        """Determine if failure should be injected."""
        if not self._enabled:
            return False

        scenario = self._scenarios.get(failure_type)
        if scenario is None:
            return False

        # Check probability
        if random.random() < scenario.probability:
            self._injection_count[failure_type] = self._injection_count.get(failure_type, 0) + 1
            return True

        return False

    def inject(self, failure_type: FailureType) -> Any:
        """
        Inject a failure of the given type.
        Returns error payload appropriate for the failure type.
        """
        scenario = self._scenarios.get(failure_type)
        if scenario and scenario.delay_ms > 0:
            time.sleep(scenario.delay_ms / 1000.0)

        # Call registered callback if present
        callback = self._callbacks.get(failure_type)
        if callback:
            return callback(failure_type, scenario)

        # Return appropriate error based on type
        return self._create_error_payload(failure_type, scenario)

    def _create_error_payload(self, failure_type: FailureType, scenario: FailureScenario | None) -> Any:
        """Create appropriate error payload for failure type."""
        error_msg = scenario.error_message if scenario else "Injected failure"

        if failure_type == FailureType.ACK_TIMEOUT:
            return {"error": "timeout", "message": error_msg}
        elif failure_type == FailureType.PARTIAL_FILL:
            return {"status": "partial", "filled_qty": 5, "remaining_qty": 5}
        elif failure_type == FailureType.MALFORMED_PAYLOAD:
            return {"error": "parse_error", "raw_data": "{invalid json"}
        elif failure_type == FailureType.STALE_QUOTE:
            return {"error": "stale_data", "quote_age_seconds": 10}
        elif failure_type == FailureType.DB_WRITE_FAIL:
            raise OSError(error_msg)
        elif failure_type == FailureType.BROKER_DISCONNECT:
            return {"error": "connection_lost", "message": error_msg}
        else:
            return {"error": "unknown", "message": error_msg}

    def reset_counts(self) -> None:
        """Reset injection counts."""
        for k in self._injection_count:
            self._injection_count[k] = 0

    def get_stats(self) -> dict[str, int]:
        """Get injection statistics."""
        return dict(self._injection_count)

    @contextmanager
    def context(self, failure_type: FailureType, probability: float = 1.0):
        """
        Context manager for injecting failures.
        
        Usage:
            with fi.context(FailureType.ACK_TIMEOUT, probability=1.0):
                # Test code that should handle timeout
        """
        old_enabled = self._enabled
        old_scenario = self._scenarios.get(failure_type)

        self.enable()
        self.register_scenario(FailureScenario(
            failure_type=failure_type,
            probability=probability
        ))

        try:
            yield self
        finally:
            self._enabled = old_enabled
            if old_scenario:
                self._scenarios[failure_type] = old_scenario
            else:
                self._scenarios.pop(failure_type, None)


# Convenience functions for common failure scenarios
@contextmanager
def inject_ack_timeout(probability: float = 1.0):
    """Inject ACK timeout failure."""
    fi = FailureInjector.get_instance()
    with fi.context(FailureType.ACK_TIMEOUT, probability):
        yield


@contextmanager
def inject_partial_fill(probability: float = 1.0):
    """Inject partial fill failure."""
    fi = FailureInjector.get_instance()
    with fi.context(FailureType.PARTIAL_FILL, probability):
        yield


@contextmanager
def inject_stale_quote(probability: float = 1.0):
    """Inject stale quote failure."""
    fi = FailureInjector.get_instance()
    with fi.context(FailureType.STALE_QUOTE, probability):
        yield


@contextmanager
def inject_broker_disconnect(probability: float = 1.0):
    """Inject broker disconnect failure."""
    fi = FailureInjector.get_instance()
    with fi.context(FailureType.BROKER_DISCONNECT, probability):
        yield


# Pytest fixtures for common failure scenarios
@pytest.fixture
def failure_injector():
    """Fixture providing a failure injector."""
    fi = FailureInjector.get_instance()
    fi.enable()
    yield fi
    fi.disable()
    fi.reset_counts()


@pytest.fixture
def ack_timeout(failure_injector):
    """Fixture for ACK timeout scenario."""
    with failure_injector.context(FailureType.ACK_TIMEOUT):
        yield


@pytest.fixture
def partial_fill(failure_injector):
    """Fixture for partial fill scenario."""
    with failure_injector.context(FailureType.PARTIAL_FILL):
        yield


@pytest.fixture
def broker_disconnect(failure_injector):
    """Fixture for broker disconnect scenario."""
    with failure_injector.context(FailureType.BROKER_DISCONNECT):
        yield


# Test examples
def test_handles_ack_timeout(ack_timeout):
    """Test that code handles ACK timeout properly."""
    fi = FailureInjector.get_instance()
    assert fi.should_inject(FailureType.ACK_TIMEOUT)


def test_handles_partial_fill(partial_fill):
    """Test that code handles partial fill properly."""
    fi = FailureInjector.get_instance()
    assert fi.should_inject(FailureType.PARTIAL_FILL)


def test_probabilistic_failure():
    """Test that probabilistic failure injection works."""
    fi = FailureInjector.get_instance()
    fi.enable()
    fi.register_scenario(FailureScenario(
        failure_type=FailureType.INVALID_ORDER_STATE,
        probability=0.5
    ))

    # Run many times and check probability is roughly correct
    results = [fi.should_inject(FailureType.INVALID_ORDER_STATE) for _ in range(1000)]
    injected_count = sum(results)

    # Should be around 50% +/- some margin
    assert 400 < injected_count < 600, f"Expected ~500, got {injected_count}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
