# OPB WEB CLOSURE WIP44 — SSO URL Flow Analysis

## Result

The seven remaining URL candidates were traced specifically through the SSO/authentication module.

WIP44 makes **no source mutation**.

The objective is to determine, for each candidate, whether it is:
1. a browser redirect URL,
2. an OAuth/SSO callback URL,
3. an identity-provider URL that must remain external,
4. an application public URL that must use the canonical resolver, or
5. a request-origin value that must not be replaced.

## Safety

SSO/OAuth URL handling is security-sensitive. A generic string replacement could break:
- redirect URI registration,
- state/nonce handling,
- callback routing,
- IdP URLs,
- authentication flow.

Therefore each target must be repaired according to its semantic role.

## Configuration model

Deployment URL → Admin URL Override → Effective URL → canonical public URL resolver → application-generated external URLs.

## Deployment

NOT deployed to AWS.
NOT production-certified.

Next: use the WIP44 flow map to make only the semantically correct SSO changes, then run focused authentication/RBAC/URL regression tests.
