# Branch Strategy and Release Flow

**Status:** Active
**Effective version:** 2.61.0

## Branches

| Branch | Purpose | Merge policy | Release state |
|---|---|---|---|
| `main` | Production-ready source of truth | Protected; PR + CI required | Candidate / released |
| `develop` | Integration branch for completed work | PR + CI | Pre-release |
| `release/*` | Release hardening and stabilization | Bug fixes only; PR + CI | Release candidate |
| `feature/*` | Isolated implementation work | PR into `develop` | Development |
| `hotfix/*` | Production correction | PR into `main`, then back-merge to `develop` | Emergency |

## Required gates

1. Keep `main` green; do not commit directly except approved emergency recovery.
2. Every pull request must pass lint, targeted regression, configuration/schema validation, security checks, and architecture-boundary checks.
3. Release branches are frozen for features; only defect, security, documentation, or release-engineering changes are allowed.
4. A release may be tagged only after the paper/live-readiness gates explicitly report their current state.
5. Changes to risk, execution, broker adapters, configuration authority, or safety invariants require regression evidence and reviewer sign-off.
6. Hotfixes must be merged back into `develop` so the correction is not lost.

## Versioning

The canonical version is `VERSION`. Code and release tooling should read it rather than maintaining independent version constants. Historical release notes may retain prior versions.

## Repository synchronization

Before release completion:

```text
git fetch origin
git status
git diff origin/main...HEAD
git log -1 --oneline
```

The release bundle must contain only tracked source/documentation/assets plus explicitly required runtime data. Secrets, local configuration, databases, logs, caches, and generated temporary files remain ignored.
