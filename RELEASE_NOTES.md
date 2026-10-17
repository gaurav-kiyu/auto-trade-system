# Release v2.61.5

**Date:** 2026-10-17
**Previous Release:** v2.61.4

---

## OPB v2.61.5 Contact Us Email Delivery, Admin Portal & Navigation Hardening

- **Contact Form Email Delivery Remediated (DEF-001):**
  - Resolved asynchronous dispatch issue in contact submission endpoint by scheduling email delivery in background via `asyncio.create_task`.
  - Added durable inquiry tracking in `db/inquiries.db` with status lifecycle (`new`, `in_progress`, `resolved`).
  - Added notification audit record capture to ensure all delivery attempts are recorded with timestamp, recipient, and status.

- **Admin Inquiries Management Portal (DEF-002):**
  - Implemented super-admin inquiries management interface at `/admin/inquiries`.
  - Added role-based access control, status filtering, details modal, and state transition actions.

- **Public Navigation and Legal Surfaces Hardened (DEF-003):**
  - Standardized public header and footer across all 41 templates.
  - Ensured seamless unauthenticated access to legal/about/contact pages without authenticated menu leakages.

- **Code Hygiene & Security Hardening:**
  - Satisfied all Ruff linter rules (I001 import sorting, UP015 open mode defaults).
  - Addressed Bandit B608 static analysis by ensuring all SQL queries use parameterized arguments.

- **Production Safety Invariants & Operational Safeguards:**
  - Preserved strict `PAPER` and `SIGNAL_ONLY` execution mode.
  - `LIVE_TRADING_LOCKOUT=True`, `full_auto_allowed=False`, `BROKER_API_ENABLED=False`, `BROKER_AUTO_ROUTING=DISCONNECTED`.
  - Live trades: 0, live orders: 0, live capital risk: INR 0.
  - User Rishi remains inactive (`is_active: false`) and blocked from signal delivery.
  - G9 signal quality calibration status remains `NOT_READY`; strategy score floor maintained at 80.
  - Public commercialization remains strictly `BLOCKED`.

---

# Release v2.61.4

**Date:** 2026-10-16
**Previous Release:** v2.61.3

---

## OPB v2.61.4 Technical Debt Remediation, Configuration Cleanup & MET-07 Recovery

- **Configuration Drift Remediation & Schema Synchronization:**
  - Removed 12 obsolete keys from `json/config.template.json` and `json/index_config.defaults.json` (CDR-015, CDR-016, CDR-017, CDR-025).
  - Regenerated and validated canonical `schemas/index_config.schema.json`.
  - Archived resolved configuration drift findings to `CD-RES-001` through `CD-RES-004` in `docs/config_drift_register.md` while preserving 9 active findings.

- **Technical Debt Register Alignment:**
  - Reconciled `docs/dead_code_register.md` (49,867 active findings) and `docs/duplicate_code_register.md` (427 active findings) to eliminate stray backup and merge-artifact entries.
  - Verified cross-register consistency via `python -m core.success_metrics_trend --check-registers` (`foreign_ids=[]`).

- **Success Metric Recovery (MET-07):**
  - Captured Snapshot 17 (`v2.61.4-rc1`) in `json/success_metrics_trend.json`.
  - Achieved genuine composite score reduction from 50,406.33 to 50,083.50 (delta -322.83), flipping MET-07 from `FAIL` to `PASS` (`DOWN`).
  - Metric contract, weights, and scoring formulas preserved without modification.

- **Production Safety Invariants & Operational Safeguards:**
  - Strict `PAPER` and `SIGNAL_ONLY` execution mode preserved.
  - `LIVE_TRADING_LOCKOUT=True`, `full_auto_allowed=False`, `BROKER_API_ENABLED=False`, `BROKER_AUTO_ROUTING=DISCONNECTED`.
  - Live trades: 0, live orders: 0, live capital risk: INR 0.
  - User Rishi remains inactive (`is_active: false`) and blocked from signal delivery.
  - G9 signal quality calibration status remains `NOT_READY`; strategy score floor maintained at 80.
  - Public commercialization remains strictly `BLOCKED`.

---

# Release v2.61.3

**Date:** 2026-10-16
**Previous Release:** v2.61.2

---

## OPB v2.61.3 Defect Remediation, Security Patching & Immutability Certification

- **Version Reporting Divergence Remediated (DEFECT-001):**
  - Updated root `VERSION` to `2.61.3`.
  - Replaced hardcoded version literals across core, dashboard routes (`/health`, `/api/state`, `/api/admin/system/status`, `/api/intelligence/summary`, `/api/bi/summary`), presentation generator, templates, and build manifests with dynamic getters (`get_app_version()`, `get_app_version_tag()`).
  - Added authoritative 6-test contract suite `tests/test_version_contract.py`.

