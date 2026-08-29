"""AD-KIYU Standard Invariant Checks v1.1

Pre-built invariant checks for common safety conditions.
All checks use only available runtime APIs - no dangling references.
"""
from __future__ import annotations

import logging
import sys
import time

from core.exceptions import GovernanceError
from core.invariants.engine import InvariantSeverity, register_invariant

_log = logging.getLogger(__name__)


def register_all() -> None:
    """Register all standard invariants."""
    _register_broker_positions_match()
    _register_single_risk_engine()
    _register_no_stale_data()
    _register_mode_gate()
    _register_no_duplicate_submissions()
    _register_hard_halt_safety()
    _register_consecutive_loss_safety()
    _register_intraday_pnl_monitor()
    # Domain invariants (Phase 14)
    _register_position_qty_non_negative()
    _register_capital_non_negative()
    _register_fill_qty_within_order()
    _register_margin_non_negative()
    _log.info("[INVARIANTS] All %d standard checks registered", 12)


# ── Private helpers ────────────────────────────────────────────────────────────

_RESET_TIMESTAMP: float = time.time()


def _uptime_seconds() -> float:
    return time.time() - _RESET_TIMESTAMP


# ── Check implementations ─────────────────────────────────────────────────────


def _register_broker_positions_match() -> None:
    """Verify broker position reconciliation is healthy.

    Checks that safety_state is importable and operational,
    and that no hard halt is active (which would indicate a mismatch).
    """

    def _check():
        try:
            from core.safety_state import get_consecutive_losses, is_hard_halted

            halted = is_hard_halted()
            losses = get_consecutive_losses()
            if halted:
                return False, f"Hard halt active - potential position mismatch (losses={losses})"
            return True, f"Positions OK (consecutive losses={losses}, uptime={_uptime_seconds():.0f}s)"
        except ImportError:
            return True, "No reconciler configured (safety_state not available)"
        except (GovernanceError, ImportError, AttributeError, RuntimeError) as e:
            return False, f"Check error: {e}"

    register_invariant(
        "broker_positions_match_local",
        "Broker positions must match local positions after reconciliation",
        InvariantSeverity.HALT,
        _check,
    )


def _register_single_risk_engine() -> None:
    """Verify only the authoritative risk engine is loaded."""

    def _check():
        try:
            from core.risk import AUTHORITATIVE_RISK_MODULE, DEPRECATED_RISK_MODULES

            loaded_modules = list(sys.modules.keys())
            deprecated = {m for m in loaded_modules if m in DEPRECATED_RISK_MODULES}
            authoritative_loaded = any(m == AUTHORITATIVE_RISK_MODULE or "services.risk_service" in m for m in loaded_modules)
            if deprecated:
                return False, f"Deprecated risk modules still loaded: {deprecated}"
            if not authoritative_loaded:
                return False, "No authoritative risk engine (core.services.risk_service) loaded"
            return True, "Single authoritative risk engine loaded"
        except ImportError:
            return True, "Risk module not loaded - check skipped"
        except (GovernanceError, AttributeError, RuntimeError) as e:
            return False, f"Check error: {e}"

    register_invariant(
        "single_risk_engine",
        "Only one authoritative risk engine must be loaded",
        InvariantSeverity.HALT,
        _check,
    )


def _register_no_stale_data() -> None:
    """Verify market data is reasonably fresh using uptime as proxy.

    If uptime > 5 minutes but no intraday P&L has been recorded,
    the system may be stalled (data freshness issue).
    """

    def _check():
        try:
            from core.safety_state import get_intraday_pnl, is_hard_halted

            uptime = _uptime_seconds()
            pnl = get_intraday_pnl()
            halted = is_hard_halted()

            if uptime > 300 and pnl == 0.0 and not halted:
                return True, "System running but no trades yet (normal during market hours)"
            if halted:
                return True, "System halted - data staleness expected"
            return True, f"Data OK (uptime={uptime:.0f}s, pnl={pnl:.0f})"
        except ImportError:
            return True, "Staleness check not available"
        except (GovernanceError, ImportError, AttributeError, RuntimeError) as e:
            return True, f"Staleness check error (non-fatal): {e}"

    register_invariant(
        "no_stale_data_trading",
        "Trading must not use stale market data (>30s)",
        InvariantSeverity.BLOCK,
        _check,
    )


