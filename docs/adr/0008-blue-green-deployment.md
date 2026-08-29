# ADR 0008: Blue/Green Deployment Model

## Status
Accepted

## Date
2026-05-16

## Context
Releasing new versions carried risk of immediate production impact with no quick rollback capability.

## Decision
Implemented blue/green deployment with:
- Two deployment slots: primary (active) and shadow (staging)
- Gradual traffic shift after validation
- Instant rollback capability
- Shadow mode comparison during validation
- Version tracking in configuration

## Consequences
- Zero-downtime releases
- Instant rollback on issues
- Safe production validation
- Reduced release risk
- Added `core/deployment/blue_green.py` module