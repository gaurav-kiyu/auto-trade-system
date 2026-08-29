# OPB WEB CLOSURE WIP34 — Confirmed Runtime URL Bypass

## Candidate
`core/auth/routes.py:1089`

## Objective
Isolate the single confirmed runtime URL-construction bypass from WIP33.

## Safety
This pass does not perform a blind global replacement. The exact source context is recorded in `WEB_CLOSURE_WIP34_CONFIRMED_RUNTIME_BYPASS.md`.

The required repair is limited to the external URL construction at that location and must use the canonical `get_public_base_url()` resolver.

## Required verification
- Admin URL Override changes generated external URL.
- Deployment URL remains the infrastructure baseline.
- Effective URL is reflected centrally.
- No production localhost/loopback URL is emitted.
- Existing auth/RBAC/CSRF behavior remains unchanged.

## Deployment
NOT deployed to AWS.
NOT production-certified.

Next: apply the surgical change to the identified runtime construction and run the targeted URL + Web/RBAC regression suites.
