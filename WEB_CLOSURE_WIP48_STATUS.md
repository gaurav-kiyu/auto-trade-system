# OPB WEB CLOSURE WIP48 — SSO Callback Closure

## Result

A final concrete scan of SSO/auth URL construction was performed.

The application-owned callback remains on the canonical action URL builder in `core/auth/routes.py`.

The remaining SSO URL material in `core/auth/sso.py` is provider-side configuration/authorization/token behavior and must not be blindly replaced by the OPB public URL.

## Decision

No source mutation was made.

The previous seven candidates are therefore not seven outstanding defects. They are a mixture of provider configuration and application callback semantics.

## Closure direction

The URL resolver work should now stop expanding this SSO candidate list.

Next focus should move to actual Web functional closure:
- side-menu links
- sub-menu navigation
- buttons/actions
- eye/details actions
- logout
- signal test controls
- RBAC/privilege visibility
- admin setup
- notification flows
- desktop browser execution
- then mobile.

## Deployment

NOT deployed to AWS.
NOT production-certified.