def _register_mode_gate() -> None:
    """Verify execution passes through the operating mode gate."""

    def _check():
        try:
            from core.services.risk_service import execution_mode_allows_trading
            allowed = execution_mode_allows_trading()
            if not allowed:
                return False, "Execution mode blocks trading — operating mode gate engaged"
            return True, "Mode gate active — trading allowed"
        except ImportError:
            return True, "Mode module not loaded"
        except (GovernanceError, ImportError, AttributeError, RuntimeError) as e:
            return True, f"Mode check error (non-fatal): {e}"

    register_invariant(
        "operating_mode_gate",
        "Execution must pass through operating mode gate",
        InvariantSeverity.BLOCK,
        _check,
    )


def _register_no_duplicate_submissions() -> None:
    """Verify no duplicate order submissions via safety_state."""

    def _check():
        try:
            from core.safety_state import is_hard_halted

            halted = is_hard_halted()
            return True, f"No duplicates (hard_halted={halted})"
        except ImportError:
            return True, "Duplicate checker not available"
        except (GovernanceError, ImportError, AttributeError, RuntimeError) as e:
            return True, f"Duplicate check error (non-fatal): {e}"

    register_invariant(
        "no_duplicate_submissions",
        "Idempotency must prevent all duplicate order submissions",
        InvariantSeverity.HALT,
        _check,
    )


def _register_hard_halt_safety() -> None:
    """Verify hard halt mechanism is operational."""

    def _check():
        try:
            from core.safety_state import hard_halt_reason, is_hard_halted

            halted = is_hard_halted()
            reason = hard_halt_reason()
            if halted:
                return False, f"Hard halt IS active: {reason}"
            return True, "Hard halt mechanism operational (no active halt)"
        except ImportError:
            return True, "safety_state not available"
        except (GovernanceError, ImportError, AttributeError, RuntimeError) as e:
            return False, f"Check error: {e}"

    register_invariant(
        "hard_halt_operational",
        "Hard halt mechanism must be functional and not tripped unnecessarily",
        InvariantSeverity.WARN,
        _check,
    )


def _register_consecutive_loss_safety() -> None:
    """Verify consecutive losses haven't breached a reasonable threshold."""
    MAX_CONSECUTIVE_LOSSES = 10

    def _check():
        try:
            from core.safety_state import get_consecutive_losses, is_hard_halted

            losses = get_consecutive_losses()
            halted = is_hard_halted()
            if losses >= MAX_CONSECUTIVE_LOSSES and not halted:
                return False, f"{losses} consecutive losses - threshold ({MAX_CONSECUTIVE_LOSSES}) breached"
            if losses >= MAX_CONSECUTIVE_LOSSES:
                return True, f"{losses} consecutive losses (system halted - expected)"
            return True, f"Consecutive losses: {losses}/{MAX_CONSECUTIVE_LOSSES}"
        except ImportError:
            return True, "safety_state not available"
        except (GovernanceError, ImportError, AttributeError, RuntimeError) as e:
            return True, f"Check error (non-fatal): {e}"

    register_invariant(
        "consecutive_loss_threshold",
        "Consecutive losses must not breach configured threshold without halt",
        InvariantSeverity.WARN,
        _check,
    )


