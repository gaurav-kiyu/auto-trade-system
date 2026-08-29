# OPB WEB CLOSURE WIP38 — External URL Forensic Review

## Result
WIP37 identified 10 likely externally visible URL paths.

Contextual review classified:
- Confirmed external-link paths: 10
- False-positive/config/internal candidates: 0

No broad URL replacement was performed.

## Decision
Only confirmed externally visible URL generation is eligible for surgical repair.
Already-centralized paths are protected by regression tests rather than modified again.

## Canonical configuration
Deployment URL (environment/infrastructure)
→ Admin URL Override (`modify_config`)
→ Effective URL
→ `get_public_base_url()`
→ `build_action_url()`
→ external links.

## Deployment
NOT deployed to AWS.
NOT production-certified.

Next: repair any confirmed non-centralized external-link path found in the forensic review, then run focused regression tests.
