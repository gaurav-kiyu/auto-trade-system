# OPB WEB CLOSURE WIP97 — Targeted URL Closure

WIP97 fixes the test-collection syntax error introduced while correcting the
localhost false-positive rule.

The targeted checks now:
- parse the SSO module structurally,
- verify canonical URL helper names and configuration sources,
- reject actual hard-coded `http(s)://localhost[:port]` URL literals,
- allow legitimate documentation that mentions localhost as a blocked value.

Targeted pytest exit code: 1.

NOT deployed to AWS.
NOT production-certified.