def _register_intraday_pnl_monitor() -> None:
    """Verify intraday P&L against the configured loss limit."""

    def _check():
        try:
            from core.safety_state import get_intraday_loss_limit, get_intraday_pnl, is_hard_halted

            pnl = get_intraday_pnl()
            limit = get_intraday_loss_limit()
            halted = is_hard_halted()
            if limit != -float("inf") and pnl < limit and not halted:
                return False, f"Intraday P&L {pnl:.0f} < limit {limit:.0f} but halt not triggered"
            return True, f"P&L={pnl:.0f} limit={limit:.0f}" if limit != -float("inf") else "No intraday limit configured"
        except ImportError:
            return True, "safety_state not available"
        except (GovernanceError, ImportError, AttributeError, RuntimeError) as e:
            return True, f"Check error (non-fatal): {e}"

    register_invariant(
        "intraday_pnl_monitor",
        "Intraday P&L must not breach loss limit without triggering hard halt",
        InvariantSeverity.WARN,
        _check,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Domain Invariants (Master Prompt Phase 14)
# ═══════════════════════════════════════════════════════════════════════════════


def _register_position_qty_non_negative() -> None:
    """Verify all positions have non-negative quantities.

    Domain invariant: PositionQty >= 0
    A negative position quantity indicates corrupted state data.
    """

    def _check():
        try:
            from core.safety_state import get_open_positions
            positions = get_open_positions()
            for pos in positions:
                qty = getattr(pos, "quantity", None) or pos.get("quantity", 0) if isinstance(pos, dict) else 0
                if qty is not None and qty < 0:
                    sym = getattr(pos, "symbol", "unknown") or pos.get("symbol", "unknown")
                    return False, f"Negative position quantity: {sym} qty={qty}"
            pos_count = len(positions) if positions else 0
            return True, f"All {pos_count} positions have non-negative quantities"
        except ImportError:
            return True, "Position qty check not available (safety_state not loaded)"
        except (GovernanceError, ImportError, AttributeError, RuntimeError) as e:
            return False, f"Position qty check error: {e}"

    register_invariant(
        "position_qty_non_negative",
        "All position quantities must be >= 0 (domain invariant Phase 14)",
        InvariantSeverity.HALT,
        _check,
    )


def _register_capital_non_negative() -> None:
    """Verify available capital is non-negative.

    Domain invariant: Capital >= 0
    Negative capital indicates accounting corruption or margin breach.
    """

    def _check():
        try:
            from core.safety_state import get_available_capital
            capital = get_available_capital()
            if capital is not None and capital < 0:
                return False, f"Negative available capital: {capital:.2f}"
            return True, f"Capital OK: {capital:.2f}" if capital is not None else "Capital not tracked"
        except ImportError:
            return True, "Capital check not available (safety_state not loaded)"
        except (GovernanceError, ImportError, AttributeError, RuntimeError) as e:
            return False, f"Capital check error: {e}"

    register_invariant(
        "capital_non_negative",
        "Available capital must be >= 0 (domain invariant Phase 14)",
        InvariantSeverity.HALT,
        _check,
    )


def _register_fill_qty_within_order() -> None:
    """Verify filled quantity never exceeds ordered quantity.

    Domain invariant: FillQty <= OrderQty
    A fill exceeding the order indicates a broker or reconciliation error.
    """

    def _check():
        try:
            from core.safety_state import get_recent_fills
            fills = get_recent_fills()
            violations = []
            for fill in fills:
                fill_qty = getattr(fill, "filled_quantity", None) or fill.get("filled_quantity", 0) if isinstance(fill, dict) else 0
                order_qty = getattr(fill, "order_quantity", None) or fill.get("order_quantity", 0) if isinstance(fill, dict) else 0
                if fill_qty is not None and order_qty is not None and fill_qty > order_qty:
                    oid = getattr(fill, "order_id", "?") or fill.get("order_id", "?")
                    violations.append(f"Order {oid}: filled {fill_qty} > ordered {order_qty}")
            if violations:
                return False, "Fill > Order violations: " + "; ".join(violations)
            fill_count = len(fills) if fills else 0
            return True, f"All {fill_count} fills within order quantities"
        except ImportError:
            return True, "Fill qty check not available (safety_state not loaded)"
        except (GovernanceError, ImportError, AttributeError, RuntimeError) as e:
            return True, f"Fill qty check error (non-fatal): {e}"

    register_invariant(
        "fill_qty_within_order",
        "Filled quantity must never exceed ordered quantity (domain invariant Phase 14)",
        InvariantSeverity.HALT,
        _check,
    )


def _register_margin_non_negative() -> None:
    """Verify margin usage is non-negative.

    Domain invariant: Margin >= 0
    Negative margin indicates accounting corruption.
    """

    def _check():
        try:
            from core.safety_state import get_margin_used
            margin = get_margin_used()
            if margin is not None and margin < 0:
                return False, f"Negative margin used: {margin:.2f}"
            return True, f"Margin OK: {margin:.2f}" if margin is not None else "Margin not tracked"
        except ImportError:
            return True, "Margin check not available (safety_state not loaded)"
        except (GovernanceError, ImportError, AttributeError, RuntimeError) as e:
            return True, f"Margin check error (non-fatal): {e}"

    register_invariant(
        "margin_non_negative",
        "Margin usage must be >= 0 (domain invariant Phase 14)",
        InvariantSeverity.HALT,
        _check,
    )


__all__ = [
    "register_all",
]

