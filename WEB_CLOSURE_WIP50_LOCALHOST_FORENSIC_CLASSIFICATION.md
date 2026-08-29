# OPB WEB CLOSURE WIP50 — UI Localhost/Origin Forensic Classification

UI/static localhost-origin hits reviewed: 1

## Classification
- **LIKELY_RUNTIME_ENDPOINT**: 1

## Explicit browser origins

## Likely runtime endpoints
- `templates/enterprise/admin_config.html:545` — `'PUBLIC_BASE_URL_ADMIN_OVERRIDE': 'Canonical public HTTPS origin controlled by Super Admin/Admin users with modify_config permission. This value overrides deployment fallback URLs and is reflected in notification links, email action buttons, Telegram links, SSO redirects, and other externally visible cockpit URLs. Every change is backed up and recorded in the configuration audit log. Use a public http(s) origin; localhost/127.0.0.1 is blocked in production.',`

## WebSocket origins

## Test/example references

## Ambiguous