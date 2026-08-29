# OPB WEB CLOSURE WIP30 — Public URL Single-Source-of-Truth Sweep

## Objective
Continue the Web closure after WIP29 and identify remaining places that could bypass the canonical Public URL resolver.

## Result
A repository-wide inventory was performed for:
- localhost / loopback URLs
- the current production hostname
- `request.base_url`
- explicit external-origin construction

**Matches found: 133**

This pass deliberately classifies references before modifying them. Test fixtures, documentation, local development configuration, and infrastructure-specific references must not be blindly replaced because doing so can damage local testing or deployment behavior.

## WIP29 URL model retained
1. Deployment URL — environment/infrastructure, read-only in application UI.
2. Admin URL Override — application-level, editable through privileged Setup Configuration with `modify_config`.
3. Effective URL — runtime value used by generated external links.

## Next closure action
Classify each remaining reference into:
- canonical runtime URL construction (must use resolver),
- intentional local/test fixture,
- infrastructure-only configuration,
- documentation/example.

Only runtime bypasses should be repaired.

## Deployment
NOT deployed to AWS.
NOT production-certified.
