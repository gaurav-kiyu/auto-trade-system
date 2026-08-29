# Architecture Decision Records (ADR) Index

This directory contains Architecture Decision Records for the OPB Trading Platform.

## Current ADRs

This repo has two parallel ADR numbering series that grew independently and
are **not** cross-referenced from each other's text — both are real and
current; neither supersedes the other. Some topics (broker abstraction,
idempotent order IDs) are covered once in each series from a different
angle — check both if researching one of those topics.

### `NNNN-title.md` series

| ID | Title | Status | Date |
|----|-------|--------|------|
| 0001 | Formal State Machine for Execution Lifecycle | ACCEPTED | 2026-05-16 |
| 0002 | Event-Driven Architecture | ACCEPTED | 2026-05-16 |
| 0003 | Plugin Strategy Framework | ACCEPTED | 2026-05-16 |
| 0004 | Broker Abstraction with Contract Enforcement | ACCEPTED | 2026-05-16 |
| 0005 | Portfolio Engine for Multi-Strategy Tracking | ACCEPTED | 2026-05-16 |
| 0006 | Shadow Mode for Safe Feature Rollout | ACCEPTED | 2026-05-16 |
| 0007 | Replay Engine for Incident Debugging | ACCEPTED | 2026-05-16 |
| 0008 | Blue/Green Deployment Model | ACCEPTED | 2026-05-16 |
| 0009 | API Gateway / Control Plane | ACCEPTED | 2026-05-16 |
| 0010 | Architecture Governance Framework | ACCEPTED | 2026-05-22 |
| 0011 | ML Classifier Architecture — LightGBM Win-Probability Predictor | ACCEPTED | 2026-07-18 |
| 0012 | Configuration System Architecture — Three-Layer Merge with Secure Secrets | ACCEPTED | 2026-07-18 |
| 0013 | Monitoring & Observability Stack — Prometheus, Loki, Grafana, OpenTelemetry | ACCEPTED | 2026-07-18 |
| 0017 | Vertical Slice Architecture | ACCEPTED | 2026-07-30 |
| 0018 | Modular Monolith Architecture | ACCEPTED | 2026-07-30 |

### `ADR-00N-title.md` series

| ID | Title | Status | Date |
|----|-------|--------|------|
| ADR-001 | Event Store as the Single Source of Truth for Execution State | ACCEPTED | Jul 2026 |
| ADR-002 | Idempotency-First Order Submission Design | ACCEPTED | Jul 2026 |
| ADR-003 | Paper Mode Invariant | ACCEPTED | Jul 2026 |
| ADR-004 | 3-Layer Config Merge with OPBUYING_* Environment Injection | ACCEPTED | Jul 2026 |
| ADR-005 | DDD with Ports/Adapters for Broker Independence | ACCEPTED | Jul 2026 |
| ADR-006 | Circuit Breaker Pattern for Market Data and Broker Resilience | ACCEPTED | Jul 2026 |
| ADR-007 | Deterministic client_order_id Generation for Idempotency | ACCEPTED | Jul 2026 |
| ADR-008 | SQLite with WAL Mode for Single-Node, PostgreSQL for Production | ACCEPTED | Jul 2026 |

## ADR Lifecycle

- **PROPOSED** — Under review, not yet implemented
- **ACCEPTED** — Approved and implemented
- **SUPERSEDED** — Replaced by a newer ADR
- **DEPRECATED** — No longer relevant

## New ADR Template

```markdown
# ADR-NNN: Title

## Status
[PROPOSED | ACCEPTED | SUPERSEDED | DEPRECATED]

## Context
...

## Decision
...

## Consequences
...
```
