# OPB WEB CLOSURE WIP57 — Navigation Implementation Map

Distinct navigation targets: 36

Each route is mapped to source references and any directly discoverable backend registration.

## `/`
### Backend registrations
- `core/control_plane/server.py:743` — `/`
- `core/enterprise_dashboard/routes/pages.py:104` — `/`
### Source references
- `run_backtest.py:1` — `#!/usr/bin/env python3`
- `run_backtest.py:2` — `"""`
- `run_backtest.py:3` — `OPBuying Candle Backtest - Quant Research Edition`
- `run_backtest.py:4` — `==================================================`
- `run_backtest.py:5` — ``
- `run_backtest.py:6` — `Implements Tasks 1-9 from the quant redesign brief:`
- `run_backtest.py:7` — ``
- `run_backtest.py:8` — `Task 1: Option premium model (delta-scaled P&L, not raw index pts)`
- `run_backtest.py:9` — `Task 2: Regime-adaptive RR targets (TRENDING wider TP, CHOPPY tighter)`
- `run_backtest.py:10` — `Task 3: Score spread analysis (score distribution 60-95+)`
- `run_backtest.py:11` — `Task 4: Signal filtering report (score gap, breakout, ADX filters)`
- `run_backtest.py:12` — `Task 5: Regime performance breakdown (TRENDING/NEUTRAL/CHOPPY/EVENT)`
- `run_backtest.py:13` — `Task 6: Directional breakdown (CALL vs PUT win rates)`
- `run_backtest.py:14` — `Task 7: Full metrics - expectancy, PF, Sharpe, Calmar, RR ratio`
- `run_backtest.py:15` — `Task 8: Signal quality analysis - which features fire, what outcomes`
- `run_backtest.py:16` — `Task 9: Before/after comparison output`
- `run_backtest.py:17` — ``
- `run_backtest.py:18` — `Usage`
- `run_backtest.py:19` — `-----`
- `run_backtest.py:20` — `# Live download (30-day Yahoo 1m):`
- `run_backtest.py:21` — `python run_backtest.py --yf-quarter`
- `run_backtest.py:22` — ``
- `run_backtest.py:23` — `# Custom symbol / period:`
- `run_backtest.py:24` — `python run_backtest.py --yf-quarter --yf-symbol ^NSEI --yf-days 30`
- `run_backtest.py:25` — ``
- `run_backtest.py:26` — `# CSV replay (offline):`
- `run_backtest.py:27` — `python run_backtest.py tests/fixtures/replay_minute_bars.csv`
- `run_backtest.py:28` — ``
- `run_backtest.py:29` — `# Raw index mode (before/after comparison):`
- `run_backtest.py:30` — `python run_backtest.py --yf-quarter --raw-index`

## `/ab-tester`
### Backend registrations
- `core/enterprise_dashboard/routes/pages.py:419` — `/ab-tester`
### Source references
- `tests/test_web_page_permission_menu_contract.py:28` — `assert '{% if can_deploy_models %}<a href="/ab-tester"' in nav`
- `templates/enterprise/_nav.html:489` — `<a href="/ab-tester" class="opb-ws-item {% if current_page == 'ab_tester' %}active{% endif %}"><span>🔬 A/B Testing Framework</span></a>`
- `templates/enterprise/_nav.html:632` — `{% if can_deploy_models %}<a href="/ab-tester" class="drawer-nav-item {% if current_page == 'ab_tester' %}active{% endif %}"><span style="font-size:1rem;margin-right:0.4rem;">🔬</span> <span>A/B Testing Framework</span></a>{% endif %}`
- `core/enterprise_dashboard/routes/pages.py:419` — `@app.get("/ab-tester", response_class=HTMLResponse)`

## `/admin/config`
### Backend registrations
- `core/enterprise_dashboard/routes/pages.py:158` — `/admin/config`
### Source references
- `static/theme_engine.js:1022` — `window.location.href = '/admin/config';`
- `scripts/generate_all_master_consolidated_documents.py:80` — `| `open_admin.bat` | `http://localhost:8000/admin/config` | Super Admin / Admin | Live Configuration Editor & Notification Controls |`
- `scripts/run_consolidated_full_system_verification.py:9` — `5. Configuration Editor & Dual Multi-User Alerting (/admin/config)`
- `scratch/test_all_app_routes.py:56` — `"/admin/config",`
- `scratch/generate_final_deliverables.py:70` — `| Configuration UI mapping disconnect | Upgraded `/admin/config` with dedicated Notifications Tab, helper hints, and hot-reload synchronization. | ✅ CLOSED & VERIFIED |`
- `scratch/test_page_routes_only.py:47` — `"/admin/config",`
- `tests/test_enterprise_dashboard.py:2198` — `"""GET /admin/config renders page for admin user."""`
- `tests/test_enterprise_dashboard.py:2202` — `r = c.get("/admin/config")`
- `tests/test_all_ui_screens_and_navigation.py:72` — `("/admin/config", "Admin Config Editor"),`
- `tests/test_all_ui_screens_and_navigation.py:108` — `resp = client.get("/admin/config")`
- `tests/test_all_ui_screens_and_navigation.py:174` — `protected_routes = ["/", "/admin/config", "/admin/signals", "/admin/users", "/my-signals"]`
- `templates/enterprise/dashboard.html:554` — `<a href="/admin/config" class="opb-quick-tile"><i class="fas fa-cogs" style="color:#34d399;"></i> Config</a>`
- `templates/enterprise/admin_config.html:280` — `<a class="btn btn-sm btn-primary" href="/admin/config" style="text-decoration:none;font-weight:700;">⚙️ Configuration Cockpit</a>`
- `templates/enterprise/admin_portfolio_analyzer.html:132` — `<a class="btn btn-sm btn-ghost" href="/admin/config" style="text-decoration:none;font-weight:700;">⚙️ Configuration Cockpit</a>`
- `templates/enterprise/admin_signals.html:56` — `<a class="btn btn-sm btn-ghost" href="/admin/config" style="text-decoration:none;font-weight:700;">⚙️ Configuration Cockpit</a>`
- `templates/enterprise/admin_users.html:116` — `<a class="btn btn-sm btn-ghost" href="/admin/config" style="text-decoration:none;font-weight:700;">⚙️ Configuration Cockpit</a>`
- `templates/enterprise/_nav.html:496` — `<a href="/admin/config" class="opb-nav-item {% if current_page in ('admin_config', 'admin_signals', 'admin_portfolio_analyzer', 'governance', 'security', 'observability', 'system_health', 'data_quality', 'capacity', 'event_store', 'pricing_plans', 'whats_new', 'presentation', 'kill_switch') %}active{% endif %}">`
- `templates/enterprise/_nav.html:501` — `{% if can_modify_config %}<a href="/admin/config" class="opb-ws-item {% if current_page == 'admin_config' %}active{% endif %}"><span>⚙️ Core System Configuration</span></a>{% endif %}`
- `templates/enterprise/_nav.html:622` — `{% if can_modify_config %}<a href="/admin/config" class="drawer-nav-item {% if current_page == 'admin_config' %}active{% endif %}"><span style="font-size:1rem;margin-right:0.4rem;">⚙️</span> <span>System Configuration</span></a>{% endif %}`
- `core/enterprise_dashboard/main.py:450` — `# -- Admin Root Redirect Route (/admin and /admin/ -> /admin/config) --`
- `core/enterprise_dashboard/main.py:454` — `return RedirectResponse(url="/admin/config", status_code=307)`
- `core/enterprise_dashboard/routes/pages.py:3` — `Handles: /, /login, /register, /admin/users, /admin/config,`
- `core/enterprise_dashboard/routes/pages.py:158` — `@app.get("/admin/config", response_class=HTMLResponse)`

## `/admin/kill-switch`
### Backend registrations
- `core/enterprise_dashboard/routes/pages.py:281` — `/admin/kill-switch`
### Source references
- `static/theme_engine.js:1038` — `window.location.href = '/admin/kill-switch';`
- `static/theme_engine.js:1041` — `window.location.href = '/admin/kill-switch';`
- `scripts/generate_all_master_consolidated_documents.py:91` — `| Kill Switch | `http://localhost:8000/admin/kill-switch` | Super Admin / Risk Mgr | Instant Global Trading Emergency Halt |`
- `scratch/test_all_app_routes.py:57` — `"/admin/kill-switch",`
- `scratch/test_page_routes_only.py:48` — `"/admin/kill-switch",`
- `tests/test_enterprise_dashboard.py:2206` — `"""GET /admin/kill-switch renders page for admin user."""`
- `tests/test_enterprise_dashboard.py:2210` — `r = c.get("/admin/kill-switch")`
- `tests/test_web_dashboard.py:110` — `# /admin/kill-switch should redirect to login (no session cookie)`
- `tests/test_web_dashboard.py:111` — `resp = client.get("/admin/kill-switch", follow_redirects=False)`
- `tests/test_all_ui_screens_and_navigation.py:76` — `("/admin/kill-switch", "Admin Kill Switch"),`
- `templates/enterprise/dashboard.html:555` — `<a href="/admin/kill-switch" class="opb-quick-tile" style="color: var(--danger-color, #dc2626);"><i class="fas fa-power-off" style="color: var(--danger-color, #dc2626);"></i> Kill Switch</a>`
- `templates/enterprise/_nav.html:434` — `{% if can_halt_trading %}<a href="/admin/kill-switch" class="btn btn-danger btn-sm" style="display:inline-flex;align-items:center;gap:0.35rem;font-weight:800;padding:0.35rem 0.75rem;font-size:0.75rem;text-decoration:none;border-radius:0.4rem;box-shadow:0 2px 8px rgba(220,38,38,0.35);flex-shrink:0;white-space:nowrap;min-width:max-content;">`
- `templates/enterprise/_nav.html:514` — `{% if can_modify_risk %}<a href="/admin/kill-switch" class="opb-ws-item {% if current_page == 'kill_switch' %}active{% endif %}" style="color: var(--danger-color, #ef4444);"><span>🚨 Emergency Kill Switch</span></a>{% endif %}`
- `templates/enterprise/_nav.html:539` — `<a href="/admin/kill-switch" class="mobile-kill-btn" title="Emergency Kill Switch" style="display:inline-flex;align-items:center;gap:0.25rem;background:linear-gradient(135deg,#ef4444 0%,#dc2626 100%);color:#ffffff!important;border:1px solid #b91c1c;padding:0.25rem 0.6rem;border-radius:0.45rem;font-size:0.72rem;font-weight:800;letter-spacing:0.03em;text-decoration:none;white-space:nowrap;box-shadow:0 2px 6px rgba(220,38,38,0.4);">`
- `templates/enterprise/_nav.html:636` — `{% if can_halt_trading %}<a href="/admin/kill-switch" class="drawer-nav-item {% if current_page == 'kill_switch' %}active{% endif %}" style="color:var(--danger-color, #ef4444);"><span style="font-size:1rem;margin-right:0.4rem;">🚨</span> <span>Emergency Kill Switch</span></a>{% endif %}`
- `core/enterprise_dashboard/routes/pages.py:4` — `/admin/kill-switch, /change-password, and SPA redirect pages.`
- `core/enterprise_dashboard/routes/pages.py:281` — `@app.get("/admin/kill-switch", response_class=HTMLResponse)`

