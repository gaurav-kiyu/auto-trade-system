import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional, List
from core.execution.idempotency.manager import IdempotencyManager
from core.execution.retry_policy.manager import RetryPolicy
from core.execution.order_submission.manager import OrderSubmissionManager
from core.execution.broker_gateway import broker_gateway
# ...existing code...
class ExecutionService:
    """
    Hardened Execution Service.
    Orchestrates the flow from Risk Validation -> Order Management -> Broker Gateway.
    """
    
    def __init__(self, portfolio_service=None):
        self.portfolio = portfolio_service
        self.idempotency = IdempotencyManager()
        self.retry_policy = RetryPolicy()
        self.submission = OrderSubmissionManager(broker_gateway)

    def execute_trade(self, symbol: str, qty: int, price: float, 
                      direction: str, risk_per_trade: float) -> ExecutionResult:
        # ...existing code...


    def execute_trade(self, symbol: str, qty: int, price: float, 
                      direction: str, risk_per_trade: float) -> ExecutionResult:
        """
        The primary execution pipeline.
        Implements the 'Safe-by-Default' flow.
        """
        start_time = time.time()
        
        # 1. Risk Validation Gate
        if risk_engine:
            risk_check = risk_engine.validate_trade_intent(
                symbol=symbol, 
                qty=qty, 
                price=price, 
                direction=direction, 
                risk_per_trade=risk_per_trade
            )
            
            if not risk_check.is_allowed:
                log.warning(f"Trade blocked by RiskEngine: {risk_check.reason}")
                return ExecutionResult(False, error=risk_check.reason)
            
            if risk_check.suggested_qty is not None:
                qty = risk_check.suggested_qty
        
        # 2. Create Deterministic Intent
        request = OrderRequest(
            symbol=symbol,
            qty=qty,
            price=price,
            order_type="MARKET",
            direction=direction,
            product="MIS",
            variety="REGULAR"
        )
        intent_id = order_manager.create_order_intent(request)

        # 3. Execute via OrderManager -> BrokerGateway
        response = order_manager.execute_intent(intent_id, request)
        
        # 4. Telemetry & Observability
        obs_manager.record_order_latency(start_time)
        if response.status == OrderStatus.FILLED:
            obs_manager.record_slippage(symbol, direction, price, response.avg_price)

        if response.status == OrderStatus.FILLED or response.order_id != "ERROR":
            return ExecutionResult(
                success=True, 
                order_id=response.order_id, 
                fill_price=response.avg_price, 
                filled_qty=response.filled_qty
            )
        
        return ExecutionResult(False, error=response.error)

    def cancel_trade(self, order_id: str) -> bool:
        """Safe cancellation of an existing order."""
        response = broker_gateway.cancel_order(order_id)
        return response.status == OrderStatus.CANCELLED

        # Execution tracking
        self._executions: dict[str, ExecutionAuditTrail] = {}
        self._execution_counter = 0

        # Paper trading price cache (for simulating realistic fills)
        self._paper_price_cache: dict[str, float] = {}

        self._logger = LoggingService(
            log_dir="logs",
            log_filename_prefix="execution_service_",
            retain_days=30,
            json_log_file="",
            version="UNKNOWN",
            enable_correlation_ids=True,
            enable_contextual_logging=True
        )

        self._logger.info("ExecutionService initialized")

    def execute_order(
        self,
        order_request: OrderRequest,
        execution_context: ExecutionContext = None
    ) -> OrderResult:
        """
        Execute an order with idempotency and duplicate prevention.

        Args:
            order_request: The order to execute
            execution_context: Context information for the execution

        Returns:
            OrderResult indicating success or failure
        """
        # Generate execution ID for tracking
        execution_id = f"exec_{self._execution_counter}_{int(time.time())}"
        self._execution_counter += 1

        # Set default execution context if not provided
        if execution_context is None:
            execution_context = ExecutionContext()

        # Generate idempotency key if not provided
        if not order_request.idempotency_key:
            order_request.idempotency_key = self._generate_idempotency_key(
                order_request, execution_context
            )

        # Check for duplicate execution if enabled
        if self.config.enable_duplicate_prevention:
            if self.is_duplicate_order(order_request.idempotency_key):
                self._logger.warning(
                    f"Duplicate order prevented: {order_request.idempotency_key}"
                )
                # Return the cached result for the duplicate order
                cached_result = self._get_idempotency_result(order_request.idempotency_key)
                if cached_result is not None:
                    return cached_result
                else:
                    # Fallback: return a rejected duplicate result
                    return OrderResult(
                        order_id="duplicate",
                        status=OrderStatus.REJECTED,
                        reject_reason="Duplicate order detected",
                        timestamp=datetime.now()
                    )

        # Record the execution start
        start_time = time.time()
        audit_trail = ExecutionAuditTrail(
            execution_id=execution_id,
            order_request=order_request,
            execution_context=execution_context
        )

        try:
            # Execute with retries
            order_result = self._execute_with_retries(order_request, execution_context)

            # Calculate latency
            latency_ms = int((time.time() - start_time) * 1000)
            audit_trail.latency_ms = latency_ms

            # Handle successful execution
            if order_result.status in [OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED]:
                # Store in idempotency cache to prevent future duplicates
                self._store_idempotency_key(order_request.idempotency_key, order_result)

                # Persist trade if we have persistence and the order was filled
                if (self.trade_persistence and
                    order_result.filled_quantity > 0 and
                    self.config.enable_audit_trail):
                    self._persist_trade_from_order(order_request, order_result, execution_context)

                # Record audit trail
                if self.config.enable_audit_trail:
                    audit_trail.order_result = order_result
                    self.record_execution_audit(audit_trail)

                self._logger.info(
                    f"Order executed successfully: {order_result.order_id} "
                    f"({order_result.filled_quantity} lots @ {order_result.average_price})"
                )

            else:
                # Order failed or was rejected
                audit_trail.order_result = order_result
                if self.config.enable_audit_trail:
                    self.record_execution_audit(audit_trail)

                self._logger.warning(
                    f"Order execution failed: {order_result.status.value} - "
                    f"{order_result.reject_reason}"
                )

            return order_result

        except Exception as e:
            # Handle unexpected errors
            latency_ms = int((time.time() - start_time) * 1000)
            audit_trail.latency_ms = latency_ms
            audit_trail.order_result = OrderResult(
                order_id="error",
                status=OrderStatus.REJECTED,
                reject_reason=f"Execution service error: {str(e)}",
                timestamp=datetime.now()
            )

            if self.config.enable_audit_trail:
                self.record_execution_audit(audit_trail)

            self._logger.error(f"Unexpected error in order execution: {e}", exc_info=True)
            return audit_trail.order_result

    def cancel_order(self, order_id: str) -> bool:
        """
        Cancel an existing order.

        Args:
            order_id: The order ID to cancel

        Returns:
            True if cancellation successful, False otherwise
        """
        try:
            # Check if order exists and is cancellable
            current_status = self.get_order_status(order_id)
            if current_status in [OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.EXPIRED]:
                self._logger.warning(f"Cannot cancel order {order_id} with status {current_status.value}")
                return False

            # Attempt cancellation via broker
            start_time = time.time()
            success = self.broker_port.cancel_order(order_id)
            latency_ms = int((time.time() - start_time) * 1000)

            if success:
                self._logger.info(f"Order {order_id} cancelled successfully in {latency_ms}ms")
            else:
                self._logger.warning(f"Failed to cancel order {order_id}")

            return success

        except Exception as e:
            self._logger.error(f"Error cancelling order {order_id}: {e}", exc_info=True)
            return False

    def get_order_status(self, order_id: str) -> OrderStatus:
        """
        Get the current status of an order.

        Args:
            order_id: The order ID to check

        Returns:
            Current order status
        """
        if not order_id or order_id in ["duplicate", "error"]:
            return OrderStatus.REJECTED

        try:
            # Query broker for order status
            # Note: This assumes the broker port has a method to get order status
            # In a real implementation, this might involve querying the broker or checking persistence
            if hasattr(self.broker_port, 'get_order_status'):
                return self.broker_port.get_order_status(order_id)
            else:
                # Fallback: assume submitted orders are still pending unless we have other info
                self._logger.debug(f"No direct order status method available for order {order_id}")
                return OrderStatus.SUBMITTED  # Conservative assumption

        except Exception as e:
            self._logger.error(f"Error getting order status for {order_id}: {e}")
            return OrderStatus.REJECTED

    def verify_order_fill(
        self,
        order_id: str,
        timeout_seconds: int = 30
    ) -> dict[str, Any]:
        """
        Verify that an order has been filled and get fill details.

        Args:
            order_id: The order ID to verify
            timeout_seconds: Maximum time to wait for fill confirmation

        Returns:
            Dictionary containing fill verification results
        """
        try:
            start_time = time.time()

            # Use broker's wait_for_fill method if available
            if hasattr(self.broker_port, 'wait_for_fill'):
                fill_ok = self.broker_port.wait_for_fill(order_id, timeout=timeout_seconds)
            else:
                # Fallback: poll for fill status
                fill_ok = self._poll_for_fill_status(order_id, timeout_seconds)

            # Get fill details
            filled_quantity = 0
            average_price = 0.0

            if hasattr(self.broker_port, 'get_filled_quantity'):
                filled_quantity = self.broker_port.get_filled_quantity(order_id) or 0

            if hasattr(self.broker_port, 'get_average_price'):
                average_price = self.broker_port.get_average_price(order_id) or 0.0

            # Verify with terminal check if available
            status_verified = True
            if hasattr(self.broker_port, 'verify_terminal_ok'):
                try:
                    status_verified = self.broker_port.verify_terminal_ok(order_id)
                except Exception:
                    status_verified = False

            latency_ms = int((time.time() - start_time) * 1000)

            result = {
                "ok": bool(fill_ok or filled_quantity > 0),
                "filled_quantity": int(filled_quantity),
                "average_price": float(average_price),
                "status_verified": bool(status_verified),
                "latency_ms": latency_ms,
                "order_id": order_id,
                "timestamp": datetime.now().isoformat()
            }

            self._logger.debug(f"Fill verification for {order_id}: {result}")
            return result

        except Exception as e:
            self._logger.error(f"Error verifying order fill for {order_id}: {e}", exc_info=True)
            return {
                "ok": False,
                "filled_quantity": 0,
                "average_price": 0.0,
                "status_verified": False,
                "latency_ms": int((time.time() - start_time) * 1000) if 'start_time' in locals() else 0,
                "order_id": order_id,
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            }

    def is_duplicate_order(self, idempotency_key: str) -> bool:
        """
        Check if an order with the given idempotency key has already been processed.

        Args:
            idempotency_key: Unique key to check for duplication

        Returns:
            True if order is duplicate, False otherwise
        """
        with self._lock:
            # Clean expired entries first
            self._cleanup_idempotency_cache()

            # Check if key exists in cache
            is_duplicate = idempotency_key in self._idempotency_cache

            if is_duplicate:
                self._logger.debug(f"Duplicate order detected: {idempotency_key}")

            return is_duplicate

    def record_execution_audit(
        self,
        audit_trail: ExecutionAuditTrail
    ) -> bool:
        """
        Record an execution audit trail for compliance and debugging.

        Args:
            audit_trail: The execution audit trail to record

        Returns:
            True if recording successful, False otherwise
        """
        try:
            with self._lock:
                self._executions[audit_trail.execution_id] = audit_trail

                # Also persist to trade persistence if available
                if self.trade_persistence:
                    # Convert audit trail to format suitable for persistence
                    trade_data = self._audit_trail_to_trade_data(audit_trail)
                    if trade_data:
                        self.trade_persistence.save_trade(trade_data)

                self._logger.debug(f"Execution audit recorded: {audit_trail.execution_id}")
                return True

        except Exception as e:
            self._logger.error(f"Error recording execution audit: {e}", exc_info=True)
            return False

    def get_execution_audit_trail(
        self,
        execution_id: str
    ) -> ExecutionAuditTrail | None:
        """
        Retrieve an execution audit trail by ID.

        Args:
            execution_id: The execution ID to retrieve

        Returns:
            ExecutionAuditTrail if found, None otherwise
        """
        with self._lock:
            return self._executions.get(execution_id)

    def health_check(self) -> dict[str, Any]:
        """
        Perform a health check on the execution service.

        Returns:
            Dictionary containing health check results
        """
        try:
            with self._lock:
                # Cleanup expired idempotency entries
                self._cleanup_idempotency_cache()

                # Check broker health
                broker_healthy = True  # Assume healthy if no health_check method
                if hasattr(self.broker_port, 'health_check'):
                    broker_health = self.broker_port.health_check()
                    broker_healthy = broker_health.get("status") == "healthy"

                # Check persistence health
                persistence_healthy = True  # Assume healthy if no health_check method
                if hasattr(self.trade_persistence, 'health_check'):
                    persistence_health = self.trade_persistence.health_check()
                    persistence_healthy = persistence_health.get("status") == "healthy"

                # Determine overall status
                overall_status = "healthy" if (broker_healthy and persistence_healthy) else "unhealthy"

                return {
                    "status": overall_status,
                    "service": "ExecutionService",
                    "broker_healthy": broker_healthy,
                    "persistence_healthy": persistence_healthy
                }

        except Exception as e:
            self._logger.error(f"Error in execution service health check: {e}", exc_info=True)
            return {
                "status": "unhealthy",
                "service": "ExecutionService",
                "error": str(e)
            }

    # Private helper methods

    def _generate_idempotency_key(
        self,
        order_request: OrderRequest,
        execution_context: ExecutionContext
    ) -> str:
        """
        Generate a unique idempotency key for an order request.

        Args:
            order_request: The order request
            execution_context: The execution context

        Returns:
            Unique idempotency key string
        """
        # Create a string representation of the order and context
        key_data = {
            "symbol": order_request.symbol,
            "direction": order_request.direction,
            "strike_price": order_request.strike_price,
            "lot_size": order_request.lot_size,
            "order_type": order_request.order_type.value if isinstance(order_request.order_type, OrderType) else str(order_request.order_type),
            "price": order_request.price,
            "stop_loss": order_request.stop_loss,
            "target": order_request.target,
            "strategy_id": order_request.strategy_id,
            "signal_id": execution_context.signal_id,
            "timestamp": execution_context.signal_timestamp.isoformat() if execution_context.signal_timestamp else None
        }

        # Remove None values
        key_data = {k: v for k, v in key_data.items() if v is not None}

        # Create deterministic hash
        key_string = "&".join(f"{k}={v}" for k, v in sorted(key_data.items()))
        return hashlib.sha256(key_string.encode()).hexdigest()[:32]

    def _store_idempotency_key(self, key: str, order_result: OrderResult) -> None:
        """
        Store an idempotency key and its associated order result in the LRU cache.

        Args:
            key: The idempotency key to store
            order_result: The order result to associate with the key
        """
        with self._lock:
            # Add to cache (front of OrderedDict) as a tuple (timestamp, order_result)
            self._idempotency_cache[key] = (datetime.now(), order_result)
            self._idempotency_cache.move_to_end(key, last=False)  # Most recent at front

            # Trim cache if too large
            while len(self._idempotency_cache) > self.config.idempotency_cache_size:
                self._idempotency_cache.popitem(last=True)  # Remove oldest (last)

    def _get_idempotency_result(self, key: str) -> OrderResult | None:
        """
        Get the cached order result for the given idempotency key, if it exists and is not expired.

        Returns:
            The cached OrderResult if found, None otherwise.
        """
        with self._lock:
            self._cleanup_idempotency_cache()
            if key in self._idempotency_cache:
                return self._idempotency_cache[key][1]  # return the order_result
            return None

    def _cleanup_idempotency_cache(self) -> None:
        """
        Remove expired entries from the idempotency cache.
        """
        with self._lock:
            expiry_time = datetime.now() - timedelta(hours=self.config.idempotency_expiry_hours)

            # Find expired keys - note: value is now (timestamp, order_result)
            expired_keys = [
                key for key, (timestamp, _) in self._idempotency_cache.items()
                if timestamp < expiry_time
            ]

            # Remove expired keys
            for key in expired_keys:
                del self._idempotency_cache[key]

            if expired_keys:
                self._logger.debug(f"Cleaned up {len(expired_keys)} expired idempotency keys")

    def _execute_with_retries(
        self,
        order_request: OrderRequest,
        execution_context: ExecutionContext
    ) -> OrderResult:
        """
        Execute an order with retry mechanism and exponential backoff.

        Args:
            order_request: The order to execute
            execution_context: Execution context

        Returns:
            OrderResult from the execution attempt
        """
        last_exception = None

        for attempt in range(1, self.config.max_retries + 1):
            try:
                # Calculate delay for this attempt (exponential backoff)
                if attempt > 1:
                    delay = min(
                        self.config.base_retry_delay * (self.config.retry_exponential_base ** (attempt - 2)),
                        self.config.max_retry_delay
                    )
                    self._logger.debug(f"Retry attempt {attempt} after {delay:.1f}s delay")
                    time.sleep(delay)

                # Attempt order execution
                result = self._attempt_order_execution(order_request, execution_context)

                # If successful, return immediately
                if result.status == OrderStatus.FILLED:
                    return result
                # Retryable statuses: PENDING, PARTIALLY_FILLED, SUBMITTED
                # These indicate the order was accepted but not yet filled.
                if result.status in [OrderStatus.PARTIALLY_FILLED, OrderStatus.SUBMITTED, OrderStatus.PENDING]:
                    if last_exception is None:
                        last_exception = Exception(f"Order status {result.status.value} may be retryable")
                # REJECTED could be from broker throwing exception with error message in reject_reason
                # Preserve the original error message from the broker's REJECTED result
                elif result.status == OrderStatus.REJECTED and result.reject_reason:
                    if last_exception is None:
                        last_exception = Exception(result.reject_reason)

            except Exception as e:
                last_exception = e
                self._logger.warning(f"Order execution attempt {attempt} failed: {e}")

                # If this is the last attempt, we'll fall through to return the error
                if attempt == self.config.max_retries:
                    break

        # If we exhausted all retries, return the last error
        if last_exception:
            return OrderResult(
                order_id="retry_exhausted",
                status=OrderStatus.REJECTED,
                reject_reason=f"Max retries ({self.config.max_retries}) exceeded: {str(last_exception)}",
                timestamp=datetime.now()
            )

        # Fallback (shouldn't reach here)
        return OrderResult(
            order_id="unknown_error",
            status=OrderStatus.REJECTED,
            reject_reason="Unknown error during order execution retries",
            timestamp=datetime.now()
        )

    def _attempt_order_execution(
        self,
        order_request: OrderRequest,
        execution_context: ExecutionContext
    ) -> OrderResult:
        """
        Attempt a single order execution.

        Args:
            order_request: The order to execute
            execution_context: Execution context

        Returns:
            OrderResult from the execution attempt
        """
        try:
            # Handle paper trading mode
            if (execution_context.execution_mode == ExecutionMode.PAPER or
                getattr(self.broker_port, '__class__.__name__', '') == 'PaperBrokerAdapter'):
                return self._execute_paper_order(order_request, execution_context)

            # Execute via broker port
            if hasattr(self.broker_port, 'place_order'):
                # Use broker's place_order method - it expects an Order object
                place_order_result = self.broker_port.place_order(order_request)

                # Handle case where place_order returns an OrderResult (for test compatibility)
                # or a string order ID (proper broker interface)
                if isinstance(place_order_result, OrderResult):
                    # The broker returned a full OrderResult (test scenario)
                    return place_order_result
                elif isinstance(place_order_result, str):
                    # The broker returned an order ID string (proper interface)
                    order_id = place_order_result

                    # Check if the order was filled immediately by the broker
                    filled_quantity = 0
                    average_price = 0.0
                    if hasattr(self.broker_port, 'get_filled_quantity'):
                        filled_quantity = self.broker_port.get_filled_quantity(order_id) or 0
                    if hasattr(self.broker_port, 'get_average_price'):
                        average_price = self.broker_port.get_average_price(order_id) or 0.0

                    if filled_quantity > 0:
                        # The broker reports that the order was filled
                        return OrderResult(
                            order_id=str(order_id) if order_id else "",
                            status=OrderStatus.FILLED,
                            filled_quantity=filled_quantity,
                            average_price=average_price,
                            commission=0.0,  # TODO: Get commission from broker if available
                            timestamp=datetime.now(),
                            broker_order_id=str(order_id) if order_id else None,
                            broker_timestamp=datetime.now()
                        )
                    else:
                        # The order was placed but not yet filled
                        return OrderResult(
                            order_id=str(order_id) if order_id else "",
                            status=OrderStatus.SUBMITTED if order_id else OrderStatus.REJECTED,
                            broker_order_id=str(order_id) if order_id else None,
                            timestamp=datetime.now()
                        )
                else:
                    # Unexpected return type
                    self._logger.warning(f"Broker place_order returned unexpected type: {type(place_order_result)}")
                    # Fallback: simulate execution for testing
                    self._logger.warning("Broker port does not have place_order method, simulating execution")
                    return self._execute_paper_order(order_request, execution_context)
            else:
                # Fallback: simulate execution for testing
                self._logger.warning("Broker port does not have place_order method, simulating execution")
                return self._execute_paper_order(order_request, execution_context)

        except Exception as e:
            self._logger.error(f"Error during order execution attempt: {e}", exc_info=True)
            return OrderResult(
                order_id="execution_error",
                status=OrderStatus.REJECTED,
                reject_reason=str(e),
                timestamp=datetime.now()
            )

    def _execute_paper_order(
        self,
        order_request: OrderRequest,
        execution_context: ExecutionContext
    ) -> OrderResult:
        """
        Execute a paper/simulated order.

        Args:
            order_request: The order to execute
            execution_context: Execution context

        Returns:
            OrderResult from the paper execution
        """
        try:
            # Simulate network delay
            time.sleep(self.config.paper_fill_delay_ms / 1000.0)

            # Generate a fake order ID
            order_id = f"paper_{int(time.time()*1000)}_{hash(order_request.symbol) % 10000}"

            # Determine fill price based on order type and market conditions
            if order_request.order_type == OrderType.MARKET:
                # For market orders, use current price with slippage
                base_price = self._get_current_price_for_symbol(order_request.symbol)
                slippage = base_price * (self.config.paper_fill_slippage_pct / 100.0)

                if order_request.direction.upper() == "BUY":
                    fill_price = base_price + slippage  # Pay more when buying
                else:
                    fill_price = base_price - slippage  # Receive less when selling

            elif order_request.order_type == OrderType.LIMIT:
                # For limit orders, use the limit price if it would execute
                base_price = self._get_current_price_for_symbol(order_request.symbol)
                if order_request.direction.upper() == "BUY" and order_request.price >= base_price:
                    fill_price = order_request.price
                elif order_request.direction.upper() == "SELL" and order_request.price <= base_price:
                    fill_price = order_request.price
                else:
                    # Limit order would not execute immediately
                    return OrderResult(
                        order_id=order_id,
                        status=OrderStatus.PENDING,
                        reason="Limit order not executed - price not reached",
                        timestamp=datetime.now()
                    )
            else:
                # For other order types (SL, SL-M), use the trigger price or current price
                fill_price = order_request.price or self._get_current_price_for_symbol(order_request.symbol)

            # Apply some randomness to make it feel realistic
            import random
            price_variation = random.uniform(-0.5, 0.5)  # ±0.5 points variation
            fill_price += price_variation

            # Ensure price is positive
            fill_price = max(0.01, fill_price)

            # Calculate commission (simplified)
            commission = abs(fill_price) * order_request.lot_size * 0.0005  # 0.05% commission

            return OrderResult(
                order_id=order_id,
                status=OrderStatus.FILLED,
                filled_quantity=order_request.lot_size,
                average_price=fill_price,
                commission=commission,
                timestamp=datetime.now()
            )

        except Exception as e:
            self._logger.error(f"Error in paper order execution: {e}", exc_info=True)
            return OrderResult(
                order_id="paper_error",
                status=OrderStatus.REJECTED,
                reject_reason=str(e),
                timestamp=datetime.now()
            )

    def _get_current_price_for_symbol(self, symbol: str) -> float:
        """
        Get current price for a symbol (used for paper trading simulation).

        Args:
            symbol: Trading symbol

        Returns:
            Current price for the symbol
        """
        # Check cache first
        if symbol in self._paper_price_cache:
            return self._paper_price_cache[symbol]

        # In a real implementation, this would come from market data
        # For now, return a reasonable default based on symbol
        default_prices = {
            "NIFTY": 19500.0,
            "BANKNIFTY": 44000.0,
            "FINNIFTY": 18500.0,
            "RELIANCE": 2400.0,
            "TCS": 3200.0,
            "HDFCBANK": 1400.0,
            "INFY": 1450.0,
            "ICICIBANK": 850.0,
            "KOTAKBANK": 1650.0,
            "LT": 2800.0,
            "SBIN": 580.0,
            "BHARTIARTL": 820.0,
            "ASIANPAINT": 2900.0,
            "MARUTI": 8800.0,
            "HINDUNILVR": 2200.0,
            "AXISBANK": 900.0
        }

        price = default_prices.get(symbol, 1000.0)  # Default to 1000 if unknown

        # Cache the price for a short time
        self._paper_price_cache[symbol] = price

        # Clear old cache entries periodically (simple approach)
        if len(self._paper_price_cache) > 50:
            # Remove oldest 10 entries
            keys_to_remove = list(self._paper_price_cache.keys())[:10]
            for key in keys_to_remove:
                del self._paper_price_cache[key]

        return price

    def _persist_trade_from_order(
        self,
        order_request: OrderRequest,
        order_result: OrderResult,
        execution_context: ExecutionContext
    ) -> None:
        """
        Persist a trade record from an executed order.

        Args:
            order_request: The original order request
            order_result: The result of the order execution
            execution_context: Execution context
        """
        try:
            if not self.trade_persistence:
                return

            # Only persist filled orders
            if order_result.filled_quantity <= 0:
                return

            # Convert to trade data format
            trade_data = {
                "symbol": order_request.symbol,
                "direction": order_request.direction.upper(),
                "strike_price": order_request.strike_price,
                "lot_size": order_request.lot_size,
                "entry_price": order_result.average_price,
                "entry_time": order_result.timestamp,
                "exit_price": 0.0,  # Will be updated when position is closed
                "exit_time": None,
                "exit_reason": "OPEN",  # Position is still open
                "gross_pnl": 0.0,  # Will be calculated when position is closed
                "brokerage": order_result.commission,
                "taxes": 0.0,  # Simplified - in reality would calculate based on P&L
                "net_pnl": -order_result.commission,  # Negative due to commissions
                "strategy": order_request.strategy_id or "UNKNOWN",
                "tags": [],  # Empty tags for now
                "regime_at_entry": None,  # Would come from market data/context
                "session_at_entry": None,  # Would come from market data/context
                "created_at": order_result.timestamp
            }

            # Save the trade record
            trade_id = self.trade_persistence.save_trade(trade_data)
            self._logger.debug(f"Trade persisted with ID {trade_id} from order {order_result.order_id}")

        except Exception as e:
            self._logger.error(f"Error persisting trade from order: {e}", exc_info=True)

    def _audit_trail_to_trade_data(
        self,
        audit_trail: ExecutionAuditTrail
    ) -> dict[str, Any] | None:
        """
        Convert an execution audit trail to trade data for persistence.

        Args:
            audit_trail: The execution audit trail to convert

        Returns:
            Trade data dictionary, or None if conversion fails
        """
        try:
            # This is a simplified conversion - in reality would be more complex
            if not audit_trail.order_result or audit_trail.order_result.filled_quantity <= 0:
                return None

            order_req = audit_trail.order_request
            order_res = audit_trail.order_result

            return {
                "symbol": order_req.symbol,
                "direction": order_req.direction.upper(),
                "strike_price": order_req.strike_price,
                "lot_size": order_req.lot_size,
                "entry_price": order_res.average_price,
                "entry_time": order_res.timestamp,
                "exit_price": 0.0,
                "exit_time": None,
                "exit_reason": "OPEN",
                "gross_pnl": 0.0,
                "brokerage": order_res.commission,
                "taxes": 0.0,
                "net_pnl": -order_res.commission,
                "strategy": order_req.strategy_id or "UNKNOWN",
                "tags": [],
                "regime_at_entry": None,
                "session_at_entry": None,
                "created_at": order_res.timestamp
            }
        except Exception as e:
            self._logger.error(f"Error converting audit trail to trade data: {e}")
            return None

    def _poll_for_fill_status(
        self,
        order_id: str,
        timeout_seconds: int
    ) -> bool:
        """
        Poll for fill status when broker doesn't have wait_for_fill method.

        Args:
            order_id: The order ID to poll
            timeout_seconds: Maximum time to poll

        Returns:
            True if order filled, False if timeout
        """
        start_time = time.time()
        poll_interval = 0.5  # Start with 500ms intervals
        max_poll_interval = 5.0  # Max 5 seconds between polls

        while (time.time() - start_time) < timeout_seconds:
            try:
                # Check if we have a way to get filled quantity
                if hasattr(self.broker_port, 'get_filled_quantity'):
                    filled_qty = self.broker_port.get_filled_quantity(order_id) or 0
                    if filled_qty > 0:
                        return True
                elif hasattr(self.broker_port, 'get_order_status'):
                    status = self.broker_port.get_order_status(order_id)
                    if status in [OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED]:
                        return True

                # Wait before next poll (with exponential backoff)
                time.sleep(min(poll_interval, max_poll_interval))
                poll_interval = min(poll_interval * 1.5, max_poll_interval)  # Exponential backoff

            except Exception as e:
                self._logger.debug(f"Error polling for fill status: {e}")
                time.sleep(poll_interval)

        return False  # Timeout reached
