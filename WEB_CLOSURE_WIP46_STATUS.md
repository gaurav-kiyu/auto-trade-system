# OPB WEB CLOSURE WIP46 — SSO Call-Site Analysis

## Result
All seven WIP45-retained SSO candidates were traced to their enclosing functions and URL consumers.

Targets traced: 7

No source mutation was made.

## Why this is the correct next stage
The remaining candidates are in authentication code. Their correctness depends on whether a URL is:
- an application callback/redirect,
- an identity-provider endpoint,
- a request-origin value,
- or a configuration value.

The WIP46 dossier records resolver usage, request-origin references, and URL-like literals for each target.

## Canonical application URL
Deployment URL → Admin URL Override → Effective URL → canonical resolver/builder.

Identity-provider URLs and protocol-specific OAuth parameters must not be rewritten into the application URL.

## Deployment
NOT deployed to AWS.
NOT production-certified.

Next: use the call-site dossier to repair only application-owned URL consumers and leave IdP/protocol URLs unchanged.