## `/admin/portfolio-analyzer`
### Backend registrations
- `core/enterprise_dashboard/routes/admin.py:633` — `/admin/portfolio-analyzer`
### Source references
- `scratch/test_all_app_routes.py:54` — `"/admin/portfolio-analyzer",`
- `scratch/test_page_routes_only.py:45` — `"/admin/portfolio-analyzer",`
- `tests/test_all_ui_screens_and_navigation.py:75` — `("/admin/portfolio-analyzer", "Admin Portfolio Analyzer"),`
- `tests/test_admin_portfolio_analyzer.py:16` — `/admin/portfolio-analyzer now requires admin auth (it previously had no`
- `tests/test_admin_portfolio_analyzer.py:115` — `resp = client.get("/admin/portfolio-analyzer")`
- `tests/test_admin_portfolio_analyzer.py:130` — `resp = client.get("/admin/portfolio-analyzer")`
- `tests/test_admin_portfolio_analyzer.py:139` — `r_get = client.get("/admin/portfolio-analyzer")`
- `tests/test_admin_portfolio_analyzer.py:169` — `r_get = client.get("/admin/portfolio-analyzer")`
- `templates/enterprise/admin_config.html:282` — `<a class="btn btn-sm btn-ghost" href="/admin/portfolio-analyzer" style="text-decoration:none;font-weight:700;">💼 Multi-Broker Portfolio</a>`
- `templates/enterprise/admin_portfolio_analyzer.html:134` — `<a class="btn btn-sm btn-primary" href="/admin/portfolio-analyzer" style="text-decoration:none;font-weight:700;">💼 Multi-Broker Portfolio</a>`
- `templates/enterprise/admin_portfolio_analyzer.html:312` — `<a aria-disabled="true" class="btn-accent" href="/admin/portfolio-analyzer" id="broker-oauth-link" rel="noopener noreferrer" style="padding:0.65rem 1.25rem; text-decoration:none; display:inline-flex; align-items:center; gap:0.5rem; font-size:0.85rem; background: #3b82f6; pointer-events:none; opacity:0.6;" target="_blank">`
- `templates/enterprise/admin_portfolio_analyzer.html:472` — `oauthLink.href = '/admin/portfolio-analyzer';`
- `templates/enterprise/admin_signals.html:58` — `<a class="btn btn-sm btn-ghost" href="/admin/portfolio-analyzer" style="text-decoration:none;font-weight:700;">💼 Multi-Broker Portfolio</a>`
- `templates/enterprise/admin_users.html:118` — `<a class="btn btn-sm btn-ghost" href="/admin/portfolio-analyzer" style="text-decoration:none;font-weight:700;">💼 Multi-Broker Portfolio</a>`
- `templates/enterprise/_nav.html:503` — `{% if can_manage_brokers or can_view_state %}<a href="/admin/portfolio-analyzer" class="opb-ws-item {% if current_page == 'admin_portfolio_analyzer' %}active{% endif %}"><span>💼 Multi-Broker Portfolio</span></a>{% endif %}`
- `templates/enterprise/_nav.html:624` — `{% if can_manage_brokers or can_view_state %}<a href="/admin/portfolio-analyzer" class="drawer-nav-item {% if current_page == 'admin_portfolio_analyzer' %}active{% endif %}"><span style="font-size:1rem;margin-right:0.4rem;">💼</span> <span>Multi-Broker Portfolio</span></a>{% endif %}`
- `core/enterprise_dashboard/routes/admin.py:633` — `@app.get("/admin/portfolio-analyzer")`

## `/admin/signals`
### Backend registrations
- `core/enterprise_dashboard/routes/pages.py:170` — `/admin/signals`
### Source references
- `scripts/generate_all_master_consolidated_documents.py:49` — `7. **Signal Tracker & Historical Accuracy Engine (`/admin/signals` & `/my-signals`)**: SQLite persistence tracking signal generation, targets, SL, win rates (100.0%), and personal user feeds.`
- `scripts/generate_all_master_consolidated_documents.py:82` — `| Signal Accuracy Hub | `http://localhost:8000/admin/signals` | Super Admin | Historical Signal Performance & Category Win Rates |`
- `scripts/run_consolidated_full_system_verification.py:11` — `7. Signal Tracker & Historical Accuracy Engine (/admin/signals & /my-signals)`
- `tests/test_web_page_permission_menu_contract.py:44` — `assert '{% if can_modify_config or can_view_logs %}<a href="/admin/signals"' in nav`
- `tests/test_notification_url_production_contract.py:22` — `assert build_action_url("/admin/signals", cfg=cfg) == DEFAULT_PRODUCTION_URL + "/admin/signals"`
- `tests/test_all_ui_screens_and_navigation.py:73` — `("/admin/signals", "Admin Signal Manager"),`
- `tests/test_all_ui_screens_and_navigation.py:174` — `protected_routes = ["/", "/admin/config", "/admin/signals", "/admin/users", "/my-signals"]`
- `templates/enterprise/admin_config.html:281` — `<a class="btn btn-sm btn-ghost" href="/admin/signals" style="text-decoration:none;font-weight:700;">🎯 Signal Accuracy Matrix</a>`
- `templates/enterprise/admin_portfolio_analyzer.html:133` — `<a class="btn btn-sm btn-ghost" href="/admin/signals" style="text-decoration:none;font-weight:700;">🎯 Signal Accuracy Matrix</a>`
- `templates/enterprise/admin_signals.html:57` — `<a class="btn btn-sm btn-primary" href="/admin/signals" style="text-decoration:none;font-weight:700;">🎯 Signal Accuracy Matrix</a>`
- `templates/enterprise/admin_users.html:117` — `<a class="btn btn-sm btn-ghost" href="/admin/signals" style="text-decoration:none;font-weight:700;">🎯 Signal Accuracy Matrix</a>`
- `templates/enterprise/_nav.html:502` — `{% if can_modify_config or can_view_logs %}<a href="/admin/signals" class="opb-ws-item {% if current_page == 'admin_signals' %}active{% endif %}"><span>🎯 Signal Accuracy & Dispatch Matrix</span></a>{% endif %}`
- `templates/enterprise/_nav.html:623` — `{% if can_modify_config or can_view_logs %}<a href="/admin/signals" class="drawer-nav-item {% if current_page == 'admin_signals' %}active{% endif %}"><span style="font-size:1rem;margin-right:0.4rem;">🎯</span> <span>Signal Accuracy Matrix</span></a>{% endif %}`
- `core/enterprise_dashboard/routes/pages.py:170` — `@app.get("/admin/signals", response_class=HTMLResponse)`

## `/admin/users`
### Backend registrations
- `core/enterprise_dashboard/routes/pages.py:146` — `/admin/users`
### Source references
- `scripts/generate_all_master_consolidated_documents.py:46` — `4. **Super Admin User & Signal Permission Control Center (`/admin/users`)**: 1-click Master Signal Switches, Granular Category Subscriptions, Conviction Tier Cutoffs, Multi-Timeframe Quota Controls (Daily, Weekly, Monthly), and Dedicated User Channel Routing.`
- `scripts/generate_all_master_consolidated_documents.py:68` — `## 🛡️ SUPER ADMIN CONTROL PLANE (`/admin/users`)`
- `scripts/generate_all_master_consolidated_documents.py:69` — `Accessible at `http://localhost:8000/admin/users`:`
- `scripts/generate_all_master_consolidated_documents.py:81` — `| Super Admin Users | `http://localhost:8000/admin/users` | Super Admin | User Signal Permissions, Category Subscriptions & Quotas |`
- `scripts/run_consolidated_full_system_verification.py:8` — `4. Super Admin RBAC, Quotas & Category Permissions (/admin/users)`
- `scratch/test_all_app_routes.py:55` — `"/admin/users",`
- `scratch/generate_final_deliverables.py:50` — `4. **Super Admin User & Signal Control Center (`/admin/users`)**:`
- `scratch/generate_final_deliverables.py:69` — `| Uncontrolled user signal access | Implemented `UserPermissionManager` and Super Admin Control Panel (`/admin/users`) with category filters, tier cutoffs, and quotas. | ✅ CLOSED & VERIFIED |`
- `scratch/generate_final_deliverables.py:103` — `"<b>Super Admin User Control Center (/admin/users):</b> Master switches, 8 asset categories, daily/weekly/monthly quotas, and tier cutoffs.",`
- `scratch/generate_final_deliverables.py:282` — `p.text = "Super Admin Control Features (/admin/users)"`
- `scratch/test_page_routes_only.py:46` — `"/admin/users",`
- `tests/test_enterprise_dashboard.py:2190` — `"""GET /admin/users renders page for admin user."""`
- `tests/test_enterprise_dashboard.py:2194` — `r = c.get("/admin/users")`
- `tests/test_dashboard_comprehensive.py:2016` — `resp = c.get("/admin/users", headers={"accept": "application/json"}, follow_redirects=False)`
- `tests/test_dashboard_comprehensive.py:2021` — `resp = c.get("/admin/users", follow_redirects=False)`
- `tests/test_all_ui_screens_and_navigation.py:74` — `("/admin/users", "Admin User Manager"),`
- `tests/test_all_ui_screens_and_navigation.py:174` — `protected_routes = ["/", "/admin/config", "/admin/signals", "/admin/users", "/my-signals"]`
- `templates/enterprise/_nav.html:500` — `{% if can_manage_permissions %}<a href="/admin/users" class="opb-ws-item {% if current_page == 'admin_users' %}active{% endif %}"><span>👥 User Authorization & Controls</span></a>{% endif %}`
- `templates/enterprise/_nav.html:621` — `{% if can_manage_permissions %}<a href="/admin/users" class="drawer-nav-item {% if current_page == 'admin_users' %}active{% endif %}"><span style="font-size:1rem;margin-right:0.4rem;">👥</span> <span>User Authorization & Access</span></a>{% endif %}`
- `core/auth/registration_notifications.py:133` — `<p><a href='{build_action_url('/admin/users')}' style='display:inline-block;padding:10px 16px;background:#2563eb;color:white;text-decoration:none;border-radius:6px'>Open User Controls</a></p>`
- `core/auth/registration_notifications.py:139` — `f"Review: {build_action_url('/admin/users')}\n"`
- `core/enterprise_dashboard/routes/pages.py:3` — `Handles: /, /login, /register, /admin/users, /admin/config,`
- `core/enterprise_dashboard/routes/pages.py:146` — `@app.get("/admin/users", response_class=HTMLResponse)`

