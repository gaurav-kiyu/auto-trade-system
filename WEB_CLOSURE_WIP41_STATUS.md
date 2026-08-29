# OPB WEB CLOSURE WIP41 — Final URL Repair Matrix

## Current state
The seven WIP40 targets were re-inspected against the actual current source.

- Repair candidates: 7
- Already centralized: 0
- Ambiguous: 0

No source mutation was made unless the current source contained a recognizable, safe external URL construction pattern.

## Why
This prevents another false-positive repair cycle. The target source must actually show a direct/non-centralized external URL construction before it is changed.

## Canonical model
Deployment URL (environment)
→ Admin URL Override (`modify_config`)
→ Effective URL
→ `get_public_base_url()` / `build_action_url()`
→ external links.

## Deployment
NOT deployed to AWS.
NOT production-certified.

Next: repair only the mutation-ready candidates in this final matrix, then run focused URL/RBAC/notification/SSO regression tests.
