# OPB FINAL SECURITY TRIAGE

Static precheck found 74 localhost URL literals and 28 potential literal-secret assignments.
These are not automatically vulnerabilities; tests, documentation and examples can legitimately contain blocked localhost values or placeholder secrets.

## Localhost URL distribution
- production_candidate: 48
- tests: 7
- tools/scratch: 19

## Potential secret distribution
- production_candidate: 5
- tests: 23

## Production-candidate localhost hits
- `docker-compose.monitoring.yml:13` — `#   Grafana:    http://localhost:3000  (admin/admin)`
- `docker-compose.monitoring.yml:14` — `#   Prometheus: http://localhost:9090`
- `docker-compose.monitoring.yml:15` — `#   Loki:       http://localhost:3100`
- `docker-compose.monitoring.yml:37` — `test: ["CMD", "wget", "-q", "http://localhost:9090/-/healthy"]`
- `docker-compose.monitoring.yml:56` — `- GF_SERVER_ROOT_URL=http://localhost:3000`
- `docker-compose.monitoring.yml:65` — `test: ["CMD", "wget", "-q", "http://localhost:3000/api/health"]`
- `docker-compose.monitoring.yml:84` — `test: ["CMD", "wget", "-q", "http://localhost:3100/ready"]`
- `k8s/prometheusrule.yaml:13` — `#   curl http://localhost:9090/metrics | grep '^opb_'`
- `deploy/docker-compose.observability.yml:12` — `#   # Access Grafana at http://localhost:3000 (admin/admin)`
- `deploy/docker-compose.observability.yml:13` — `#   # Prometheus at http://localhost:9090`
- `deploy/docker-compose.observability.yml:14` — `#   # Loki at http://localhost:3100`
- `deploy/docker-compose.observability.yml:42` — `test: ["CMD", "wget", "-q", "--tries=1", "-O-", "http://localhost:9090/-/ready"]`
- `deploy/docker-compose.observability.yml:60` — `test: ["CMD", "wget", "-q", "--tries=1", "-O-", "http://localhost:3100/ready"]`
- `deploy/docker-compose.observability.yml:101` — `test: ["CMD", "wget", "-q", "--tries=1", "-O-", "http://localhost:3000/api/health"]`
- `json/config.template.json:1511` — `"otlp_endpoint": "http://localhost:4317",`
- `json/config.template.json:1767` — `"zipkin_endpoint": "http://localhost:9411/api/v2/spans"`
- `json/index_config.defaults.json:1301` — `"otlp_endpoint": "http://localhost:4317",`
- `json/index_config.defaults.json:1309` — `"zipkin_endpoint": "http://localhost:9411/api/v2/spans",`
- `json/config.json:1541` — `"otlp_endpoint": "http://localhost:4317",`
- `json/config.json:1773` — `"zipkin_endpoint": "http://localhost:9411/api/v2/spans",`
- `.tmp/opb_manual_cfg_d5nh58h4.json:1511` — `"otlp_endpoint": "http://localhost:4317",`
- `.tmp/opb_manual_cfg_d5nh58h4.json:1767` — `"zipkin_endpoint": "http://localhost:9411/api/v2/spans",`
- `.tmp/opb_manual_cfg_jsaa8xre.json:1511` — `"otlp_endpoint": "http://localhost:4317",`
- `.tmp/opb_manual_cfg_jsaa8xre.json:1767` — `"zipkin_endpoint": "http://localhost:9411/api/v2/spans",`
- `.tmp/opb_manual_cfg_6_478ydc.json:1511` — `"otlp_endpoint": "http://localhost:4317",`
- `.tmp/opb_manual_cfg_6_478ydc.json:1767` — `"zipkin_endpoint": "http://localhost:9411/api/v2/spans",`
- `core/ai_engine.py:209` — `base = ai_cfg.api_base_url or "http://localhost:11434"`
- `core/notifications/url_resolver.py:20` — `DEFAULT_DEV_URL = "http://localhost:8000"`
- `core/notifications/url_resolver.py:132` — `- Development -> http://localhost:8000`
- `core/observability/opentelemetry.py:79` — `- otlp_endpoint (str): OTLP gRPC endpoint (default "http://localhost:4317").`
- `core/observability/opentelemetry.py:300` — `otlp_endpoint = cfg.get("otlp_endpoint", "http://localhost:4317")`
- `core/observability/opentelemetry.py:381` — `- zipkin_endpoint (str): Zipkin HTTP endpoint (default "http://localhost:9411/api/v2/spans").`
- `core/observability/opentelemetry.py:390` — `zipkin_endpoint = cfg.get("zipkin_endpoint", "http://localhost:9411/api/v2/spans")`
- `core/enterprise_dashboard/models.py:168` — `def __init__(self, base_url: str = "http://127.0.0.1:8000", timeout: float = 2.0) -> None:`
- `archive/unrelated_modules/docker-compose.realestate.yml:15` — `#   API:      http://localhost:8766`
- `archive/unrelated_modules/docker-compose.realestate.yml:16` — `#   Health:   http://localhost:8766/api/realestate/health`
- `archive/unrelated_modules/docker-compose.realestate.yml:17` — `#   Adminer:  http://localhost:8080 (if DB enabled)`
- `archive/unrelated_modules/docker-compose.realestate.yml:46` — `test: ["CMD", "curl", "-f", "http://localhost:8766/api/realestate/health"]`
- `archive/unrelated_modules/k6/realestate-load-test.js:6` — `//   k6 run --env BASE_URL=http://localhost:8765 k6/realestate-load-test.js`
- `archive/unrelated_modules/k6/realestate-load-test.js:15` — `const BASE_URL = __ENV.BASE_URL || "http://localhost:8765";`
- `archive/unrelated_modules/e2e/realestate-flows.spec.js:10` — `const BASE_URL = process.env.BASE_URL || 'http://localhost:8765';`
- `archive/unrelated_modules/scripts/seed_realestate_data.py:156` — `api_base: str = "http://localhost:8766",`
- `archive/unrelated_modules/scripts/seed_realestate_data.py:241` — `parser.add_argument("--api", type=str, default="http://localhost:8766", help="API base URL")`
- `archive/unrelated_modules/scripts/realestate_synthetic_monitor.py:213` — `default=os.environ.get("RE_URL", "http://localhost:8765"),`
- `.github/workflows/realestate.yml:131` — `http://localhost:8765/realestate`
- `.github/workflows/realestate-ci.yml:173` — `curl -sf http://localhost:8765/api/realestate/health > /dev/null 2>&1 && break`
- `.github/workflows/realestate-ci.yml:177` — `curl -f http://localhost:8765/api/realestate/health || echo "Server not ready yet"`
- `deploy/grafana/datasources.yml:29` — `url: "http://localhost:8765/trace?trace_id=$${__value.raw}"`

## Production-candidate potential literal secrets
- `reports/hygiene_scan_report.html:2023` — `<td>    return create_groww_adapter(access_token="test_token", l...</td>`
- `reports/hygiene_scan_report.html:2047` — `<td>            access_token="test_token",</td>`
- `reports/hygiene_scan_report.html:2317` — `<td>    return create_mstock_adapter(api_key="test_key", access_...</td>`
- `reports/hygiene_scan_report.html:2413` — `<td>    return create_upstox_adapter(access_token="test_token", ...</td>`
- `templates/enterprise/profile.html:740` — `showToast('Error changing password: ' + err.message, 'error');`

## Decision
Do not mass-delete or replace these values blindly. Production-candidate hits must be reviewed individually.
Test/documentation placeholders should be explicitly classified as non-production fixtures.
Real credentials must be removed/rotated immediately if any are found.