## `/capacity`
### Backend registrations
- `core/enterprise_dashboard/routes/pages.py:443` — `/capacity`
### Source references
- `scripts/constitution_scorecard.py:192` — `"core/capacity_planning.py", weight=1.0),`
- `scripts/check_performance_budget.py:318` — `For full capacity benchmarks, use ``python scripts/capacity_benchmark.py``.`
- `scripts/capacity_benchmark.py:13` — `python scripts/capacity_benchmark.py                    # Full run`
- `scripts/capacity_benchmark.py:14` — `python scripts/capacity_benchmark.py --quick            # Quick run (fewer iterations)`
- `scripts/capacity_benchmark.py:15` — `python scripts/capacity_benchmark.py --json             # Machine-readable output`
- `scripts/capacity_benchmark.py:16` — `python scripts/capacity_benchmark.py --ci               # CI mode (json + exit code)`
- `scripts/capacity_benchmark.py:30` — `# This allows the benchmark to work when run as python scripts/capacity_benchmark.py`
- `scratch/test_all_app_routes.py:50` — `"/capacity",`
- `scratch/test_page_routes_only.py:41` — `"/capacity",`
- `tests/test_capacity.py:1` — `"""Tests for core/enterprise_dashboard/routes/capacity.py.`
- `tests/test_capacity_benchmark.py:1` — `"""Unit tests for scripts/capacity_benchmark.py — Capacity Benchmark Engine.`
- `tests/test_all_ui_screens_and_navigation.py:70` — `("/capacity", "Capacity Planning"),`
- `templates/enterprise/capacity.html:142` — `const data = await apiFetch('/api/capacity/report');`
- `templates/enterprise/capacity.html:183` — `const data = await apiFetch('/api/capacity/throughput');`
- `templates/enterprise/_nav.html:509` — `{% if can_view_state %}<a href="/capacity" class="opb-ws-item {% if current_page == 'capacity' %}active{% endif %}"><span>⚡ Capacity & Scalability</span></a>{% endif %}`
- `templates/enterprise/_nav.html:630` — `{% if can_view_state %}<a href="/capacity" class="drawer-nav-item {% if current_page == 'capacity' %}active{% endif %}"><span style="font-size:1rem;margin-right:0.4rem;">⚡</span> <span>Capacity & Scalability</span></a>{% endif %}`
- `core/constitution/evidence/prn_ast_evidence.py:1084` — `"ROL-16": ("FinOps", "core/capacity_planning.py"),`
- `core/enterprise_dashboard/routes/capacity.py:3` — `Handles: /api/capacity/* endpoints:`
- `core/enterprise_dashboard/routes/capacity.py:4` — `- /api/capacity/report       — Full capacity analysis report`
- `core/enterprise_dashboard/routes/capacity.py:5` — `- /api/capacity/forecast     — DB growth forecasts`
- `core/enterprise_dashboard/routes/capacity.py:6` — `- /api/capacity/triggers     — Scaling triggers status`
- `core/enterprise_dashboard/routes/capacity.py:7` — `- /api/capacity/throughput   — Throughput trend analysis`
- `core/enterprise_dashboard/routes/capacity.py:8` — `- /api/capacity/changelog    — Capacity change log`
- `core/enterprise_dashboard/routes/capacity.py:33` — `@app.get("/api/capacity/report", tags=["Capacity"])`
- `core/enterprise_dashboard/routes/capacity.py:45` — `@app.get("/api/capacity/forecast", tags=["Capacity"])`
- `core/enterprise_dashboard/routes/capacity.py:62` — `@app.get("/api/capacity/triggers", tags=["Capacity"])`
- `core/enterprise_dashboard/routes/capacity.py:78` — `@app.get("/api/capacity/throughput", tags=["Capacity"])`
- `core/enterprise_dashboard/routes/capacity.py:90` — `@app.get("/api/capacity/changelog", tags=["Capacity"])`
- `core/enterprise_dashboard/routes/pages.py:443` — `@app.get("/capacity", response_class=HTMLResponse)`

## `/data-quality`
### Backend registrations
- `core/enterprise_dashboard/routes/pages.py:467` — `/data-quality`
### Source references
- `scratch/test_all_app_routes.py:51` — `"/data-quality",`
- `scratch/test_page_routes_only.py:42` — `"/data-quality",`
- `tests/test_all_ui_screens_and_navigation.py:66` — `("/data-quality", "Data Quality"),`
- `templates/enterprise/_nav.html:508` — `{% if can_view_state %}<a href="/data-quality" class="opb-ws-item {% if current_page == 'data_quality' %}active{% endif %}"><span>📊 Data Quality & Integrity Guard</span></a>{% endif %}`
- `templates/enterprise/_nav.html:629` — `{% if can_view_state %}<a href="/data-quality" class="drawer-nav-item {% if current_page == 'data_quality' %}active{% endif %}"><span style="font-size:1rem;margin-right:0.4rem;">📊</span> <span>Data Quality Guard</span></a>{% endif %}`
- `core/enterprise_dashboard/routes/pages.py:467` — `@app.get("/data-quality", response_class=HTMLResponse)`

## `/event-store`
### Backend registrations
- `core/enterprise_dashboard/routes/pages.py:407` — `/event-store`
### Source references
- `scratch/test_all_app_routes.py:58` — `"/event-store",`
- `tests/test_enterprise_dashboard_integration.py:7` — `- /event-store HTML page route`
- `tests/test_enterprise_dashboard_integration.py:293` — `"""Test the /event-store HTML page route."""`
- `tests/test_enterprise_dashboard_integration.py:301` — `resp = c.get("/event-store", headers={"accept": "text/html"})`
- `tests/test_enterprise_dashboard_integration.py:307` — `resp = admin_client.get("/event-store")`
- `tests/test_all_ui_screens_and_navigation.py:67` — `("/event-store", "Event Store"),`
- `templates/enterprise/_nav.html:510` — `{% if can_view_logs %}<a href="/event-store" class="opb-ws-item {% if current_page == 'event_store' %}active{% endif %}"><span>📜 Event Store & Audit Log</span></a>{% endif %}`
- `templates/enterprise/_nav.html:631` — `{% if can_view_logs %}<a href="/event-store" class="drawer-nav-item {% if current_page == 'event_store' %}active{% endif %}"><span style="font-size:1rem;margin-right:0.4rem;">📜</span> <span>Event Store & Audit Log</span></a>{% endif %}`
- `core/enterprise_dashboard/routes/pages.py:407` — `@app.get("/event-store", response_class=HTMLResponse)`

## `/expiry-harvester`
### Backend registrations
- `core/enterprise_dashboard/routes/pages.py:259` — `/expiry-harvester`
### Source references
- `scripts/generate_all_master_consolidated_documents.py:59` — `17. **0DTE Expiry Day Delta-Neutral Harvester (`/expiry-harvester`)**: Automated 09:20 AM straddle engine with 25% trailing SL and delta-neutral rebalancing.`
- `scripts/generate_all_master_consolidated_documents.py:89` — `| 0DTE Harvester | `http://localhost:8000/expiry-harvester` | Options Traders | Automated Expiry Straddle Delta Harvester |`
- `scripts/run_consolidated_full_system_verification.py:21` — `17. 0DTE Expiry Day Smart Delta-Neutral Harvester (/expiry-harvester)`
- `tests/test_all_ui_screens_and_navigation.py:62` — `("/expiry-harvester", "Expiry Harvester"),`
- `templates/enterprise/_nav.html:464` — `<a href="/expiry-harvester" class="opb-ws-item {% if current_page == 'expiry_harvester' %}active{% endif %}"><span>🌾 Expiry Day Harvester</span></a>`
- `templates/enterprise/_nav.html:609` — `<a href="/expiry-harvester" class="drawer-nav-item {% if current_page == 'expiry_harvester' %}active{% endif %}"><span style="font-size:1rem;margin-right:0.4rem;">🌾</span> <span>Expiry Harvester</span></a>`
- `core/enterprise_dashboard/routes/pages.py:259` — `@app.get("/expiry-harvester", response_class=HTMLResponse)`

## `/fii-dii-radar`
### Backend registrations
- `core/enterprise_dashboard/routes/pages.py:249` — `/fii-dii-radar`
### Source references
- `scripts/generate_all_master_consolidated_documents.py:58` — `16. **FII / DII Participant-Wise Smart Money Positioning Radar (`/fii-dii-radar`)**: NSE participant-wise Open Interest analysis across FIIs, DIIs, Pro Desks, and Retail with Short Squeeze warnings.`
- `scripts/generate_all_master_consolidated_documents.py:88` — `| FII / DII Radar | `http://localhost:8000/fii-dii-radar` | Super Admin / Traders | Participant-Wise Net Positioning & Trap Alerts |`
- `scripts/run_consolidated_full_system_verification.py:20` — `16. FII / DII Participant-Wise Smart Money Positioning Radar (/fii-dii-radar)`
- `tests/test_all_ui_screens_and_navigation.py:59` — `("/fii-dii-radar", "FII / DII Radar"),`
- `templates/enterprise/_nav.html:463` — `<a href="/fii-dii-radar" class="opb-ws-item {% if current_page == 'fii_dii_radar' %}active{% endif %}"><span>🏦 Institutional FII/DII</span></a>`
- `templates/enterprise/_nav.html:608` — `<a href="/fii-dii-radar" class="drawer-nav-item {% if current_page == 'fii_dii_radar' %}active{% endif %}"><span style="font-size:1rem;margin-right:0.4rem;">🏦</span> <span>Institutional FII/DII</span></a>`
- `core/enterprise_dashboard/routes/pages.py:249` — `@app.get("/fii-dii-radar", response_class=HTMLResponse)`

## `/forgot-password`
### Backend registrations
- `core/auth/routes.py:1174` — `/forgot-password`
- `core/enterprise_dashboard/routes/pages.py:293` — `/forgot-password`
### Source references
- `tests/test_all_ui_screens_and_navigation.py:51` — `("/forgot-password", "Forgot Password"),`
- `tests/test_password_reset_recovery.py:39` — `# public /forgot-password page. It's now read from`
- `templates/enterprise/login.html:418` — `<a href="/forgot-password" style="color:var(--accent-color, #38bdf8);text-decoration:none;font-size:0.75rem;font-weight:700;">Forgot password?</a>`
- `templates/enterprise/forgot_password.html:287` — `const res = await fetch('/api/auth/forgot-password', {`
- `core/auth/routes.py:1174` — `@router.post("/forgot-password")`
- `core/enterprise_dashboard/main.py:400` — `csrf_protection.exempt("/api/auth/forgot-password")`
- `core/enterprise_dashboard/main.py:404` — `csrf_protection.exempt("/api/auth/forgot-password")`
- `core/enterprise_dashboard/routes/pages.py:293` — `@app.get("/forgot-password", response_class=HTMLResponse)`
- `core/auth/handler/handler.py:725` — `unauthenticated /forgot-password page - effectively a published backdoor to reset any`

