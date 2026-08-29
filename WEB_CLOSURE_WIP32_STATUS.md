# OPB WEB CLOSURE WIP32 — Runtime URL Boundary Triage

## Result
WIP31 identified 50 runtime candidates.

This pass classified them conservatively:
- High-confidence runtime URL construction: 48
- Lower-confidence references needing contextual review: 2

No uncertain URL was mass-rewritten.

## New regression boundary
Runtime Python under `core`, `index_app`, and `infrastructure` must not directly embed the production hostname. The canonical resolver remains the sole runtime source for the configured public origin.

## Two-layer URL configuration remains
- Deployment URL: environment/infrastructure, read-only in Setup UI.
- Admin URL Override: application-level, privileged `modify_config`.
- Effective URL: central runtime result.

## Deployment
NOT deployed to AWS.
NOT production-certified.

Next: repair confirmed runtime bypasses individually, then execute focused Web/RBAC/URL regression suites.
