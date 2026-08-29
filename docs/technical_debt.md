# Technical Debt — Pointer

This file exists because `scripts/pre_implementation_check.py`'s architecture
document check expects it to be present. The previous content of this file
described a fabricated "GAURAV Platform v5.0.0" status ("Zero Open Critical
Technical Debt") that contradicted the project's real debt tracking and was
removed as part of a documentation-accuracy cleanup.

The authoritative technical debt tracking for this project lives in:

- **[`/TECHNICAL_DEBT_REGISTER.md`](../TECHNICAL_DEBT_REGISTER.md)** — the
  itemized, human-maintained register (DEBT-001…, severities, resolution
  status).
- **[`docs/dead_code_register.md`](dead_code_register.md)** — auto-generated
  by `scripts/scan_dead_code.py` (unused imports, orphaned symbols).
- **[`docs/duplicate_code_register.md`](duplicate_code_register.md)** —
  auto-generated duplicate-symbol scan, same script.

Do not restate debt counts or status here — read the registers above, since
this file will drift out of sync with them the moment either changes.
