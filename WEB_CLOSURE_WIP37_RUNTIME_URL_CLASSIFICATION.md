# OPB WEB CLOSURE WIP37 — Runtime URL Classification

Fresh WIP36 findings: 48
Likely externally visible URL paths: 10
Likely configuration/internal references: 38

## Likely externally visible
- **external-url-construction** `core/notifications/rich_signal_formatter.py:206` — `cockpit_url = build_action_url("/my-signals", base_url=base_url)`
- **external-url-construction** `core/auth/sso.py:17` — `redirect_uri="https://example.com/api/auth/sso/callback",`
- **external-url-construction** `core/auth/sso.py:167` — `redirect_uri=cfg.get("sso_redirect_uri", ""),`
- **external-url-construction** `core/auth/sso.py:199` — `_log.warning("[SSO] SSO not configured: missing client_id or redirect_uri")`
- **external-url-construction** `core/auth/sso.py:212` — `redirect_uri=self._config.redirect_uri,`
- **external-url-construction** `core/auth/sso.py:258` — `redirect_uri=self._config.redirect_uri,`
- **external-url-construction** `core/auth/sso.py:431` — `issues.append("Missing sso_redirect_uri")`
- **external-url-construction** `core/auth/routes.py:1081` — `sso_redirect_uri = build_action_url(`
- **external-url-construction** `core/auth/routes.py:1085` — `app_config["sso_redirect_uri"] = sso_redirect_uri`
- **external-url-construction** `core/auth/routes.py:1093` — `sso._config.redirect_uri = build_action_url(`

## Configuration/internal or ambiguous — no automatic rewrite
- **external-url-construction** `core/ai_engine.py:49` — `"AI_ENGINE_API_BASE_URL": "",`
- **external-url-construction** `core/ai_engine.py:140` — `api_base_url=str(merged.get("AI_ENGINE_API_BASE_URL") or "").strip(),`
- **localhost** `core/ai_engine.py:209` — `base = ai_cfg.api_base_url or "http://localhost:11434"`
- **external-url-construction** `core/all_nse_scanner.py:442` — `base_url = get_public_base_url(self._cfg)`
- **external-url-construction** `core/all_nse_scanner.py:464` — `base_url=base_url,`
- **production-host** `core/notifications/url_resolver.py:19` — `DEFAULT_PRODUCTION_URL = "https://gaurav-cockpit.servegame.com"`
- **localhost** `core/notifications/url_resolver.py:20` — `DEFAULT_DEV_URL = "http://localhost:8000"`
- **external-url-construction** `core/notifications/url_resolver.py:96` — `"PUBLIC_BASE_URL",`
- **external-url-construction** `core/notifications/url_resolver.py:97` — `"APP_BASE_URL",`
- **external-url-construction** `core/notifications/url_resolver.py:98` — `"EXTERNAL_BASE_URL",`
- **external-url-construction** `core/notifications/url_resolver.py:99` — `"OPBUYING_PUBLIC_BASE_URL",`
- **external-url-construction** `core/notifications/url_resolver.py:110` — `val = active_cfg.get("PUBLIC_BASE_URL")`
- **production-host** `core/notifications/url_resolver.py:131` — `- Production -> https://gaurav-cockpit.servegame.com`
- **localhost** `core/notifications/url_resolver.py:132` — `- Development -> http://localhost:8000`
- **external-url-construction** `core/notifications/url_resolver.py:159` — `for env_key in ("PUBLIC_BASE_URL", "APP_BASE_URL", "EXTERNAL_BASE_URL", "PUBLIC_URL", "OPBUYING_PUBLIC_BASE_URL"):`
- **external-url-construction** `core/notifications/url_resolver.py:171` — `for cfg_key in ("PUBLIC_BASE_URL", "APP_BASE_URL", "EXTERNAL_BASE_URL", "PUBLIC_URL"):`
- **external-url-construction** `core/notifications/url_resolver.py:181` — `for cfg_key in ("PUBLIC_BASE_URL", "APP_BASE_URL", "EXTERNAL_BASE_URL", "PUBLIC_URL"):`
- **external-url-construction** `core/notifications/__init__.py:21` — `"get_public_base_url",`
- **request.base_url** `core/auth/routes.py:1089` — `# this deployment. Do not derive it from request.base_url because that`
- **localhost** `core/observability/opentelemetry.py:79` — `- otlp_endpoint (str): OTLP gRPC endpoint (default "http://localhost:4317").`
- **localhost** `core/observability/opentelemetry.py:300` — `otlp_endpoint = cfg.get("otlp_endpoint", "http://localhost:4317")`
- **localhost** `core/observability/opentelemetry.py:381` — `- zipkin_endpoint (str): Zipkin HTTP endpoint (default "http://localhost:9411/api/v2/spans").`
- **localhost** `core/observability/opentelemetry.py:390` — `zipkin_endpoint = cfg.get("zipkin_endpoint", "http://localhost:9411/api/v2/spans")`
- **loopback** `core/enterprise_dashboard/models.py:168` — `def __init__(self, base_url: str = "http://127.0.0.1:8000", timeout: float = 2.0) -> None:`
- **external-url-construction** `core/enterprise_dashboard/models.py:169` — `self._base_url = base_url.rstrip("/")`
- **external-url-construction** `core/enterprise_dashboard/main.py:789` — `if key in {"PUBLIC_BASE_URL", "PUBLIC_BASE_URL_ADMIN_OVERRIDE"}:`
- **external-url-construction** `core/enterprise_dashboard/main.py:892` — `if any(k in applied for k in ("PUBLIC_BASE_URL", "PUBLIC_BASE_URL_ADMIN_OVERRIDE")):`
- **external-url-construction** `core/telegram/callback_handler.py:18` — `base_url = get_public_base_url()`
- **external-url-construction** `core/enterprise_dashboard/routes/admin.py:79` — `base_url = get_public_base_url(cfg)`
- **external-url-construction** `core/enterprise_dashboard/routes/admin.py:97` — `base_url=base_url,`
- **external-url-construction** `core/enterprise_dashboard/routes/admin.py:292` — `"public_url": {`
- **external-url-construction** `index_app/index_trader.py:1195` — `_dash_notifier = DashboardNotifier(base_url=_dash_url)`
- **external-url-construction** `infrastructure/adapters/brokers/groww/adapter.py:59` — `_BASE_URL = "https://api.groww.in/v1"`
- **external-url-construction** `infrastructure/adapters/brokers/mstock/adapter.py:58` — `_BASE_URL = "https://api.mstock.trade/openapi/typea"`
- **external-url-construction** `infrastructure/adapters/brokers/icicidirect/adapter.py:70` — `_BASE_URL = "https://api.icicidirect.com/breezeapi/api/v1"`
- **external-url-construction** `infrastructure/adapters/brokers/dhan/adapter.py:70` — `_BASE_URL = "https://api.dhan.co/v2"`
- **external-url-construction** `infrastructure/adapters/brokers/upstox/adapter.py:60` — `_HFT_BASE_URL = "https://api-hft.upstox.com/v2"`
- **external-url-construction** `infrastructure/adapters/brokers/upstox/adapter.py:61` — `_BASE_URL = "https://api.upstox.com/v2"`