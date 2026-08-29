# OPB Phase-13 Security Hardening — Configuration Secret Cleanup

Date: 2026-08-25

## Finding
A real Telegram bot token was present in the supplied production package in `json/config.json`, `.env`, and historical `json/config.json.backup.*` files.

## Remediation
- Removed the token from `json/config.json` by setting `BOT_TOKEN` to an empty value.
- Removed `.env` from the distribution package.
- Removed historical `json/config.json.backup.*` files containing the credential.
- Kept `json/config.template.json` and `json/index_config.defaults.json` placeholder values intact.
- Verified the targeted configuration/security tests pass.
- Re-ran Docker security hardening: 16/16 checks passed.
- Re-ran configuration drift detector: no critical/high findings; existing low/info findings remain unchanged.

## Required operational action
Because the credential was exposed in a package, the corresponding Telegram bot token must be revoked/rotated at the provider before production use. The replacement value should be supplied through the configured environment/secret mechanism, not committed to source or distribution archives.

## Validation
- Targeted config/security tests: 132 passed
- Docker security hardening: 16/16 passed
- Production-candidate token-shaped literal scan: no remaining copies of the exposed token after cleanup
