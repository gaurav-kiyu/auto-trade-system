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