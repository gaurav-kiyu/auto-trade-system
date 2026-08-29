# OPB WEB CLOSURE WIP39 — External URL Remediation Matrix

## Result
The 10 confirmed external-link paths from WIP38 were inspected against their actual source context.

- Already centralized: 3
- Non-centralized candidates requiring surgical repair: 7

No blind global replacement was performed.

## Principle
A path is repaired only if the actual source line constructs an externally visible URL outside:
`build_action_url()` / `get_public_base_url()`.

If it is already centralized, it is not modified again.

## Configuration model
Deployment URL (environment/infrastructure)
→ Admin URL Override (`modify_config`)
→ Effective URL
→ canonical resolver
→ external links.

## Deployment
NOT deployed to AWS.
NOT production-certified.

Next: surgically repair only the non-centralized candidates in the matrix and then run targeted regression tests.
