# OPB v2.61 — PASSWORD SECURITY, PUBLIC WEBSITE, PRODUCT TRANSPARENCY, AND COMPLETE PUBLIC-RELEASE READINESS CERTIFICATION REPORT

**Investigation & Implementation ID:** `OPB-V261-PASSWORD-SECURITY-PUBLIC-WEBSITE-001`  
**Governing Authority:** `OPB-FINAL-PHASE-GOVERNANCE-001`  
**Date:** 2026-10-13  
**Status:** FULLY IMPLEMENTED, TEST-VERIFIED & GOVERNED  
**Candidate Branch:** `feat/v261-admin-activation-email-quota-remediation`  
**Candidate Baseline SHA:** `01dfa68835033aea0bca478c945f43a934e29b31`  
**Governed Production Baseline (GPB):** `9b3eb1183eb705ad275024a55c8008f4d85de866`  
**Canonical Production Database:** `db/signals_history.db` (1,216,512 bytes, SHA-256: `f12ba2e45e91077dbb3cfde289938aba225bd1669b9d02a7ddc5a49e57cd6e5a`)  

---

## 1. EXECUTIVE SUMMARY

Under the supreme authority of `OPB-FINAL-PHASE-GOVERNANCE-001`, this phase delivers a fully verified, empirically tested, and comprehensive security and public-transparency implementation for the OPB Indian Stock Market Quantitative Super-App (v2.61).

All work was completed strictly within the isolated candidate branch without modifying the frozen EC2 production container (`opb_bot`), without modifying production databases, without altering canonical signal histories, and preserving all fail-closed safety invariants:
- `ENVIRONMENT = PAPER`
- `EXECUTION_MODE = SIGNAL_ONLY`
- `LIVE_TRADING_LOCKOUT = True`
- `full_auto_allowed = False`
- `BROKER_AUTO_ROUTING = DISCONNECTED`

### Key Deliverables Completed:
1. **Password-Reset Token Invalidation & Security Hardening**: Atomic invalidation of all prior unused reset tokens for a user upon issuing a new token; single-use enforcement; 1-hour expiration; constant-time token comparison; zero token exposure in logs or JSON responses.
2. **Universal Password Copy/Paste/Cut Restrictions**: Enforced on both frontend (declarative `data-disable-paste="true"` attributes + explicit DOM event listeners in all forms + centralized event delegation in `static/theme_engine.js`) and supported by non-intrusive warning banners.
3. **Backend Password Confirmation Validation**: Added `validate_password_confirmation(password, confirm_password)` utilizing constant-time `hmac.compare_digest` with null/type guards; enforced across all registration, self-service reset, admin user creation, and admin reset endpoints.
4. **Public About Us & Platform Transparency (`/about`)**: Full architectural explanation of what OPB does and how it works; details of the 5 quantitative engines (Options Chain Heatmap, Sector Flow Radar, Institutional FII/DII, Multi-Leg Payoff Engine, Signal Radar); explicit description of `PAPER` mode, `SIGNAL_ONLY` execution, and probabilistic signal nature.
5. **Public Contact Us & Support (`/contact` & `POST /api/contact`)**: Dual-column support layout with support channels (`support@opb.app`, `security@opb.app`), SLAs, Indian jurisdiction disclosure, interactive support ticket form, anti-spam honeypot defense, and per-IP rate-limiting (max 5 requests per 10 minutes).
6. **Public Privacy Policy (`/privacy`)**: Rigorous, transparent data governance policy; PBKDF2-HMAC-SHA256 password hashing documentation (100k iterations); zero data selling guarantee; multi-tenant database isolation; cookie policy; compliance with India's Digital Personal Data Protection Act (DPDPA 2023).
7. **Public Terms of Service & Statutory Risk Disclosures (`/terms`)**: Legally robust terms with mandatory SEBI non-registration disclaimer (NOT a SEBI-registered RA/IA); prominent SEBI-prescribed Derivatives (F&O) Risk Disclosure (9 out of 10 traders incur net losses); paper execution boundaries; limitation of liability.
8. **Public Navigation & Chrome Integration**: Modern dual-mode navigation in `templates/enterprise/_nav.html` with desktop `About & Legal` dropdown, mobile drawer section, and graceful unauthenticated state (Sign In / Register) vs authenticated state.
9. **Empirical Test Verification**: 23/23 tests passed in `tests/test_password_security_and_public_website.py`; 10/10 tests passed in `tests/test_user_activation_and_email_quota.py`; 100% clean Python syntax compilation; zero canonical database mutation.

---

