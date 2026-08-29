# OPB Phase-13 Release Candidate v8

## Production deployment safety pass

- Removed remaining `__pycache__` / `.pyc` artifacts from the release package.
- Updated Kustomize application version to `2.59.0`.
- Excluded canary deployment and HPA from the default production Kustomize set because the trading worker must remain single-active until distributed execution locking/idempotency is proven.
- Corrected Kubernetes Secret key names so explicit `secretKeyRef` mappings match the Secret template.
- Added explicit Angel broker and admin secret mappings.
- Synchronized canary manifest metadata to `2.59.0-canary` for controlled, manual use.
- Added an Azure Linux VM production runbook using the existing Docker Compose architecture.
- Added an Azure deployment gate checklist.

## Release status

Frozen release candidate: `v2.59.0`.
Full local pytest completed at 100% with warnings only.