## `/governance`
### Backend registrations
- `core/enterprise_dashboard/routes/pages.py:431` — `/governance`
### Source references
- `core/metrics_exporter.py:74` — `"constitution_security_governance_pct": Gauge("opb_constitution_security_governance_pct", "Constitution security/governance passing %"),`
- `static/theme_engine.js:1019` — `window.location.href = '/governance';`
- `scripts/gap_audit.py:28` — `results.append(("WS7 AI Governance", all([exists("core/ai/model_registry.py"), exists("core/ai/governance.py"), exists("core/ai/rollback_controller.py")])))`
- `scratch/test_all_app_routes.py:49` — `"/governance",`
- `scratch/test_page_routes_only.py:40` — `"/governance",`
- `tests/test_web_page_permission_menu_contract.py:12` — `assert '{% if can_toggle_strategies %}<a href="/governance"' in nav`
- `tests/test_all_ui_screens_and_navigation.py:68` — `("/governance", "Constitution Governance"),`
- `tests/test_governance.py:1` — `"""Tests for core/ai/governance.py."""`
- `tests/test_governance.py:9` — `"""Test suite for core/ai/governance.py."""`
- `templates/enterprise/dashboard.html:553` — `<a href="/governance" class="opb-quick-tile"><i class="fas fa-gavel" style="color:#8b5cf6;"></i> Governance</a>`
- `templates/enterprise/data_quality.html:223` — `const data = await apiFetch('/api/governance/quality');`
- `templates/enterprise/data_quality.html:266` — `const data = await apiFetch('/api/governance/quality');`
- `templates/enterprise/data_quality.html:290` — `const data = await apiFetch('/api/governance/quality');`
- `templates/enterprise/governance.html:205` — `const data = await apiFetch('/api/governance/status');`
- `templates/enterprise/governance.html:218` — `const data = await apiFetch('/api/governance/pending');`
- `templates/enterprise/governance.html:250` — `const url = filter ? `/api/governance/history?strategy_name=${encodeURIComponent(filter)}` : '/api/governance/history';`
- `templates/enterprise/governance.html:273` — `const data = await apiFetch('/api/governance/quality');`
- `templates/enterprise/governance.html:308` — `const res = await apiFetch('/api/governance/approve', {`
- `templates/enterprise/governance.html:325` — `const res = await apiFetch('/api/governance/reject', {`
- `templates/enterprise/governance.html:373` — `const res = await apiFetch('/api/governance/request', {`
- `templates/enterprise/_nav.html:504` — `{% if can_toggle_strategies %}<a href="/governance" class="opb-ws-item {% if current_page == 'governance' %}active{% endif %}"><span>⚖️ Governance Policy Gate</span></a>{% endif %}`
- `templates/enterprise/_nav.html:625` — `{% if can_toggle_strategies %}<a href="/governance" class="drawer-nav-item {% if current_page == 'governance' %}active{% endif %}"><span style="font-size:1rem;margin-right:0.4rem;">⚖️</span> <span>Governance Policy Gate</span></a>{% endif %}`
- `core/enterprise_dashboard/routes/governance.py:3` — `Handles: /api/governance/* endpoints for strategy lifecycle management:`
- `core/enterprise_dashboard/routes/governance.py:4` — `- /api/governance/status         — Governance system health`
- `core/enterprise_dashboard/routes/governance.py:5` — `- /api/governance/pending        — Pending approval requests`
- `core/enterprise_dashboard/routes/governance.py:6` — `- /api/governance/history        — Request history (all or per-strategy)`
- `core/enterprise_dashboard/routes/governance.py:7` — `- /api/governance/rules          — Approval rules configuration`
- `core/enterprise_dashboard/routes/governance.py:8` — `- /api/governance/log            — Approval audit log`
- `core/enterprise_dashboard/routes/governance.py:9` — `- /api/governance/report         — Comprehensive governance report`
- `core/enterprise_dashboard/routes/governance.py:10` — `- /api/governance/request        — Request a transition`

## `/intelligence`
### Backend registrations
- `core/enterprise_dashboard/routes/pages.py:491` — `/intelligence`
### Source references
- `core/presentation_generator.py:619` — `["GET", "/api/intelligence/summary", "All intelligence modules"],`
- `static/theme_engine.js:1016` — `window.location.href = '/intelligence';`
- `scratch/test_all_app_routes.py:42` — `"/intelligence",`
- `scratch/test_page_routes_only.py:33` — `"/intelligence",`
- `tests/test_intelligence_pipeline.py:1` — `"""Tests for core/enterprise_dashboard/routes/intelligence_pipeline.py."""`
- `tests/test_intelligence_analysis.py:1` — `"""Tests for core/enterprise_dashboard/routes/intelligence_analysis.py."""`
- `tests/test_intelligence_incidents.py:1` — `"""Tests for core/enterprise_dashboard/routes/intelligence_incidents.py."""`
- `tests/test_all_ui_screens_and_navigation.py:69` — `("/intelligence", "Continuous Intelligence"),`
- `tests/test_config_validator.py:116` — `"""append_tier_engine_errors - tier/intelligence checks."""`
- `tests/test_intelligence_bi.py:1` — `"""Tests for core/enterprise_dashboard/routes/intelligence_bi.py."""`
- `tests/test_intelligence.py:1` — `"""Tests for core/enterprise_dashboard/routes/intelligence.py.`
- `tests/test_intelligent_test_generator.py:86` — `api_tests = gen.generate_api_tests("core/enterprise_dashboard/routes/intelligence.py")`
- `tests/test_impact_analysis_engine.py:154` — `router_path = Path("core/enterprise_dashboard/routes/intelligence.py")`
- `templates/enterprise/intelligence.html:259` — `<code style="color:#60a5fa;">/api/intelligence/summary</code>`
- `templates/enterprise/intelligence.html:442` — `<code style="color:#60a5fa;">/api/intelligence/summary</code>`
- `templates/enterprise/intelligence.html:549` — `const data = await apiFetch('/api/intelligence/bi/report');`
- `templates/enterprise/intelligence.html:648` — `const data = await apiFetch('/api/intelligence/security/scan');`
- `templates/enterprise/intelligence.html:697` — `const data = await apiFetch('/api/intelligence/performance/analyze');`
- `templates/enterprise/intelligence.html:745` — `const data = await apiFetch('/api/intelligence/architecture/analyze');`
- `templates/enterprise/intelligence.html:800` — `const data = await apiFetch('/api/intelligence/bi/deployments');`
- `templates/enterprise/intelligence.html:840` — `const data = await apiFetch('/api/intelligence/summary');`
- `templates/enterprise/intelligence.html:914` — `const data = await apiFetch('/api/intelligence/summary');`
- `templates/enterprise/intelligence.html:997` — `const data = await apiFetch('/api/intelligence/incidents/list?limit=10');`
- `templates/enterprise/intelligence.html:1010` — `const openData = await apiFetch('/api/intelligence/incidents/open');`
- `templates/enterprise/intelligence.html:1054` — `const data = await apiFetch('/api/intelligence/incidents/list?limit=15');`
- `templates/enterprise/intelligence.html:1080` — `const data = await apiFetch('/api/intelligence/incidents/get/'+id);`
- `templates/enterprise/intelligence.html:1103` — `const data = await apiFetch('/api/intelligence/incidents/acknowledge/'+id, {method:'POST'});`
- `templates/enterprise/intelligence.html:1119` — `const data = await apiFetch('/api/intelligence/incidents/resolve/'+id, {`
- `templates/enterprise/intelligence.html:1138` — `const data = await apiFetch('/api/intelligence/incidents/close/'+id, {`
- `templates/enterprise/intelligence.html:1156` — `const data = await apiFetch('/api/intelligence/incidents/detect', {method:'POST'});`

## `/intelligence/presentation`
### Backend registrations
- `core/enterprise_dashboard/routes/pages.py:520` — `/intelligence/presentation`
### Source references
- `templates/enterprise/presentation.html:166` — `const r = await fetch('/api/intelligence/presentation/templates');`
- `templates/enterprise/presentation.html:262` — `const r = await fetch('/api/intelligence/presentation/generate', {`
- `templates/enterprise/presentation.html:311` — `const r = await fetch('/api/intelligence/presentation/generate-all', {`
- `templates/enterprise/_nav.html:513` — `{% if can_view_state %}<a href="/intelligence/presentation" class="opb-ws-item {% if current_page == 'presentation' %}active{% endif %}"><span>📊 Institutional Presentation</span></a>{% endif %}`
- `templates/enterprise/_nav.html:635` — `{% if can_view_state %}<a href="/intelligence/presentation" class="drawer-nav-item {% if current_page == 'presentation' %}active{% endif %}"><span style="font-size:1rem;margin-right:0.4rem;">📊</span> <span>Institutional Presentation</span></a>{% endif %}`
- `core/enterprise_dashboard/routes/intelligence.py:459` — `@app.get("/api/intelligence/presentation/templates")`
- `core/enterprise_dashboard/routes/intelligence.py:479` — `@app.post("/api/intelligence/presentation/generate-all")`
- `core/enterprise_dashboard/routes/intelligence_bi.py:260` — `@app.post("/api/intelligence/presentation/generate")`
- `core/enterprise_dashboard/routes/pages.py:520` — `@app.get("/intelligence/presentation", response_class=HTMLResponse)`

## `/live-pnl`
### Backend registrations
- `core/enterprise_dashboard/routes/pages.py:383` — `/live-pnl`
### Source references
- `scratch/test_all_app_routes.py:45` — `"/live-pnl",`
- `scratch/test_page_routes_only.py:36` — `"/live-pnl",`
- `tests/test_enterprise_dashboard_integration.py:5` — `- /live-pnl HTML page route`
- `tests/test_enterprise_dashboard_integration.py:248` — `"""Test the /live-pnl HTML page route."""`
- `tests/test_enterprise_dashboard_integration.py:256` — `resp = c.get("/live-pnl", headers={"accept": "text/html"})`
- `tests/test_enterprise_dashboard_integration.py:262` — `resp = admin_client.get("/live-pnl")`
- `tests/test_all_ui_screens_and_navigation.py:55` — `("/live-pnl", "Live PnL Screen"),`
- `templates/enterprise/dashboard.html:546` — `<a href="/live-pnl" class="opb-quick-tile"><i class="fas fa-dollar-sign" style="color: var(--success-color, #16a34a);"></i> Live P&L</a>`
- `templates/enterprise/_pwa_mobile_nav.html:69` — `<a href="/live-pnl" class="nav-item{% if current_page == 'live_pnl' %} active{% endif %}">`
- `templates/enterprise/profile.html:549` — `<a href="/live-pnl" class="quick-nav-link">`
- `templates/enterprise/_nav.html:470` — `<a href="/live-pnl" class="opb-nav-item {% if current_page in ('live_pnl', 'trade_journal', 'trade_copier', 'payoff_calculator', 'performance') %}active{% endif %}">`
- `templates/enterprise/_nav.html:474` — `<a href="/live-pnl" class="opb-ws-item {% if current_page == 'live_pnl' %}active{% endif %}"><span>📈 Live P&L Cockpit</span></a>`
- `templates/enterprise/_nav.html:612` — `<a href="/live-pnl" class="drawer-nav-item {% if current_page == 'live_pnl' %}active{% endif %}"><span style="font-size:1rem;margin-right:0.4rem;">📈</span> <span>Live P&L Cockpit</span></a>`
- `templates/enterprise/_nav.html:661` — `<a href="/live-pnl" class="mobile-dock-tab {% if current_page == 'live_pnl' %}active{% endif %}" title="Live P&L Cockpit">`
- `core/enterprise_dashboard/routes/pages.py:383` — `@app.get("/live-pnl", response_class=HTMLResponse)`

