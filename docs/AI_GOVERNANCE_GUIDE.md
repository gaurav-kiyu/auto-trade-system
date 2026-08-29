# AI Governance Guide

This file previously did not exist despite being referenced from `CLAUDE.md`.
It describes what actually happens when an AI agent (or any contributor)
changes code in this repo, based on the real, verified mechanics of
`core/constitution_ai_gate.py` and `scripts/pre_implementation_check.py` —
not an aspirational protocol.

## What's actually enforced automatically

1. **Pre-commit hook** (`pre-implementation-governance` in
   `.pre-commit-config.yaml`, backed by `scripts/pre_implementation_check.py
   --files <staged .py files>`) — blocks a commit that introduces a new,
   staged reference to a risk-sensitive pattern (see list below) in a file
   not already covered by the reviewed-change allowlist, or that touches a
   `BLOCKED_CHANGES` test-certification file at all. Activate once per
   clone with `make install-hooks`.
2. **CI** (`.github/workflows/ci.yml`'s `governance` job,
   `bitbucket-pipelines.yml`'s `&governance-step`) — reconstructs the
   PR/push diff and runs the same check as a blocking step, plus
   `scripts/score_system.py --ci --check-min 5.0`.

## What's real but opt-in (not automatically invoked)

- `core/constitution_ai_gate.py`'s `AIGovernanceGate` — a Python API an
  agent can call voluntarily:
  ```python
  from core.constitution_ai_gate import get_gate
  gate = get_gate()
  gate.acknowledge_constitution()
  gate.validate(changed_files=[...], action_description="...")
  ```
  Its risk-keyword scan reads whole-file content (not a diff), so it is
  stricter/noisier than the diff-based pre-commit hook — expect it to flag
  files that merely *contain* a risk keyword, not just files with new
  risk-sensitive lines.
- `core/constitution/__init__.py`'s `ConstitutionValidator` — the 111-category
  scoring engine (see `docs/constitution_scoring_framework.md`). Largely
  self-certified from static repo inspection, not a live audit.

## The one workflow that actually gates a change today

Before staging a change to a risk-sensitive file/pattern:

```bash
python scripts/pre_implementation_check.py --files <changed files>
```

If it reports a violation for a *legitimately reviewed* change (e.g. wiring
a documented `--paper` CLI flag that references `PAPER_MODE`):

```bash
python scripts/pre_implementation_check.py --allow-add <file> \
    --pattern <PATTERN> --reason "<why this is safe>" --reviewer operator
python scripts/pre_implementation_check.py --list-allowlist   # audit view
```

Commit the updated `json/pre_implementation_allowlist.json` alongside the
change. Never hand-edit that file — only `--allow-add` validates the
pattern is a known risk-sensitive one and rejects `BLOCKED_CHANGES` files
outright (they can never be allowlisted).

## Risk-sensitive patterns (`RISK_SENSITIVE_PATTERNS`)

`_trip_hard_halt`, `MAX_DAILY_LOSS`, `MAX_DRAWDOWN`, `SL_PCT`, `TARGET_PCT`,
`TRAIL_PCT`, `PORTFOLIO_MAX_SL_RISK_PCT`, `can_enter_position`,
`get_position_size`, `PAPER_MODE`, `PaperBrokerAdapter`, `datetime.now()`

## Risk-sensitive files (`RISK_SENSITIVE_FILES`, warning-only list)

`core/services/risk_service.py`, `index_app/index_trader.py`,
`core/adapters/broker_adapters.py`, `core/config_bootstrap.py`,
`core/environment.py`, `core/datetime_ist.py`

## Blocked changes (`BLOCKED_CHANGES`, never allowlistable)

`test_smoke.py`, `test_broker_contract_certification.py`,
`test_exactly_once_certification.py`
