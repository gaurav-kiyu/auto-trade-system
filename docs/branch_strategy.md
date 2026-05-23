# Branch Strategy

## Overview
AD-KIYU uses **GitHub Flow** (trunk-based development) with **semantic versioning**.
All branches originate from and merge into `master`.

## Branch Naming

| Prefix | Purpose | Example |
|--------|---------|---------|
| `feature/` | New functionality or enhancement | `feature/iron-condor-strategy` |
| `fix/` | Bug fix on existing code | `fix/broker-timeout-handling` |
| `hotfix/` | Urgent production fix (bypasses normal pipeline) | `hotfix/config-corruption` |
| `chore/` | Non-functional changes (CI, docs, deps) | `chore/update-dependencies` |
| `refactor/` | Code restructuring without behavior change | `refactor/risk-engine-api` |

## Workflow

### Feature / Fix Branches
```
master → feature/xxx → PR → CI passes → merge to master → tag release
```

1. Branch from `master`
2. Make changes
3. Open PR with `PULL_REQUEST_TEMPLATE.md`
4. CI must pass (all stages: lint → test → chaos → build)
5. At least one approving review from module owner (see `docs/ownership_matrix.md`)
6. Merge to `master` (squash merge preferred)

### Hotfix Branches
```
master → hotfix/xxx → PR → CI (expedited) → merge to master → tag patch release
```
Hotfixes bypass normal review but still require CI. Create a post-hotfix PR to add
proper tests and update the tech debt register (`docs/technical_debt.md`).

## Release Process
Releases are tagged from `master` using semantic versioning:
- **Patch** (1.2.3 → 1.2.4): Bug fixes, documentation, non-functional changes
- **Minor** (1.2.3 → 1.3.0): New features, non-breaking enhancements
- **Major** (1.2.3 → 2.0.0): Breaking changes, architecture changes

### Release Steps
1. Update `VERSION` file
2. Commit: `git commit -m "Release vX.Y.Z"`
3. Tag: `git tag vX.Y.Z`
4. Push: `git push origin master --tags`
5. CI builds immutable release (`make dist checksum`)

## Required CI Stages
1. **Lint** — ruff, mypy (fast)
2. **Test** — `make test` (unit + integration)
3. **Slow Test** — concurrency stress, replay regression
4. **Chaos** — chaos certification suite
5. **Exactly-Once** — execution certification suite
6. **Build** — `make dist` + `make checksum`
7. **Release** — manual trigger via Bitbucket UI

## Protected Branches
- `master` is protected: requires CI pass, review approval, no direct pushes
- Release tags are protected: once pushed, tags cannot be deleted or overwritten
