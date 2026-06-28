## Description

Please include a summary of the change and which issue is fixed.

Fixes # (issue)

## Type of Change

- [ ] Bug fix (non-breaking change that fixes an issue)
- [ ] New feature (non-breaking change that adds functionality)
- [ ] Breaking change (fix or feature that would cause existing functionality to not work as expected)
- [ ] Documentation update
- [ ] Test addition or modification
- [ ] Performance improvement
- [ ] Refactoring (no functional changes)

## Risk Assessment

- [ ] No risk — documentation, tests, or cosmetics only
- [ ] Low risk — well-understood change with existing test coverage
- [ ] Medium risk — touches core trading/risk/execution logic
- [ ] High risk — modifies risk controls, kill switches, or broker integration

## Checklist

- [ ] My code follows the project's coding standards (type hints, docstrings, imports)
- [ ] I have added/updated tests that prove my fix is effective or my feature works
- [ ] All existing tests pass: `python -m pytest tests/ -q`
- [ ] Certification gates pass: `python -m core.certification.gate`
- [ ] Pre-implementation check passes: `python scripts/pre_implementation_check.py --files <my_files>`
- [ ] No dead code introduced: `python scripts/scan_dead_code.py`
- [ ] Config keys have safe defaults in `index_config.defaults.json` (if applicable)
- [ ] I have regenerated config schemas if defaults changed: `python scripts/generate_config_schemas.py`
- [ ] I have updated documentation (README, runbooks, ADRs) if needed

## Testing

Describe the testing you performed:
1. 
2. 
3. 

## Additional Context

Add any other context about the pull request here.
