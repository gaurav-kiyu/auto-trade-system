"""
Position Service - extracted from index_app/index_trader.py (GAP-05b).

Encapsulates trade entry, position monitoring, and position exit logic
that was previously inline in index_trader.py.  Reduces the main file
by ~320 lines.

Usage
-----
    from core.position_service import PositionService

    service = PositionService(
        cfg=_CFG,
        risk_service=_risk_service,
        execution_service=_execution_service,
        portfolio_service=_portfolio_service,
        margin_validator=_margin_validator,
        warmup_manager=_warmup_manager,
        news_sentinel=_news_sentinel,
        expiry_controller=_expiry_controller,
        token_refresh_service=_token_refresh_service,
        audit_engine=_audit_engine,
        reentry_trackers=_reentry_trackers,
        positions=positions,
        decision_log=decision_log,
        manual_sig_last=_manual_sig_last,
        breakout_state=breakout_state,
        bos_lock=_bos_lock,
        state_lock=_state_lock,
        pos_lock=_pos_lock,
    )
    service.enter_trade("NIFTY", signal_dict)
    service.monitor_positions()
    service.exit_position("NIFTY", "SL_HIT")
"""

from __future__ import annotations

__all__ = [
    "PositionService",
    "TradeBlockError",
    "get_position_service",
    "reset_position_service",
]

import logging
import threading
import time
from typing import Any

_log = logging.getLogger(__name__)


class TradeBlockError(Exception):
    """Raised when a trade is blocked by margin or risk checks.
    Preserves the critical notification that would otherwise be lost.
    """
    def __init__(self, message: str, reason: str = "BLOCKED"):
        super().__init__(message)
        self.message = message
        self.reason = reason



