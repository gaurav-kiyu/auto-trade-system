# OPB WEB CLOSURE WIP40 — Surgical URL Repair Worksheet

## Current state
WIP39 isolated **7** genuine non-centralized external URL candidates.

WIP40 records their exact source context before mutation.

## Safety rule
No broad replacement is permitted.

Each target must be repaired only at its actual externally-visible URL construction point, preserving:
- route/query parameters,
- authentication and RBAC,
- CSRF behavior,
- response schema,
- notification semantics,
- existing deployment configuration.

## Canonical destination
`build_action_url()` / `get_public_base_url()`.

## Configuration model
Deployment URL = infrastructure/environment, read-only in Setup UI.
Admin URL Override = application-level, `modify_config`.
Effective URL = runtime canonical result.

## Deployment
NOT deployed to AWS.
NOT production-certified.

Next: apply the seven surgical changes from this worksheet, then run targeted regression tests.
