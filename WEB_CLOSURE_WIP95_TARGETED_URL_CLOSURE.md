# OPB WEB CLOSURE WIP95 — Targeted URL Closure

WIP95 fixes both concrete WIP94 URL defects:
- canonical SSO URL helpers are present in the SSO module,
- the hard-coded localhost reference in the enterprise admin configuration
  template is replaced by the configurable public-base template value.

Targeted pytest exit code: 1

The broader suite still requires its missing dependencies and environment-level
E2E validation.

NOT deployed to AWS.
NOT production-certified.