## `/login`
### Backend registrations
- `tests/test_auth_comprehensive.py:167` — `/login`
- `core/auth/routes.py:220` — `/login`
- `core/auth/routes.py:225` — `/login`
- `core/enterprise_dashboard/routes/pages.py:128` — `/login`
### Source references
- `core/admin_portfolio_analyzer.py:25` — `"auth_url": "https://kite.zerodha.com/connect/login?v=3&api_key=DEMO_KEY",`
- `core/admin_portfolio_analyzer.py:52` — `"auth_url": "https://api.upstox.com/v2/login/authorization/dialog",`
- `core/admin_portfolio_analyzer.py:70` — `"auth_url": "https://api.icicidirect.com/api/v2/login",`
- `core/admin_portfolio_analyzer.py:79` — `"auth_url": "https://www.hdfcsec.com/login",`
- `core/admin_portfolio_analyzer.py:88` — `"auth_url": "https://neo.kotaksecurities.com/login",`
- `core/admin_portfolio_analyzer.py:97` — `"auth_url": "https://api.dhan.co/login",`
- `core/admin_portfolio_analyzer.py:115` — `"auth_url": "https://www.motilaloswal.com/login",`
- `core/admin_portfolio_analyzer.py:124` — `"auth_url": "https://www.sharekhan.com/login",`
- `core/admin_portfolio_analyzer.py:133` — `"auth_url": "https://developer.paytmmoney.com/tokens/login",`
- `core/admin_portfolio_analyzer.py:142` — `"auth_url": "https://www.mstock.com/api/login",`
- `core/constitution_evidence_data.py:106` — `add("SEC-02", "Dashboard auth routes: /login, /register, /change-password", "code_review", 0.3)`
- `scratch/test_all_app_routes.py:38` — `"/login",`
- `scratch/test_page_routes_only.py:29` — `"/login",`
- `tests/test_dashboard_integration.py:168` — `resp = client_basic.get("/login")`
- `tests/test_dashboard_integration.py:176` — `resp = client_basic.get("/login")`
- `tests/test_sso.py:41` — `assert "github.com/login/oauth/authorize" in gh["authorize_url"]`
- `tests/test_enterprise_dashboard_integration.py:236` — `assert "/login" in resp.headers.get("location", "")`
- `tests/test_enterprise_dashboard_integration.py:259` — `assert "/login" in resp.headers.get("location", "")`
- `tests/test_enterprise_dashboard_integration.py:281` — `assert "/login" in resp.headers.get("location", "")`
- `tests/test_enterprise_dashboard_integration.py:304` — `assert "/login" in resp.headers.get("location", "")`
- `tests/test_enterprise_dashboard.py:1992` — `"""GET / redirects to /login when no session cookie."""`
- `tests/test_enterprise_dashboard.py:2001` — `"""GET /login renders login page."""`
- `tests/test_enterprise_dashboard.py:2006` — `r = c.get("/login")`
- `tests/test_enterprise_dashboard.py:2222` — `"""GET /security with no session redirects to /login (unauthenticated)."""`
- `tests/test_enterprise_dashboard.py:2227` — `assert r.headers["location"] == "/login"`
- `tests/test_web_dashboard.py:98` — `resp = client.get("/login")`
- `tests/test_metrics_trend_routes.py:475` — `assert "/login" in resp.headers.get("location", "")`
- `tests/test_enterprise_dashboard_pages.py:441` — `assert "/login" in resp.headers.get("location", "")`
- `tests/test_enterprise_dashboard_pages.py:488` — `assert "/login" in resp.headers.get("location", "")`
- `tests/test_auth_comprehensive.py:163` — `"""Add a POST /login route to the app."""`

## `/logout`
### Backend registrations
- `archive/unrelated_modules/realestate/auth_service.py:406` — `/logout`
- `core/auth/routes.py:282` — `/logout`
- `core/auth/routes.py:283` — `/logout`
- `core/enterprise_dashboard/main.py:457` — `/logout`
- `core/enterprise_dashboard/main.py:458` — `/logout`
### Source references
- `scratch/test_all_app_routes.py:62` — `"/logout",`
- `scratch/test_all_app_routes.py:63` — `"/api/auth/logout",`
- `scratch/test_page_routes_only.py:49` — `"/logout",`
- `scratch/test_page_routes_only.py:50` — `"/api/auth/logout",`
- `tests/test_dashboard_comprehensive.py:591` — `assert "/api/auth/logout" in exempt`
- `tests/test_dashboard_comprehensive.py:1130` — `resp = c.post("/api/auth/logout")`
- `tests/test_auth_system.py:960` — `resp = test_client.post("/api/auth/logout", cookies=cookies)`
- `tests/test_auth_system.py:1269` — `assert "/api/auth/logout" in str(routes)`
- `templates/enterprise/intelligence.html:533` — `async function logout(){await apiFetch('/api/auth/logout',{method:'POST'});window.location.href='/login';}`
- `templates/enterprise/_nav.html:444` — `<a href="/logout" class="btn btn-ghost btn-sm" style="padding:0.3rem 0.55rem;font-size:0.75rem;white-space:nowrap;flex-shrink:0;" title="Sign Out">`
- `templates/enterprise/_nav.html:569` — `<a href="/logout" class="btn btn-danger btn-sm" style="padding:0.25rem 0.55rem;font-size:0.72rem;font-weight:700;text-decoration:none;border-radius:0.375rem;white-space:nowrap;">`
- `templates/enterprise/_nav.html:645` — `<a href="/logout" class="drawer-logout-btn">`
- `archive/unrelated_modules/realestate/auth_service.py:7` — `- Login/logout API endpoints`
- `archive/unrelated_modules/realestate/auth_service.py:406` — `@router.post("/logout")`
- `core/auth/routes.py:282` — `@router.get("/logout")`
- `core/auth/routes.py:283` — `@router.post("/logout")`
- `core/enterprise_dashboard/main.py:408` — `csrf_protection.exempt("/api/auth/logout")`
- `core/enterprise_dashboard/main.py:456` — `# -- Logout Redirect Route (/logout -> /api/auth/logout) --`
- `core/enterprise_dashboard/main.py:457` — `@app.get("/logout")`
- `core/enterprise_dashboard/main.py:458` — `@app.post("/logout")`
- `core/enterprise_dashboard/main.py:460` — `return RedirectResponse(url="/api/auth/logout", status_code=307)`

## `/margin-radar`
### Backend registrations
- `core/enterprise_dashboard/routes/pages.py:229` — `/margin-radar`
### Source references
- `scripts/generate_all_master_consolidated_documents.py:56` — `14. **Unified Multi-Broker Margin & Collateral Radar (`/margin-radar`)**: Consolidates available cash, collateral, used margin, and 75% peak margin warning shields across 11 brokers.`
- `scripts/generate_all_master_consolidated_documents.py:86` — `| Margin Radar | `http://localhost:8000/margin-radar` | Super Admin / Risk Mgr | Consolidated Multi-Broker Margin & 75% Warning |`
- `scripts/run_consolidated_full_system_verification.py:18` — `14. Unified Multi-Broker Margin & Collateral Radar with 75% Warning (/margin-radar)`
- `tests/test_all_ui_screens_and_navigation.py:61` — `("/margin-radar", "Margin Radar"),`
- `templates/enterprise/dashboard.html:552` — `<a href="/margin-radar" class="opb-quick-tile"><i class="fas fa-shield-alt" style="color:#f59e0b;"></i> Margins</a>`
- `templates/enterprise/margin_radar.html:106` — `const res = await fetch('/api/portfolio/margin-radar', {credentials: 'include'});`
- `templates/enterprise/_nav.html:465` — `<a href="/margin-radar" class="opb-ws-item {% if current_page == 'margin_radar' %}active{% endif %}"><span>🛡️ Broker Margin Matrix</span></a>`
- `templates/enterprise/_nav.html:606` — `<a href="/margin-radar" class="drawer-nav-item {% if current_page == 'margin_radar' %}active{% endif %}"><span style="font-size:1rem;margin-right:0.4rem;">🛡️</span> <span>Broker Margin Radar</span></a>`
- `core/enterprise_dashboard/routes/pages.py:229` — `@app.get("/margin-radar", response_class=HTMLResponse)`
- `core/enterprise_dashboard/routes/monitoring.py:514` — `@app.get("/api/portfolio/margin-radar")`

## `/metrics-trend`
### Backend registrations
- `core/enterprise_dashboard/routes/pages.py:455` — `/metrics-trend`
### Source references
- `scratch/test_all_app_routes.py:60` — `"/metrics-trend",`
- `tests/test_metrics_trend_routes.py:9` — `- /metrics-trend HTML page route (auth redirect + authenticated render)`
- `tests/test_metrics_trend_routes.py:472` — `resp = client.get("/metrics-trend", headers={"accept": "text/html"})`
- `tests/test_metrics_trend_routes.py:500` — `resp = c.get("/metrics-trend")`
- `templates/enterprise/_pwa_mobile_nav.html:65` — `<a href="/metrics-trend" class="nav-item{% if current_page == 'metrics_trend' %} active{% endif %}">`
- `templates/enterprise/_nav.html:490` — `<a href="/metrics-trend" class="opb-ws-item {% if current_page == 'metrics_trend' %}active{% endif %}"><span>📈 Success Metrics & Trends</span></a>`
- `templates/enterprise/_nav.html:617` — `<a href="/metrics-trend" class="drawer-nav-item {% if current_page == 'metrics_trend' %}active{% endif %}"><span style="font-size:1rem;margin-right:0.4rem;">📈</span> <span>Success Metrics & Trends</span></a>`
- `core/enterprise_dashboard/routes/pages.py:455` — `@app.get("/metrics-trend", response_class=HTMLResponse)`

## `/my-signals`
### Backend registrations
- `core/enterprise_dashboard/routes/pages.py:195` — `/my-signals`
### Source references
- `core/all_nse_scanner.py:613` — `{"text": "🏛️ Cockpit Dashboard", "url": f"{base_url}/my-signals"},`
- `scripts/generate_all_master_consolidated_documents.py:49` — `7. **Signal Tracker & Historical Accuracy Engine (`/admin/signals` & `/my-signals`)**: SQLite persistence tracking signal generation, targets, SL, win rates (100.0%), and personal user feeds.`
- `scripts/generate_all_master_consolidated_documents.py:83` — `| My Signals Feed | `http://localhost:8000/my-signals` | End-Users | Personal Delivered Signals Feed & Filters |`
- `scripts/run_consolidated_full_system_verification.py:11` — `7. Signal Tracker & Historical Accuracy Engine (/admin/signals & /my-signals)`
- `tests/test_phase14_url_and_notification_audit.py:62` — `url = build_action_url("/my-signals", cfg=cfg)`
- `tests/test_phase14_url_and_notification_audit.py:63` — `self.assertEqual(url, "https://gaurav-cockpit.servegame.com/my-signals")`
- `tests/test_phase14_url_and_notification_audit.py:107` — `self.assertIn("https://gaurav-cockpit.servegame.com/my-signals", html)`
- `tests/test_phase14_url_and_notification_audit.py:117` — `self.assertIn("https://gaurav-cockpit.servegame.com/my-signals", res_exec["alert_text"])`
- `tests/test_phase14_url_and_notification_audit.py:125` — `self.assertIn("https://gaurav-cockpit.servegame.com/my-signals", res_dash["alert_text"])`
- `tests/test_notification_url_production_contract.py:13` — `assert build_action_url("/my-signals", base_url="http://127.0.0.1:8000") == (`
- `tests/test_notification_url_production_contract.py:14` — `DEFAULT_PRODUCTION_URL + "/my-signals"`
- `tests/test_all_ui_screens_and_navigation.py:53` — `("/my-signals", "User Signals Screen"),`
- `tests/test_all_ui_screens_and_navigation.py:174` — `protected_routes = ["/", "/admin/config", "/admin/signals", "/admin/users", "/my-signals"]`
- `templates/enterprise/dashboard.html:545` — `<a href="/my-signals" class="opb-quick-tile"><i class="fas fa-bell" style="color:#38bdf8;"></i> Signals</a>`
- `templates/enterprise/pricing_plans.html:120` — `window.location.href = '/my-signals';`
- `templates/enterprise/profile.html:545` — `<a href="/my-signals" class="quick-nav-link">`
- `templates/enterprise/_nav.html:454` — `<a href="/my-signals" class="opb-nav-item {% if current_page in ('user_signals', 'my_signals', 'signals') %}active{% endif %}">⚡ Signals Radar</a>`
- `templates/enterprise/_nav.html:600` — `<a href="/my-signals" class="drawer-nav-item {% if current_page in ('user_signals', 'my_signals', 'signals') %}active{% endif %}"><span style="font-size:1.1rem;margin-right:0.4rem;">⚡</span> <span>Signals Radar</span></a>`
- `templates/enterprise/_nav.html:657` — `<a href="/my-signals" class="mobile-dock-tab {% if current_page in ('user_signals', 'my_signals', 'signals') %}active{% endif %}" title="Signals Radar">`
- `core/notifications/rich_signal_formatter.py:206` — `cockpit_url = build_action_url("/my-signals", base_url=base_url)`
- `core/telegram/callback_handler.py:41` — `f"Please review & place order at: {base_url}/my-signals"`
- `core/telegram/callback_handler.py:48` — `"alert_text": f"🏛️ Cockpit Dashboard: {base_url}/my-signals",`
- `core/enterprise_dashboard/routes/admin.py:149` — `{"text": "🏛️ Cockpit Dashboard", "url": f"{base_url}/my-signals"},`
- `core/enterprise_dashboard/routes/pages.py:195` — `@app.get("/my-signals", response_class=HTMLResponse)`

