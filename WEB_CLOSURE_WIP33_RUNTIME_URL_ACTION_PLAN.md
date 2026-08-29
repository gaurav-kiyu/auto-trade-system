# OPB WEB CLOSURE WIP33 — Runtime URL Action Plan

High-confidence candidates from WIP32: 48
Clear URL-construction candidates: 1
Input/config/reference candidates: 47

## Clear URL-construction candidates
- `core/auth/routes.py:1089` — `# this deployment. Do not derive it from request.base_url because that`

## Input/config/reference candidates — DO NOT AUTO-REWRITE
- `launcher.py:697` — `webbrowser.open(f"http://localhost:{port}/")`
- `launcher.py:709` — `f"http://localhost:{port}/ manually once it's ready, or check "`
- `core/ai_engine.py:209` — `base = ai_cfg.api_base_url or "http://localhost:11434"`
- `json/index_config.defaults.json:1301` — `"otlp_endpoint": "http://localhost:4317",`
- `json/index_config.defaults.json:1309` — `"zipkin_endpoint": "http://localhost:9411/api/v2/spans",`
- `json/config.template.json:1511` — `"otlp_endpoint": "http://localhost:4317",`
- `json/config.template.json:1767` — `"zipkin_endpoint": "http://localhost:9411/api/v2/spans"`
- `json/config.json:715` — `"PUBLIC_BASE_URL": "https://gaurav-cockpit.servegame.com",`
- `json/config.json:1541` — `"otlp_endpoint": "http://localhost:4317",`
- `json/config.json:1773` — `"zipkin_endpoint": "http://localhost:9411/api/v2/spans",`
- `scripts/generate_master_pptx.py:484` — `"Enterprise Dashboard: http://localhost:8765 (enable in config.json)",`
- `scripts/generate_all_master_consolidated_documents.py:69` — `Accessible at `http://localhost:8000/admin/users`:`
- `scripts/generate_all_master_consolidated_documents.py:79` — `| `open_app.bat` | `http://localhost:8000` | All Users / Operators | Main Enterprise Trading & Analytics Dashboard |`
- `scripts/generate_all_master_consolidated_documents.py:80` — `| `open_admin.bat` | `http://localhost:8000/admin/config` | Super Admin / Admin | Live Configuration Editor & Notification Controls |`
- `scripts/generate_all_master_consolidated_documents.py:81` — `| Super Admin Users | `http://localhost:8000/admin/users` | Super Admin | User Signal Permissions, Category Subscriptions & Quotas |`
- `scripts/generate_all_master_consolidated_documents.py:82` — `| Signal Accuracy Hub | `http://localhost:8000/admin/signals` | Super Admin | Historical Signal Performance & Category Win Rates |`
- `scripts/generate_all_master_consolidated_documents.py:83` — `| My Signals Feed | `http://localhost:8000/my-signals` | End-Users | Personal Delivered Signals Feed & Filters |`
- `scripts/generate_all_master_consolidated_documents.py:84` — `| Sector Rotation Radar | `http://localhost:8000/sector-radar` | All Users | 12 NSE Sectors Relative Strength Quadrants |`
- `scripts/generate_all_master_consolidated_documents.py:85` — `| Trade Copier | `http://localhost:8000/trade-copier` | Super Admin / Fund Mgr | Multi-Broker Parallel Trade Replication |`
- `scripts/generate_all_master_consolidated_documents.py:86` — `| Margin Radar | `http://localhost:8000/margin-radar` | Super Admin / Risk Mgr | Consolidated Multi-Broker Margin & 75% Warning |`
- `scripts/generate_all_master_consolidated_documents.py:87` — `| Strategy Sandbox | `http://localhost:8000/strategy-sandbox` | Quant Analysts / Users | Interactive Parameter Tuning Backtest Studio |`
- `scripts/generate_all_master_consolidated_documents.py:88` — `| FII / DII Radar | `http://localhost:8000/fii-dii-radar` | Super Admin / Traders | Participant-Wise Net Positioning & Trap Alerts |`
- `scripts/generate_all_master_consolidated_documents.py:89` — `| 0DTE Harvester | `http://localhost:8000/expiry-harvester` | Options Traders | Automated Expiry Straddle Delta Harvester |`
- `scripts/generate_all_master_consolidated_documents.py:90` — `| Pricing Plans | `http://localhost:8000/pricing-plans` | Clients / End-Users | 100% Free UPI QR Subscription & Auto-Unlock |`
- `scripts/generate_all_master_consolidated_documents.py:91` — `| Kill Switch | `http://localhost:8000/admin/kill-switch` | Super Admin / Risk Mgr | Instant Global Trading Emergency Halt |`
- `scripts/generate_all_master_consolidated_documents.py:155` — `Visit [`http://localhost:8000/pricing-plans`](http://localhost:8000/pricing-plans) to select your plan. Scan the zero-fee UPI QR code with any UPI app (Google Pay, PhonePe, Paytm, BHIM) to immediately activate your account and quota.`
- `scripts/generate_pptx.py:386` — `("Web Dashboard", "Enable web_dashboard_enabled: true in config.json\nAccess: http://localhost:8765 (FastAPI + RBAC)", RED),`
- `scripts/docker_healthcheck.py:49` — `"http://127.0.0.1:8765/api/system/health/docker", timeout=5`
- `.tmp/opb_manual_cfg_6_478ydc.json:1511` — `"otlp_endpoint": "http://localhost:4317",`
- `.tmp/opb_manual_cfg_6_478ydc.json:1767` — `"zipkin_endpoint": "http://localhost:9411/api/v2/spans",`
- `.tmp/opb_manual_cfg_jsaa8xre.json:1511` — `"otlp_endpoint": "http://localhost:4317",`
- `.tmp/opb_manual_cfg_jsaa8xre.json:1767` — `"zipkin_endpoint": "http://localhost:9411/api/v2/spans",`
- `.tmp/opb_manual_cfg_d5nh58h4.json:1511` — `"otlp_endpoint": "http://localhost:4317",`
- `.tmp/opb_manual_cfg_d5nh58h4.json:1767` — `"zipkin_endpoint": "http://localhost:9411/api/v2/spans",`
- `archive/unrelated_modules/scripts/seed_realestate_data.py:156` — `api_base: str = "http://localhost:8766",`
- `archive/unrelated_modules/scripts/seed_realestate_data.py:241` — `parser.add_argument("--api", type=str, default="http://localhost:8766", help="API base URL")`
- `archive/unrelated_modules/scripts/launch_realestate.py:151` — `host_url = f"http://localhost:{port}"`
- `archive/unrelated_modules/scripts/realestate_synthetic_monitor.py:213` — `default=os.environ.get("RE_URL", "http://localhost:8765"),`
- `archive/unrelated_modules/scripts/realestate_synthetic_monitor.py:214` — `help="Base URL of the platform (default: http://localhost:8765)",`
- `archive/unrelated_modules/e2e/realestate-flows.spec.js:10` — `const BASE_URL = process.env.BASE_URL || 'http://localhost:8765';`
- `core/notifications/url_resolver.py:20` — `DEFAULT_DEV_URL = "http://localhost:8000"`
- `core/notifications/url_resolver.py:132` — `- Development -> http://localhost:8000`
- `core/observability/opentelemetry.py:79` — `- otlp_endpoint (str): OTLP gRPC endpoint (default "http://localhost:4317").`
- `core/observability/opentelemetry.py:300` — `otlp_endpoint = cfg.get("otlp_endpoint", "http://localhost:4317")`
- `core/observability/opentelemetry.py:381` — `- zipkin_endpoint (str): Zipkin HTTP endpoint (default "http://localhost:9411/api/v2/spans").`
- `core/observability/opentelemetry.py:390` — `zipkin_endpoint = cfg.get("zipkin_endpoint", "http://localhost:9411/api/v2/spans")`
- `core/enterprise_dashboard/models.py:168` — `def __init__(self, base_url: str = "http://127.0.0.1:8000", timeout: float = 2.0) -> None:`

## Repair rule
Only clear runtime URL-construction sites should be changed to call the canonical public URL resolver.
User-supplied URL fields, environment-variable reads, deployment config, tests and fixtures must remain inputs/configuration and must not be replaced by resolver calls.