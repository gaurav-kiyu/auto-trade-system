# OPB WEB CLOSURE WIP35 — SSO URL Candidate Reconciliation

## Finding
The apparent WIP33/WIP34 SSO candidate at `core/auth/routes.py:1089` was **already repaired in the supplied WIP34 source**.

The source currently constructs the callback through:

`build_action_url("/api/auth/sso/callback", cfg=app_config)`

It does **not** contain the previously suspected direct `request.base_url + callback` construction.

Therefore **no source mutation was made in WIP35**. This is intentional: applying another edit would be a false-positive repair.

## Verified boundary
- SSO route uses `build_action_url`: True
- URL resolver contains `build_action_url` and canonical resolution: True
- `PUBLIC_BASE_URL_ADMIN_OVERRIDE` is present in resolver: True

## Regression guard
Added `tests/test_sso_public_url_boundary_contract.py` to ensure SSO remains connected to the centralized action URL builder and canonical public URL resolver.

## Deployment
NOT deployed to AWS.
NOT production-certified.

## Next
Continue classification of remaining URL candidates and then move to authenticated browser/runtime closure rather than repeatedly modifying already-correct source.
