# Pull Request Template

## Description
<!-- Describe the change and why it's needed. Link to any related issues. -->

## Type of Change
- [ ] Bug fix (non-breaking change that fixes a defect)
- [ ] New feature (non-breaking change that adds functionality)
- [ ] Breaking change (fix or feature that breaks existing behavior)
- [ ] Refactor (code change that neither fixes a bug nor adds a feature)
- [ ] Configuration change (config keys, env vars, deployment)
- [ ] Documentation (docs, ADRs, runbooks, comments)
- [ ] Governance (tests, invariants, hardening, compliance)

## Risk Assessment
- [ ] **Financial risk**: This change affects order placement, position sizing, or capital management
- [ ] **Broker risk**: This change touches broker adapter code (Kite, Angel, etc.)
- [ ] **Strategy risk**: This change modifies signal generation or exit logic
- [ ] **Data risk**: This change modifies market data ingestion or storage schema
- [ ] **None of the above**

If any risk box is checked, the PR requires review by the relevant module owner (see `docs/ownership_matrix.md`).

## Test Evidence
- [ ] All existing tests pass
- [ ] New tests added for changed code
- [ ] Manual testing performed (describe below)

```
# Paste test output here
```

## Checklist
- [ ] Code follows project conventions (no datetime.now(), no broker SDK coupling)
- [ ] Config keys have safe defaults in `index_config.defaults.json`
- [ ] Schemas regenerated if config keys changed (`python scripts/generate_config_schemas.py`)
- [ ] New modules have corresponding `tests/test_<module>.py`
- [ ] ADR required? Checked `docs/adr/0010-architecture-governance.md` for trigger conditions
- [ ] New runbook required? Considered incident scenarios

## Deployment Notes
<!-- Any special deployment instructions, rollback steps, or migration steps -->