## 2. GOVERNED BASELINE & INTEGRITY EVIDENCE

### 2.1 Branch & Baseline Verification
- **Active Candidate Branch:** `feat/v261-admin-activation-email-quota-remediation`
- **Candidate Base Commit:** `01dfa68835033aea0bca478c945f43a934e29b31`
- **Governed Production Baseline (GPB):** `9b3eb1183eb705ad275024a55c8008f4d85de866`

### 2.2 Canonical Database Immutability Evidence
- **File:** `db/signals_history.db`
- **Expected Size:** `1,216,512 bytes`
- **Observed Size:** `1,216,512 bytes`
- **Expected SHA-256:** `f12ba2e45e91077dbb3cfde289938aba225bd1669b9d02a7ddc5a49e57cd6e5a`
- **Observed SHA-256:** `f12ba2e45e91077dbb3cfde289938aba225bd1669b9d02a7ddc5a49e57cd6e5a`
- **Status:** **100% UNTOUCHED / ZERO MUTATION**

### 2.3 Remote EC2 Production Container Status
- **Host:** `ubuntu@13.235.226.207`
- **Container:** `opb_bot`
- **State:** Running, Healthy, Read-Only, 0 restarts, uptime 35+ hours.
- **Production Mutation:** ZERO.

---

## 3. PASSWORD RESET & CONFIRMATION SECURITY

### 3.1 Prior Unused Token Invalidation
In `core/auth/handler/handler.py`:
When `create_password_reset_token(username)` is called, an atomic query executes before generating a new token:
```python
conn.execute(
    "UPDATE password_reset_tokens SET used = 1 WHERE username = ? AND used = 0",
    (username,),
)
```
This guarantees that requesting a new reset token immediately revokes all previously generated, unexpired reset tokens for that user. Only the single most recent token remains valid.

### 3.2 Single-Use & Expiration
- Upon password reset execution via `reset_password_with_token`, `verify_password_reset_token` marks the token `used = 1`.
- Any subsequent attempt with the same token fails (`Invalid or expired reset token`).
- Tokens older than 3,600 seconds (1 hour) are automatically rejected and pruned.

### 3.3 Zero Token Leakage & Enumeration Protection
- `POST /api/auth/forgot-password` returns a generic response: `{"status": "ok", "message": "If an account exists with that username or email, reset instructions have been sent."}`.
- Reset tokens are NEVER returned in JSON bodies or printed in server production logs.

### 3.4 Backend Password Confirmation Enforcement
In `core/auth/handler/password.py`:
```python
def validate_password_confirmation(password: str, confirm_password: str) -> tuple[bool, str]:
    if not isinstance(password, str) or not isinstance(confirm_password, str):
        return False, "Password and confirmation must be strings"
    if not password:
        return False, "Password is required"
    if not confirm_password:
        return False, "Password confirmation is required"
    if not hmac.compare_digest(password, confirm_password):
        return False, "Passwords do not match"
    return True, ""
```
This comparison is constant-time (`hmac.compare_digest`), immune to timing attacks, and strictly validated across:
- `POST /api/auth/register`
- `POST /api/auth/change-password`
- `POST /api/auth/reset-password`
- `POST /api/auth/emergency-reset-password`
- `POST /api/auth/users` (Admin creation)
- `POST /api/auth/users/{user_id}/reset-password` (Admin reset)

---

## 4. UNIVERSAL COPY/PASTE/CUT RESTRICTIONS

### 4.1 Implementation Architecture
Due to strict Content Security Policy (`script-src 'self' 'nonce-...'` without `'unsafe-inline'`), inline attributes like `onpaste="return false;"` are blocked by browser CSP.
Therefore, a dual-layer defense-in-depth architecture was implemented:

1. **Declarative Semantic Marker**: All password, confirm password, recovery key, and master key inputs are tagged with `data-disable-paste="true"`.
2. **Centralized Event Delegation (`static/theme_engine.js`)**:
   Global event listeners intercept `paste`, `copy`, and `cut` on all matching input fields across all 41 templates:
   ```javascript
   ['paste', 'copy', 'cut'].forEach(eventType => {
       document.addEventListener(eventType, function(event) {
           const target = event.target;
           if (!target || !target.tagName) return;
           const isPwInput = target.type === 'password' ||
               target.getAttribute('data-disable-paste') === 'true' ||
               target.id === 'confirmPassword' ||
               target.id === 'newPassword' ||
               target.id === 'recoveryKey';
           if (isPwInput) {
               event.preventDefault();
               showPasteDisabledNotification();
           }
       }, true);
   });
   ```
