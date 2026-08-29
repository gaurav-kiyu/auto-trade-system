# ADR 0017: Vertical Slice Architecture

## Status
Accepted

## Date
2026-07-30

## Context
The codebase has grown to ~615+ test files and hundreds of modules across the trading platform. As the system evolves, we need a clear architectural pattern that organizes code by business capability rather than technical layer. The existing horizontal layering (controllers → services → repositories) leads to:

1. **Scattered changes** — A single feature touches 5+ layers across the codebase
2. **High cognitive load** — Developers must navigate 3-4 directories to understand one feature
3. **Difficult parallel development** — Multiple teams stepping on each other in shared layer files
4. **Weak cohesion** — Related business logic is dispersed across technical boundaries

The Master Engineering Constitution v4.0 mandates Vertical Slice as an architecture standard (AST-03) alongside DDD and Clean Architecture.

## Decision

We adopt **Vertical Slice Architecture** as the primary organization pattern for new features, while preserving existing horizontal layers for established modules (migration on modification).

### Core Principles

1. **Slice by Business Capability** — Each slice contains everything needed for a business operation: command/query handler, domain logic, persistence mapping, validation, and tests
2. **Cross-Layer, Not Cross-Slice** — Logic flows vertically through technical layers within a single slice, not horizontally across slices
3. **Slice Ownership** — Each slice has a single owner (documented in `docs/ownership_matrix.md`)
4. **No Slice-to-Slice Direct Calls** — Slices communicate only through the mediator pattern or domain events
5. **Shared Kernel** — Truly cross-cutting concerns (auth, logging, metrics, configuration) live in a shared kernel outside slices

### Slice Structure

```
core/slices/<slice_name>/
├── __init__.py          # Public API for this slice
├── commands.py          # Command handlers
├── queries.py           # Query handlers  
├── domain.py            # Domain models and logic
├── persistence.py       # Database/serialization mapping
└── tests/               # Slice-specific tests
    └── test_<slice>.py
```

### Existing Slices (Identified)

| Slice | Location | Owner | Status |
|-------|----------|-------|--------|
| Trading Orchestration | `core/services/use_cases/trading_orchestrator.py` | Core | ✅ Migrated |
| Strategy Execution | `core/strategy/orchestrator.py` | Core | ✅ Migrated |
| Order Execution | `core/execution/` | Execution | ✅ Migrated |
| Self-Healing | `core/self_healing/` | SRE | ✅ Migrated |
| Auth & Sessions | `core/auth/` | Security | ✅ Migrated |

### Boundary Rules

1. A slice MUST NOT import from another slice's implementation (`core/slices/*/`) — use mediator/events only
2. A slice MAY import from `core/ports/*`, `core/patterns/*`, `core/shared/*`
3. A slice MUST expose a public API via `__init__.py` for mediator dispatch
4. Test files for a slice MUST be in `tests/test_slice_<name>.py` or within the slice directory
5. Adding a new slice requires an ADR update and ownership assignment

## Consequences

### Positive
- Features are self-contained and independently deployable
- Reduced merge conflicts from parallel development
- Clearer code navigation — one directory per business capability
- Simplified testing — slice tests exercise a complete vertical flow
- Easier refactoring — changes to one slice don't cascade across layers

### Negative
- Migration effort for ~40 existing modules across core/
- Risk of duplicated shared logic across slices (mitigated by shared kernel)
- Learning curve for developers accustomed to horizontal layering
- Slice boundary enforcement requires CI tooling

## Compliance
Enforcement mechanisms:
1. CI runs `scripts/check_slice_boundaries.py` to verify no cross-slice imports
2. PR review checklist verifies slice structure for new modules
3. `docs/ownership_matrix.md` updated when slices are added
4. `tests/test_architecture_slice_boundaries.py` validates slice isolation

## References
- Master Engineering Constitution v4.0 — AST-03 (Vertical Slice)
- ADR 0010: Architecture Governance Framework
- ADR 0002: Event-Driven Architecture (for slice communication via domain events)
- ADR 0003: Plugin Strategy Framework