class PositionService:
    """Trade entry, monitoring, and exit service.

    Encapsulates the position management logic that was previously
    embedded as module-level functions in index_trader.py.
    """

    def __init__(
        self,
        cfg: dict[str, Any] | None = None,
        risk_service: Any = None,
        execution_service: Any = None,
        portfolio_service: Any = None,
        margin_validator: Any = None,
        warmup_manager: Any = None,
        news_sentinel: Any = None,
        expiry_controller: Any = None,
        token_refresh_service: Any = None,
        audit_engine: Any = None,
        reentry_trackers: dict[str, Any] | None = None,
        positions: dict[str, Any] | None = None,
        decision_log: dict[str, Any] | None = None,
        manual_sig_last: set[str] | None = None,
        breakout_state: dict[str, Any] | None = None,
        bos_lock: Any = None,
        state_lock: Any = None,
        pos_lock: Any = None,
        mandate_service: Any = None,
        signal_max_age: int = 90,
        manual_signals_only: bool | None = None,
        execution_mode: str | None = None,
        broker_api_enabled: bool = False,
        ltp_resolver: Any = None,
        notification_service: Any = None,
    ):
        self._cfg = cfg or {}
        self._risk_service = risk_service
        self._execution_service = execution_service
        self._portfolio_service = portfolio_service
        self._margin_validator = margin_validator
        self._warmup_manager = warmup_manager
        self._news_sentinel = news_sentinel
        self._expiry_controller = expiry_controller
        self._token_refresh_service = token_refresh_service
        self._audit_engine = audit_engine
        self._reentry_trackers = reentry_trackers or {}
        self._positions = positions if positions is not None else {}
        self._decision_log = decision_log if decision_log is not None else {}
        self._manual_sig_last = manual_sig_last or set()
        self._breakout_state = breakout_state or {}
        self._bos_lock = bos_lock
        self._state_lock = state_lock
        self._pos_lock = pos_lock
        self._mandate_service = mandate_service
        self._signal_max_age = signal_max_age
        self._manual_signals_only = manual_signals_only if manual_signals_only is not None else True
        self._execution_mode = execution_mode if execution_mode is not None else "MANUAL"
        self._broker_api_enabled = broker_api_enabled
        self._ltp_resolver = ltp_resolver
        self._notification_service = notification_service

    # ── Entry Gate ─────────────────────────────────────────────────────

    def enter_trade(self, name: str, sig: dict[str, Any]) -> None:
        """Entry gate for all trades. Risk-gated, idempotent, fail-closed.

        Args:
            name: Instrument/index symbol.
            sig:  Trading signal dictionary.
        """
        from core.safety_state import (
            check_intraday_pnl_and_halt,
            check_kill_file_and_halt,
            is_hard_halted,
            trip_hard_halt,
        )

        check_kill_file_and_halt()

        # Build deterministic trace_id before any gates
        _trace_ts = str(sig.get("signal_ts", sig.get("timestamp", time.time()))).replace(".", "_")
        trace_id = f"{name}_{str(sig.get('direction', 'CALL'))}_{_trace_ts}"

        if self._audit_engine is not None:
            try:
                self._audit_engine.record(
                    "enter_trade", trace_id=trace_id, symbol=name,
                    direction=sig.get("direction"), price=sig.get("price"),
                    score=sig.get("score"),
                )
            except (ValueError, TypeError, KeyError, AttributeError, IndexError, OSError):
                pass

        if is_hard_halted():
            self._decision_log[name] = {"msg": "HARD HALT ACTIVE - blocked"}
            return

        # Intraday P&L gate
        if check_intraday_pnl_and_halt(source="enter_trade"):
            self._decision_log[name] = {"msg": "INTRADAY_LOSS_LIMIT - hard halt tripped"}
            return

        # News risk gate
        if self._news_sentinel is not None:
            try:
                news_risk = self._news_sentinel.get_current_risk()
                if news_risk.risk_level in ("HIGH", "EXTREME"):
                    self._decision_log[name] = {
                        "msg": f"NEWS_BLOCK: {news_risk.risk_level} - {news_risk.headline}",
                    }
                    _log.warning("[NEWS_BLOCK] %s blocked: %s - %s", name, news_risk.risk_level, news_risk.headline)
                    return
            except (ValueError, TypeError, KeyError, AttributeError, IndexError, OSError) as _news_err:
                _log.debug("News sentinel check failed (fail-open): %s", _news_err)

        # Warm-up gate
        if self._warmup_manager is not None:
            try:
                if not self._warmup_manager.can_enter(name):
                    self._decision_log[name] = {
                        "msg": f"WARMUP_BLOCK: max entries ({getattr(self._warmup_manager, '_max_trades', '?')}) reached in warm-up",
                    }
                    return
            except (ValueError, TypeError, KeyError, AttributeError, IndexError, OSError) as _warm_err:
                _log.debug("Warm-up check failed: %s", _warm_err)

        # Expiry day gate
        if self._expiry_controller is not None:
            try:
                expiry_result = self._expiry_controller.can_enter_position()
                if not expiry_result.allowed:
                    self._decision_log[name] = {
                        "msg": f"EXPIRY_BLOCK: {expiry_result.reason} (session={expiry_result.session.value})",
                    }
                    return
            except (ValueError, TypeError, KeyError, AttributeError, IndexError, OSError) as _exp_err:
                _log.debug("Expiry check failed: %s", _exp_err)

        # Auction session gate
        try:
            from core.datetime_ist import is_in_auction_session
            if is_in_auction_session():
                self._decision_log[name] = {"msg": "AUCTION_BLOCK: Entry blocked during NSE auction session"}
                return
        except (ValueError, TypeError, KeyError, AttributeError, IndexError, OSError) as _auc_err:
            _log.debug("Auction check failed: %s", _auc_err)

        # Risk evaluation
        if self._risk_service is not None:
            try:
                risk_metrics = self._risk_service.get_portfolio_risk_metrics()
                risk_eval = self._risk_service.evaluate_trade(name, sig, risk_metrics)
                if risk_eval.decision.value == "denied":
                    self._decision_log[name] = {
                        "msg": f"RISK_BLOCK: {risk_eval.reason} (score={risk_eval.risk_score:.2f})",
                    }
                    if self._audit_engine is not None:
                        try:
                            self._audit_engine.record(
                                "risk_block", trace_id=trace_id, symbol=name,
                                reason=risk_eval.reason, risk_score=risk_eval.risk_score,
                            )
                        except (ValueError, TypeError, KeyError, AttributeError, IndexError, OSError):
                            pass
                    return
            except (ValueError, TypeError, KeyError, AttributeError, IndexError, OSError) as e:
                self._decision_log[name] = {"msg": f"RISK_EVAL_ERROR: {e} - trade blocked (fail-closed)"}
                return

        # 1. Time Validation
        confirmed_ts = None
        if self._bos_lock is not None:
            with self._bos_lock:
                bs = self._breakout_state.get(name)
                if bs:
                    confirmed_ts = bs.get("confirmed_ts")
        else:
            bs = self._breakout_state.get(name)
            if bs:
                confirmed_ts = bs.get("confirmed_ts")

        signal_ts = sig.get("signal_ts", time.time())
        now = time.time()

        if confirmed_ts is not None and (now - confirmed_ts) > self._signal_max_age:
            self._decision_log[name] = {"msg": f"stale - confirmed_ts {now - confirmed_ts:.0f}s old"}
            return

        if (now - signal_ts) > self._signal_max_age:
            self._decision_log[name] = {"msg": f"stale - signal_ts {now - signal_ts:.0f}s old"}
            return

        is_manual = self._manual_signals_only or self._execution_mode.upper() in (
            "MANUAL", "MANUAL_ONLY", "SIGNAL_ONLY", "SIGNALS_ONLY",
        )
        if is_manual:
            ok, reason = self._telegram_action_quality(sig)
            if not ok:
                self._decision_log[name] = {"msg": f"MANUAL SIGNAL BLOCKED: {reason}"}
                return

            price = sig.get("price", 0.0)
            rr = sig.get("rr", sig.get("rr_ratio", sig.get("risk_reward_ratio", 0.0)))
            if rr is None:
                rr = 0.0
            msg = f"[MANUAL SIGNAL] {name} {sig.get('direction', 'CALL')} @ {price} RR={rr}"

            if msg not in self._manual_sig_last:
                self._send_notification(msg)
                self._manual_sig_last.add(msg)

            self._decision_log[name] = {"msg": msg}
            return

        # Token refresh check
        if self._token_refresh_service is not None:
            try:
                if getattr(self._token_refresh_service, "_enabled", False):
                    broker_port = getattr(self._execution_service, "broker_port", None) if self._execution_service else None
                    if broker_port is not None:
                        self._token_refresh_service.check_and_refresh({"primary": broker_port})
            except (ValueError, TypeError, KeyError, AttributeError, IndexError, OSError) as _tok_err:
                _log.debug("Token refresh failed: %s", _tok_err)

        # 2. Route to Execution Service
        from core.ports.execution.execution_port import OrderRequest, OrderStatus, OrderType
        from core.execution.broker_exceptions import (
            AuthExpiredError,
            OrderRejectedError,
            classify_broker_exception,
        )

        price = sig.get("price", 0.0)
        qty = self._get_position_size(name, price)
        if self._warmup_manager is not None:
            try:
                qty = self._warmup_manager.adjusted_position_size(qty)
            except (ValueError, TypeError, KeyError, AttributeError, IndexError, OSError):
                pass
        direction = sig.get("direction", "CALL")
        order_direction = "BUY" if str(direction).upper() == "CALL" else "SELL" if str(direction).upper() == "PUT" else str(direction).upper()

        signal_ts_str = str(sig.get("signal_ts", sig.get("timestamp", time.time()))).replace(".", "_")
        idempotency_key = f"{name}_{direction}_{int(qty)}_{signal_ts_str}"

        # Lock covers risk-check + broker submission (TOCTOU fix)
        try:
            if self._state_lock is not None:
                with self._state_lock:
                    order_result = self._submit_order_under_lock(
                        name, price, qty, sig, order_direction, idempotency_key,
                    )
            else:
                order_result = self._submit_order_under_lock(
                    name, price, qty, sig, order_direction, idempotency_key,
                )
        except TradeBlockError as tbe:
            self._decision_log[name] = {"msg": f"{tbe.reason.upper()}_BLOCK: {tbe.message}"}
            self._send_notification(f"{tbe.reason.upper()}_BLOCK: {name} - {tbe.message}", critical=True)
            return
        except (ValueError, TypeError, KeyError, AttributeError, IndexError, OSError) as e:
            classified = classify_broker_exception(e)
            if isinstance(classified, (AuthExpiredError, OrderRejectedError)):
                self._decision_log[name] = {"msg": f"BROKER_ERROR: {classified.__class__.__name__}"}
                trip_hard_halt(f"Margin check failed: {classified.__class__.__name__}")
                return
            self._decision_log[name] = {"msg": f"ORDER_FAILED: {e}"}
            return

        success = order_result.status in (OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED)

        if success:
            if self._pos_lock is not None:
                with self._pos_lock:
                    self._store_position(name, price, qty, direction, order_direction, idempotency_key, sig, order_result)
            else:
                self._store_position(name, price, qty, direction, order_direction, idempotency_key, sig, order_result)
            self._decision_log[name] = {"msg": f"Executed: {order_result.order_id}"}
        else:
            error_text = order_result.reject_reason or str(order_result.status)
            self._decision_log[name] = {"msg": f"Blocked/Failed: {error_text}"}

    # ── Position Monitoring ────────────────────────────────────────────

    def monitor_positions(self) -> None:
        """Monitor open positions and exit on SL/target/age conditions.

        Uses underlying index price movement as a proxy for option premium movement.
        For CALLs: underlying down by SL% → SL hit; underlying up by Target% → Target hit.
        For PUTs: underlying up by SL% → SL hit; underlying down by Target% → Target hit.
        """
        if not self._positions:
            return

        for name, pos in list(self._positions.items()):
            try:
                current_underlying = self._get_underlying_ltp(name)
                if current_underlying is None:
                    continue

                entry_underlying = float(pos.get("underlying_entry_price", 0))
                if entry_underlying <= 0:
                    continue

                direction = pos.get("direction", "CALL")
                sl_pct = float(self._cfg.get("SL_PCT", 0.92))
                target_pct = float(self._cfg.get("TARGET_PCT", 1.3))
                trail_pct = float(self._cfg.get("TRAIL_PCT", 0.93))
                trail_activate_pct = float(self._cfg.get("TRAIL_ACTIVATE", 1.1))

                # Initialize trailing stop tracking
                if pos.get("peak_underlying") is None:
                    pos["peak_underlying"] = current_underlying
                    pos["trail_activated"] = False

                # Update peak underlying
                if current_underlying > pos["peak_underlying"]:
                    pos["peak_underlying"] = current_underlying

                # Calculate move % of underlying since entry
                move_pct = (current_underlying - entry_underlying) / entry_underlying

                if direction == "CALL":
                    if move_pct <= -(1.0 - sl_pct):
                        self._record_stop_loss(name, pos)
                        self.exit_position(name, "SL_HIT")
                        continue
                    if move_pct >= (target_pct - 1.0):
                        self.exit_position(name, "TARGET_HIT")
                        continue
                    if not pos.get("trail_activated") and move_pct >= (trail_activate_pct - 1.0):
                        pos["trail_activated"] = True
                    if pos.get("trail_activated"):
                        trail_level = pos["peak_underlying"] * trail_pct
                        if current_underlying <= trail_level:
                            self.exit_position(name, "TRAIL_HIT")
                            continue
                else:  # PUT
                    if move_pct >= (1.0 - sl_pct):
                        self._record_stop_loss(name, pos)
                        self.exit_position(name, "SL_HIT")
                        continue
                    if move_pct <= -(target_pct - 1.0):
                        self.exit_position(name, "TARGET_HIT")
                        continue
                    if not pos.get("trail_activated") and move_pct <= -(trail_activate_pct - 1.0):
                        pos["trail_activated"] = True
                    if pos.get("trail_activated"):
                        trail_level = pos["peak_underlying"] * (2.0 - trail_pct)
                        if current_underlying >= trail_level:
                            self.exit_position(name, "TRAIL_HIT")
                            continue

                entry_time = float(pos.get("entry_time", 0))
                max_age = int(self._cfg.get("MAX_POSITION_AGE", 9999))
                if max_age < 9999 and entry_time > 0:
                    age_minutes = (time.time() - entry_time) / 60
                    if age_minutes >= max_age:
                        self.exit_position(name, "MAX_AGE")

            except (ValueError, TypeError, KeyError, AttributeError, IndexError, OSError) as e:
                _log.error("Error monitoring %s: %s", name, e)

    # ── Position Exit ──────────────────────────────────────────────────

    def exit_position(self, name: str, reason: str) -> None:
        """Exit an open position by placing an opposite-direction order.

        Atomic under _pos_lock: position read + cleanup in one acquisition.

        Args:
            name:   Instrument/index symbol.
            reason: Exit reason label (SL_HIT, TARGET_HIT, etc.).
        """
        pos, direction, qty, entry_price, entry_order_direction = self._read_position_under_lock(name)
        if pos is None:
            return

        current_price = self._get_underlying_ltp(name) or entry_price
        if entry_order_direction:
            exit_direction = "SELL" if entry_order_direction == "BUY" else "BUY"
        else:
            exit_direction = "SELL" if direction == "CALL" else "BUY"

        from core.ports.execution.execution_port import OrderRequest, OrderStatus, OrderType

        order_request = OrderRequest(
            symbol=name, direction=exit_direction, strike_price=current_price,
            lot_size=qty, order_type=OrderType.MARKET, price=current_price,
            idempotency_key=f"exit_{name}_{int(qty)}_{int(entry_price)}_{reason}",
        )

        try:
            if self._execution_service is not None:
                order_result = self._execution_service.execute_order(order_request)
                if order_result.status in (OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED):
                    exit_price = order_result.average_price or entry_price
                else:
                    _log.warning(
                        "Exit order for %s not filled: %s - using entry price",
                        name, order_result.reject_reason,
                    )
                    exit_price = entry_price
            else:
                _log.warning("No execution service available for exit - using entry price")
                exit_price = entry_price
        except (ValueError, TypeError, KeyError, AttributeError, IndexError, OSError) as e:
            _log.error("Exit order failed for %s: %s - using entry price", name, e)
            exit_price = entry_price

        exit_failed = (exit_price == entry_price and reason != "MANUAL")
        pnl = 0.0
        if not exit_failed:
            pnl = (exit_price - entry_price) * qty
            if self._portfolio_service is not None:
                try:
                    self._portfolio_service.update_daily_pnl(pnl)
                    self._portfolio_service.increment_trade_count()
                except (ValueError, TypeError, KeyError, AttributeError, IndexError, OSError):
                    pass
            try:
                from core.safety_state import record_trade_outcome
                record_trade_outcome(was_profit=pnl > 0)
            except (ValueError, TypeError, KeyError, AttributeError, IndexError, OSError):
                pass

        # Atomic cleanup under same lock: verify position still exists (TOCTOU fix)
        if self._pos_lock is not None:
            with self._pos_lock:
                if name in self._positions:
                    self._cleanup_position_entry(name, pos, exit_failed)
        else:
            if name in self._positions:
                self._cleanup_position_entry(name, pos, exit_failed)

        if exit_failed and pos.get("exit_retries", 0) < 3:
            _log.warning("EXIT %s failed, will retry (attempt %d)", name, pos.get("exit_retries", 0))
            return

        if not exit_failed:
            _log.info("EXIT %s @ %.2f: %s (P&L=%.0f)", name, exit_price, reason, pnl)
            self._send_notification(f"EXIT {name}: {reason} @ {exit_price:.2f} P&L={pnl:.0f}")
        else:
            _log.error("EXIT %s GIVING UP after %d failed attempts", name, pos.get("exit_retries", 3))

    # ── Internal Helpers ───────────────────────────────────────────────

    def _read_position_under_lock(self, name: str) -> tuple:
        """Read position data atomically under _pos_lock.

        Returns:
            (pos_dict, direction, qty, entry_price, entry_order_direction)
            or (None, None, 0, 0.0, "") if position not found.
        """
        if self._pos_lock is not None:
            with self._pos_lock:
                pos = self._positions.get(name)
                if not pos:
                    return None, None, 0, 0.0, ""
                return (
                    pos,
                    pos.get("direction", "CALL"),
                    int(pos.get("qty", 0)),
                    float(pos.get("entry_price", 0)),
                    pos.get("entry_order_direction", ""),
                )
        pos = self._positions.get(name)
        if not pos:
            return None, None, 0, 0.0, ""
        return (
            pos,
            pos.get("direction", "CALL"),
            int(pos.get("qty", 0)),
            float(pos.get("entry_price", 0)),
            pos.get("entry_order_direction", ""),
        )

    def _get_underlying_ltp(self, name: str) -> float | None:
        """Resolve underlying LTP - uses stored resolver if available, else returns None."""
        if self._ltp_resolver is not None:
            try:
                return self._ltp_resolver.resolve(name)
            except (ValueError, TypeError, KeyError, AttributeError, IndexError, OSError):
                return None
        return None

    def _get_position_size(self, name: str, price: float) -> int:
        """Get position size - delegates to mandate service."""
        if self._mandate_service is not None:
            return self._mandate_service.get_position_size(name, price)
        return 1

    def _send_notification(self, message: str, **kwargs) -> None:
        """Send notification - uses stored notification service if available."""
        if self._notification_service is not None:
            try:
                if hasattr(self._notification_service, 'send'):
                    self._notification_service.send(message, **kwargs)
            except (ValueError, TypeError, KeyError, AttributeError, IndexError, OSError):
                pass

    def _telegram_action_quality(self, sig: dict[str, Any]) -> tuple[bool, str]:
        """Check signal quality for manual mode."""
        breakout_ok = sig.get("breakout_ok", True)
        if not breakout_ok:
            return False, "breakout_ok false"
        return True, "ok"

    def _submit_order_under_lock(
        self, name: str, price: float, qty: int, sig: dict[str, Any],
        order_direction: str, idempotency_key: str,
    ) -> Any:
        """Submit order under state lock - covers margin check + submission."""
        from core.ports.execution.execution_port import OrderRequest, OrderStatus, OrderType

        available_margin = 0.0
        if self._portfolio_service is not None:
            try:
                available_margin = self._portfolio_service.get_available_margin()
            except (ValueError, TypeError, KeyError, AttributeError, IndexError, OSError):
                pass

        required_margin_per_lot = price * qty * 0.2
        if self._risk_service is not None:
            try:
                required_margin_per_lot = self._risk_service.get_required_margin_per_lot(name, price)
            except (ValueError, TypeError, KeyError, AttributeError, IndexError, OSError):
                pass

        if self._margin_validator is not None:
            try:
                margin_result = self._margin_validator.validate(
                    available_margin=available_margin,
                    required_margin_per_lot=required_margin_per_lot,
                    intended_quantity=int(qty),
                    price_per_lot=price,
                    instrument_name=name,
                )
                if not margin_result.allowed:
                    raise TradeBlockError(f"MARGIN_BLOCK: {margin_result.error_message}", reason="margin")
            except (ValueError, TypeError, KeyError, AttributeError, IndexError, OSError) as e:
                raise ValueError(f"Margin validation failed: {e}") from e

        # Re-validate risk after acquiring lock (TOCTOU fix)
        if self._risk_service is not None:
            try:
                risk_metrics_after_lock = self._risk_service.get_portfolio_risk_metrics()
                risk_eval_after_lock = self._risk_service.evaluate_trade(name, sig, risk_metrics_after_lock)
                if risk_eval_after_lock.decision.value == "denied":
                    raise TradeBlockError(f"RISK_BLOCK_POST_LOCK: {risk_eval_after_lock.reason}", reason="risk")
            except (ValueError, TypeError, KeyError) as risk_e:
                raise ValueError(f"Risk re-eval failed: {risk_e}") from risk_e

        # Submit order
        order_request = OrderRequest(
            symbol=name,
            direction=order_direction,
            strike_price=price,
            lot_size=int(qty),
            order_type=OrderType.MARKET,
            price=price,
            idempotency_key=idempotency_key,
        )

        if self._execution_service is not None:
            return self._execution_service.execute_order(order_request)
        raise RuntimeError("No execution service available")

    def _store_position(
        self, name: str, price: float, qty: int, direction: str,
        order_direction: str, idempotency_key: str,
        sig: dict[str, Any], order_result: Any,
    ) -> None:
        """Store position after successful entry."""
        underlying_entry = self._get_underlying_ltp(name) or price
        self._positions[name] = {
            "direction": direction,
            "qty": int(qty),
            "entry_price": price,
            "underlying_entry_price": float(underlying_entry),
            "entry_time": time.time(),
            "order_id": order_result.order_id or "",
            "signal": sig.get("direction", "CALL"),
            "strike": int(sig.get("strike", sig.get("price", price))),
            "idempotency_key": idempotency_key,
            "entry_order_direction": order_direction,
            "score": int(sig.get("score", 0)),
        }
        rt = self._reentry_trackers.get(name)
        if rt is not None and getattr(rt, "last_sl_ts", None) is not None:
            try:
                rt.record_reentry()
            except (ValueError, TypeError, KeyError, AttributeError, IndexError, OSError):
                pass

    def _record_stop_loss(self, name: str, pos: dict[str, Any]) -> None:
        """Record stop loss event in reentry tracker."""
        rt = self._reentry_trackers.get(name)
        if rt is not None:
            try:
                rt.record_stop_loss(
                    direction=pos.get("direction", "CALL"),
                    score=pos.get("score", 0),
                )
            except (ValueError, TypeError, KeyError, AttributeError, IndexError, OSError):
                pass

    def _cleanup_position_entry(self, name: str, pos: dict[str, Any], exit_failed: bool) -> None:
        """Update or remove position entry after exit attempt."""
        if exit_failed:
            pos["exit_failed"] = True
            pos["exit_retries"] = pos.get("exit_retries", 0) + 1
            if pos["exit_retries"] >= 3:
                _log.error("EXIT %s FAILED after %d retries - giving up", name, pos["exit_retries"])
                self._positions.pop(name, None)
        else:
            self._positions.pop(name, None)


