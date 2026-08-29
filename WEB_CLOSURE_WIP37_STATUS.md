# OPB WEB CLOSURE WIP37 — Runtime URL Classification

## Result
WIP36 found 48 unique runtime URL-related lines across 706 runtime Python files.

Conservative classification:
- Likely externally visible URL paths: 10
- Configuration/internal/ambiguous references: 38

No broad replacement was performed.

## Architecture retained
Deployment URL (environment)
→ Admin URL Override (privileged `modify_config`)
→ Effective URL
→ `get_public_base_url()`
→ `build_action_url()`
→ externally visible links.

## Regression protection
Added WIP37 contracts for:
- canonical resolver
- Admin override
- SSO centralization
- three-layer Setup UI.

## Deployment
NOT deployed to AWS.
NOT production-certified.

Next: inspect the likely external paths individually and repair only confirmed bypasses, then execute targeted regression tests.
