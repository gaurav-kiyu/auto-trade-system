# OPB WEB CLOSURE WIP96 — Targeted URL Closure

WIP96 resolves the WIP94 false-positive test and verifies the canonical SSO
URL boundary without importing the full application dependency graph.

A prose statement such as "localhost/127.0.0.1 is blocked in production" is
not itself a hard-coded localhost URL. The targeted scan therefore rejects
actual `http(s)://localhost[:port]` literals only.

Targeted pytest exit code: 2

NOT deployed to AWS.
NOT production-certified.
