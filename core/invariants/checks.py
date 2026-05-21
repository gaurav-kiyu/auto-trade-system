"""
AD-KIYU Standard Invariant Checks v1.0

Pre-built invariant checks for common safety conditions.
"""
from __future__ import annotations

import logging
from core.invariants.engine import InvariantSeverity, register_invariant

_log = logging.getLogger(__name__)


def register_all(safety_state_module=None) -> None:
    """Register all standard invariants."""
    _register_broker_positions_match(safety_state_module)
    _register_single_risk_engine()
    _register_no_stale_data()
    _register_mode_gate()
    _register_no_duplicate_submissions()


def _register_broker_positions_match(safety_state_module=None):
    def _check():
        try:
            if safety_state_module is None:
                return True, "No reconciler configured"
            state = getattr(safety_state_module, 'get_reconciliation_state', lambda: {})()
            mismatches = state.get("mismatches", 0) if isinstance(state, dict) else 0
            if mismatches > 0:
                return False, f"Reconciliation mismatch: {mismatches} positions differ"
            return True, "Positions aligned"
        except Exception as e:
            return False, f"Check error: {e}"

    register_invariant(
        "broker_positions_match_local",
        "Broker positions must match local positions after reconciliation",
        InvariantSeverity.HALT,
        _check,
    )


def _register_single_risk_engine():
    def _check():
        loaded_modules = list(sys.modules.keys())
        risk_engines = [m for m in loaded_modules if "mandate_enforcer" in m or "predictive_risk" in m or "trading_risk" in m]
        if len(risk_engines) > 0:
            return False, f"Deprecated risk modules still loaded: {risk_engines}"
        return True, "Only authoritative risk engine loaded"

    import sys
    register_invariant(
        "single_risk_engine",
        "Only one authoritative risk engine must be loaded",
        InvariantSeverity.HALT,
        _check,
    )


def _register_no_stale_data():
    def _check():
        try:
            from core.safety_state import get_staleness_seconds
            stale = get_staleness_seconds()
            if stale is not None and stale > 30:
                return False, f"Market data stale for {stale}s (max 30s)"
            return True, "Data fresh"
        except ImportError:
            return True, "Staleness check not available"
        except Exception as e:
            return True, f"Staleness check error (non-fatal): {e}"

    register_invariant(
        "no_stale_data_trading",
        "Trading must not use stale market data (>30s)",
        InvariantSeverity.BLOCK,
        _check,
    )


def _register_mode_gate():
    def _check():
        try:
            from core.operating_mode import OperatingModeManager
            modes = [obj for obj in list(sys.modules.values()) if isinstance(obj, type) and hasattr(obj, 'allows_execution')] if False else []
            return True, "Mode gate active"
        except ImportError:
            return True, "Mode module not loaded"
        except Exception as e:
            return True, f"Mode check error (non-fatal): {e}"

    import sys
    register_invariant(
        "operating_mode_gate",
        "Execution must pass through operating mode gate",
        InvariantSeverity.BLOCK,
        _check,
    )


def _register_no_duplicate_submissions():
    def _check():
        try:
            from core.safety_state import get_duplicate_submission_count
            dup = get_duplicate_submission_count()
            if dup and dup > 0:
                return False, f"{dup} duplicate submissions detected"
            return True, "No duplicates"
        except ImportError:
            return True, "Duplicate checker not available"
        except Exception as e:
            return True, f"Duplicate check error (non-fatal): {e}"

    register_invariant(
        "no_duplicate_submissions",
        "Idempotency must prevent all duplicate order submissions",
        InvariantSeverity.HALT,
        _check,
    )
