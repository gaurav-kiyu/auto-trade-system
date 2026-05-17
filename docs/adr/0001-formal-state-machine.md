# ADR 0001: Formal State Machine for Execution Lifecycle

## Status
Accepted

## Date
2026-05-16

## Context
The trading system used organic if/else transitions for order lifecycle, which was fragile and error-prone.

## Decision
Implemented formal state machine with strict legal transitions:
- States: CREATED, RISK_APPROVED, SUBMITTING, UNKNOWN, ACKNOWLEDGED, PARTIALLY_FILLED, FILLED, CANCEL_PENDING, CANCELLED, RECONCILING, REJECTED, FAILED_FINAL
- Valid transitions defined in VALID_TRANSITIONS dictionary
- Transition validation enforced before any state change

## Consequences
- Prevents invalid state transitions
- Easier debugging via transition history
- Easier testing with known states
- Easier recovery from ambiguous states
- Added `core/execution/execution_state.py` module