# OPB WEB CLOSURE WIP34 — Confirmed Runtime URL Bypass

Candidate: `core/auth/routes.py:1089`

Matched source line: `# this deployment. Do not derive it from request.base_url because that`

## Context

`1085:             app_config["sso_redirect_uri"] = sso_redirect_uri`
`1086:             sso = SSOAuthenticator.from_config(auth_handler, app_config)`
`1087: `
`1088:         # Keep the OAuth callback on the canonical public origin configured for`
`1089:         # this deployment. Do not derive it from request.base_url because that`
`1090:         # can be the internal reverse-proxy/upstream host (or localhost), which`
`1091:         # would make the provider redirect the user to an unusable URL.`
`1092:         app_config = getattr(request.app.state, "config", {}) or {}`
`1093:         sso._config.redirect_uri = build_action_url(`
`1094:             "/api/auth/sso/callback",`

## Repair rule
Replace only the actual externally generated URL construction with the central `get_public_base_url()` resolver. Do not change user input, deployment configuration, tests, or documentation.

## Verification requirement
The repaired path must be covered by a regression test proving that an Admin URL Override changes the generated external URL and that no localhost/loopback origin is emitted in production.