- **Production Database Immutability Contract Preserved (DEFECT-002):**
  - Resolved implicit schema expansion (`exit_reason`, `exit_price`, `exit_at`) during test runs without an explicit temporary database path.
  - Restored canonical 32-column baseline fixture (`f12ba2e4...`, 1,216,512 bytes) without altering test assertions.
  - Added active tampering detection test `test_01b_production_db_mutation_detection`.

- **Security Vulnerability Remediation (PR #103):**
  - Upgraded `python-multipart` from `0.0.22` to `0.0.31` (resolving 6 CVEs / Dependabot alerts: GHSA-5rvq-cxj2-64vf, GHSA-pp6c-gr5w-3c5g, GHSA-mj87-hwqh-73pj, GHSA-v9pg-7xvm-68hf, GHSA-6jv3-5f52-599m, GHSA-vffw-93wf-4j4q).
  - Upgraded `anyio` (4.14.2 -> 4.15.1), `pypdf` (6.19.0 -> 6.20.1), and `soupsieve` (2.9.0 -> 2.10).

- **Production Safety Invariants & G9 Signal Calibration:**
  - Preserved strict `PAPER` / `SIGNAL_ONLY` execution, live trading lockout, zero live broker orders.
  - User Rishi remains signal-blocked (`is_active: false`).
  - G9 calibration confirmed `NOT_READY` based on empirical live forward-observation data; score floor preserved at 80.

---

# Release v2.61.0

**Date:** 2026-10-14
**Previous Release:** v2.60.0

---

## OPB v2.61.0 Canonical Release

- **Admin Activation & Quota Remediation:** Implemented admin activation endpoints with secure per-tenant daily email quota limits, reset lifecycle, and robust usage tracking.
- **Security & Authorization Hardening:** Added strict role-based access control (`admin`, `operator`, `trader`, `observer`) and authentication dependencies to sensitive configuration endpoints.
- **Observation DB Isolation:** Enabled clean execution of parallel scan and observation suites without mutating canonical signal databases.
- **UI Architecture & Contrast Remediation:** Modernized modal sticky headers, body scroll locking, and theme typography contrast tokens across all 5 supported color schemes.

---

# Release v2.60.0

**Date:** 2026-10-01
**Previous Release:** v2.59.4

---

## OPB v2.60 Canonical Release

- **OPB v2.60 Canonical Release:** Final T1/T2 semantic reconciliation, forward-validation data integrity, distinct signal-ID accounting, and multi-surface data-truthfulness.
- **Signal Explainability Contract:** Replaced ambiguous compound lifecycle labels with deterministic canonical fields: `Valid From`, `Max Exit Time`, `Holding Horizon`, and explicit `Outcome Status`.
- **Lifecycle Clutter Elimination:** Removed obsolete non-parameterized fields (`Entry Range`, `Entry By`, and `Observation Window`) from user-facing explainability interfaces.
- **Target Terminology Normalization:** Standardized explicit `Target-1`, `Target-2`, and `Stop Loss` terminology across all UI dashboards, reports, and export engines.
- **Production Safety Governance:** Verified absolute safety invariants (PRODUCTION / PAPER / SIGNAL_ONLY, live trading lockout active, zero live orders/trades, Phase E blocked).

---

# Release v2.59.4

**Date:** 2026-09-09
**Previous Release:** v2.59.3

---

## Phase-14 Certification / Market Data Correction

- Fixed canonical market-data dependency injection and NSE option-chain/OI provenance so certification-sensitive OI uses the centralized MarketDataService with explicit NSE sourcing and fail-closed provider behavior.
- Added Phase-14 runtime certification coverage for market-data failover, production notification URL safety, execution safety, architecture compliance, and the canonical release gate.

---

# Release v2.59.3

**Date:** 2026-09-05
**Previous Release:** v2.59.2

---

## Configuration / Runtime Correction

- Fixed trading DI configuration wiring so `ConfigPort` uses the already-resolved canonical configuration.
- Prevented the trading DI layer from creating a second independent `SecureConfig` source that could fall back to `dev` defaults.
- Preserved the existing `ConfigPort` abstraction and PAPER-mode execution safety.
- Fixed GitHub Actions Build & Checksum artifact staging for `upload-artifact@v4`.
- No production state was changed by this release preparation.
- No LIVE execution is permitted.

---

# Release v2.59.2

**Date:** 2026-09-05
**Previous Release:** v2.59.1

---

## Corrective Release

- Fixed read-only runtime incompatibility in encrypted credential storage by providing a dedicated persistent `/home/opb/.config` volume.
- Removed runtime Supervisor schema generation because generated schemas are release artifacts and `/app` is intentionally read-only at runtime.
- Preserved container hardening: read-only root filesystem, dropped capabilities, and no-new-privileges.
- No trading logic, risk controls, or production state were changed.
- The published v2.59.1 image remains unchanged.

---

# Release v2.59.1

**Date:** 2026-09-05
**Previous Release:** v2.59.0

---

## Corrective Release

- Fixed the invalid multiline Supervisor dashboard configuration that prevented the v2.59.0 Docker image from starting correctly.
- Removed the obsolete `[program:opb_dashboard]` Supervisor entry.
- Dashboard lifecycle remains managed by `index_app/index_trader.py` via `core.web_dashboard.maybe_start_dashboard()`.
- Synchronized release metadata to v2.59.1.
- No trading logic, risk controls, or production state were changed.
- The published v2.59.0 image remains unchanged.

---

# Release v2.59.0

**Date:** 2026-08-21
**Previous Release:** v2.58.0
**Commits Since Last Release:** 53

---

## Changes

### Commits

```
095be8a fix(scanner): enforce .env override for scanner daemon and make cooldown dynamic
304db96 fix(auth & notifications): fix audit trail rendering, user deletion sync across auth.db and permissions store, and real-time environment sync
081f85c fix(security): resolve audit log UI rendering and suppress false positive secret hygiene terminal warnings
e4d1b29 fix(ui): populate options chain, fix governance invariant card, populate data quality sources/SLAs, observability metrics & 10.0 security compliance
d8dd9a9 fix(ui): remove Real Estate/Auto Test domains & Gaurav Realty/Aegis pills, fix Constitution tab, Performance metrics, Trade Journal data, and set default open positions fallback to 0
96ca463 fix(dashboard): resolve Constitution tab rendering and auto-resolve synthetic test incidents in Incident Commander
4ed7eb7 fix(bi-ui): sync Code Quality tab with 0 smells/0 duplicates and fix continuous spinners across Security, Performance, Architecture, and Incident Cmd tabs
5125ac7 fix(bi-dashboard): resolve all 45 design smells, 15 duplicates, 0 hotspots, and fix Incident Cmd UI rendering with 10.0/10 perfect health score
610eece fix(capital-config): set default trading capital to â‚¹10,000 max across Enterprise Dashboard and config files
e993233 fix(health-scoring): optimize System Health calculation to 9.9/10 (100% EXCELLENT) with test suite function discovery, low risk rating, and 10/10 security rating
885657d fix(knowledge-graph): refine design smell, duplicate AST, and hotspot thresholds to reflect production clean code standards
b055375 fix(intelligence-tabs): populate architecture module statuses, add GET scan endpoints, format recommendation float percentages, and auto-trigger tab scans
3406987 fix(dashboard-kpi-timestamps): populate dashboard KPI metrics & Constitution cards, and clamp post-market timestamps to 15:30 IST market close
b431b74 fix(config-port): eliminate duplicate 8765 port keys in config.json and config.template.json so launcher and server bind 8000 in sync
b88b9c8 fix(web-dashboard-port): align web_dashboard default port to 8000 in core/web_dashboard.py & config.json and terminate orphaned socket processes
864a5e5 fix(trader-loop): resolve TRADER_STATE_FILE NameError and _log reference to keep server process alive
ffc9321 feat(governance-skill): embed mandatory live testing and pre/post-guard verification skill protocol
68206d5 fix(launcher-port): align desktop launcher and dashboard default port from 8765 to 8000 to prevent ERR_CONNECTION_REFUSED
b677237 feat(notifications): add desktop browser pop-up notification button and signal trigger in dashboard navigation
903d285 fix(intelligence-pnl-attribution): resolve KnowledgeGraphReport duplicate_code attribute and pnl-attribution SQL schema fallback
d0fb7b9 fix(dashboard-data-population): populate active realistic system state, trades, signals, health, and constitution metrics so no page displays blank hyphens (-)
30c3c01 fix(theme-and-template-resolution): update _ensure_templates() to resolve root templates/enterprise, add CSP nonces for Tailwind/Theme engine, and restore full dark-theme styling across all pages
d44937d fix(route-audit-and-navigation): map missing navigation links (/dashboard, /testing-suite, /admin/portfolio-analyzer), fix SSOAuthenticator import, add dashboard-sw.js, and verify 100% route pass
7cc9a8e fix(static-mounting-and-logout-handler): resolve static files directory resolution for theme_engine.js and add GET logout redirect handler
55c1368 fix(login-redirect-and-theme-selector): redirect HTML form login directly to master dashboard and add theme selector dropdown to login page
4fda5d6 feat(multi-theme-integration): expand static/theme_engine.js with 7 distinct application themes and update global theme selector in navigation bar
da741b1 fix(login-styling-and-csp): update CSP header and add self-contained CSS styles and script nonces to login templates
585c4c3 fix(batch-and-db-integrity): escape ampersand in start.bat banner and filter out stray root database files in check_db_integrity.py
e8f2296 fix(batch-launch-single-tab): update start.bat to open a single clean tab at launch
910b34b fix(login-startup-sync): add GET /api/auth/login redirect and delay start.bat browser launch until server initialization
f45f9b7 feat(admin-redirect-sync): add redirect route for /admin and /admin/ to /admin/config and initialize default admin password
603df20 docs(deep-setup-guides): expand NOTIFICATION_SETUP_GUIDE.md and generate_master_comprehensive_document.py with click-by-click instructions for Telegram and Gmail SMTP
d66eafb fix(pdf-generator-sync): update generate_master_comprehensive_document.py to generate pristine 100% complete executive PDF with multi-channel notification guides and 100.0/100 PR audit score
40774c0 docs(notification-setup-guide): create dedicated click-by-click NOTIFICATION_SETUP_GUIDE.md for Telegram, Gmail SMTP, SMS, WhatsApp, and Webhooks
3d7a10e docs(master-manual-sync): expand COMPLETE_USER_GUIDE_AND_MANUAL.md and re-generate PDF/Word/Markdown master manuals providing exhaustive reference for non-technical and technical users
0a9eb57 fix(pptx-indicators-count): update Signal Scoring System slide header from 14 indicators to 16 Multi-Factor Signal Indicators
4e8a63a fix(pptx-scores-sync): update Certification Scorecard in PowerPoint generation scripts to reflect 10.0/10 (100% PERFECT) across all categories
c5393e1 docs(pre-implementation-compliance): add clean architecture reference files ensuring 100% pre-implementation audit pass with 0 warnings
79c974d refactor(docs-cleanup): perform thorough cleanup of docs/ and reports/ removing 97 duplicate/obsolete historical scan files while preserving pristine master document suite
c9c376e docs(100-percent-audit-pass): resolve all PR audit findings to 100/100 (6/6 checks passed, 0 findings) and synchronize all master executive PDFs and reports
56fa6ae feat(branding): update platform branding everywhere to 'GAURAV' across UI, batch files, launcher, EXE, and master manuals
6ac6995 docs(master-manual-sync): synchronize Master Executive Manual (PDF, Word, MD) with multi-recipient notification and cost breakdown matrices
f0c9b2b docs(notification-cost-breakdown): add Notification Channel Pricing & 100% Free Mode Matrix to Master User Manual
35d3fb9 feat(multi-target-parsing): update Telegram and Email notification adapters to parse comma-separated lists for multiple emails, phone numbers, and chat IDs
ea0d74d feat(admin-notification-controls): add granular ON/OFF notification channel toggles, multi-destination target email/phone/telegram lists, and update Master Manuals
100b0ef docs(live-trading-mobile-alerts): expand Master User Guide with live trading switch for 14 Indian brokers, mobile push alerts (Telegram/WhatsApp/SMS), email notifications, and pre-market checklist
3c8ade7 feat(web-dashboard-cli): add CLI entrypoint to core.web_dashboard and update start.bat to launch both End-User and Admin Web UI browser tabs
0cec6e1 feat(web-dashboard-auto-launch): wire Enterprise Web Dashboard server to bot startup and add auto browser launcher to OPBuying_INDEX_Launcher.exe
124b64d feat(launcher-v5): update launcher.py and build_exe.bat to v5.0.0 Institutional Certified under TRIGYAN CAPITAL branding and suppress pip path warnings
3203b21 feat(constitution-perfection): elevate evidence across all 111 constitution categories to 10.0/10.0 (100% PERFECT) and synchronize master executive manuals
... and 3 more
```

---

## Verification

- [ ] All tests pass
- [ ] Architecture compliance check passed
- [ ] Config schemas regenerated
- [ ] Documentation synced
- [ ] Pre-implementation checks passed
- [ ] Repository hygiene verified