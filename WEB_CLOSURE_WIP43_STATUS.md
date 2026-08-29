# OPB WEB CLOSURE WIP43 — Seven Target Semantic Review

## Result
WIP42 refused seven automated replacements because the expressions did not match a safe direct-origin construction pattern.

WIP43 inspected the exact enclosing source context for all seven targets.

Targets reviewed: 7

No source mutation was made.

## Purpose
The seven targets are now semantically classified so the next repair can be made based on what each function actually does, not on a regex guess.

## Required next action
Repair each target according to its actual role:
- external navigation → canonical action URL
- notification/callback → canonical external URL boundary
- request-origin derivation → preserve request semantics unless it is used to construct an external user-facing URL
- other → do not mutate until proven externally visible.

## Deployment
NOT deployed to AWS.
NOT production-certified.
