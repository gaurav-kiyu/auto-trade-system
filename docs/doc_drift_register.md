# Documentation Drift Register

**Authority:** Final Master System Constitution — Mandatory Technical Debt Governance  
**Purpose:** Track documentation that has drifted from the actual implementation  
**Last Updated:** 2026-05-30  
**Review Cycle:** Every release

---

## Format

| ID | Document | Section | Expected | Actual | Detected | Status |
|----|----------|---------|----------|--------|----------|--------|
| DDR-001 | — | — | — | — | — | — |

---

## Active Entries

*No documentation drift entries currently tracked.*

## Drift Categories

| Category | Description | Detection Method |
|----------|-------------|-----------------|
| **MISSING_SECTION** | Document lacks section for existing feature | Manual review |
| **OUTDATED** | Document describes behavior that no longer matches code | Cross-reference |
| **MISSING_DOC** | No documentation exists for a feature or module | Automated scan |
| **CONTRADICTORY** | Two documents describe the same thing differently | Regular audit |
| **STALE_REFERENCE** | Document references removed/renamed files or APIs | Link checker |
| **VERSION_MISMATCH** | Document version differs from implementation version | Version comparison |

## Remediation Policy

1. **Detection**: Automated via `scripts/sync_artifacts.py --check-doc-drift` and CI documentation sync step
2. **Documentation Sync Log**: All drift fixes recorded in `docs/DOCUMENTATION_SYNC_LOG.md`
3. **Prevention**: Documentation must be updated in the same PR as code changes (enforced by pre-commit hook)

## Resolved Entries

*No entries have been resolved yet.*

---

*End of Documentation Drift Register — v1.0*
