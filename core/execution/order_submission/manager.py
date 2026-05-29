"""
Order Submission Manager.

Handles the actual interaction with the BrokerPort to submit orders.
"""

from __future__ import annotations

import logging

from core.common.kernels.models import OrderResult as KernelOrderResult
from core.ports.broker import LegacyBrokerPort, OrderRequest

log = logging.getLogger("order_submission")

class OrderSubmissionManager:
    def __init__(self, broker_port: LegacyBrokerPort):
        self.broker_port = broker_port

    def submit(self, request: OrderRequest) -> KernelOrderResult:
        try:
            result = self.broker_port.place_order(request)

            # Handle cases where broker returns a string ID instead of OrderResult
            if isinstance(result, str):
                return KernelOrderResult(
                    order_id=result,
                    status="SUBMITTED",
                    timestamp=None,  # Should be set by a time provider
                )
            return result
        except Exception as e:
            log.error(f"Submission failed: {e}")
            return KernelOrderResult(
                order_id="ERROR",
                status="REJECTED",
                reject_reason=str(e),
            )
