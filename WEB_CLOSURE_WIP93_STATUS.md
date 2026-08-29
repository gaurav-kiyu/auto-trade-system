# OPB WEB CLOSURE WIP93 — Canonical URL Closure

WIP93 fixes the two concrete failures identified by WIP92:
1. SSO now exposes a canonical public/base URL boundary.
2. The enterprise admin configuration template no longer contains a
hard-coded localhost URL.

The canonical URL helpers resolve public_base_url, base_url, then
deployment_url, allowing environment-specific configuration without
hard-coded deployment hosts.

Focused WIP tests were rerun after the changes.

NOT deployed to AWS.
NOT production-certified.