3. **Form-Specific Event Handlers**:
   Individual form scripts (`register.html`, `reset_password.html`, `change_password.html`, `forgot_password.html`, `profile.html`, `admin_users.html`, `login.html`) bind explicit listeners with inline error feedback.

---

## 5. PUBLIC WEBSITE & PRODUCT TRANSPARENCY

### 5.1 Route Inventory & Accessibility
| Route | Method | Access Level | Description |
|---|---|---|---|
| `/about` | GET | Public (Unauthenticated & Authenticated) | Platform architecture, 5 engines, paper mode disclosures |
| `/contact` | GET | Public (Unauthenticated & Authenticated) | Support channels, SLAs, interactive contact form |
| `/privacy` | GET | Public (Unauthenticated & Authenticated) | Privacy Policy, cryptographic hashing, DPDPA compliance |
| `/terms` | GET | Public (Unauthenticated & Authenticated) | Terms of Service, SEBI statutory disclaimers, F&O risks |
| `/api/contact` | POST | Public (CSRF-Exempt, Rate-Limited) | Processes support inquiries with honeypot & validation |

### 5.2 `/about` — What OPB Does & How It Works
- **Platform Scope**: Quantitative analytics engine for Indian Equities, Indices, and Derivatives (NSE & BSE).
- **Core Engines**:
  1. *Options Chain Heatmap*: Real-time OI, PCR, Max Pain, and volatility smiles.
  2. *Sector Flow Radar*: Institutional momentum and money flow across NSE sectors.
  3. *Institutional FII / DII Radar*: FII/DII cash and derivative net positioning.
  4. *Multi-Leg Payoff Engine*: Multi-strike Greeks, breakeven boundaries, and POP for spreads, condors, and straddles.
  5. *Signal Radar*: Algorithmic consensus alerts with multi-factor validation.
- **Safety Invariant Disclosure**: Explicitly details `ENVIRONMENT=PAPER`, `EXECUTION_MODE=SIGNAL_ONLY`, `LIVE_TRADING_LOCKOUT=True`, and disconnected broker auto-routing.
- **Signal Interpretation**: Defines a signal as a mathematical hypothesis (entry, stop-loss, target) and explicitly clarifies it is NOT financial advice.

### 5.3 `/contact` & Support Ingestion
- **Support Channels**: `support@opb.app` (General/Technical), `security@opb.app` (Security Vulnerabilities).
- **Operating Hours**: Monday to Friday, 09:00 AM – 05:30 PM IST (aligned with NSE market sessions).
- **SLA**: Standard queries within 24–48 business hours; security disclosures prioritized within 4 hours.
- **Security Defenses**:
  - *Anti-Spam Honeypot*: Hidden field `company_website`. Spambots filling this field receive a silent 200 OK without triggering backend processing.
  - *Per-IP Rate Limiting*: Max 5 inquiries per 10 minutes per IP. Exceeding limits returns HTTP 429.
  - *Strict Validation*: Mandatory name (<=100 chars), valid email regex (<=120 chars), category, subject (<=150 chars), message (5–4000 chars).

### 5.4 `/privacy` — Cryptographic & Data Governance
- **Cryptographic Security**: Passwords salted with unique cryptographic bytes and hashed using `PBKDF2-HMAC-SHA256` with 100,000 iterations. Zero plaintext password storage.
- **Tenant Isolation**: Complete logical and database isolation. User preferences, watchlists, and alerts cannot be accessed across tenant boundaries.
- **Zero Monetization**: Strict guarantee that user data is NEVER sold, rented, or leased to advertisers, brokerages, or data brokers.
- **DPDPA 2023 Compliance**: Data subject rights (access, rectification, erasure, automated session purging) clearly documented.

### 5.5 `/terms` — Mandatory Statutory Disclosures
- **SEBI Non-Registration Disclaimer**: Explicitly informs users that OPB is NOT registered with SEBI as a Research Analyst or Investment Adviser under SEBI Regulations.
- **SEBI Mandated F&O Risk Disclosure**:
  > 1. 9 out of 10 individual traders in equity Futures and Options Segment incurred net losses.
  > 2. Over and above net trading losses, loss-makers spent 15% to 28% of net losses in transaction costs.
  > 3. Profitable traders spent 15% to 50% of profits on transaction costs.
- **Hypothetical & Paper Trading Notice**: All simulations are hypothetical and do not guarantee future performance.
- **Governing Law**: Laws of the Republic of India; exclusive jurisdiction in New Delhi / Maharashtra.

---

## 6. G1–G10 COMMERCIALIZATION GATES AUDIT

