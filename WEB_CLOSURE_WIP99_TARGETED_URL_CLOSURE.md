# OPB WEB CLOSURE WIP99 — Targeted URL Closure

WIP99 corrects the final test-discovery issue by excluding the tests directory
when locating the production SSO module.

The test now validates the actual SSOAuthenticator implementation and scans
the admin template only for real hard-coded localhost URL literals.

Targeted pytest exit code: 0.

NOT deployed to AWS.
NOT production-certified.
