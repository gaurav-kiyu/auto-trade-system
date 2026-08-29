# OPB WEB CLOSURE WIP47 — SSO URL Semantic Evidence

## Result

The concrete implementations of:
- `get_authorization_url()`
- `handle_callback()`
- `sso_login()`
- `get_public_base_url()`

were inspected directly.

No source mutation was performed.

## Decision boundary

An IdP authorization/token endpoint is not the same thing as the OPB application's public origin.

Only application-owned redirect/callback URLs should inherit:
Deployment URL → Admin Override → Effective URL.

The identity provider's own endpoint must remain provider configuration.

## Next

The next repair should target only application-owned SSO callback/redirect construction if the concrete implementation proves it bypasses the canonical resolver. Provider endpoint configuration must remain unchanged.
