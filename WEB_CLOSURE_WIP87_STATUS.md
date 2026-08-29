# OPB WEB CLOSURE WIP87 — Critical Downstream Trace

WIP87 resolves the concrete downstream function candidates used by the 20
critical mutation handlers.

This pass does not assume that the controller must contain the audit call.
The persistence/service boundary is the correct place to verify centralized
auditing and avoid duplicate events.

No broad source mutation was made.

Final closure requires every critical durable mutation to have a proven
server-side audit path.

NOT deployed to AWS.
NOT production-certified.
