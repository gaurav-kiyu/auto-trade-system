# OPB WEB CLOSURE WIP36 — Fresh Runtime URL Rescan

## Scope
Continue Web closure from WIP35 without repeating already-resolved SSO work.

## Scan
Runtime Python under:
- `core`
- `index_app`
- `infrastructure`

was rescanned for:
- `request.base_url`
- localhost/loopback origins
- production hostname literals
- callback/redirect/external/public/base URL construction patterns.

**Runtime files scanned:** 706
**Unique flagged runtime lines:** 48

## Important
This is a forensic discovery pass. No blanket URL mutation was performed.

The previously confirmed SSO route remains connected to the central `build_action_url()` → `get_public_base_url()` chain.

## Configuration model retained
- Deployment URL: environment/infrastructure, read-only in application Setup UI.
- Admin URL Override: application-level, privileged `modify_config`.
- Effective URL: runtime value.

## Deployment
NOT deployed to AWS.
NOT production-certified.

## Next
Classify the fresh runtime findings and repair only genuine external URL bypasses. Then execute the relevant regression tests.
