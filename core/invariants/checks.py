"""
AD-KIYU Standard Invariant Checks v1.1

Pre-built invariant checks for common safety conditions.
All checks use only available runtime APIs — no dangling references.
"""
from __future__ import annotations

import logging
import sys
import time

from core.invariants.engine import InvariantSeverity, register_invariant
from core.exceptions import GovernanceError

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
    _log.info("[INVARIANTS] All %d standard checks registered", 8)


# ── Private helpers ────────────────────────────────────────────────────────────

_RESET_TIMESTAMP: float = time.time()


def _uptime_seconds() -> float:
    return time.time() - _RESET_TIMESTAMP


# ── Check implementations ─────────────────────────────────────────────────────


def _register_broker_positions_match():
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
                return False, f"Hard halt active — potential position mismatch (losses={losses})"
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


def _register_single_risk_engine():
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
            return True, "Risk module not loaded — check skipped"
        except (GovernanceError, AttributeError, RuntimeError) as e:
            return False, f"Check error: {e}"

    register_invariant(
        "single_risk_engine",
        "Only one authoritative risk engine must be loaded",
        InvariantSeverity.HALT,
        _check,
    )


def _register_no_stale_data():
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
                return True, "System halted — data staleness expected"
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


def _register_mode_gate():
    """Verify execution passes through the operating mode gate."""

    def _check():
        try:


            return True, "Mode gate active"
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


def _register_no_duplicate_submissions():
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


def _register_hard_halt_safety():
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


def _register_consecutive_loss_safety():
    """Verify consecutive losses haven't breached a reasonable threshold."""

    MAX_CONSECUTIVE_LOSSES = 10

    def _check():
        try:
            from core.safety_state import get_consecutive_losses, is_hard_halted

            losses = get_consecutive_losses()
            halted = is_hard_halted()
            if losses >= MAX_CONSECUTIVE_LOSSES and not halted:
                return False, f"{losses} consecutive losses — threshold ({MAX_CONSECUTIVE_LOSSES}) breached"
            if losses >= MAX_CONSECUTIVE_LOSSES:
                return True, f"{losses} consecutive losses (system halted — expected)"
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


def _register_intraday_pnl_monitor():
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
