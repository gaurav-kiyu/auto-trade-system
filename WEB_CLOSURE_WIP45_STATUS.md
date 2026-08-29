# OPB WEB CLOSURE WIP45 — SSO Semantic Repair

## Result
Seven WIP44 SSO candidates were evaluated against their exact source expressions.

- Safely repaired: 0
- Manual/unchanged: 7

Only direct application-owned callback/redirect construction from `request.base_url` was eligible for automatic repair.

Identity-provider URLs, arbitrary request-origin derivation, and already-centralized paths were not changed.

## Regression protection
Added:
- canonical public URL resolver check
- SSO callback builder check
- direct application callback/base URL concatenation guard.

## Deployment
NOT deployed to AWS.
NOT production-certified.

Next: run the focused SSO/authentication/RBAC regression suite and inspect any manually retained targets.