## `/observability`
### Backend registrations
- `core/enterprise_dashboard/routes/pages.py:479` — `/observability`
### Source references
- `scripts/constitution_scorecard.py:146` — `"core/observability/opentelemetry.py", weight=1.0),`
- `scripts/constitution_scorecard.py:224` — `"core/observability/opentelemetry.py", weight=1.0),`
- `scripts/gap_audit.py:30` — `results.append(("WS9 Observability", exists("core/observability.py")))`
- `scratch/test_all_app_routes.py:52` — `"/observability",`
- `scratch/test_page_routes_only.py:43` — `"/observability",`
- `tests/test_opentelemetry.py:2` — `Tests for core/observability/opentelemetry.py — OpenTelemetry integration.`
- `tests/test_all_ui_screens_and_navigation.py:64` — `("/observability", "Observability"),`
- `templates/enterprise/_nav.html:506` — `{% if can_view_logs %}<a href="/observability" class="opb-ws-item {% if current_page == 'observability' %}active{% endif %}"><span>📉 Observability & Tracing</span></a>{% endif %}`
- `templates/enterprise/_nav.html:627` — `{% if can_view_logs %}<a href="/observability" class="drawer-nav-item {% if current_page == 'observability' %}active{% endif %}"><span style="font-size:1rem;margin-right:0.4rem;">📉</span> <span>Observability & Tracing</span></a>{% endif %}`
- `core/observability/metrics.py:3` — `Moved from core/observability.py into the core/observability/ package.`
- `core/constitution/_evidence_main.py:1154` — `"core/observability/ subpackage isolates monitoring and telemetry concerns",`
- `core/constitution/evidence/lay_qgt_evidence.py:961` — `"Observability Added": "core/observability",`
- `core/enterprise_dashboard/routes/pages.py:479` — `@app.get("/observability", response_class=HTMLResponse)`

## `/options-chain`
### Backend registrations
- `core/enterprise_dashboard/routes/pages.py:333` — `/options-chain`
### Source references
- `scripts/generate_all_master_consolidated_documents.py:48` — `6. **Live Options Chain & Spot Calibration Engine (`/options-chain`)**: Real-time Nifty, Bank Nifty, and Fin Nifty options matrix with live spot LTP alignment, strike distance coloring, PCR, and Max Pain.`
- `scripts/run_consolidated_full_system_verification.py:10` — `6. Spot-Calibrated Options Chain Matrix (/options-chain)`
- `scratch/test_all_app_routes.py:46` — `"/options-chain",`
- `scratch/generate_final_deliverables.py:57` — `6. **Live Spot-Calibrated Options Chain (`/options-chain`)**:`
- `scratch/generate_final_deliverables.py:67` — `| Static options chain spot prices | Injected real-time spot resolver into `/options-chain` with dynamic strike distance calculations. | ✅ CLOSED & VERIFIED |`
- `scratch/test_page_routes_only.py:37` — `"/options-chain",`
- `tests/test_enterprise_dashboard_pages.py:7` — `- /options-chain HTML page route`
- `tests/test_enterprise_dashboard_pages.py:481` — `"""Test the /options-chain HTML page route."""`
- `tests/test_enterprise_dashboard_pages.py:485` — `resp = client.get("/options-chain", headers={"accept": "text/html"})`
- `tests/test_enterprise_dashboard_pages.py:492` — `resp = admin_client.get("/options-chain")`
- `tests/test_all_ui_screens_and_navigation.py:54` — `("/options-chain", "Options Chain Screen"),`
- `tests/test_all_ui_screens_and_navigation.py:165` — `resp = client.get("/api/options-chain?symbol=NIFTY")`
- `templates/enterprise/dashboard.html:547` — `<a href="/options-chain" class="opb-quick-tile"><i class="fas fa-list" style="color:#ec4899;"></i> Chains</a>`
- `templates/enterprise/profile.html:553` — `<a href="/options-chain" class="quick-nav-link">`
- `templates/enterprise/_nav.html:457` — `<a href="/options-chain" class="opb-nav-item {% if current_page in ('options_chain', 'sector_radar', 'fii_dii_radar', 'expiry_harvester', 'margin_radar') %}active{% endif %}">`
- `templates/enterprise/_nav.html:461` — `<a href="/options-chain" class="opb-ws-item {% if current_page == 'options_chain' %}active{% endif %}"><span>⚡ Options Chain Heatmap</span></a>`
- `templates/enterprise/_nav.html:605` — `<a href="/options-chain" class="drawer-nav-item {% if current_page == 'options_chain' %}active{% endif %}"><span style="font-size:1rem;margin-right:0.4rem;">⚡</span> <span>Options Chain Matrix</span></a>`
- `templates/enterprise/_nav.html:665` — `<a href="/options-chain" class="mobile-dock-tab {% if current_page == 'options_chain' %}active{% endif %}" title="Options Matrix">`
- `core/enterprise_dashboard/routes/pages.py:333` — `@app.get("/options-chain", response_class=HTMLResponse)`

## `/payoff-calculator`
### Backend registrations
- `core/enterprise_dashboard/routes/pages.py:359` — `/payoff-calculator`
### Source references
- `tests/test_payoff_calculator_routes.py:5` — `- POST /api/payoff-calculator/compute happy path (straddle-shaped legs)`
- `tests/test_payoff_calculator_routes.py:8` — `- /payoff-calculator HTML page route (auth redirect + authenticated render)`
- `tests/test_payoff_calculator_routes.py:73` — `the CSRF-protected /api/payoff-calculator/compute endpoint - mirrors the`
- `tests/test_payoff_calculator_routes.py:101` — `# ── POST /api/payoff-calculator/compute ───────────────────────────────────────`
- `tests/test_payoff_calculator_routes.py:112` — `resp = csrf_client.post("/api/payoff-calculator/compute", json={`
- `tests/test_payoff_calculator_routes.py:124` — `resp = csrf_client.post("/api/payoff-calculator/compute", json={`
- `tests/test_payoff_calculator_routes.py:134` — `resp = csrf_client.post("/api/payoff-calculator/compute", json={`
- `tests/test_payoff_calculator_routes.py:145` — `resp = csrf_client.post("/api/payoff-calculator/compute", json={"spot_price": 24500, "legs": []})`
- `tests/test_payoff_calculator_routes.py:152` — `resp = csrf_client.post("/api/payoff-calculator/compute", json={"spot_price": 100, "legs": legs})`
- `tests/test_payoff_calculator_routes.py:158` — `resp = csrf_client.post("/api/payoff-calculator/compute", json={`
- `tests/test_payoff_calculator_routes.py:167` — `resp = csrf_client.post("/api/payoff-calculator/compute", json={`
- `tests/test_payoff_calculator_routes.py:176` — `resp = csrf_client.post("/api/payoff-calculator/compute", json={`
- `tests/test_payoff_calculator_routes.py:183` — `resp = csrf_client.post("/api/payoff-calculator/compute", json={`
- `tests/test_payoff_calculator_routes.py:190` — `resp = csrf_client.post("/api/payoff-calculator/compute", json={"legs": _long_straddle_legs()})`
- `tests/test_payoff_calculator_routes.py:199` — `resp = client.get("/payoff-calculator", headers={"accept": "text/html"})`
- `tests/test_payoff_calculator_routes.py:223` — `resp = c.get("/payoff-calculator")`
- `templates/enterprise/payoff_calculator.html:170` — `const res = await fetch('/api/payoff-calculator/compute', {`
- `templates/enterprise/_nav.html:477` — `<a href="/payoff-calculator" class="opb-ws-item {% if current_page == 'payoff_calculator' %}active{% endif %}"><span>🧮 Multi-Leg Payoff Engine</span></a>`
- `templates/enterprise/_nav.html:615` — `<a href="/payoff-calculator" class="drawer-nav-item {% if current_page == 'payoff_calculator' %}active{% endif %}"><span style="font-size:1rem;margin-right:0.4rem;">🧮</span> <span>Payoff Calculator</span></a>`
- `core/enterprise_dashboard/routes/payoff_calculator.py:69` — `@app.post("/api/payoff-calculator/compute", tags=["PayoffCalculator"])`
- `core/enterprise_dashboard/routes/pages.py:359` — `@app.get("/payoff-calculator", response_class=HTMLResponse)`

## `/performance`
### Backend registrations
- `core/enterprise_dashboard/routes/pages.py:321` — `/performance`
### Source references
- `core/constitution_evidence_data.py:234` — `add("OBS-02", "Performance metrics module (core/performance_metrics.py) - trade win rate, Sharpe, drawdown", "code_review", 0.3)`
- `scripts/score_system.py:250` — `if _exists("core/performance_metrics.py"):`
- `scripts/constitution_scorecard.py:186` — `"core/performance_optimizer.py", weight=1.0),`
- `scratch/test_all_app_routes.py:43` — `"/performance",`
- `scratch/test_page_routes_only.py:34` — `"/performance",`
- `tests/test_health_checker.py:103` — `# overall_status may be FAIL due to DB/performance errors in test env`
- `tests/test_strategy_performance_tracker.py:1` — `"""Tests for core/strategy/performance_tracker.py — StrategyPerformanceTracker.`
- `tests/test_enterprise_dashboard_notifications.py:485` — `resp = client.get("/api/performance/comparison", headers={"accept": "application/json"})`
- `tests/test_enterprise_dashboard_notifications.py:492` — `resp = client.get("/api/performance/comparison", headers={"accept": "application/json"})`
- `tests/test_enterprise_dashboard_notifications.py:501` — `resp = client.get("/api/performance/comparison", headers={"accept": "application/json"})`
- `tests/test_enterprise_dashboard_notifications.py:510` — `resp = client.get("/api/performance/comparison", headers={"accept": "application/json"})`
- `tests/test_enterprise_dashboard_notifications.py:519` — `resp = client.get("/api/performance/comparison", headers={"accept": "application/json"})`
- `tests/test_enterprise_dashboard_notifications.py:527` — `resp = client.get("/api/performance/comparison", headers={"accept": "application/json"})`
- `tests/test_enterprise_dashboard_notifications.py:535` — `resp = client.get("/api/performance/comparison", headers={"accept": "application/json"})`
- `tests/test_enterprise_dashboard_notifications.py:540` — `resp = client.get("/api/performance/comparison", headers={"accept": "application/json"})`
- `tests/test_enterprise_dashboard_notifications.py:548` — `resp = client.get("/api/performance/comparison", headers={"accept": "application/json"})`
- `tests/test_enterprise_dashboard_notifications.py:555` — `resp = client.get("/api/performance/comparison?days=30", headers={"accept": "application/json"})`
- `tests/test_enterprise_dashboard_notifications.py:561` — `resp = client.get("/api/performance/comparison?mode=PAPER", headers={"accept": "application/json"})`
- `tests/test_enterprise_dashboard_notifications.py:567` — `resp = client.get("/api/performance/comparison?days=abc", headers={"accept": "application/json"})`
- `tests/test_enterprise_dashboard_notifications.py:590` — `resp = c.get("/api/performance/comparison", headers={"accept": "application/json"})`
- `tests/test_enterprise_dashboard_pages.py:4` — `- /api/system/performance endpoint`
- `tests/test_enterprise_dashboard_pages.py:6` — `- /performance HTML page route`
- `tests/test_enterprise_dashboard_pages.py:118` — `"""Test the /api/system/performance endpoint."""`
- `tests/test_enterprise_dashboard_pages.py:122` — `resp = client.get("/api/system/performance", headers={"accept": "application/json"})`
- `tests/test_enterprise_dashboard_pages.py:139` — `resp = client.get("/api/system/performance", headers={"accept": "application/json"})`
- `tests/test_enterprise_dashboard_pages.py:171` — `resp = c.get("/api/system/performance", headers={"accept": "application/json"})`
- `tests/test_enterprise_dashboard_pages.py:189` — `resp = c.get("/api/system/performance", headers={"accept": "application/json"})`
- `tests/test_enterprise_dashboard_pages.py:196` — `resp = client.get("/api/system/performance", headers={"accept": "application/json"})`
- `tests/test_enterprise_dashboard_pages.py:205` — `resp = client.get("/api/system/performance", headers={"accept": "application/json"})`
- `tests/test_enterprise_dashboard_pages.py:215` — `resp = client.get("/api/system/performance", headers={"accept": "application/json"})`

