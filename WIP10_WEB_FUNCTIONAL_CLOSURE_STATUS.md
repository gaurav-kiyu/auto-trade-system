# OPB WEB FUNCTIONAL CLOSURE — WIP10 STATUS

Baseline: `auto-trade-system_24AUG2026_WEB-CLOSURE-WIP9`

## Scope of this WIP

This package is a **Web-first functional closure build**. It is not deployed to AWS by this package generation.

### Completed in WIP10

- Granular RBAC gates for user management and permission management.
- Super Admin-only role/privilege assignment; legacy `admin` root account remains backward-compatible as the immutable root identity.
- Admin accounts can manage users only when `manage_users` is effective.
- Per-user permission records cannot elevate a user merely because their stored permission-record role is stale.
- User creation rejects unsupported roles and prevents non-root administrators from creating elevated-role accounts.
- Role changes synchronize the auth role and permission metadata and remain audit logged.
- Admin User Manager is protected by the effective `manage_permissions` permission.
- Removed duplicate standalone User Controls links from Admin Configuration, Signals and Portfolio screens; User Authorization & Controls remains in the Admin/Governance submenu.
- Admin User Manager now has per-column header filters, including user, role, signal status, conviction tier, category, quota and channel.
- Actions column is explicitly visible/sticky and the Eye action now has a visible `View` label.
- Stop-loss outcome filtering remains available in Admin Signals via the Outcome Status column (`SL_HIT`).
- Removed remaining CSP-sensitive inline HTML event attributes from Strategy Sandbox, mobile drawer search and Profile forms.
- Added CSP nonce to the mobile drawer search script.
- Added event-listener wiring for Strategy Sandbox sliders/search and Profile forms.
- Desktop dropdown hover bridge strengthened with a larger pointer-safe corridor and focus/tab support.

## Validation performed

- Python compilation: PASS
- Jinja templates: 42 / 42 parse successfully
- Extracted JavaScript blocks: 58 / 58 syntax-valid under Node.js
- Relevant auth/RBAC/admin/UI suites: PASS
- Full signal dispatch-order suite still contains 3 pre-existing signal-gating failures in WIP9; these are unrelated to the WIP10 UI/RBAC changes and were not modified.

## Deployment rule

**DO NOT DEPLOY WIP10 TO AWS until the remaining Web click-path audit is complete.**

Next closure pass: systematically exercise every Web route → control → JavaScript handler → API → response → DOM update, then run the full theme matrix. Mobile remains the next phase only after Web closure.