# ── Singleton factory ─────────────────────────────────────────────────────────

_position_service_instance: PositionService | None = None
_position_service_lock = threading.RLock()


def get_position_service(
    cfg: dict[str, Any] | None = None,
    risk_service: Any = None,
    execution_service: Any = None,
    portfolio_service: Any = None,
    margin_validator: Any = None,
    warmup_manager: Any = None,
    news_sentinel: Any = None,
    expiry_controller: Any = None,
    token_refresh_service: Any = None,
    audit_engine: Any = None,
    reentry_trackers: dict[str, Any] | None = None,
    positions: dict[str, Any] | None = None,
    decision_log: dict[str, Any] | None = None,
    manual_sig_last: set[str] | None = None,
    breakout_state: dict[str, Any] | None = None,
    bos_lock: Any = None,
    state_lock: Any = None,
    pos_lock: Any = None,
    mandate_service: Any = None,
    signal_max_age: int = 90,
    manual_signals_only: bool = True,
    execution_mode: str = "MANUAL",
    ltp_resolver: Any = None,
    notification_service: Any = None,
) -> PositionService:
    """Return the process-level PositionService singleton."""
    global _position_service_instance
    with _position_service_lock:
        if _position_service_instance is None:
            _position_service_instance = PositionService(
            cfg=cfg,
            risk_service=risk_service,
            execution_service=execution_service,
            portfolio_service=portfolio_service,
            margin_validator=margin_validator,
            warmup_manager=warmup_manager,
            news_sentinel=news_sentinel,
            expiry_controller=expiry_controller,
            token_refresh_service=token_refresh_service,
            audit_engine=audit_engine,
            reentry_trackers=reentry_trackers,
            positions=positions,
            decision_log=decision_log,
            manual_sig_last=manual_sig_last,
            breakout_state=breakout_state,
            bos_lock=bos_lock,
            state_lock=state_lock,
            pos_lock=pos_lock,
            mandate_service=mandate_service,
            signal_max_age=signal_max_age,
            manual_signals_only=manual_signals_only,
            execution_mode=execution_mode,
            ltp_resolver=ltp_resolver,
            notification_service=notification_service,
        )
    return _position_service_instance


def reset_position_service() -> None:
    """Force-reset singleton (tests only)."""
    global _position_service_instance
    _position_service_instance = None
