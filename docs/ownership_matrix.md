# Module Ownership — Pointer

This file exists because `scripts/pre_implementation_check.py`'s architecture
document check expects it to be present. The previous content described a
fabricated "GAURAV Platform v5.0.0" ownership table (wrong broker count,
wrong dashboard module/port, invented team names) that was removed as part
of a documentation-accuracy cleanup.

This is a single-maintainer project — there is no multi-team ownership split
to document. For an accurate, current map of real modules and what they do,
see:

- **[`/CLAUDE.md`](../CLAUDE.md)** — "Key Core Modules" and "Governance &
  Compliance Modules" tables, kept in sync with the actual codebase.
- **[`docs/adr/`](adr/)** — architecture decision records for the "why"
  behind major components.

Do not restate a module list or ownership table here — it will drift out of
sync with CLAUDE.md the moment either changes.
