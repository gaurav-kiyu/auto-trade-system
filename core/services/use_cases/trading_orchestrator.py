"""
Trading Orchestrator - Main Application Service

This orchestrator demonstrates the complete execution flow:
market data → signal generation → validation → ML inference → risk evaluation →
execution decision → broker routing → reconciliation → state persistence →
analytics/reporting → alerts

This is the main application service that coordinates all domain services
through well-defined interfaces, following the Clean Architecture principles.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from core.domains.execution.model import Fill, Order, OrderResult
from core.domains.ml.model import MLConfidence, MLPrediction
from core.domains.risk.model import RiskDecision

# Import domain models and ports (interfaces)
from core.domains.signal_engine.model import SignalQuality, TradingSignal
from core.domains.state.model import TradingState
from core.domains.strategy.model import StrategyDecision
from core.ports.config import ConfigPort
from core.ports.execution import ExecutionPort

# Import ports (interfaces) that this orchestrator depends on
from core.ports.market_data import MarketDataPort
from core.ports.ml_model import MlModelPort
from core.ports.notification import NotificationPort
from core.ports.persistence import PersistencePort
from core.ports.risk import RiskPort

# Import shared kernels and utilities
from core.common.kernels.correlation_id import CorrelationIdManager
from core.common.utilities.logging import StructuredLogger
from core.common.utilities.metrics import MetricsCollector
from core.common.utilities.result import Failure, Result, Success


@dataclass
class OrchestratorConfig:
    """Configuration for the trading orchestrator."""
    symbol: str
    strategy_name: str
    max_position_size: int
    enable_ml_enhancement: bool = True
    enable_risk_checks: bool = True
    enable_persistence: bool = True
    enable_notifications: bool = True
    paper_trading: bool = True


class TradingOrchestrator:
    """
    Main orchestrator for the trading system.

    This class demonstrates the complete execution flow by coordinating
    various domain services through well-defined interfaces.
    """

    def __init__(
        self,
        market_data_port: MarketDataPort,
        ml_model_port: MlModelPort,
        risk_port: RiskPort,
        execution_port: ExecutionPort,
        persistence_port: PersistencePort,
        notification_port: NotificationPort,
        config_port: ConfigPort,
        correlation_id_manager: CorrelationIdManager,
        metrics_collector: MetricsCollector,
        logger: StructuredLogger
    ):
        self.market_data = market_data_port
        self.ml_model = ml_model_port
        self.risk_engine = risk_port
        self.execution_engine = execution_port
        self.persistence = persistence_port
        self.notification = notification_port
        self.config = config_port
        self.correlation_id = correlation_id_manager
        self.metrics = metrics_collector
        self.logger = logger

        # Internal state
        self._current_state: TradingState | None = None
        self._last_signal_time: datetime | None = None

    def process_trading_cycle(self, symbol: str) -> Result[None, str]:
        """
        Execute one complete trading cycle.

        This demonstrates the full flow:
        1. Market data acquisition
        2. Signal generation
        3. Signal validation
        4. ML enhancement (optional)
        5. Risk evaluation
        6. Execution decision
        7. Broker routing
        8. Fill handling & reconciliation
        9. State persistence
        10. Analytics & reporting
        11. Alerting & notifications

        Args:
            symbol: Trading symbol to process

        Returns:
            Result indicating success or failure with error message
        """
        # Generate correlation ID for this trading cycle
        corr_id = self.correlation_id.generate_id()

        with self.logger.contextualize(correlation_id=corr_id, symbol=symbol):
            self.logger.info("Starting trading cycle")

            try:
                # Step 1: Market Data Acquisition
                market_data_result = self._acquire_market_data(symbol)
                if market_data_result.is_failure:
                    return market_data_result

                market_data = market_data_result.unwrap()

                # Step 2: Signal Generation
                signal_result = self._generate_trading_signal(market_data, symbol)
                if signal_result.is_failure:
                    return signal_result

                trading_signal = signal_result.unwrap()

                # Skip if signal quality is too low
                if trading_signal.quality == SignalQuality.WEAK:
                    self.logger.info("Signal quality too weak, skipping")
                    return Success(None)

                # Step 3: Signal Validation (basic checks)
                validation_result = self._validate_signal(trading_signal)
                if validation_result.is_failure:
                    return validation_result

                # Step 4: ML Enhancement (if enabled)
                enhanced_signal_result = self._enhance_with_ml(trading_signal, market_data)
                if enhanced_signal_result.is_failure:
                    return enhanced_signal_result

                final_signal = enhanced_signal_result.unwrap()

                # Step 5: Strategy Decision
                strategy_decision_result = self._make_strategy_decision(final_signal)
                if strategy_decision_result.is_failure:
                    return strategy_decision_result

                strategy_decision = strategy_decision_result.unwrap()

                # Skip if strategy says no action
                if not strategy_decision.should_trade:
                    self.logger.info("Strategy decision: no trade")
                    return Success(None)

                # Step 6: Risk Evaluation
                risk_decision_result = self._evaluate_risk(strategy_decision, symbol)
                if risk_decision_result.is_failure:
                    return risk_decision_result

                risk_decision = risk_decision_result.unwrap()

                # Skip if risk says no
                if not risk_decision.allowed:
                    self.logger.info(f"Risk rejecting trade: {risk_decision.reason}")
                    # Send notification about risk rejection
                    if self.config.get_bool("notify_on_risk_reject", False):
                        self._send_risk_rejection_notification(strategy_decision, risk_decision)
                    return Success(None)

                # Step 7: Execution Decision & Sizing
                order_result = self._create_execution_order(
                    strategy_decision, risk_decision, symbol
                )
                if order_result.is_failure:
                    return order_result

                order = order_result.unwrap()

                # Step 8: Broker Routing
                execution_result = self._route_to_broker(order)
                if execution_result.is_failure:
                    return execution_result

                order_result_obj = execution_result.unwrap()

                # Step 9: Fill Handling & Reconciliation
                fill_result = self._process_fills(order_result_obj, symbol)
                if fill_result.is_failure:
                    return fill_result

                fills = fill_result.unwrap()

                # Step 10: State Persistence
                if self.config.get_bool("enable_persistence", True):
                    persistence_result = self._persist_state(
                        order, fills, strategy_decision, risk_decision
                    )
                    if persistence_result.is_failure:
                        # Log but don't fail the cycle for persistence issues
                        self.logger.warning(
                            "Failed to persist state",
                            error=persistence_result.failure()
                        )

                # Step 11: Analytics & Reporting
                analytics_result = self._update_analytics(
                    order, fills, strategy_decision
                )
                if analytics_result.is_failure:
                    self.logger.warning(
                        "Failed to update analytics",
                        error=analytics_result.failure()
                    )

                # Step 12: Alerting & Notifications
                if self.config.get_bool("enable_notifications", True):
                    notification_result = self._send_trade_notifications(
                        order, fills, strategy_decision
                    )
                    if notification_result.is_failure:
                        self.logger.warning(
                            "Failed to send notifications",
                            error=notification_result.failure()
                        )

                self.logger.info("Trading cycle completed successfully")
                return Success(None)

            except Exception as e:
                self.logger.error("Unexpected error in trading cycle", error=str(e))
                self.metrics.increment("trading_cycle.errors")
                return Failure(f"Unexpected error: {str(e)}")

    # Private helper methods demonstrating each step of the flow

    def _acquire_market_data(self, symbol: str) -> Result[Any, str]:
        """Step 1: Acquire and validate market data."""
        self.logger.debug("Acquiring market data")
        self.metrics.increment("market_data.requests")

        start_time = time.time()
        try:
            market_data = self.market_data.get_latest_data(symbol)

            # Validate data freshness
            if not self.market_data.is_data_fresh(market_data, max_age_seconds=30):
                return Failure("Market data is stale")

            latency_ms = (time.time() - start_time) * 1000
            self.metrics.timing("market_data.latency_ms", latency_ms)

            self.logger.debug("Market data acquired successfully",
                            data_points=len(market_data) if hasattr(market_data, '__len__') else 'unknown')
            return Success(market_data)

        except Exception as e:
            self.metrics.increment("market_data.errors")
            return Failure(f"Failed to acquire market data: {str(e)}")

    def _generate_trading_signal(self, market_data: Any, symbol: str) -> Result[TradingSignal, str]:
        """Step 2: Generate trading signal from market data."""
        self.logger.debug("Generating trading signal")

        try:
            # This would typically involve:
            # - Technical indicator calculations
            # - Pattern recognition
            # - Order flow analysis
            # - etc.

            signal = self._create_signal_from_data(market_data, symbol)
            self.logger.debug("Trading signal generated",
                            signal_strength=signal.strength,
                            quality=signal.quality.name)
            return Success(signal)

        except Exception as e:
            return Failure(f"Failed to generate trading signal: {str(e)}")

    def _validate_signal(self, signal: TradingSignal) -> Result[None, str]:
        """Step 3: Validate trading signal."""
        self.logger.debug("Validating trading signal")

        # Basic signal validation
        if signal.strength < 0.1:  # Arbitrary threshold
            return Failure("Signal strength too low")

        if not signal.is_valid():
            return Failure("Signal failed validation checks")

        return Success(None)

    def _enhance_with_ml(self, signal: TradingSignal, market_data: Any) -> Result[TradingSignal, str]:
        """Step 4: Enhance signal with ML predictions (if enabled)."""
        if not self.config.get_bool("enable_ml_enhancement", True):
            return Success(signal)  # Return unchanged if ML disabled

        self.logger.debug("Enhancing signal with ML")

        try:
            # Prepare features for ML model
            features = self._extract_features_for_ml(signal, market_data)

            # Get ML prediction
            ml_prediction: MLPrediction = self.ml_model.predict_win_probability(features)

            # Adjust signal based on ML confidence
            if ml_prediction.confidence == MLConfidence.HIGH:
                # Boost signal strength
                enhanced_signal = TradingSignal(
                    symbol=signal.symbol,
                    strength=min(1.0, signal.strength * 1.2),
                    direction=signal.direction,
                    quality=SignalQuality.STRONG,
                    timestamp=signal.timestamp,
                    metadata={**signal.metadata, "ml_enhanced": True, "ml_confidence": ml_prediction.confidence.value}
                )
            elif ml_prediction.confidence == MLConfidence.LOW:
                # Reduce signal strength or mark as weak
                enhanced_signal = TradingSignal(
                    symbol=signal.symbol,
                    strength=signal.strength * 0.5,
                    direction=signal.direction,
                    quality=SignalQuality.WEAK,
                    timestamp=signal.timestamp,
                    metadata={**signal.metadata, "ml_enhanced": True, "ml_confidence": ml_prediction.confidence.value}
                )
            else:
                # Medium confidence - slight adjustment
                enhanced_signal = TradingSignal(
                    symbol=signal.symbol,
                    strength=signal.strength * (0.8 + ml_prediction.prediction_value * 0.4),
                    direction=signal.direction,
                    quality=signal.quality,
                    timestamp=signal.timestamp,
                    metadata={**signal.metadata, "ml_enhanced": True, "ml_confidence": ml_prediction.confidence.value}
                )

            self.logger.debug("Signal enhanced with ML",
                            original_strength=signal.strength,
                            enhanced_strength=enhanced_signal.strength,
                            ml_prediction=ml_prediction.prediction_value)

            return Success(enhanced_signal)

        except Exception as e:
            self.logger.warning("ML enhancement failed, using original signal", error=str(e))
            # Return original signal on ML failure - fail soft
            return Success(signal)

    def _make_strategy_decision(self, signal: TradingSignal) -> Result[StrategyDecision, str]:
        """Step 5: Make strategy decision based on signal."""
        self.logger.debug("Making strategy decision")

        try:
            # This would involve:
            # - Checking strategy rules
            # - Position limits
            # - Time-based constraints
            # - etc.

            # Simplified example
            should_trade = (
                signal.quality in [SignalQuality.STRONG, SignalQuality.MODERATE] and
                signal.strength > 0.3
            )

            decision = StrategyDecision(
                should_trade=should_trade,
                direction=signal.direction,
                suggested_size=0,  # Will be determined by risk engine
                reason=f"Signal quality: {signal.quality.name}, strength: {signal.strength:.2f}",
                strategy_name=self.config.get("strategy.name", "default"),
                metadata={"signal_strength": signal.strength, "signal_quality": signal.quality.name}
            )

            return Success(decision)

        except Exception as e:
            return Failure(f"Failed to make strategy decision: {str(e)}")

    def _evaluate_risk(self, strategy_decision: StrategyDecision, symbol: str) -> Result[RiskDecision, str]:
        """Step 6: Evaluate risk for the proposed trade."""
        if not self.config.get_bool("enable_risk_checks", True):
            # Return approved risk decision if risk checks disabled
            return Success(RiskDecision(
                allowed=True,
                reason="Risk checks disabled",
                suggested_size=1  # Default size
            ))

        self.logger.debug("Evaluating risk")

        try:
            # Get current portfolio state for risk calculation
            portfolio_state = self._get_current_portfolio_state()

            # Evaluate risk
            risk_decision = self.risk_engine.evaluate_trade(
                symbol=symbol,
                direction=strategy_decision.direction,
                suggested_size=strategy_decision.suggested_size,
                portfolio_state=portfolio_state,
                market_conditions=self._get_current_market_conditions()
            )

            self.logger.debug("Risk evaluation completed",
                            allowed=risk_decision.allowed,
                            reason=risk_decision.reason,
                            suggested_size=risk_decision.suggested_size)

            return Success(risk_decision)

        except Exception as e:
            return Failure(f"Risk evaluation failed: {str(e)}")

    def _create_execution_order(
        self,
        strategy_decision: StrategyDecision,
        risk_decision: RiskDecision,
        symbol: str
    ) -> Result[Order, str]:
        """Step 7: Create execution order based on strategy and risk decisions."""
        self.logger.debug("Creating execution order")

        try:
            # Determine final order size based on risk decision
            order_size = risk_decision.suggested_size

            # Apply any strategy-specific sizing adjustments
            final_size = self._apply_strategy_sizing(
                order_size, strategy_decision, risk_decision
            )

            # Create the order
            order = Order(
                symbol=symbol,
                direction=strategy_decision.direction,
                quantity=final_size,
                order_type="MARKET",  # Could be configurable
                price=None,  # Market order
                strategy_id=strategy_decision.strategy_name,
                risk_decision_id=risk_decision.reason,  # Simplified
                timestamp=datetime.now()
            )

            self.logger.debug("Execution order created",
                            symbol=symbol,
                            direction=strategy_decision.direction,
                            quantity=final_size)

            return Success(order)

        except Exception as e:
            return Failure(f"Failed to create execution order: {str(e)}")

    def _route_to_broker(self, order: Order) -> Result[OrderResult, str]:
        """Step 8: Route order to broker for execution."""
        self.logger.debug("Routing order to broker")

        try:
            # Execute the order through the broker interface
            order_result = self.execution_engine.execute_order(order)

            self.logger.debug("Order executed by broker",
                            order_id=order_result.order_id,
                            status=order_result.status.name,
                            filled_quantity=order_result.filled_quantity)

            return Success(order_result)

        except Exception as e:
            return Failure(f"Broker execution failed: {str(e)}")

    def _process_fills(self, order_result: OrderResult, symbol: str) -> Result[list[Fill], str]:
        """Step 9: Process fills and perform reconciliation."""
        self.logger.debug("Processing fills")

        try:
            # If order wasn't filled, return empty fills list
            if order_result.filled_quantity == 0:
                return Success([])

            # Create fill objects from order result
            fills = [
                Fill(
                    order_id=order_result.order_id,
                    fill_id=f"fill_{order_result.order_id}_{int(datetime.now().timestamp())}",
                    symbol=symbol,
                    quantity=order_result.filled_quantity,
                    price=order_result.average_price or 0.0,
                    timestamp=datetime.now(),
                    commission=order_result.commission or 0.0,
                    liquidity_flag="unknown"
                )
            ]

            # Perform reconciliation (verify fill matches expectations)
            reconciliation_result = self._reconcile_fills(order_result, fills)
            if reconciliation_result.is_failure:
                self.logger.warning("Fill reconciliation failed",
                                  error=reconciliation_result.failure())
                # Don't fail the cycle for reconciliation issues

            self.logger.debug("Fills processed",
                            fill_count=len(fills),
                            total_quantity=sum(f.quantity for f in fills))

            return Success(fills)

        except Exception as e:
            return Failure(f"Failed to process fills: {str(e)}")

    def _persist_state(
        self,
        order: Order,
        fills: list[Fill],
        strategy_decision: StrategyDecision,
        risk_decision: RiskDecision
    ) -> Result[None, str]:
        """Step 10: Persist trading state."""
        self.logger.debug("Persisting trading state")

        try:
            # Create state snapshot
            state_snapshot = TradingState(
                timestamp=datetime.now(),
                last_order=order,
                last_fills=fills,
                last_strategy_decision=strategy_decision,
                last_risk_decision=risk_decision,
                portfolio_snapshot=self._get_current_portfolio_state()
            )

            # Persist state
            self.persistence.save_state(state_snapshot)

            # Also persist individual trades for analytics
            for fill in fills:
                trade_record = self._create_trade_record(order, fill, strategy_decision)
                self.persistence.save_trade(trade_record)

            self.logger.debug("State persisted successfully")
            return Success(None)

        except Exception as e:
            return Failure(f"Failed to persist state: {str(e)}")

    def _update_analytics(
        self,
        order: Order,
        fills: list[Fill],
        strategy_decision: StrategyDecision
    ) -> Result[None, str]:
        """Step 11: Update analytics and metrics."""
        self.logger.debug("Updating analytics")

        try:
            # Update performance metrics
            if fills:
                total_pnl = sum(
                    (fill.price - order.price) * fill.quantity
                    for fill in fills
                    if order.price is not None
                )

                self.metrics.record("trade.pnl", total_pnl)
                self.metrics.increment("trades.total")
                if total_pnl > 0:
                    self.metrics.increment("trades.winning")
                else:
                    self.metrics.increment("trades.losing")

            # Update strategy performance
            self.metrics.record(f"strategy.{strategy_decision.strategy_name}.usage", 1)

            # Update risk metrics
            portfolio_risk = self._get_current_portfolio_risk()
            self.metrics.record("portfolio.risk_score", portfolio_risk)

            self.logger.debug("Analytics updated")
            return Success(None)

        except Exception as e:
            return Failure(f"Failed to update analytics: {str(e)}")

    def _send_trade_notifications(
        self,
        order: Order,
        fills: list[Fill],
        strategy_decision: StrategyDecision
    ) -> Result[None, str]:
        """Step 12: Send trade notifications."""
        self.logger.debug("Sending trade notifications")

        try:
            if not fills:
                # No fills to report
                return Success(None)

            # Create trade notification
            notification = self._create_trade_notification(order, fills, strategy_decision)

            # Send through notification service
            self.notification.send_notification(notification)

            self.logger.debug("Trade notifications sent")
            return Success(None)

        except Exception as e:
            return Failure(f"Failed to send notifications: {str(e)}")

    # Helper methods (simplified implementations)

    def _get_current_portfolio_state(self) -> Any:
        """Get current portfolio state for risk calculations."""
        # In a real implementation, this would retrieve current positions, PnL, etc.
        return {}  # Simplified

    def _get_current_market_conditions(self) -> dict[str, Any]:
        """Get current market conditions for risk assessment."""
        return {
            "volatility": "medium",
            "liquidity": "normal",
            "trend": "neutral"
        }

    def _apply_strategy_sizing(
        self,
        base_size: int,
        strategy_decision: StrategyDecision,
        risk_decision: RiskDecision
    ) -> int:
        """Apply strategy-specific sizing adjustments."""
        # Apply any strategy-specific multipliers
        strategy_multiplier = self.config.get_float(
            f"strategy.{strategy_decision.strategy_name}.size_multiplier",
            1.0
        )

        adjusted_size = int(base_size * strategy_multiplier)

        # Ensure we don't exceed maximum position size
        max_size = self.config.get_int("max_position_size", 100)
        return min(adjusted_size, max_size)

    def _reconcile_fills(self, order_result: OrderResult, fills: list[Fill]) -> Result[None, str]:
        """Reconcile expected order with actual fills."""
        # Simplified reconciliation
        expected_qty = order_result.filled_quantity
        actual_qty = sum(fill.quantity for fill in fills)

        if expected_qty != actual_qty:
            return Failure(f"Fill quantity mismatch: expected {expected_qty}, got {actual_qty}")

        return Success(None)

    def _create_trade_record(self, order: Order, fill: Fill, strategy_decision: StrategyDecision) -> Any:
        """Create a trade record for persistence."""
        # Simplified trade record
        return {
            "order_id": order.order_id,
            "fill_id": getattr(fill, 'fill_id', 'unknown'),
            "symbol": order.symbol,
            "direction": order.direction,
            "quantity": fill.quantity,
            "price": fill.price,
            "timestamp": fill.timestamp.isoformat(),
            "strategy": strategy_decision.strategy_name,
            "pnl": 0.0  # Would be calculated properly
        }

    def _create_trade_notification(self, order: Order, fills: list[Fill], strategy_decision: StrategyDecision) -> Any:
        """Create a trade notification."""
        # Simplified notification
        return {
            "type": "trade_execution",
            "order_id": order.order_id,
            "symbol": order.symbol,
            "direction": order.direction,
            "quantity": sum(f.quantity for f in fills),
            "price": sum(f.price * f.quantity for f in fills) / sum(f.quantity for f in fills) if fills else 0,
            "strategy": strategy_decision.strategy_name,
            "timestamp": datetime.now().isoformat()
        }

    def _send_risk_rejection_notification(
        self,
        strategy_decision: StrategyDecision,
        risk_decision: RiskDecision
    ) -> None:
        """Send notification about risk rejection."""
        try:
            notification = {
                "type": "risk_rejection",
                "symbol": strategy_decision.direction,  # Simplified
                "reason": risk_decision.reason,
                "strategy": strategy_decision.strategy_name,
                "timestamp": datetime.now().isoformat()
            }
            self.notification.send_notification(notification)
        except Exception:
            # Don't let notification failures affect trading
            pass

    def _extract_features_for_ml(self, signal: TradingSignal, market_data: Any) -> list[float]:
        """Extract features for ML model."""
        # Simplified feature extraction
        return [
            signal.strength,
            1.0 if signal.direction == "BUY" else 0.0,
            (signal.timestamp.hour + signal.timestamp.minute / 60.0) / 24.0,  # Time of day feature
            len(getattr(signal, 'metadata', {})) / 10.0  # Metadata feature
        ]

    def _create_signal_from_data(self, market_data: Any, symbol: str) -> TradingSignal:
        """Create a trading signal from market data (simplified)."""
        # In reality, this would involve complex technical analysis
        # For demonstration, we'll create a basic signal

        # Use market data to generate a deterministic signal if possible
        strength = 0.5  # default
        if isinstance(market_data, dict) and 'close' in market_data:
            close_list = market_data['close']
            if isinstance(close_list, list) and len(close_list) > 0:
                # Use the last close price
                close_price = close_list[-1]
                # Normalize to [0, 1] by taking the fractional part of the price divided by 100
                strength = (close_price % 100) / 100.0

        direction = "BUY" if strength > 0.5 else "SELL"

        # Determine quality based on strength
        if strength > 0.7:
            quality = SignalQuality.STRONG
        elif strength > 0.4:
            quality = SignalQuality.MODERATE
        else:
            quality = SignalQuality.WEAK

        return TradingSignal(
            symbol=symbol,
            strength=strength,
            direction=direction,
            quality=quality,
            timestamp=datetime.now(),
            metadata={"generated_by": "demo_orchestrator"}
        )

    def _get_current_portfolio_risk(self) -> float:
        """Get current portfolio risk score."""
        # Simplified risk calculation
        return 0.3  # 30% risk utilization


# Example usage
if __name__ == "__main__":
    # This would normally be set up through dependency injection
    # For demonstration, we show how the orchestrator would be used

    print("Trading Orchestrator Example")
    print("=" * 40)
    print("This example demonstrates the clean architecture approach")
    print("where the orchestrator coordinates all services through interfaces.")
    print("")
    print("Execution Flow:")
    print("1. Market Data Acquisition")
    print("2. Signal Generation")
    print("3. Signal Validation")
    print("4. ML Enhancement (optional)")
    print("5. Strategy Decision")
    print("6. Risk Evaluation")
    print("7. Order Creation")
    print("8. Broker Routing")
    print("9. Fill Processing")
    print("10. State Persistence")
    print("11. Analytics Update")
    print("12. Notifications")
    print("")
    print("Key Benefits:")
    print("- Separation of Concerns")
    print("- Testability")
    print("- Maintainability")
    print("- Flexibility to swap implementations")
    print("- Clear dependency flow")
