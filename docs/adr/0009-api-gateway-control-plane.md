# ADR 0009: API Gateway / Control Plane

## Status
Accepted

## Date
2026-05-16

## Context
System lacked unified runtime control interface for operators to pause, resume, or halt trading without direct code intervention.

## Decision
Implemented API Gateway / Control Plane with:
- REST-style control actions: PAUSE, RESUME, HARD_HALT, SOFT_STOP
- Feature flag updates at runtime
- Risk limit modifications
- Broker failover triggers
- Configuration reload
- Control history tracking for audit

## Consequences
- Safe runtime control without code changes
- Emergency kill switch capability
- Feature flag toggling without redeploy
- Audit trail of all control actions
- Operator-friendly interface
- Added `core/api_gateway.py` module