# Prioritized Backlog

**Date:** June 22, 2026  
**Current Score:** 9.0/10  
**Target:** 9.9+/10  
**Deliverable #19** — Master Constitution Prompt

---

## ✅ Completed (No Longer Backlog)

| Priority | Area | Improvement | Status | Evidence |
|----------|------|-------------|--------|----------|
| P0 | Security | TOTP-based MFA/2FA for dashboard login | ✅ IMPLEMENTED | `core/auth/mfa.py` — TOTP secret generation, provisioning URI, token verification, session state, recovery codes, API routes, `require_mfa_verified` FastAPI dependency |
| P1 | Testing | Property-based tests (Hypothesis) | ✅ IMPLEMENTED | `tests/test_property_based.py` — 8 Hypothesis tests covering VaR invariants and invariants engine state |
| P4 | Security | SAML/SSO integration for enterprise auth | ✅ IMPLEMENTED | `core/auth/sso.py` — Google/Microsoft/GitHub OAuth2; `tests/test_sso.py` — 61 passing |

---

## Priority Matrix (Remaining)

| Priority | Area | Improvement | Effort | Score Impact | Risk | State |
|----------|------|-------------|--------|-------------|------|-------|
| P2 | **SRE** | Jaeger/Zipkin distributed tracing for order lifecycle | 3 days | +0.2 | Medium | ✅ EXISTS (`core/observability/opentelemetry.py`) |
| P3 | **Operations** | Kubernetes HPA auto-scaling triggers | 2 days | +0.2 | Low | ✅ DONE (`k8s/*.yaml`) |
| P5 | **Testing** | Fuzz testing for data parsing (option chain, trade files) | 1 day | +0.1 | Low | ✅ EXISTS (`tests/test_fuzz_data_parsing.py`) |
| P6 | **Data** | Feature quality SLA — automated freshness monitoring | 1 day | +0.1 | Low | ✅ DONE (`core/feature_quality_sla.py`) |
| P7 | **Strategy** | Walk-forward validation automation in CI pipeline | 1 day | +0.1 | Low | ✅ DONE (`bitbucket-pipelines.yml`) |
| P8 | **Dashboard** | MTTR + Error Budget API endpoints and HTML pages | 0.5 day | +0.1 | Low | ✅ DONE (`enterprise_dashboard.py` + `dashboard.html`) |
| P9 | **Infrastructure** | ELK/Loki stack configuration for log aggregation | 2 days | +0.1 | Medium | ✅ DONE (`deploy/loki/`, `deploy/promtail/`, `deploy/docker-compose.observability.yml`) |
| P10 | **Analytics** | Cross-asset correlation matrix dashboard widget | 0.5 day | +0.05 | Low | ✅ DONE (`enterprise_dashboard.py` + `dashboard.html`) |

---

## All Backlog Items Complete

### P2 — Distributed Tracing
**Status:** ✅ Already Exists
- `core/observability/opentelemetry.py` — complete Jaeger/Zipkin/OTLP export support
- No additional work needed

### P3 — Kubernetes HPA Auto-Scaling
**Status:** ✅ Implemented
- 6 K8s manifests in `k8s/`: Deployment, Service, HPA, ConfigMap, PVC, Kustomize
- HPA scales on CPU 70% / memory 80% (1–5 replicas)
- Prometheus metrics port exposed on `:9090/metrics`
- See `k8s/README.md` for deployment instructions

### P5 — Fuzz Testing
**Status:** ✅ Already Exists
- `tests/test_fuzz_data_parsing.py` — 100+ Hypothesis-based tests
- No additional work needed

### P6 — Feature Quality SLA
**Status:** ✅ Implemented
- `core/feature_quality_sla.py` — automated freshness monitor for 14 ML features
- Bridges DataQualityMonitor + DataFreshnessGuard + SLOGovernance + MetricsExporter
- 35 passing tests

### P7 — Walk-Forward in CI
**Status:** ✅ Implemented
- Walk-forward step added to `bitbucket-pipelines.yml`
- Runs `test_walkforward_engine.py` + `test_walkforward_anchored.py`

### P8 — MTTR / Error Budget API & Dashboard
**Status:** ✅ Implemented
- 3 API endpoints: `/api/mttr/report`, `/api/error-budget/status`, `/api/error-budget/risk-summary`
- Full dashboard pages with P50/P90/P99, burn rates, at-risk flags

### P9 — ELK/Loki Observability Stack
**Status:** ✅ Implemented
- `deploy/loki/loki-config.yml`, `deploy/promtail/promtail-config.yml`
- `deploy/docker-compose.observability.yml` — Loki + Promtail + Grafana
- Auto-provisioned Grafana datasources

### P10 — Cross-Asset Correlation Dashboard
**Status:** ✅ Implemented
- 2 API endpoints: `/api/cross-asset/correlation`, `/api/cross-asset/relative-value`
- Correlation matrix with color-coded strength visualization

---

## Technical Debt Items (Non-Blocking)

| Item | Area | Severity | Effort |
|------|------|----------|--------|
| Remove deprecated `trading_system` import paths | Architecture | LOW | 1h |
| Consolidate duplicate `logging.getLogger()` patterns | Code Quality | LOW | 2h |
| Add type hints to remaining untyped functions | Code Quality | LOW | 4h |
| Standardize error response format across all API endpoints | API | MEDIUM | 3h |
| Remove hardcoded database paths in `enterprise_dashboard.py` | Architecture | MEDIUM | 1h |
| Add `__all__` exports to all `core/` modules | API | LOW | 2h |

---

## Scoring Path to 9.9+

With all P2–P10 items completed, the remaining gap to 9.9+ is:
- **~2 engineering days** of technical debt cleanup
- **Time-based validation** — 90-day paper trading track record
- **Score potential with debt cleared:** 9.4–9.6/10
- **Full 9.9+:** Requires sustained production track record
