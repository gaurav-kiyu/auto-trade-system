# OPB WEB CLOSURE WIP31 — URL Classification & Runtime Boundary

## Result

The WIP30 inventory contained 133 explicit public-origin/loopback/request-base references.

A conservative classification was performed:

- Runtime candidates: 50
- Test/documentation/local-fixture candidates: 83
- No blanket replacement was performed.

## Why

The goal is to eliminate genuine production URL bypasses without corrupting:
- test fixtures,
- local development,
- deployment configuration,
- documentation/examples.

The canonical runtime contract remains:

Deployment URL (environment)
→ Admin URL Override (privileged application config)
→ Effective URL
→ Central public URL resolver
→ externally generated links.

## Regression guards added

- canonical notification resolver exists;
- SSO uses canonical public URL resolution;
- Admin Setup exposes Deployment URL, Admin Override and Effective URL;
- loopback protection remains present.

## Deployment

NOT deployed to AWS.
NOT production-certified.

Next: inspect the runtime-candidate list and repair only confirmed runtime URL bypasses, followed by authenticated browser verification.
