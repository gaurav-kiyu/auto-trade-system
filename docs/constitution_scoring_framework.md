# Constitution Scoring Framework

This file previously did not exist despite being referenced from `CLAUDE.md`
and `scripts/pre_implementation_check.py`'s context-gathering output. It is
written from the actual implementation in `core/constitution/__init__.py`
(`ConstitutionValidator`), not from a separate spec — that module is the
source of truth; this doc summarizes it.

## Category groups (111 total, `CATEGORIES` dict)

| Group | Prefix | Count | Covers |
|---|---|---|---|
| Classic | `ARCH`/`SEC`/`RSK`/`EXE`/`TST`/`OBS`/`GOV`/`DR` | 31 | Architecture, security, risk, execution, testing, observability, governance, disaster recovery |
| Enterprise layers | `LAY-*` | 12 | Cross-cutting platform layers |
| Quality gates | `QGT-*` | 12 | Release/quality gate criteria |
| Principles | `PRN-*` | 13 | Engineering principles |
| Architecture standards | `AST-*` | 13 | Standards referenced by the ADR series (e.g. vertical-slice/modular-monolith ADRs cite `AST-03`, `AST-07`) |
| Security/governance | `SGS-*` | 11 | Security + governance controls |
| Platform | `PLS-*` | 6 | Platform-level concerns |
| SRE | `SRE-*` | 9 | Site reliability categories |
| Knowledge | `KNW-*` | 4 | Documentation/knowledge management |

Each category is initialized with `max_score=10.0`.

## Evidence-gated scoring (`validate_score_evidence()`)

A category's score is only accepted at face value if backed by evidence:

- Score **> 8.0** requires evidence to be present.
- Score **> 9.0** requires evidence to be present (stricter check).
- Score **> 9.5** requires **9 named audit types** to be present in the
  category's `audits` field.

The same evidence-gate logic is duplicated (near-verbatim) in
`core/constitution_ai_gate.py`'s `AIGovernanceGate.validate()` step 6 — keep
both in sync if the thresholds change.

## Evidence collection

On construction, `ConstitutionValidator.__init__()` calls
`_collect_auto_evidence()`, which scans `core/constitution/evidence/` on
disk and auto-populates category evidence from static repo inspection.
Scores are therefore largely self-certified from the current repo state,
not from an independent live audit — treat a high score as "the repo
currently looks compliant by this automated check," not as a substitute for
manual review.

## 10-step change pipeline (`CHANGE_PIPELINE_STEPS`)

`review → impact_analysis → design → implementation → testing → validation
→ documentation → audit → acceptance → release`

`validate_change_pipeline()` accepts a caller-supplied `dict[str, bool]` and
checks it against this list — it trusts whatever the caller claims for each
step; it does not independently re-verify that a step actually happened.

## How this is actually invoked

- `scripts/score_system.py` is the CLI entry point (`--category`, `--json`,
  `--check-min`). It delegates evidence collection to
  `ConstitutionValidator` with a filesystem-scan fallback.
- **Not** wired into any git hook — running it is opt-in / CI-scheduled
  (see `.github/workflows/ci.yml`'s `governance` job).
- The real, always-enforced pre-commit gate for *risk-sensitive code
  changes* specifically is `scripts/pre_implementation_check.py`, which is a
  separate, narrower, diff-aware mechanism — see `CLAUDE.md`'s
  "Pre-commit Hook (AI Governance)" section.

## Commands

```bash
python scripts/score_system.py                          # Full report
python scripts/score_system.py --category RSK-01        # Single category
python scripts/score_system.py --json --check-min 6.0   # CI mode
```
