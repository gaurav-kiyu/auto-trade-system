# OPB WEB CLOSURE WIP61 — Admin Users Handler/API Trace

## Result

The Admin Users unit was traced one level deeper from UI surface to concrete
event/handler and API references.

No broad source mutation was made.

The goal is to identify the exact implementation path for:
- column filtering,
- Actions,
- eye/details,
- role/privilege changes,
- persistence.

## Next repair rule

Only handlers whose source path and API contract are proven will be changed.
This avoids a cosmetic UI fix that leaves the underlying action broken.

After Admin Users closure, proceed to registration/email and then signals.

NOT deployed to AWS.
NOT production-certified.
