# ADR 0010: Architecture Governance Framework

## Status
Accepted

## Date
2026-05-22

## Context
The codebase has grown to ~300+ modules across multiple layers. With 20+ contributors and
production trading at stake, the project needs formal architecture governance to:

1. Track design decisions and their rationale over time (ADR chain).
2. Document module ownership to prevent orphaned code and enable accountability.
3. Maintain a technical debt register to make invisible quality issues visible.
4. Define clear module boundaries and dependency rules to prevent architectural erosion.

Without governance, undocumented design drift leads to conflicting implementations,
hard-to-debug integration failures, and increased onboarding cost for new developers.

## Decision

### 1. ADR Chain (Mandatory)
All significant architectural decisions MUST be documented as ADR files in `docs/adr/`.

Trigger conditions for a new ADR:
- Adding a new top-level module directory
- Changing inter-module dependency direction
- Introducing a new external dependency
- Changing the config merge strategy
- Changing the state machine lifecycle
- Adding a new execution mode
- Modifying risk authority ownership
- Changing broker abstraction boundaries
- Introducing a new AI/ML component

ADR format (MUST include): Status, Date, Context, Decision, Consequences.

### 2. Module Ownership Matrix
Every module under `core/`, `infrastructure/`, and `index_app/` MUST have an
identified owner documented in `docs/ownership_matrix.md`.

Owner responsibilities:
- Code review for all changes to owned modules
- Maintaining backward compatibility or managing deprecation
- Responding to issues within 48 hours during market hours
- Updating tests when module behavior changes

### 3. Technical Debt Register
A living document at `docs/technical_debt.md` tracks known architectural debt items.

Each entry MUST include:
- Description of the debt
- Location (module, file, or cross-cutting concern)
- Estimated remediation effort (S/M/L/XL)
- Impact severity (LOW/MEDIUM/HIGH/CRITICAL)
- Status (IDENTIFIED/PLANNED/IN_PROGRESS/RESOLVED/ACCEPTED)

Debt items with CRITICAL impact MUST be resolved before the next minor release.
HIGH impact items MUST have a remediation plan within one release cycle.

### 4. Module Boundary Rules
- `core/` modules MUST NOT import from `infrastructure/` directly (adapter pattern enforced).
- `core/ports/` defines all port interfaces; `infrastructure/` provides implementations.
- Circular imports between `core/` packages are prohibited (lint-enforced).
- Strategy modules MUST NOT import broker adapters directly — MUST go through
  `core/adapters/broker_adapters.py` or the execution engine.
- AI modules MUST NOT mutate live strategy state — MUST go through ModelRegistry
  with approval workflow.

## Consequences
### Positive
- Clearer design rationale preserved for future developers.
- Every module has a named owner responsible for quality.
- Technical debt is visible and prioritized rather than silently accumulating.
- Dependency rules prevent architectural drift at source.

### Negative
- Overhead of maintaining ADRs and ownership matrix.
- Risk of ADRs being treated as ceremony rather than insight (mitigated by
  making them mandatory in PR review checklist).
- Ownership may become stale if team composition changes without update.

## Compliance
Enforcement mechanisms:
1. PR review checklist MUST verify ADR requirement for triggering changes.
2. `docs/ownership_matrix.md` is reviewed monthly for stale entries.
3. Technical debt register is reviewed during release planning.
4. CI pipeline runs `scripts/check_architecture_compliance.py` (future work).

## References
- ADR 0001: Formal State Machine
- ADR 0004: Broker Abstraction
- ADR 0005: Portfolio Engine
- ADR 0006: Shadow Mode
- `docs/operations/` — Incident governance runbooks