## `/pricing-plans`
### Backend registrations
- `core/enterprise_dashboard/routes/pages.py:269` — `/pricing-plans`
### Source references
- `scripts/generate_all_master_consolidated_documents.py:62` — `20. **100% Free Direct UPI QR Billing & Auto-Provisioning Engine (`/pricing-plans`)**: Zero-fee native NPCI UPI QR code generation and instant user quota activation.`
- `scripts/generate_all_master_consolidated_documents.py:90` — `| Pricing Plans | `http://localhost:8000/pricing-plans` | Clients / End-Users | 100% Free UPI QR Subscription & Auto-Unlock |`
- `scripts/generate_all_master_consolidated_documents.py:155` — `Visit [`http://localhost:8000/pricing-plans`](http://localhost:8000/pricing-plans) to select your plan. Scan the zero-fee UPI QR code with any UPI app (Google Pay, PhonePe, Paytm, BHIM) to immediately activate your account and quota.`
- `tests/test_web_page_permission_menu_contract.py:35` — `assert '{% if can_modify_config %}<a href="/pricing-plans"' in nav`
- `tests/test_all_ui_screens_and_navigation.py:52` — `("/pricing-plans", "Pricing Plans"),`
- `templates/enterprise/_nav.html:511` — `{% if can_modify_config %}<a href="/pricing-plans" class="opb-ws-item {% if current_page == 'pricing_plans' %}active{% endif %}"><span>💎 Subscription & Pricing Plans</span></a>{% endif %}`
- `templates/enterprise/_nav.html:633` — `{% if can_modify_config %}<a href="/pricing-plans" class="drawer-nav-item {% if current_page == 'pricing_plans' %}active{% endif %}"><span style="font-size:1rem;margin-right:0.4rem;">💎</span> <span>Subscription & Pricing</span></a>{% endif %}`
- `core/enterprise_dashboard/routes/pages.py:269` — `@app.get("/pricing-plans", response_class=HTMLResponse)`

## `/profile`
### Backend registrations
- `core/auth/routes.py:325` — `/profile`
- `core/auth/routes.py:349` — `/profile`
- `core/enterprise_dashboard/routes/pages.py:116` — `/profile`
### Source references
- `templates/enterprise/profile.html:609` — `const res = await fetch('/api/auth/profile', {`
- `templates/enterprise/profile.html:679` — `const res = await fetch('/api/auth/profile', {`
- `templates/enterprise/_nav.html:441` — `<a href="/profile" style="text-decoration:none;display:inline-flex;align-items:center;gap:0.4rem;color:var(--text-primary,#ffffff);font-size:0.8rem;font-weight:700;white-space:nowrap;flex-shrink:0;">`
- `templates/enterprise/_nav.html:640` — `<a href="/profile" class="drawer-nav-item {% if current_page == 'profile' %}active{% endif %}"><span style="font-size:1rem;margin-right:0.4rem;">👤</span> <span>Profile Settings</span></a>`
- `core/auth/routes.py:325` — `@router.get("/profile")`
- `core/auth/routes.py:349` — `@router.post("/profile")`
- `core/enterprise_dashboard/routes/pages.py:116` — `@app.get("/profile", response_class=HTMLResponse)`

## `/register`
### Backend registrations
- `archive/unrelated_modules/realestate/rera_compliance.py:349` — `/register`
- `archive/unrelated_modules/realestate/webhooks.py:348` — `/register`
- `core/auth/routes.py:137` — `/register`
- `core/enterprise_dashboard/routes/pages.py:137` — `/register`
### Source references
- `core/constitution_evidence_data.py:106` — `add("SEC-02", "Dashboard auth routes: /login, /register, /change-password", "code_review", 0.3)`
- `scripts/register_constitution_evidence.py:10` — `python scripts/register_constitution_evidence.py`
- `scratch/test_all_app_routes.py:39` — `"/register",`
- `scratch/test_page_routes_only.py:30` — `"/register",`
- `tests/test_enterprise_dashboard.py:2011` — `"""GET /register renders register page."""`
- `tests/test_enterprise_dashboard.py:2016` — `r = c.get("/register")`
- `tests/test_auth_register.py:1` — `"""Tests for the /api/auth/register endpoint with rate limiting."""`
- `tests/test_auth_register.py:52` — `"""Tests for POST /api/auth/register."""`
- `tests/test_auth_register.py:57` — `"/api/auth/register",`
- `tests/test_auth_register.py:67` — `"/api/auth/register",`
- `tests/test_auth_register.py:71` — `"/api/auth/register",`
- `tests/test_auth_register.py:80` — `"/api/auth/register",`
- `tests/test_auth_register.py:89` — `"/api/auth/register",`
- `tests/test_auth_register.py:97` — `"/api/auth/register",`
- `tests/test_auth_register.py:105` — `"/api/auth/register",`
- `tests/test_auth_register.py:116` — `"/api/auth/register",`
- `tests/test_auth_register.py:133` — `"/api/auth/register",`
- `tests/test_auth_register.py:141` — `"/api/auth/register",`
- `tests/test_auth_register.py:150` — `"/api/auth/register",`
- `tests/test_auth_register.py:160` — `"/api/auth/register",`
- `tests/test_auth_register.py:172` — `"/api/auth/register",`
- `tests/test_auth_register.py:178` — `"/api/auth/register",`
- `tests/test_auth_register.py:185` — `"/api/auth/register",`
- `tests/test_auth_register.py:195` — `"/api/auth/register",`
- `tests/test_all_ui_screens_and_navigation.py:50` — `("/register", "Registration Page"),`
- `templates/enterprise/login.html:435` — `Don't have an account? <a href="/register">Create an account</a>`
- `templates/enterprise/register.html:323` — `const res = await fetch('/api/auth/register', {`
- `archive/unrelated_modules/realestate/rera_compliance.py:349` — `@router.post("/register")`
- `archive/unrelated_modules/realestate/webhooks.py:348` — `@router.post("/register")`
- `archive/unrelated_modules/tests/test_realestate_rera.py:265` — `"/api/realestate/rera/register",`

## `/sector-radar`
### Backend registrations
- `core/enterprise_dashboard/routes/pages.py:207` — `/sector-radar`
### Source references
- `scripts/generate_all_master_consolidated_documents.py:51` — `9. **Sector Rotation & Smart Money Inflow Radar (`/sector-radar`)**: 12 NSE sectors mapped across Leading, Improving, Weakening, and Lagging quadrants with an automatic +5 score boost for leading stocks.`
- `scripts/generate_all_master_consolidated_documents.py:84` — `| Sector Rotation Radar | `http://localhost:8000/sector-radar` | All Users | 12 NSE Sectors Relative Strength Quadrants |`
- `scripts/run_consolidated_full_system_verification.py:13` — `9. Sector Rotation & Smart Money Inflow Radar (/sector-radar with +5 boost)`
- `tests/test_all_ui_screens_and_navigation.py:60` — `("/sector-radar", "Sector Radar"),`
- `templates/enterprise/dashboard.html:549` — `<a href="/sector-radar" class="opb-quick-tile"><i class="fas fa-compass" style="color:#f59e0b;"></i> Sector</a>`
- `templates/enterprise/sector_radar.html:109` — `const res = await fetch('/api/market/sector-radar', {credentials: 'include'});`
- `templates/enterprise/_nav.html:462` — `<a href="/sector-radar" class="opb-ws-item {% if current_page == 'sector_radar' %}active{% endif %}"><span>📡 Sector Money Flow</span></a>`
- `templates/enterprise/_nav.html:607` — `<a href="/sector-radar" class="drawer-nav-item {% if current_page == 'sector_radar' %}active{% endif %}"><span style="font-size:1rem;margin-right:0.4rem;">📡</span> <span>Sector Radar Flow</span></a>`
- `core/enterprise_dashboard/routes/pages.py:207` — `@app.get("/sector-radar", response_class=HTMLResponse)`
- `core/enterprise_dashboard/routes/monitoring.py:398` — `@app.get("/api/market/sector-radar")`

## `/security`
### Backend registrations
- `core/enterprise_dashboard/routes/pages.py:504` — `/security`
### Source references
- `core/presentation_generator.py:549` — `["core/security_auditor.py", "97%"],`
- `core/security_auditor.py:238` — `self._persist_path = Path("json/security_audit_history.json")`
- `scripts/constitution_scorecard.py:84` — `"core/security_auditor.py", weight=1.5),`
- `scripts/constitution_scorecard.py:130` — `"core/security_auditor.py", weight=1.0),`
- `scripts/constitution_scorecard.py:184` — `"core/security_auditor.py", weight=1.0),`
- `scripts/run_coverage_heatmap.py:82` — `"core/security_auditor.py",`
- `scratch/test_all_app_routes.py:53` — `"/security",`
- `scratch/test_page_routes_only.py:44` — `"/security",`
- `tests/test_security_auditor.py:1` — `"""Tests for core/security_auditor.py — Security Auditor module."""`
- `tests/test_enterprise_dashboard.py:2222` — `"""GET /security with no session redirects to /login (unauthenticated)."""`
- `tests/test_enterprise_dashboard.py:2225` — `r = c.get("/security")`
- `tests/test_enterprise_dashboard.py:2230` — `"""Regression: /security's own APIs (/api/auth/users, /api/auth/audit) already`
- `tests/test_enterprise_dashboard.py:2240` — `r = c.get("/security")`
- `tests/test_enterprise_dashboard.py:2244` — `"""GET /security with an admin session renders 200 OK."""`
- `tests/test_enterprise_dashboard.py:2248` — `r = c.get("/security")`
- `tests/test_all_ui_screens_and_navigation.py:71` — `("/security", "Security Auditor"),`
- `tests/test_security_feeds.py:1` — `"""Tests for core/integrations/security_feeds.py — Security Feed Reporter.`
- `templates/enterprise/intelligence.html:648` — `const data = await apiFetch('/api/intelligence/security/scan');`
- `templates/enterprise/_nav.html:505` — `{% if can_view_logs %}<a href="/security" class="opb-ws-item {% if current_page == 'security' %}active{% endif %}"><span>🔒 Security Architecture</span></a>{% endif %}`
- `templates/enterprise/_nav.html:626` — `{% if can_view_logs %}<a href="/security" class="drawer-nav-item {% if current_page == 'security' %}active{% endif %}"><span style="font-size:1rem;margin-right:0.4rem;">🔒</span> <span>Security Shield & Auth</span></a>{% endif %}`
- `core/constitution/evidence/lay_qgt_evidence.py:957` — `"Security Reviewed": "core/security_auditor.py",`
- `core/constitution/evidence/prn_ast_evidence.py:1073` — `"ROL-05": ("Security", "core/security_auditor.py"),`
- `core/enterprise_dashboard/routes/intelligence_bi.py:103` — `@app.post("/api/intelligence/security/scan")`
- `core/enterprise_dashboard/routes/intelligence_bi.py:104` — `@app.get("/api/intelligence/security/scan")`
- `core/enterprise_dashboard/routes/intelligence_bi.py:122` — `@app.get("/api/intelligence/security/stats")`
- `core/enterprise_dashboard/routes/intelligence_bi.py:132` — `@app.get("/api/intelligence/security/last-report")`
- `core/enterprise_dashboard/routes/pages.py:504` — `@app.get("/security", response_class=HTMLResponse)`
- `core/domains/fixed_income/models.py:91` — `"""Generic fixed income bond/security representation.`
- `core/domains/fixed_income/models.py:268` — `bond: The bond/security held`

