# Prioritized Backlog

**Date:** June 21, 2026  
**Current Score:** 9.4/10  
**Target:** 9.9+/10  
**Deliverable #19** — Master Constitution Prompt

---

## Priority Matrix

| Priority | Area | Improvement | Effort | Score Impact | Risk |
|----------|------|-------------|--------|-------------|------|
| P0 | **Security** | TOTP-based MFA/2FA for dashboard login | 2 days | +0.3 | Low |
| P1 | **Testing** | Property-based tests (Hypothesis) for analytics modules | 1 day | +0.2 | Low |
| P2 | **SRE** | Jaeger/Zipkin distributed tracing for order lifecycle | 3 days | +0.2 | Medium |
| P3 | **Operations** | Kubernetes HPA auto-scaling triggers | 2 days | +0.2 | Low |
| P4 | **Security** | SAML/SSO integration for enterprise auth | 4 days | +0.1 | Medium |
| P5 | **Testing** | Fuzz testing for data parsing (option chain, trade files) | 1 day | +0.1 | Low |
| P6 | **Data** | Feature quality SLA — automated freshness monitoring | 1 day | +0.1 | Low |
| P7 | **Strategy** | Walk-forward validation automation in CI pipeline | 1 day | +0.1 | Low |
| P8 | **Dashboard** | MTTR + Error Budget API endpoints and HTML pages | 0.5 day | +0.1 | Low |
| P9 | **Infrastructure** | ELK/Loki stack configuration for log aggregation | 2 days | +0.1 | Medium |
| P10 | **Analytics** | Cross-asset correlation matrix dashboard widget | 0.5 day | +0.05 | Low |

---

## P0 — MFA/2FA for Dashboard (Highest Impact)

**Problem:** Dashboard authentication is password-only. No second factor.

**Solution:** TOTP-based MFA using `pyotp` library. Users enroll via QR code, then provide a 6-digit code on login.

**Implementation:**
```python
# core/auth/mfa.py
import pyotp
import qrcode
import io

class MFAManager:
    def generate_secret(self) -> str:
        return pyotp.random_base32()
    
    def get_provisioning_uri(self, username: str, secret: str) -> str:
        totp = pyotp.TOTP(secret)
        return totp.provisioning_uri(name=username, issuer_name="OPB Trading")
    
    def verify(self, secret: str, token: str) -> bool:
        totp = pyotp.TOTP(secret)
        return totp.verify(token)
```

**Files affected:** `core/auth/handler.py`, `core/auth/routes.py`, `templates/enterprise/login.html`

**Risk:** Low — opt-in feature, backward compatible.

---

## P1 — Property-Based Tests

**Problem:** Existing tests are example-based. Missing edge case coverage through property-based testing.

**Solution:** Add Hypothesis-based tests for Max Pain, IV Surface, and Factor Models.

**Target modules:**
- `core/max_pain.py` — Pain monotonicity property
- `core/iv_surface.py` — Interpolation bounds property
- `core/factor_models.py` — OLS convergence property

**Files affected:** `tests/test_max_pain.py`, `tests/test_iv_surface.py`, `tests/test_factor_models.py`

**Risk:** Low — tests only, no production code changes.

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

## P4 — SAML/SSO

**Problem:** Enterprise deployment requires integration with corporate identity providers (Okta, Azure AD, OneLogin).

**Solution:** Add `python3-saml` library integration. Enterprise config key switches between local auth and SAML.

**Files affected:** `core/auth/handler.py`, `core/auth/routes.py`, `index_config.defaults.json`

**Risk:** Medium — SAML configuration is complex, but library abstracts most of it.

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

## Estimated Total Effort to 9.9+: ~18 engineering days

| Priority | Days | Cumulative | Score After |
|----------|------|------------|-------------|
| P0 (MFA) | 2 | 2 | 9.6 |
| P1 (Hypothesis) | 1 | 3 | 9.7 |
| P2 (Tracing) | 3 | 6 | 9.75 |
| P3 (HPA) | 2 | 8 | 9.8 |
| P4 (SSO) | 4 | 12 | 9.85 |
| P5–P10 | 6 | 18 | 9.9+ |
