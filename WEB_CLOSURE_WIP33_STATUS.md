# OPB WEB CLOSURE WIP33 — Runtime URL Construction Boundary

## Result
WIP32 contained 48 high-confidence runtime candidates.

This pass classified them into:
- Clear URL-construction sites: 1
- Input/config/reference sites: 47

No blanket replacement was performed.

## Rule enforced
Only actual runtime URL construction should call the canonical public URL resolver.

Environment variables, Admin configuration values, user-supplied URLs, tests, fixtures and deployment configuration remain inputs and are not replaced.

A regression guard now detects direct runtime concatenation of `request.base_url`, `base_url`, or `public_url`.

## Public URL model
Deployment URL (environment)
→ Admin URL Override (privileged `modify_config`)
→ Effective URL
→ Central resolver
→ external links.

## Deployment
NOT deployed to AWS.
NOT production-certified.

Next: repair only the clear runtime-construction sites, then run the focused URL/RBAC/Web regression suite.
