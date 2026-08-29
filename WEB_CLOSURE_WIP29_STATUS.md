# OPB WEB CLOSURE WIP29 — Two-Layer Public URL Setup

## Decision
Confirmed and implemented:

### 1. Deployment URL — environment/infrastructure configuration
- Visible in Admin Configuration for privileged users.
- Read-only in the application UI.
- Represents the deployment/infrastructure public origin.
- Changed through environment/deployment configuration, not through application settings.
- This avoids pretending that an application-level config edit can safely mutate process environment/reverse-proxy configuration.

### 2. Admin URL Override — application-level configuration
- Visible in the same privileged Setup Configuration UI.
- Editable only through the existing `modify_config` permission boundary.
- Uses the existing Preview → Validate → Apply workflow.
- Existing configuration backup and audit logging apply.
- Cache invalidation causes the new value to propagate centrally.

### 3. Effective URL
- Displayed read-only.
- Shows the URL currently used by the application for externally visible generated links.
- This makes it immediately clear whether the deployment URL or Admin override is active.

## Propagation
Central URL resolution is used for notification links, action links, email/Telegram links and SSO callback URLs.

## Validation
Added focused regression contracts for:
- deployment URL vs Admin override separation
- setup UI visibility
- read-only deployment URL
- application-level Admin override
- config API metadata

WIP29 is NOT deployed to AWS and is NOT production-certified.
