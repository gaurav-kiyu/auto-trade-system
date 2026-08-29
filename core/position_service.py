"""Position Service - extracted from index_app/index_trader.py (GAP-05b).

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

from core.common.models import AssetType

_log = logging.getLogger(__name__)


class TradeBlockError(Exception):
    """Raised when a trade is blocked by margin or risk checks.
    Preserves the critical notification that would otherwise be lost.
    """

    def __init__(self, message: str, reason: str = "BLOCKED") -> None:
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
        # config key COOLDOWN, opt-in via general_cooldown_enabled (default
        # OFF). Distinct in scope from reentry_cooldown_mins (post-stop-loss
        # only) and TG_COOLDOWN_SECS (Telegram throttling) - this is a
        # general per-index minimum time between ANY two entries.
        self._last_entry_ts: dict[str, float] = {}

    # ── Entry Gate ─────────────────────────────────────────────────────

    def enter_trade(self, name: str, sig: dict[str, Any],
                    asset_type: AssetType | None = None) -> None:
        """Entry gate for all trades. Risk-gated, idempotent, fail-closed.

        Args:
            name: Instrument/index symbol.
            sig:  Trading signal dictionary.
            asset_type: Optional asset class (AssetType enum). When provided,
                       gates specific to that asset class are applied.
                       When None, INDEX_OPTIONS gates are used (backward compat).

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
        trace_id = f"{name}_{sig.get('direction', 'CALL')!s}_{_trace_ts}"

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

        # General per-index entry cooldown (config key COOLDOWN, opt-in via
        # general_cooldown_enabled, default OFF - a brand-new throttle with
        # no prior track record). Blocks a new entry within COOLDOWN seconds
        # of this index's last entry, regardless of how the prior trade
        # exited - distinct from reentry_cooldown_mins (post-stop-loss only).
        if self._cfg.get("general_cooldown_enabled", False):
            try:
                _last_ts = self._last_entry_ts.get(name)
                _cooldown_secs = int(self._cfg.get("COOLDOWN", 300))
                if _last_ts is not None and (time.time() - _last_ts) < _cooldown_secs:
                    self._decision_log[name] = {
                        "msg": f"COOLDOWN_BLOCK: {time.time() - _last_ts:.0f}s since last entry < {_cooldown_secs}s cooldown",
                    }
                    return
            except (ValueError, TypeError, KeyError, AttributeError, IndexError, OSError) as _cooldown_err:
                _log.debug("General cooldown check failed (fail-open): %s", _cooldown_err)

        # Asset-class-specific gates (only for index options — other asset classes skip these)
        _is_index_options = (asset_type is None or asset_type == AssetType.INDEX_OPTIONS)

        # Expiry day gate
        if _is_index_options and self._expiry_controller is not None:
            try:
                expiry_result = self._expiry_controller.can_enter_position()
                if not expiry_result.allowed:
                    self._decision_log[name] = {
                        "msg": f"EXPIRY_BLOCK: {expiry_result.reason} (session={expiry_result.session.value})",
                    }
                    return
            except (ValueError, TypeError, KeyError, AttributeError, IndexError, OSError) as _exp_err:
                _log.debug("Expiry check failed: %s", _exp_err)

        # Expiry-day trade count cap (config key EXPIRY_MAX_TRADES, opt-in
        # via expiry_max_trades_enabled, default OFF - brand-new safety cap
        # with no prior track record; ExpiryDayController has never had any
        # trade-count logic, only a time cutoff). Reuses RiskService's
        # existing, tested get_trades_today() rather than a new counter.
        if (
            _is_index_options
            and self._cfg.get("expiry_max_trades_enabled", False)
            and self._expiry_controller is not None
            and self._risk_service is not None
        ):
            try:
                if self._expiry_controller.is_expiry_day(index_name=name):
                    _expiry_max_trades = int(self._cfg.get("EXPIRY_MAX_TRADES", 2))
                    _trades_today = self._risk_service.get_trades_today()
                    if _trades_today >= _expiry_max_trades:
                        self._decision_log[name] = {
                            "msg": f"EXPIRY_MAX_TRADES_BLOCK: {_trades_today} trades today >= expiry-day cap of {_expiry_max_trades}",
                        }
                        return
            except (ValueError, TypeError, KeyError, AttributeError, IndexError, OSError) as _exp_max_err:
                _log.debug("Expiry max-trades check failed (fail-open): %s", _exp_max_err)

        # Auction session gate (NSE auction only affects index options)
        if _is_index_options:
            try:
                from core.datetime_ist import is_in_auction_session
                if is_in_auction_session():
                    self._decision_log[name] = {"msg": "AUCTION_BLOCK: Entry blocked during NSE auction session"}
                    return
            except (ValueError, TypeError, KeyError, AttributeError, IndexError, OSError) as _auc_err:
                _log.debug("Auction check failed: %s", _auc_err)

        # Force pre-trade reconciliation (config key FORCE_PRE_TRADE_RECON,
        # opt-in via force_pre_trade_recon_enabled, default OFF - reuses
        # ExecutionService's existing, tested run_ack_watchdog() rather than
        # a new mechanism. FORCE_PRE_TRADE_RECON itself already defaults
        # true, but honoring that directly would add a new broker round-trip
        # to every single entry with no prior track record in this exact
        # calling context, so it gets a fresh, explicit gate instead.
        if self._cfg.get("force_pre_trade_recon_enabled", False) and self._execution_service is not None:
            try:
                if hasattr(self._execution_service, "run_ack_watchdog"):
                    _recon_result = self._execution_service.run_ack_watchdog()
                    if _recon_result.get("still_pending", 0) > 0:
                        self._decision_log[name] = {
                            "msg": f"PRE_TRADE_RECON_BLOCK: {_recon_result['still_pending']} orders still unacknowledged by broker",
                        }
                        return
            except (ValueError, TypeError, KeyError, AttributeError, IndexError, OSError) as _recon_err:
                _log.debug("Pre-trade reconciliation failed (fail-open): %s", _recon_err)

        # Time-of-day liquidity filter (config key TIME_OF_DAY_FILTER_ENABLED,
        # opt-in via a fresh master switch, default OFF — core/time_of_day_
        # filter.py). Fully built and unit-tested but never called from the
        # live entry path. TIME_OF_DAY_FILTER_ENABLED itself already defaults
        # True with a real 14:00-15:00 IST block window, and index_trader.py
        # already has a separate, live NSE_BLOCK_NEW_ENTRIES_FROM_HOUR cutoff
        # for a related purpose — wiring this in unconditionally would add a
        # second, overlapping restriction and silently change today's real
        # trading hours. Gated behind time_of_day_hard_block_enabled so it
        # only takes effect once an admin deliberately opts in.
        if self._cfg.get("time_of_day_hard_block_enabled", False):
            try:
                from core.time_of_day_filter import create_time_of_day_filter
                _tod_allowed, _tod_reason = create_time_of_day_filter(self._cfg).should_allow_entry(
                    regime=sig.get("regime"),
                )
                if not _tod_allowed:
                    self._decision_log[name] = {"msg": f"TIME_OF_DAY_BLOCK: {_tod_reason}"}
                    return
            except (ValueError, TypeError, KeyError, AttributeError, IndexError, OSError) as _tod_err:
                _log.debug("Time-of-day filter check failed (fail-open): %s", _tod_err)

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

        # config key BREAKOUT_TIMEOUT, opt-in via breakout_timeout_enabled
        # (default OFF - a real behavior change vs. the general SIGNAL_MAX_AGE
        # check below: BREAKOUT_TIMEOUT defaults to 1800s, ~20x looser than
        # SIGNAL_MAX_AGE's default 90s, since a confirmed breakout is a
        # slower-forming event than a fresh signal tick). When disabled
        # (default), confirmed_ts keeps using the same SIGNAL_MAX_AGE window
        # it always has.
        _breakout_staleness_limit = self._signal_max_age
        if self._cfg.get("breakout_timeout_enabled", False):
            try:
                _breakout_staleness_limit = int(self._cfg.get("BREAKOUT_TIMEOUT", 1800))
            except (ValueError, TypeError):
                pass
        if confirmed_ts is not None and (now - confirmed_ts) > _breakout_staleness_limit:
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
            msg = self._build_manual_signal_message(name, sig, price, rr)

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
        from core.execution.broker_exceptions import (
            AuthExpiredError,
            OrderRejectedError,
            classify_broker_exception,
        )
        from core.ports.execution.execution_port import OrderStatus

        price = sig.get("price", 0.0)
        qty = self._get_position_size(name, price, asset_type)
        if self._warmup_manager is not None:
            try:
                qty = self._warmup_manager.adjusted_position_size(qty)
            except (ValueError, TypeError, KeyError, AttributeError, IndexError, OSError):
                pass

        # Equity-aware capital scaling (opt-in, default OFF —
        # core.services.risk_service.RiskService.scale_position, backed by the
        # existing, tested CapitalManager). Previously built and unit-tested
        # but never called from the live entry path, so drawdown/consecutive-
        # loss/profit-lock scaling never affected real qty. When disabled
        # (default), legacy behavior is unchanged.
        if self._cfg.get("capital_manager_equity_scaling_enabled", False) and self._risk_service is not None:
            try:
                scale_result = self._risk_service.scale_position(base_lots=qty, max_lots=qty)
                qty = scale_result.scaled_lots
            except (ValueError, TypeError, KeyError, AttributeError, IndexError, OSError) as _scale_err:
                _log.debug("Capital scaling failed (fail-open, using unscaled qty): %s", _scale_err)

        # Intraday session win-rate adaptive sizing (opt-in, default OFF —
        # core.intraday_performance_monitor, CLAUDE.md's v2.44-9). Fully
        # built and tested but never called from the live entry path, so
        # NORMAL/CAUTIOUS/DEFENSIVE never actually reduced size on a bad
        # session. Score-threshold-boost half of the same monitor is applied
        # in adaptive_signal.py via the same get_intraday_monitor() singleton.
        if self._cfg.get("intraday_performance_monitor_enabled", False):
            try:
                from core.intraday_performance_monitor import get_intraday_monitor
                params = get_intraday_monitor(self._cfg).get_current_params()
                qty = max(0, int(qty * params.position_size_mult))
            except (ValueError, TypeError, KeyError, AttributeError, IndexError, OSError) as _intraday_err:
                _log.debug("Intraday performance sizing failed (fail-open, using unadjusted qty): %s", _intraday_err)

        # VIX-based sizing (config key VIX_SIZE_SCALE, default True — this
        # key already existed with that default, implying it was meant to be
        # active; RiskService._get_volatility_multiplier() was fully correct
        # but only ever called from calculate_position_size(), which is
        # advisory-only in the real entry path — the real qty comes from
        # _get_position_size() above. This is the first real consumer.
        if self._cfg.get("VIX_SIZE_SCALE", True) and self._risk_service is not None:
            try:
                vix_mult = self._risk_service.get_vix_size_multiplier(float(sig.get("vix", 15.0)))
                qty = max(0, int(qty * vix_mult))
            except (ValueError, TypeError, KeyError, AttributeError, IndexError, OSError) as _vix_size_err:
                _log.debug("VIX-based sizing failed (fail-open, using unadjusted qty): %s", _vix_size_err)

        # VIX soft-warning notification (config key VIX_HALT_THRESHOLD).
        # RiskService.is_vix_soft_warning() was validated at startup but had
        # no real caller anywhere. Purely informational — never blocks or
        # resizes the trade, only surfaces an early warning ahead of the
        # hard VIX_BLOCK_THRESHOLD circuit breaker that already does block.
        if self._risk_service is not None:
            try:
                _vix_now = float(sig.get("vix", 15.0))
                if self._risk_service.is_vix_soft_warning(_vix_now):
                    self._send_notification(f"VIX_SOFT_WARNING: {name} entry at VIX={_vix_now:.1f} (>= soft threshold)")
            except (ValueError, TypeError, KeyError, AttributeError, IndexError, OSError) as _vix_warn_err:
                _log.debug("VIX soft-warning check failed (non-blocking): %s", _vix_warn_err)

        # Per-trade SL-risk cap (config key MAX_SINGLE_TRADE_LOSS_PCT,
        # opt-in, default OFF). Previously validated at startup but never
        # enforced anywhere. When disabled (default), legacy behavior is
        # unchanged. price here is the underlying/premium value used
        # elsewhere in this function as the entry reference; SL distance is
        # approximated from SL_PCT the same way monitor_positions() computes
        # a real exit, since no live option-premium feed exists to price
        # this more precisely yet.
        if self._cfg.get("max_single_trade_loss_pct_enabled", False) and self._risk_service is not None and price > 0:
            try:
                sl_pct = float(self._cfg.get("SL_PCT", 0.92))
                price_diff = abs(price - price * sl_pct)
                capital_available = float(self._cfg.get("BASE_CAPITAL", 100000.0))
                cap_lots = self._risk_service.get_single_trade_loss_cap_lots(
                    capital_available=capital_available, price_diff=price_diff, lot_size=1,
                )
                qty = min(qty, cap_lots)
            except (ValueError, TypeError, KeyError, AttributeError, IndexError, OSError, ZeroDivisionError) as _sl_cap_err:
                _log.debug("Per-trade SL-risk cap failed (fail-open, using unadjusted qty): %s", _sl_cap_err)

        # Portfolio-wide aggregate SL-risk cap (config key
        # PORTFOLIO_MAX_SL_RISK_PCT, opt-in, default OFF). Previously
        # validated at startup but never enforced anywhere — only referenced
        # in governance/AI-restriction lists asserting the key must not be
        # tampered with, never in a real risk check. Blocks (rather than
        # resizes) the new entry outright if it would push the combined
        # open-position SL-risk over the cap, since partially sizing down an
        # already-decided entry to "fit" is a different, riskier semantic
        # than simply not taking it.
        if self._cfg.get("portfolio_max_sl_risk_pct_enabled", False) and self._risk_service is not None and price > 0 and qty > 0:
            try:
                sl_pct = float(self._cfg.get("SL_PCT", 0.92))
                new_trade_risk = abs(price - price * sl_pct) * qty
                open_risk = 0.0
                for _pname, _pos in self._positions.items():
                    _p_entry = float(_pos.get("underlying_entry_price", _pos.get("entry_price", 0.0)) or 0.0)
                    _p_qty = float(_pos.get("qty", 0) or 0)
                    open_risk += abs(_p_entry - _p_entry * sl_pct) * _p_qty
                capital_available = float(self._cfg.get("BASE_CAPITAL", 100000.0))
                if not self._risk_service.check_portfolio_sl_risk(open_risk, capital_available, new_trade_risk):
                    self._decision_log[name] = {"msg": "PORTFOLIO_SL_RISK_BLOCK: combined open-position stop-loss risk would exceed PORTFOLIO_MAX_SL_RISK_PCT of capital"}
                    return
            except (ValueError, TypeError, KeyError, AttributeError, IndexError, OSError, ZeroDivisionError) as _portfolio_risk_err:
                _log.debug("Portfolio SL-risk check failed (fail-open, allowing entry): %s", _portfolio_risk_err)

        direction = sig.get("direction", "CALL")
        order_direction = "BUY" if str(direction).upper() == "CALL" else "SELL" if str(direction).upper() == "PUT" else str(direction).upper()

        # Strike selector (opt-in, default OFF — core/strike_selector.py).
        # When disabled (default), legacy behavior is unchanged: the raw
        # underlying price is used where a real option strike belongs.
        # SL/target/trail exit logic still operates on underlying % move
        # either way — this only affects the strike value stored/ordered,
        # not premium-based P&L (no live option-premium feed exists yet).
        if _is_index_options and self._cfg.get("strike_selector_enabled", False):
            try:
                from core.config_validator import get_instrument_param
                from core.strike_selector import dte_entry_check, select_strike

                step = int(get_instrument_param(self._cfg, name, "strike_step", 50))
                atm = int(round(price / step) * step) if step > 0 else int(price)
                dte = self._resolve_dte(name)
                dte_ok, dte_reason = dte_entry_check(dte, self._cfg)
                if not dte_ok:
                    self._decision_log[name] = {"msg": f"STRIKE_BLOCK: {dte_reason}"}
                    return
                strike, _strike_reason = select_strike(
                    atm, str(direction).upper(), step,
                    str(sig.get("tier", "MODERATE")), float(sig.get("vix", 15.0)), dte,
                    self._cfg,
                )
                sig["strike"] = strike

                # Live option quote feed (config key live_option_quotes_enabled,
                # opt-in, default OFF — core/live_option_quotes.py). Only
                # meaningful once a real strike has been selected above.
                # Fails open to nothing (leaves sig's bid/ask/oi/volume
                # untouched) on a paper/simulated adapter or any error - see
                # that module's own docstring for the live-validation caveat
                # on the Kite NFO tradingsymbol format.
                if self._cfg.get("live_option_quotes_enabled", False) and self._execution_service is not None:
                    try:
                        from core.live_option_quotes import fetch_live_option_quote
                        _broker_adapter = getattr(self._execution_service, "broker_port", None)
                        _live_quote = fetch_live_option_quote(
                            _broker_adapter, name, strike, str(direction).upper(), cfg=self._cfg,
                        )
                        if _live_quote is not None:
                            sig["bid"] = _live_quote["bid"]
                            sig["ask"] = _live_quote["ask"]
                            sig["oi"] = _live_quote["oi"]
                            sig["volume"] = _live_quote["volume"]
                            sig["option_symbol"] = _live_quote["symbol"]
                    except (ValueError, TypeError, KeyError, AttributeError, IndexError, OSError) as _quote_err:
                        _log.debug("Live option quote fetch failed (fail-open): %s", _quote_err)
            except (ValueError, TypeError, KeyError, AttributeError, IndexError, OSError) as _strike_err:
                _log.debug("Strike selector failed (fail-open, using price as strike): %s", _strike_err)

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
                    self._store_position(name, price, qty, direction, order_direction, idempotency_key, sig, order_result, asset_type)
            else:
                self._store_position(name, price, qty, direction, order_direction, idempotency_key, sig, order_result, asset_type)
            if self._risk_service is not None:
                try:
                    self._risk_service.record_trade_entry(name)
                except (ValueError, TypeError, KeyError, AttributeError, IndexError, OSError) as _rte_err:
                    _log.debug("record_trade_entry failed: %s", _rte_err)
            self._last_entry_ts[name] = time.time()
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
                # config key TAKE_PROFIT_AND_STOP (default true, matching
                # today's real behavior exactly - both SL and a fixed TARGET_HIT
                # are always checked). Set to false to run SL/trail-only (let
                # winners ride on the trailing stop instead of a fixed target) -
                # the only unambiguous, safe interpretation: the SL leg can
                # never be the one disabled by this key.
                _take_profit_enabled = bool(self._cfg.get("TAKE_PROFIT_AND_STOP", True))

                # Initialize trailing stop tracking
                if pos.get("peak_underlying") is None:
                    pos["peak_underlying"] = current_underlying
                    pos["trail_activated"] = False

                # Update peak underlying
                pos["peak_underlying"] = max(pos["peak_underlying"], current_underlying)

                # Calculate move % of underlying since entry
                move_pct = (current_underlying - entry_underlying) / entry_underlying

                if direction == "CALL":
                    if move_pct <= -(1.0 - sl_pct):
                        self._record_stop_loss(name, pos)
                        self.exit_position(name, "SL_HIT")
                        continue
                    if _take_profit_enabled and move_pct >= (target_pct - 1.0):
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
                    if _take_profit_enabled and move_pct <= -(target_pct - 1.0):
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

            # Feed the equity-aware capital scaler (see the matching entry-side
            # scale_position() call above) so its drawdown/streak state tracks
            # real closed trades. Same opt-in flag; a no-op when disabled.
            if self._cfg.get("capital_manager_equity_scaling_enabled", False) and self._risk_service is not None:
                try:
                    self._risk_service.record_trade_result(net_pnl=pnl, is_winner=pnl > 0)
                except (ValueError, TypeError, KeyError, AttributeError, IndexError, OSError):
                    pass

            # Feed the intraday session win-rate monitor (see the matching
            # entry-side get_current_params() call above). Same opt-in flag.
            if self._cfg.get("intraday_performance_monitor_enabled", False):
                try:
                    from core.intraday_performance_monitor import get_intraday_monitor
                    get_intraday_monitor(self._cfg).record_trade_close(pnl=pnl, was_winner=pnl > 0)
                except (ValueError, TypeError, KeyError, AttributeError, IndexError, OSError):
                    pass

            # Persist the closed trade to the legacy trades DB that the
            # live-readiness gate + all analytics read.  The v2.53 refactor
            # removed this writer while the readers kept pointing at the
            # legacy schema, so the 50-paper-trade track record could never
            # accumulate.  Restored here as best-effort — a recording failure
            # must never block or alter trading behaviour.
            try:
                from core.datetime_ist import now_ist
                from core.trade_recorder import record_closed_trade, resolve_trades_db_path
                _db_path = resolve_trades_db_path(self._cfg)
                if _db_path:
                    record_closed_trade(
                        _db_path,
                        ts=now_ist().isoformat(),
                        index_name=name,
                        direction=direction,
                        entry=entry_price,
                        exit_price=exit_price,
                        qty=qty,
                        gross_pnl=pnl,
                        net_pnl=pnl,
                        reason=reason,
                        mode="PAPER" if not self._broker_api_enabled else "LIVE",
                        regime=pos.get("regime"),
                        score=int(pos.get("score")) if pos.get("score") is not None else None,
                        version=str(self._cfg.get("VERSION", "v2.59.0")),
                    )
            except (ValueError, TypeError, KeyError, AttributeError, IndexError, OSError):
                pass

        # Atomic cleanup under same lock: verify position still exists (TOCTOU fix)
        if self._pos_lock is not None:
            with self._pos_lock:
                if name in self._positions:
                    self._cleanup_position_entry(name, pos, exit_failed)
        elif name in self._positions:
            self._cleanup_position_entry(name, pos, exit_failed)

        # config key EXIT_ORDER_RETRIES (default 3, matching the value this
        # was hardcoded to everywhere below - genuinely wired, no behavior
        # change at the default).
        _exit_order_retries = int(self._cfg.get("EXIT_ORDER_RETRIES", 3))
        if exit_failed and pos.get("exit_retries", 0) < _exit_order_retries:
            _log.warning("EXIT %s failed, will retry (attempt %d)", name, pos.get("exit_retries", 0))
            return

        if not exit_failed:
            _log.info("EXIT %s @ %.2f: %s (P&L=%.0f)", name, exit_price, reason, pnl)
            self._send_notification(f"EXIT {name}: {reason} @ {exit_price:.2f} P&L={pnl:.0f}")
        else:
            _log.error("EXIT %s GIVING UP after %d failed attempts", name, pos.get("exit_retries", _exit_order_retries))

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
                return self._ltp_resolver.resolve(name)  # type: ignore[no-any-return]
            except (ValueError, TypeError, KeyError, AttributeError, IndexError, OSError):
                return None
        return None

    def _get_position_size(self, name: str, price: float,
                            asset_type: AssetType | None = None) -> int:
        """Get position size - delegates to mandate service.

        Args:
            name: Instrument symbol.
            price: Entry price.
            asset_type: Optional asset class for asset-aware sizing.

        Returns:
            Position size as integer quantity.

        """
        if self._mandate_service is not None:
            qty = self._mandate_service.get_position_size(name, price)  # type: ignore[no-any-return]
            # Scale qty by asset type if mandate service returns base qty
            if asset_type in (AssetType.ETF, AssetType.REIT, AssetType.INVIT):
                qty = max(1, int(qty * 0.5))  # Conservative sizing for less liquid asset classes
            elif asset_type == AssetType.SME:
                qty = 1  # SME stocks trade in fixed lots
            return qty
        return 1

    def _build_manual_signal_message(self, name: str, sig: dict[str, Any], price: float, rr: Any) -> str:
        """Build the manual-mode Telegram/notification text for a signal.

        Previously just "[MANUAL SIGNAL] {name} {direction} @ {price} RR={rr}"
        - score, tier, regime, VIX, and SL/target were all already sitting
        unused on `sig` by the time this ran (see index_app/domains/signal/
        converter.py::AdaptiveSignalConverter.to_dict()). Someone deciding
        manually, in real time, needs those to make a fast, confident call -
        this is the ONLY thing a manual-mode user sees per signal, so it's
        worth getting right. SL/target are computed the same way
        monitor_positions() would manage a real position (same SL_PCT/
        TARGET_PCT config keys), so the numbers shown match what the bot
        would actually do if this became a live/paper trade.
        """
        direction = str(sig.get("direction", "CALL")).upper()
        try:
            sl_pct = float(self._cfg.get("SL_PCT", 0.92))
            target_pct = float(self._cfg.get("TARGET_PCT", 1.3))
            if direction == "PUT":
                sl_price = price * (2.0 - sl_pct)
                target_price = price * (2.0 - target_pct)
            else:
                sl_price = price * sl_pct
                target_price = price * target_pct
            levels = f"SL: {sl_price:.2f} | Target: {target_price:.2f}"
        except (ValueError, TypeError, ZeroDivisionError):
            levels = ""

        score = sig.get("score")
        tier = sig.get("tier")
        regime = sig.get("regime")
        vix = sig.get("vix")

        header = f"[MANUAL SIGNAL] {name} {direction}"
        if tier or score is not None:
            header += f" (Tier: {tier or 'N/A'}, Score: {score if score is not None else 'N/A'})"

        line2 = f"Entry: {price} | {levels} | RR={rr}" if levels else f"Entry: {price} | RR={rr}"

        line3_parts = []
        if regime:
            line3_parts.append(f"Regime: {regime}")
        if vix is not None:
            line3_parts.append(f"VIX: {vix}")
        lines = [header, line2]
        if line3_parts:
            lines.append(" | ".join(line3_parts))

        soft_blocks = sig.get("soft_blocks")
        if soft_blocks:
            lines.append(f"Caution: {', '.join(str(b) for b in soft_blocks)}")

        return "\n".join(lines)

    def _send_notification(self, message: str, **kwargs) -> None:
        """Send notification - uses stored notification service if available."""
        if self._notification_service is not None:
            try:
                if hasattr(self._notification_service, "send"):
                    self._notification_service.send(message, **kwargs)
                elif callable(self._notification_service):
                    self._notification_service(message, **kwargs)
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
        from core.ports.execution.execution_port import OrderRequest, OrderType

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

        liq_ok, liq_reason = self._check_liquidity_gate(sig)
        if not liq_ok:
            raise TradeBlockError(f"LIQUIDITY_BLOCK: {liq_reason}", reason="liquidity")

        # Submit order
        order_request = OrderRequest(
            symbol=name,
            direction=order_direction,
            strike_price=sig.get("strike", price),
            lot_size=int(qty),
            order_type=OrderType.MARKET,
            price=price,
            idempotency_key=idempotency_key,
        )

        if self._execution_service is not None:
            return self._execution_service.execute_order(order_request)
        raise RuntimeError("No execution service available")

    def _resolve_dte(self, name: str) -> int:
        """Approximate calendar days-to-expiry from the weekly expiry weekday.

        Matches ExpiryDayController's own model (index-aware weekday only,
        no holiday calendar) rather than introducing a second, inconsistent
        notion of "expiry" for the same trade.
        """
        from core.datetime_ist import now_ist

        expiry_weekday = 3  # Thursday fallback (NIFTY/BANKNIFTY/FINNIFTY default)
        if self._expiry_controller is not None:
            try:
                expiry_weekday = self._expiry_controller.get_expiry_weekday(name)
            except (ValueError, TypeError, AttributeError):
                pass
        today = now_ist()
        return (expiry_weekday - today.weekday()) % 7

    def _check_liquidity_gate(self, sig: dict[str, Any]) -> tuple[bool, str]:
        """Pre-entry bid-ask/OI/volume liquidity check (core/liquidity_guard.py).

        Fails OPEN (passes) whenever the signal carries no real option quote
        data — the current signal pipeline has no live option bid/ask feed,
        so this is mechanically wired but a no-op in production until a real
        option-quote source populates sig["bid"]/sig["ask"]. Only blocks when
        the signal actually supplies bid/ask/oi/volume and they fail the
        configured thresholds. Reuses the existing liquidity_guard_enabled
        config key (core/liquidity_guard.py already fails open on it) rather
        than introducing a second enable/disable flag for the same guard.
        """
        bid = sig.get("bid")
        ask = sig.get("ask")
        if bid is None or ask is None:
            return True, "no_quote_data"
        try:
            bid_f, ask_f = float(bid), float(ask)
        except (TypeError, ValueError):
            return True, "no_quote_data"
        if bid_f <= 0 or ask_f <= 0:
            return True, "no_quote_data"

        from core.liquidity_guard import check_entry_liquidity

        result = check_entry_liquidity(
            bid=bid_f, ask=ask_f, oi=sig.get("oi", 0), volume=sig.get("volume", 0),
            cfg=self._cfg,
        )
        return result.passed, (result.reject_reason or "")

    def _store_position(
        self, name: str, price: float, qty: int, direction: str,
        order_direction: str, idempotency_key: str,
        sig: dict[str, Any], order_result: Any,
        asset_type: AssetType | None = None,
    ) -> None:
        """Store position after successful entry.

        Args:
            name: Instrument symbol.
            price: Entry price.
            qty: Position quantity.
            direction: Trade direction (CALL/PUT).
            order_direction: Order direction (BUY/SELL).
            idempotency_key: Idempotency key.
            sig: Signal dict.
            order_result: Order result from execution service.
            asset_type: Explicit asset type (takes precedence over sig dict).
        """
        underlying_entry = self._get_underlying_ltp(name) or price
        # Determine asset type — explicit parameter takes precedence over signal dict
        _sig_asset_type = asset_type or sig.get("asset_type", AssetType.INDEX_OPTIONS)
        if isinstance(_sig_asset_type, AssetType):
            _sig_asset_type = _sig_asset_type.value

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
            "asset_type": _sig_asset_type,  # Store asset type for position tracking
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
            # config key EXIT_ORDER_RETRIES (default 3) - see exit_position()'s
            # matching _exit_order_retries read above.
            if pos["exit_retries"] >= int(self._cfg.get("EXIT_ORDER_RETRIES", 3)):
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
    broker_api_enabled: bool = False,
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
            broker_api_enabled=broker_api_enabled,
            ltp_resolver=ltp_resolver,
            notification_service=notification_service,
        )
    return _position_service_instance


def reset_position_service() -> None:
    """Force-reset singleton (tests only)."""
    global _position_service_instance
    _position_service_instance = None
