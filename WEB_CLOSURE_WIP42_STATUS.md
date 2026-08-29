# OPB WEB CLOSURE WIP42 — Surgical URL Repair

## Result
Attempted the seven WIP41 mutation-ready targets using strict exact-pattern matching.

- Targets received: 7
- Safely changed: 0
- Refused/unsafe: 7

Only direct `request.base_url.rstrip('/') + <path>` constructions were eligible for automatic mutation. Anything else was refused rather than guessed.

## Regression protection
Added:
- canonical resolver/builder check
- SSO centralization check
- runtime direct `request.base_url` concatenation guard
- three-layer Setup UI check

## Deployment
NOT deployed to AWS.
NOT production-certified.

Next: inspect the change manifest and run the focused regression suite. If any target was refused, it must be repaired from its exact source context rather than by approximation.
