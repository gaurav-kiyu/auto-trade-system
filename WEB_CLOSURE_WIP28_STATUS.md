# OPB WEB CLOSURE WIP28 — Canonical Base URL Propagation

## Scope
Web-only functional closure. No trading strategy, broker execution, risk-engine, or database-schema changes.

## Defect found
SSO callback URLs were still derived from `request.base_url`, bypassing the configurable canonical public URL. Behind a reverse proxy this can produce an internal/localhost callback even when notification links use the configured public origin.

## Repair
`core/auth/routes.py` now resolves `/api/auth/sso/callback` through the central public URL resolver.

The same canonical URL is therefore used for:
- email action links
- Telegram/action links
- cockpit notification links
- SSO callback URLs
- other externally visible generated cockpit URLs

## Configuration
`PUBLIC_BASE_URL_ADMIN_OVERRIDE` remains the application-level override controlled through Admin Configuration by users with `modify_config`.

Resolution:
1. Admin/Super Admin override
2. deployment environment URL
3. persisted legacy URL
4. environment fallback

Production loopback/localhost URLs remain rejected.

## Validation
Selected URL, notification, registration-security, Admin-auth, and CSRF suites: PASS.
Python compilation: PASS.

## Deployment
NOT deployed to AWS.
NOT production-certified.

Next: authenticated Super Admin runtime browser closure and end-to-end verification of SSO/notification/action links.
