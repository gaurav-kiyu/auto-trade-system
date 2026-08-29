# Pull Request

## Description

<!-- Provide a clear, concise description of the changes. Include motivation and context. -->

Closes #<!-- issue number -->

## Type of Change

<!-- Check the relevant option(s) -->

- [ ] 🚀 Feature (new functionality)
- [ ] 🐛 Bug fix
- [ ] 🔧 Refactor (no behavioral changes)
- [ ] 📝 Documentation only
- [ ] 🧪 Test additions/modifications
- [ ] ⚙️ Chore (tooling, CI/CD, dependencies)
- [ ] 🔥 Hotfix (emergency production fix)

## Risk Assessment

<!-- Assess the risk of this change -->

- [ ] **NONE** — Documentation/comments only
- [ ] **LOW** — Config values, tests, non-runtime code
- [ ] **MEDIUM** — New feature, behind feature flag or opt-in
- [ ] **HIGH** — Core execution path, risk controls, broker integration

## Evidence of Testing

<!-- Paste test output, screenshots, or link to CI run -->

```bash
# Test output:
$ python -m pytest tests/test_affected_module.py -q
...
```

## Checklist

- [ ] Code follows project conventions (type hints, docstrings, logging)
- [ ] Tests added/updated for the change
- [ ] All existing tests pass
- [ ] Pre-implementation check passed (if applicable): `python scripts/pre_implementation_check.py --files [changed_files]`
- [ ] Documentation updated (if applicable)
- [ ] CHANGELOG.md updated (if applicable)
- [ ] Config schemas regenerated (if defaults changed): `make schemas`
- [ ] No new secrets or credentials in code
- [ ] No new bare `except:` or bare `raise` statements
- [ ] Rollback plan documented (for HIGH risk changes)

## Rollback Plan

<!-- For HIGH risk changes, describe how to revert if issues arise -->

## Additional Context

<!-- Any other information that would help reviewers -->
