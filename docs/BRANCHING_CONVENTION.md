# Branch Naming Convention

Adopted: 2026-06-13  
Version: 1.0  
Enforcement: `scripts/pre_implementation_check.py` — `check_release_state()`

---

## 1. Rule

**Release branches MUST use the actual semver version from `VERSION` file, NOT `v0.0.0-test`.**

The `VERSION` file is the single source of truth. When creating a release branch, the branch name must match the version in `VERSION`.

---

## 2. Branch Naming Patterns

| Branch Type | Pattern | Example |
|-------------|---------|---------|
| **Release** | `release/v<MAJOR>.<MINOR>.<PATCH>` | `release/v2.53.0` |
| **Feature** | `feature/<YYYY-MM-DD>-<short-description>` | `feature/2026-06-13-brokerport-unification` |
| **Bugfix** | `fix/<short-description>` | `fix/order-modification-timeout` |
| **Main** | `main` | `main` |

---

## 3. Why This Matters

- **Traceability**: Release branches with proper versioning allow git tag matching (`v2.53.0` ↔ `release/v2.53.0`)
- **CI/CD**: Pipelines that filter on semver patterns require consistent naming
- **Audit**: Institutional audit reports reference version numbers — branch names must align
- **Rollback**: Clear version branches enable surgical hotfixes on older releases

---

## 4. Creating a Release Branch

```bash
# Verify VERSION file
cat VERSION                     # Should read "2.53.0"

# Create branch from main
git checkout main
git pull origin main
git checkout -b release/v2.53.0

# Tag the release
git tag v2.53.0
git push origin release/v2.53.0 --tags
```

---

## 5. Migration from Legacy Pattern

Old branches (`release/v0.0.0-test_*`) should be:
1. Left in place for history (don't delete)
2. Future releases MUST use semver-based naming as defined above

**Legacy → Correct mapping:**

| Legacy (don't use) | Correct |
|--------------------|---------|
| `release/v0.0.0-test_2026-06-13` | `release/v2.53.0` |
| `release/v0.0.0-test_2026-06-12` | `release/v2.53.0` |

---

## 6. Pre-commit Hook Enforcement

The pre-implementation compliance check (`scripts/pre_implementation_check.py`) checks branch naming as part of `check_release_state()`. If a release branch does not match the VERSION, a warning is emitted.

```bash
python scripts/pre_implementation_check.py --ci
# Checks: Branch name matches VERSION
```