## `/strategy-sandbox`
### Backend registrations
- `core/enterprise_dashboard/routes/pages.py:239` — `/strategy-sandbox`
### Source references
- `scripts/generate_all_master_consolidated_documents.py:57` — `15. **Interactive Strategy Sandbox & Backtest Studio (`/strategy-sandbox`)**: Real-time strategy parameter tuning sliders with instant 1-year backtest simulation.`
- `scripts/generate_all_master_consolidated_documents.py:87` — `| Strategy Sandbox | `http://localhost:8000/strategy-sandbox` | Quant Analysts / Users | Interactive Parameter Tuning Backtest Studio |`
- `scripts/run_consolidated_full_system_verification.py:19` — `15. Strategy Sandbox & Visual Backtesting Studio (/strategy-sandbox)`
- `tests/test_all_ui_screens_and_navigation.py:58` — `("/strategy-sandbox", "Strategy Sandbox"),`
- `templates/enterprise/dashboard.html:267` — `<a href="/strategy-sandbox" class="opb-tab" style="padding:0.35rem 0.75rem;font-size:0.75rem;color:var(--accent-color);border-color:var(--accent-color);" title="Launch Sandbox Studio">`
- `templates/enterprise/dashboard.html:283` — `<a href="/strategy-sandbox" class="btn btn-primary btn-sm" title="Strategy Lab" style="padding:0.3rem 0.6rem;font-size:0.75rem;">`
- `templates/enterprise/dashboard.html:550` — `<a href="/strategy-sandbox" class="opb-quick-tile"><i class="fas fa-flask" style="color:#c084fc;"></i> Sandbox</a>`
- `templates/enterprise/_nav.html:483` — `<a href="/strategy-sandbox" class="opb-nav-item {% if current_page in ('strategy_sandbox', 'intelligence', 'ab_tester', 'metrics_trend') %}active{% endif %}">`
- `templates/enterprise/_nav.html:487` — `<a href="/strategy-sandbox" class="opb-ws-item {% if current_page == 'strategy_sandbox' %}active{% endif %}"><span>🧪 Strategy Sandbox Lab</span></a>`
- `templates/enterprise/_nav.html:601` — `<a href="/strategy-sandbox" class="drawer-nav-item {% if current_page == 'strategy_sandbox' %}active{% endif %}"><span style="font-size:1.1rem;margin-right:0.4rem;">🧪</span> <span>Strategy Sandbox Lab</span></a>`
- `core/enterprise_dashboard/routes/pages.py:239` — `@app.get("/strategy-sandbox", response_class=HTMLResponse)`

## `/system-health`
### Backend registrations
- `core/enterprise_dashboard/routes/pages.py:395` — `/system-health`
### Source references
- `scratch/test_all_app_routes.py:61` — `"/system-health",`
- `tests/test_enterprise_dashboard_integration.py:6` — `- /system-health HTML page route`
- `tests/test_enterprise_dashboard_integration.py:270` — `"""Test the /system-health HTML page route."""`
- `tests/test_enterprise_dashboard_integration.py:278` — `resp = c.get("/system-health", headers={"accept": "text/html"})`
- `tests/test_enterprise_dashboard_integration.py:284` — `resp = admin_client.get("/system-health")`
- `tests/test_all_ui_screens_and_navigation.py:65` — `("/system-health", "System Health"),`
- `templates/enterprise/_nav.html:507` — `{% if can_view_state %}<a href="/system-health" class="opb-ws-item {% if current_page == 'system_health' %}active{% endif %}"><span>🏥 System Health & Telemetry</span></a>{% endif %}`
- `templates/enterprise/_nav.html:628` — `{% if can_view_state %}<a href="/system-health" class="drawer-nav-item {% if current_page == 'system_health' %}active{% endif %}"><span style="font-size:1rem;margin-right:0.4rem;">🏥</span> <span>System Health & Telemetry</span></a>{% endif %}`
- `core/enterprise_dashboard/routes/pages.py:395` — `@app.get("/system-health", response_class=HTMLResponse)`

## `/trade-copier`
### Backend registrations
- `core/enterprise_dashboard/routes/pages.py:217` — `/trade-copier`
### Source references
- `scripts/generate_all_master_consolidated_documents.py:54` — `12. **Master Multi-Account Trade Copier (`/trade-copier`)**: One-click master order trigger with automatic parallel prorating and sub-second replication across connected client broker accounts.`
- `scripts/generate_all_master_consolidated_documents.py:85` — `| Trade Copier | `http://localhost:8000/trade-copier` | Super Admin / Fund Mgr | Multi-Broker Parallel Trade Replication |`
- `scripts/run_consolidated_full_system_verification.py:16` — `12. Master Multi-Account Trade Copier (/trade-copier)`
- `tests/test_web_page_permission_menu_contract.py:19` — `assert nav.count('{% if can_manage_brokers %}<a href="/trade-copier"') == 2`
- `tests/test_all_ui_screens_and_navigation.py:57` — `("/trade-copier", "Trade Copier Screen"),`
- `templates/enterprise/_nav.html:476` — `{% if can_manage_brokers %}<a href="/trade-copier" class="opb-ws-item {% if current_page == 'trade_copier' %}active{% endif %}"><span>⚡ Multi-Account Copier</span></a>{% endif %}`
- `templates/enterprise/_nav.html:614` — `{% if can_manage_brokers %}<a href="/trade-copier" class="drawer-nav-item {% if current_page == 'trade_copier' %}active{% endif %}"><span style="font-size:1rem;margin-right:0.4rem;">⚡</span> <span>Trade Copier</span></a>{% endif %}`
- `core/enterprise_dashboard/routes/pages.py:217` — `@app.get("/trade-copier", response_class=HTMLResponse)`

## `/trade-journal`
### Backend registrations
- `core/enterprise_dashboard/routes/pages.py:371` — `/trade-journal`
### Source references
- `scratch/test_all_app_routes.py:44` — `"/trade-journal",`
- `scratch/test_page_routes_only.py:35` — `"/trade-journal",`
- `tests/test_enterprise_dashboard_integration.py:4` — `- /trade-journal HTML page route`
- `tests/test_enterprise_dashboard_integration.py:8` — `- /api/trade-journal endpoint`
- `tests/test_enterprise_dashboard_integration.py:225` — `"""Test the /trade-journal HTML page route."""`
- `tests/test_enterprise_dashboard_integration.py:233` — `resp = c.get("/trade-journal", headers={"accept": "text/html"})`
- `tests/test_enterprise_dashboard_integration.py:239` — `resp = admin_client.get("/trade-journal")`
- `tests/test_enterprise_dashboard_integration.py:321` — `"""Test the /api/trade-journal endpoint."""`
- `tests/test_enterprise_dashboard_integration.py:324` — `resp = client.get("/api/trade-journal", headers={"accept": "application/json"})`
- `tests/test_enterprise_dashboard_integration.py:333` — `resp = client.get("/api/trade-journal", headers={"accept": "application/json"})`
- `tests/test_enterprise_dashboard_integration.py:342` — `resp = client.get("/api/trade-journal?n=2", headers={"accept": "application/json"})`
- `tests/test_all_ui_screens_and_navigation.py:56` — `("/trade-journal", "Trade Journal Screen"),`
- `templates/enterprise/dashboard.html:548` — `<a href="/trade-journal" class="opb-quick-tile"><i class="fas fa-book" style="color:#10b981;"></i> Journal</a>`
- `templates/enterprise/_pwa_mobile_nav.html:61` — `<a href="/trade-journal" class="nav-item{% if current_page == 'trade_journal' %} active{% endif %}">`
- `templates/enterprise/trade_journal.html:71` — `const data = await apiFetch('/api/trade-journal');`
- `templates/enterprise/_nav.html:475` — `<a href="/trade-journal" class="opb-ws-item {% if current_page == 'trade_journal' %}active{% endif %}"><span>📔 Trade Journal & Audit</span></a>`
- `templates/enterprise/_nav.html:613` — `<a href="/trade-journal" class="drawer-nav-item {% if current_page == 'trade_journal' %}active{% endif %}"><span style="font-size:1rem;margin-right:0.4rem;">📔</span> <span>Trade Journal</span></a>`
- `core/enterprise_dashboard/main.py:1180` — `/api/system/performance, /api/system/trades, and /api/trade-journal`
- `core/enterprise_dashboard/routes/pages.py:371` — `@app.get("/trade-journal", response_class=HTMLResponse)`
- `core/enterprise_dashboard/routes/system.py:742` — `@app.get("/api/trade-journal")`

## `/whats-new`
### Backend registrations
- `core/enterprise_dashboard/routes/pages.py:345` — `/whats-new`
### Source references
- `tests/test_web_page_permission_menu_contract.py:37` — `assert '{% if can_view_logs %}<a href="/whats-new"' in nav`
- `tests/test_whats_new.py:6` — `- /whats-new HTML page route (auth redirect + authenticated render)`
- `tests/test_whats_new.py:129` — `# ── /whats-new HTML page route ────────────────────────────────────────────────`
- `tests/test_whats_new.py:154` — `resp = client.get("/whats-new", headers={"accept": "text/html"})`
- `tests/test_whats_new.py:178` — `resp = c.get("/whats-new")`
- `templates/enterprise/_nav.html:512` — `{% if can_view_logs %}<a href="/whats-new" class="opb-ws-item {% if current_page == 'whats_new' %}active{% endif %}"><span>🚀 What's New & Changelog</span></a>{% endif %}`
- `templates/enterprise/_nav.html:634` — `{% if can_view_logs %}<a href="/whats-new" class="drawer-nav-item {% if current_page == 'whats_new' %}active{% endif %}"><span style="font-size:1rem;margin-right:0.4rem;">🚀</span> <span>Release Notes & What's New</span></a>{% endif %}`
- `core/enterprise_dashboard/routes/pages.py:345` — `@app.get("/whats-new", response_class=HTMLResponse)`