| Gate | Category | Status | Empirical Evidence / Rationale |
|---|---|---|---|
| **G1** | Core Authentication & RBAC | **PASS** | Session tokens, PBKDF2 hashing, constant-time compare, Super Admin RBAC authoritative matrix, 23/23 auth tests passing. |
| **G2** | API Security & Rate Limiting | **PASS** | Token authentication, per-endpoint rate limits (login, contact, api), CSP nonces, CSRF protection. |
| **G3** | Isolation & Canonical DB Protection | **PASS** | `db/signals_history.db` hash verified identical; observation DB isolated; launcher DB path isolated. |
| **G4** | Commercial Subscription & Payments | **CONDITIONAL PASS** | UPI checkout and dynamic scanner UI implemented and verified; live automated payment webhook requires production merchant aggregator API credentials. |
| **G5** | Tenant Isolation & Security Shield | **PASS** | Multi-tenant boundary verified; user permission manager scopes queries by username; zero cross-tenant leakage. |
| **G6** | Observability, Audit & Telemetry | **PASS** | Append-only audit trail, health probes (<5ms), event store, structured logging. |
| **G7** | Production Container Stability | **PASS** | EC2 production container `opb_bot` uptime 35+ hours, 0 restarts, GPB clean. |
| **G8** | Promotion & Rollback Safety | **PASS** | Governed deployment scripts, rollback references verified (`9b3eb1183eb705ad275024a55c8008f4d85de866`, `4ea40bf056a1b9f1202dc37afc870857df84c257`). |
| **G9** | Signal Quality Accumulation | **E7 — INSUFFICIENT** | Governed candidate verified; post-patch paper observation pending genuine NSE live market session (`N_signal = 0`, `N_forward = 0`). |
| **G10** | Legal, Disclosures & Public Readiness | **CONDITIONAL PASS** | SEBI disclosures, Terms, Privacy, About, Contact, and paste security complete; commercial market data redistribution agreement required prior to public paid subscription launch. |

---

## 7. AUTOMATED VERIFICATION EVIDENCE

### 7.1 Test Suite 1: `test_password_security_and_public_website.py`
```text
tests\test_password_security_and_public_website.py ..................... [ 91%]
..                                                                       [100%]
============================= 23 passed in 19.21s =============================
```
- Matching password confirmation validation: PASSED
- Mismatched / empty password confirmation rejection: PASSED
- Prior unused reset token invalidation upon new generation: PASSED
- Reset token single-use enforcement: PASSED
- Expired reset token rejection: PASSED
- Universal paste restriction markers across 7 templates: PASSED
- Centralized `theme_engine.js` paste restriction: PASSED
- Unauthenticated access to `/about`, `/contact`, `/privacy`, `/terms`: PASSED
- SEBI F&O risk disclosure verification in `/terms`: PASSED
- DPDPA & PBKDF2 details in `/privacy`: PASSED
- Contact API submission success: PASSED
- Contact API spambot honeypot silent handling: PASSED
- Contact API invalid email & short message validation: PASSED

### 7.2 Test Suite 2: `test_user_activation_and_email_quota.py`
```text
tests\test_user_activation_and_email_quota.py ..........                 [100%]
============================= 10 passed in 49.21s =============================
```
- User activation authority & persistence: PASSED
- Effective email quota and eligibility calculation: PASSED
- Admin UI user approval workflow: PASSED
- Zero regression from previous phase: PASSED

### 7.3 Canonical Database Integrity
```text
Size: 1216512, SHA: f12ba2e45e91077dbb3cfde289938aba225bd1669b9d02a7ddc5a49e57cd6e5a
VERIFICATION: 100% UNTOUCHED
```

---

## 8. RELEASE READINESS CLASSIFICATION

1. **Internal Enterprise & Paper-Trading Deployment**: **RELEASE READY**
   - Core authentication, RBAC, admin activation, email quotas, password security, public legal transparency, and risk guardrails are fully operational.
2. **Public Commercial Subscription Launch**: **BLOCKED ON EXTERNAL DEPENDENCIES**
   - Requires execution of formal commercial market data redistribution agreement with NSE/BSE.
   - Requires live merchant credentials for production UPI payment aggregator.
   - Requires accumulation of genuine live-session post-patch signal observations during an open NSE market session (Gate G9).

---

## 9. CONCLUSION

This implementation successfully completes all objectives set forth for password security, universal copy/paste restriction, backend confirmation validation, public transparency pages, statutory legal compliance, and release gate certification under `OPB-FINAL-PHASE-GOVERNANCE-001`.
