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

| Priority | Area | Improvement | Effort | Score Impact | Risk |
|----------|------|-------------|--------|-------------|------|
| P2 | **SRE** | Jaeger/Zipkin distributed tracing for order lifecycle | 3 days | +0.2 | Medium |
| P3 | **Operations** | Kubernetes HPA auto-scaling triggers | 2 days | +0.2 | Low |
| P5 | **Testing** | Fuzz testing for data parsing (option chain, trade files) | 1 day | +0.1 | Low |
| P6 | **Data** | Feature quality SLA — automated freshness monitoring | 1 day | +0.1 | Low |
| P7 | **Strategy** | Walk-forward validation automation in CI pipeline | 1 day | +0.1 | Low |
| P8 | **Dashboard** | MTTR + Error Budget API endpoints and HTML pages | 0.5 day | +0.1 | Low |
| P9 | **Infrastructure** | ELK/Loki stack configuration for log aggregation | 2 days | +0.1 | Medium |
| P10 | **Analytics** | Cross-asset correlation matrix dashboard widget | 0.5 day | +0.05 | Low |

---

## P2 — Distributed Tracing

**Problem:** No end-to-end trace visibility across the order lifecycle. Correlation IDs exist but aren't collected in a trace store.

**Solution:** Add `opentelemetry-api` instrumentation to the WAL journal and order manager. Export to Jaeger or Zipkin.

**Target trace spans:**
- `signal.generate` → `risk.evaluate` → `order.submit` → `order.ack` → `order.fill`
- `reconciliation.run` → `reconciliation.resolve`

**Files affected:** `core/wal/journal.py`, `core/execution/order_manager.py`, `core/reconciliation_engine.py`

**Risk:** Medium — requires new dependency (`opentelemetry-api`, `opentelemetry-sdk`), but can be opt-in via config.

---

## P3 — Kubernetes HPA Auto-Scaling

**Problem:** Capacity planning produces forecasts but no auto-scaling triggers.

**Solution:** Add a metrics endpoint that exposes current load vs capacity ratios for Kubernetes HPA integration.

**Files affected:** `core/capacity_planning.py`, `infrastructure/k8s/hpa.yaml`

**Risk:** Low — Kubernetes integration is opt-in, production-only concern.

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

## Estimated Total Effort to 9.9+: ~11 engineering days

| Priority | Days | Cumulative | Score After |
|----------|------|------------|-------------|
| P2 (Tracing) | 3 | 3 | 9.2 |
| P3 (HPA) | 2 | 5 | 9.3 |
| P5–P10 | 6 | 11 | 9.9+ |

> **Note:** P0 (MFA), P1 (Hypothesis tests), and P4 (SSO) were already completed and removed from the effort estimate. Actual remaining effort: ~11 days.
