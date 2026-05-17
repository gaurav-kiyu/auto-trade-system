"""
Broker State Handler (Phase 0).

Handles unknown broker states, timeouts, and network failures safely.
Critical for preventing duplicate orders and ensuring proper error handling.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from core.datetime_ist import now_ist
from enum import Enum

log = logging.getLogger(__name__)


class BrokerStateCategory(str, Enum):
    KNOWN_TERMINAL = "KNOWN_TERMINAL"
    KNOWN_PENDING = "KNOWN_PENDING"
    TIMEOUT = "TIMEOUT"
    NETWORK_ERROR = "NETWORK_ERROR"
    UNKNOWN_STATUS = "UNKNOWN_STATUS"
    NO_RESPONSE = "NO_RESPONSE"


class ActionRecommendation(str, Enum):
    PROCEED = "PROCEED"
    RETRY = "RETRY"
    BLOCK_RETRY = "BLOCK_RETRY"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    UNKNOWN = "UNKNOWN"


@dataclass
class StateResolution:
    category: BrokerStateCategory
    action: ActionRecommendation
    message: str
    can_retry: bool
    is_terminal: bool
    timestamp: datetime = field(default_factory=now_ist)


class BrokerStateHandler:
    """
    Handles unknown/ambiguous broker states safely.

    Prevents:
    - Blind retries on terminal states
    - Lost orders from network timeouts
    - Duplicate submissions on unknown states
    """

    MAX_RETRY_COUNT = 3
    TIMEOUT_SECONDS = 30
    UNKNOWN_STATUS_THRESHOLD = 3

    def __init__(
        self,
        max_retries: int = MAX_RETRY_COUNT,
        timeout_seconds: int = TIMEOUT_SECONDS,
    ):
        self._max_retries = max_retries
        self._timeout_seconds = timeout_seconds
        self._unknown_status_counts: dict[str, int] = {}

    def resolve_status(
        self,
        status: str | None,
        retry_count: int = 0,
        last_update: datetime | None = None,
        last_error: str | None = None,
    ) -> StateResolution:
        """
        Resolve broker status to known category and recommend action.

        Args:
            status: Current broker status string
            retry_count: Number of previous retry attempts
            last_update: Last time status was updated
            last_error: Last error message if any

        Returns:
            StateResolution with category and recommended action
        """
        if status is None or status == "":
            return StateResolution(
                category=BrokerStateCategory.NO_RESPONSE,
                action=ActionRecommendation.RETRY,
                message="No status received from broker",
                can_retry=True,
                is_terminal=False,
            )

        status_upper = status.upper().strip()
        status_lower = status_upper.lower()

        if status_upper in ("COMPLETE", "FILLED"):
            return StateResolution(
                category=BrokerStateCategory.KNOWN_TERMINAL,
                action=ActionRecommendation.PROCEED,
                message=f"Order {status_lower}",
                can_retry=False,
                is_terminal=True,
            )

        if status_upper in ("REJECTED", "CANCELLED", "EXPIRED"):
            return StateResolution(
                category=BrokerStateCategory.KNOWN_TERMINAL,
                action=ActionRecommendation.BLOCK_RETRY,
                message=f"Order {status_lower} - no retry allowed",
                can_retry=False,
                is_terminal=True,
            )

        if status_upper in ("OPEN", "PENDING", "TRIGGER PENDING", "SUBMITTED"):
            if last_update and (now_ist() - last_update).total_seconds() > self._timeout_seconds:
                return StateResolution(
                    category=BrokerStateCategory.TIMEOUT,
                    action=ActionRecommendation.RETRY,
                    message=f"Order {status_lower} but exceeded {self._timeout_seconds}s timeout",
                    can_retry=True,
                    is_terminal=False,
                )
            return StateResolution(
                category=BrokerStateCategory.KNOWN_PENDING,
                action=ActionRecommendation.PROCEED,
                message=f"Order {status_lower} - awaiting fill",
                can_retry=False,
                is_terminal=False,
            )

        if status_upper in ("PARTIALLY FILLED", "PARTIAL"):
            return StateResolution(
                category=BrokerStateCategory.KNOWN_PENDING,
                action=ActionRecommendation.PROCEED,
                message="Order partially filled - tracking remaining",
                can_retry=False,
                is_terminal=False,
            )

        if "NETWORK" in status_upper or "CONNECTION" in status_upper or "TIMEOUT" in status_upper:
            return StateResolution(
                category=BrokerStateCategory.NETWORK_ERROR,
                action=ActionRecommendation.RETRY,
                message=f"Network error: {last_error or status}",
                can_retry=True,
                is_terminal=False,
            )

        count = self._unknown_status_counts.get(status_upper, 0)
        if count >= self.UNKNOWN_STATUS_THRESHOLD:
            return StateResolution(
                category=BrokerStateCategory.UNKNOWN_STATUS,
                action=ActionRecommendation.MANUAL_REVIEW,
                message=f"Unknown status '{status}' seen {count} times - requires manual review",
                can_retry=False,
                is_terminal=False,
            )

        self._unknown_status_counts[status_upper] = count + 1
        return StateResolution(
            category=BrokerStateCategory.UNKNOWN_STATUS,
            action=ActionRecommendation.RETRY,
            message=f"Unknown status '{status}' - will retry",
            can_retry=True,
            is_terminal=False,
        )

    def should_retry(
        self,
        status: str | None,
        retry_count: int,
        resolution: StateResolution | None = None,
    ) -> bool:
        """Determine if order should be retried."""
        if resolution is None:
            resolution = self.resolve_status(status, retry_count)

        if not resolution.can_retry:
            return False

        if retry_count >= self._max_retries:
            log.warning(f"Max retries ({self._max_retries}) exceeded for status: {status}")
            return False

        return True

    def handle_timeout(
        self,
        order_id: str,
        retry_count: int,
    ) -> StateResolution:
        """Handle broker timeout scenario."""
        if retry_count >= self._max_retries:
            return StateResolution(
                category=BrokerStateCategory.TIMEOUT,
                action=ActionRecommendation.BLOCK_RETRY,
                message=f"Order {order_id}: timeout after {retry_count} retries",
                can_retry=False,
                is_terminal=False,
            )

        return StateResolution(
            category=BrokerStateCategory.TIMEOUT,
            action=ActionRecommendation.RETRY,
            message=f"Order {order_id}: timeout, retry attempt {retry_count + 1}",
            can_retry=True,
            is_terminal=False,
        )

    def handle_exception(
        self,
        order_id: str,
        exception: Exception,
        retry_count: int,
    ) -> StateResolution:
        """Handle broker exception scenario."""
        exc_type = type(exception).__name__
        exc_msg = str(exception)

        if "timeout" in exc_msg.lower() or "timed out" in exc_msg.lower():
            return self.handle_timeout(order_id, retry_count)

        if "network" in exc_msg.lower() or "connection" in exc_msg.lower():
            if retry_count >= self._max_retries:
                return StateResolution(
                    category=BrokerStateCategory.NETWORK_ERROR,
                    action=ActionRecommendation.BLOCK_RETRY,
                    message=f"Network error after {retry_count} retries: {exc_msg}",
                    can_retry=False,
                    is_terminal=False,
                )
            return StateResolution(
                category=BrokerStateCategory.NETWORK_ERROR,
                action=ActionRecommendation.RETRY,
                message=f"Network error: {exc_msg}",
                can_retry=True,
                is_terminal=False,
            )

        if "auth" in exc_msg.lower() or "token" in exc_msg.lower() or "unauthorized" in exc_msg.lower():
            return StateResolution(
                category=BrokerStateCategory.NETWORK_ERROR,
                action=ActionRecommendation.BLOCK_RETRY,
                message=f"Auth error (non-retryable): {exc_msg}",
                can_retry=False,
                is_terminal=True,
            )

        if "insufficient" in exc_msg.lower() or "margin" in exc_msg.lower():
            return StateResolution(
                category=BrokerStateCategory.KNOWN_TERMINAL,
                action=ActionRecommendation.BLOCK_RETRY,
                message=f"Margin/balance error: {exc_msg}",
                can_retry=False,
                is_terminal=True,
            )

        if retry_count >= self._max_retries:
            return StateResolution(
                category=BrokerStateCategory.UNKNOWN_STATUS,
                action=ActionRecommendation.BLOCK_RETRY,
                message=f"Max retries exceeded: {exc_type} - {exc_msg}",
                can_retry=False,
                is_terminal=False,
            )

        return StateResolution(
            category=BrokerStateCategory.UNKNOWN_STATUS,
            action=ActionRecommendation.RETRY,
            message=f"Error ({exc_type}): {exc_msg}",
            can_retry=True,
            is_terminal=False,
        )

    def get_pending_orders_count(self) -> int:
        """Get count of orders with unknown status."""
        return sum(1 for count in self._unknown_status_counts.values() if count < self.UNKNOWN_STATUS_THRESHOLD)

    def clear_unknown_status(self, status: str) -> None:
        """Clear unknown status count after resolution."""
        status_upper = status.upper().strip()
        if status_upper in self._unknown_status_counts:
            del self._unknown_status_counts[status_upper]


def create_state_handler(
    max_retries: int = 3,
    timeout_seconds: int = 30,
) -> BrokerStateHandler:
    """Factory function for creating state handler."""
    return BrokerStateHandler(max_retries=max_retries, timeout_seconds=timeout_seconds)
