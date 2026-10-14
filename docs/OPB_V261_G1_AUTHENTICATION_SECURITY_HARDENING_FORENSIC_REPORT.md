# OPB v2.61 — G1 AUTHENTICATION SECURITY HARDENING FORENSIC REPORT

**Governance Authority:** `OPB-FINAL-PHASE-GOVERNANCE-001`  
**Repository:** `gaurav-kiyu/auto-trade-system`  
**Application Version:** `2.60.0`  
**Date:** 2026-10-11  

---

## 1. GOVERNANCE AUTHORITY
This phase was executed under the strict engineering mandate of **`OPB-FINAL-PHASE-GOVERNANCE-001`** and the OPB UI & System Architecture constitution. No assumption-based completion is permitted; only empirical, verifiable evidence is accepted.

---

## 2. STAGE A SYNCHRONIZATION STATUS
- **Phase 2H (Ruff I001):** CLOSED (PR #93 merged)
- **Phase 2I (Ruff F401):** CLOSED (PR #94 merged)
- **Phase 2J (Ruff F841):** CLOSED (PR #95 merged)
- **Phase 2K (Ruff W291):** CLOSED (PR #96 merged)
- **Phase 2L (Ruff W293):** CLOSED (PR #97 merged)
- **Phase 2M (SemVer Changelog):** CLOSED (PR #98 merged)
- **Phase 2N (Release Notes):** CLOSED (PR #99 merged via commit `9b3eb1183eb705ad275024a55c8008f4d85de866`)
- **Stage A Overall Verdict:** **`CERTIFIED — CLOSED & SYNCHRONIZED`**

---

## 3. FINAL SYNCHRONIZED RELEASE SHA
`9b3eb1183eb705ad275024a55c8008f4d85de866`

---

## 4. G1 PREDECESSOR
`9b3eb1183eb705ad275024a55c8008f4d85de866` (Clean synchronized master branch baseline)

---

## 5. LOCAL BRANCH
`v2.61-g1-auth-security-hardening`

---

## 6. VULNERABILITY REPRODUCTION
In the predecessor codebase (`9b3eb11`), executing:
```bash
POST /api/auth/forgot-password
Content-Type: application/json
{"username": "<valid_user>"}
```
Returned:
```json
{
  "success": true,
  "message": "Password reset token generated successfully",
  "token": "d748f3e...",
  "reset_url": "/reset-password?token=d748f3e...",
  "expires_in": 3600
}
```
Any caller without credentials could initiate password recovery for an arbitrary known username and immediately receive the valid reset token in the HTTP response, completely bypassing out-of-band email verification.

---

## 7. EXACT VULNERABLE FLOW
1. Client POSTs `{"username": "trader1"}` to `/api/auth/forgot-password`.
2. Server calls `auth_handler.create_password_reset_token("trader1")`.
3. Server returns JSON dictionary containing `"token": token` and `"reset_url": f"/reset-password?token={token}"`.
4. Client navigates to `/reset-password?token={token}` and sets a new password.
5. Account hijacked with zero user interaction or email verification.

---

## 8. RESET-FLOW CONTRACT
```text
Reset Request (username)
       ↓
Request Validation (non-empty username)
       ↓
Account Lookup (retrieve user record)
       ↓
Token Generation (cryptographic secrets.token_urlsafe)
       ↓
Token Storage (SHA-256 hash in password_reset_tokens table)
       ↓
Authorized Out-of-Band Delivery (Email via configured SMTP)
       ↓
Universal Sanitized API Response (Generic message; NO token, NO URL)
       ↓
Token Verification (/api/auth/verify-reset-token)
       ↓
Token Consumption (/api/auth/reset-password)
       ↓
Single-Use Invalidation (used = 1)
       ↓
Password Update (bcrypt / argon2)
```

---

## 9. TOKEN GENERATION
Tokens are generated using Python's cryptographically secure standard library (`secrets` module) with 32+ bytes of entropy, producing URL-safe strings with >= 256 bits of security.

---

## 10. TOKEN STORAGE
Tokens are **never stored in plaintext** in the database. `AuthHandler` computes `hashlib.sha256(token.encode()).hexdigest()` and stores only the SHA-256 digest in the SQLite `password_reset_tokens` table.

---

## 11. TOKEN DELIVERY
Primary delivery is performed out-of-band via SMTP email using `core.auth.registration_notifications._send` if the user account has a configured email address. Plaintext tokens and reset URLs are **never delivered over the public API**.

---

## 12. FALLBACK
In non-production test environments (`PYTEST_CURRENT_TEST` or `OPB_AUTH_TEST_MODE="1"`), generated tokens are mirrored to an in-memory test sink (`_test_reset_tokens`) accessible via `get_test_reset_token(username)`.

---

## 13. ENVIRONMENT GATING
The fallback is strictly gated:
```python
env = (os.getenv("OPBUYING_ENVIRONMENT") or os.getenv("ENVIRONMENT") or "").upper()
if env == "PRODUCTION":
    return None
```
In any production environment, the fallback sink is completely unreachable and returns `None`.

---

## 14. TOKEN CONSUMPTION
Tokens are consumed at `/api/auth/reset-password` by providing `token` and `new_password`.

---

## 15. EXPIRY
Tokens expire after 3,600 seconds (1 hour). Expired tokens are rejected and purged from the database.

---

## 16. SINGLE-USE / INVALIDATION
Upon successful password reset, the token record is marked `used = 1`. Subsequent attempts to verify or reuse the token are rejected.

---

## 17. PASSWORD RESET
The user password is updated using the standard secure password hashing routine with validation against the system password strength policy (minimum length, character classes, common word checks).

---

## 18. RESPONSE CONTRACT
The hardened `/api/auth/forgot-password` endpoint returns:
```json
{
  "success": true,
  "message": "If the account exists, password reset instructions have been dispatched."
}
```
No `token`, `reset_url`, or `expires_in` fields are exposed.

---

## 19. ROOT CAUSE
In `core/auth/routes.py` (lines 1318–1324), the initial prototype implementation directly included the raw generated token and `reset_url` in the JSON dictionary returned to the HTTP client.

---

## 20. DECISION CASE
**CASE A — CONTROLLED REMEDIATION**
- Vulnerability confirmed: YES
- Root cause proven: YES
- Reset-flow contract reconstructed: YES
- Safe out-of-band delivery established: YES
- Safe environment-gated test fallback established: YES
- Security invariants testable: YES

---

## 21. REMEDIATION
1. Modified `core/auth/routes.py`:
   - Added `_test_reset_tokens` and `get_test_reset_token` strictly gated against `PRODUCTION`.
   - Replaced `forgot_password` route body to eliminate `token` and `reset_url` from response.
   - Dispatched out-of-band email when user email is present.
   - Standardized universal success message to prevent username enumeration.
2. Modified `templates/enterprise/forgot_password.html`:
   - Updated success message rendering to display generic confirmation without requiring `data.reset_url`.
3. Added `tests/test_password_reset_security.py`:
   - 18 comprehensive security tests validating token non-exposure, headers, bodies, logs, enumeration protection, expiry, and single-use invariants.

---

## 22. EXACT DIFF
```diff
diff --git a/core/auth/routes.py b/core/auth/routes.py
index 5341595..46eaa9f 100644
--- a/core/auth/routes.py
+++ b/core/auth/routes.py
@@ -5,6 +5,7 @@
 from __future__ import annotations
 
 import logging
+import os
 from typing import Any
 
 try:
@@ -61,6 +62,22 @@ class Response:  # type: ignore
 
 _log = logging.getLogger(__name__)
 
+# Test delivery sink: populated ONLY in test environments, never in production.
+_test_reset_tokens: dict[str, str] = {}
+
+
+def get_test_reset_token(username: str) -> str | None:
+    """Retrieve the last generated reset token for testing purposes only.
+
+    Strictly gated: Returns None in production environments.
+    """
+    env = (os.getenv("OPBUYING_ENVIRONMENT") or os.getenv("ENVIRONMENT") or "").upper()
+    if env == "PRODUCTION":
+        return None
+    if os.getenv("PYTEST_CURRENT_TEST") or os.getenv("OPB_AUTH_TEST_MODE") == "1":
+        return _test_reset_tokens.get(username)
+    return None
+
 
 def create_auth_router(
     auth_handler: AuthHandler,
@@ -1306,21 +1323,61 @@ async def sso_providers() -> dict:
 
     @router.post("/forgot-password")
     async def forgot_password(request: Request) -> dict:
-        """Request a password reset token for a given username."""
+        """Request a password reset token for a given username.
+
+        Hardened under OPB v2.61 G1:
+        - Plaintext reset tokens and URLs are NEVER returned in the API response.
+        - Returns a generic success message to prevent account enumeration.
+        - Delivers token via configured out-of-band email notifications.
+        - Strictly-gated in-memory test delivery sink enabled only under test execution.
+        """
         body = await request.json()
         username = str(body.get("username", "")).strip()
         if not username:
             raise HTTPException(status_code=400, detail="Username is required")
-        token = auth_handler.create_password_reset_token(username)
-        if not token:
-            # Generic error to prevent username enumeration or specific detail
-            raise HTTPException(status_code=400, detail="Unable to request password reset. Please check username.")
+
+        user = auth_handler.get_user(username)
+        if user and not user.disabled:
+            token = auth_handler.create_password_reset_token(username)
+            if token:
+                # Deliver token via email if email is configured and not suppressed
+                email = (user.metadata or {}).get("email", "")
+                if email:
+                    try:
+                        from core.auth.registration_notifications import _send
+
+                        reset_link = f"/reset-password?token={token}"
+                        display = user.display_name or username
+                        _send(
+                            [email],
+                            subject="OPB — Password Reset Request",
+                            html=(
+                                f"<p>Hello {display},</p>"
+                                f"<p>A password reset request was received for your account.</p>"
+                                f"<p><a href='{reset_link}'>Click here to reset your password</a></p>"
+                                f"<p>This link expires in 1 hour.</p>"
+                            ),
+                            plain=(
+                                f"Hello {display},\n\n"
+                                f"A password reset request was received for your account.\n"
+                                f"Reset link: {reset_link}\n"
+                                f"This link expires in 1 hour.\n"
+                            ),
+                        )
+                    except Exception as exc:
+                        _log.warning("[AUTH] Password reset email dispatch failed: %s", exc)
+
+                # Safe development/test fallback (strictly forbidden in production)
+                env = (os.getenv("OPBUYING_ENVIRONMENT") or os.getenv("ENVIRONMENT") or "").upper()
+                if env != "PRODUCTION" and (
+                    os.getenv("PYTEST_CURRENT_TEST") or os.getenv("OPB_AUTH_TEST_MODE") == "1"
+                ):
+                    _test_reset_tokens[username] = token
+
+        # Universal response: prevents account enumeration, never exposes plaintext token
         return {
             "success": True,
-            "message": "Password reset token generated successfully",
-            "token": token,
-            "reset_url": f"/reset-password?token={token}",
-            "expires_in": 3600
+            "message": "If the account exists, password reset instructions have been dispatched.",
         }
```

---

## 23. SECURITY TESTS
- `tests/test_password_reset_security.py`: **18 passed** in 98.00s.

---

## 24. AUTHENTICATION TESTS
- `tests/test_password_reset_recovery.py`: **5 passed** in 8.38s.
- `tests/test_auth_register.py` + `tests/test_auth_dependencies.py` + `tests/test_auth_csrf.py`: **72 passed** in 36.62s.
- `tests/test_auth_handler.py`: **104 passed** in 84.91s.

---

## 25. FULL REGRESSION
Total authentication & security regression: **199 tests executed, 199 passed, 0 failed, 0 skipped**.

---

## 26. PARTIAL-TEST EVIDENCE
None. All reported test suites executed to complete termination without partial interruption or timeouts.

---

## 27. RUFF
- Command: `python -m ruff check core/auth/routes.py tests/test_password_reset_security.py`
- Result: **All checks passed!** (Exit code 0).

---

## 28. TYPE CHECKS
- Python 3.11 static compile & import verification: **PASS**.

---

## 29. SECURITY CHECKS
- Plaintext token exposure: **REMOVED**.
- Account enumeration: **MITIGATED**.
- Single-use invalidation: **ENFORCED**.
- Expiration check: **ENFORCED**.
- Production fallback barrier: **ENFORCED**.

---

## 30. SEMVER
- Command: `pytest tests/test_semver_enforcement.py -v`
- Result: **16 passed** in 0.87s (Exit code 0).

---

## 31. DB VERIFICATION
- Expected SHA-256: `f12ba2e45e91077dbb3cfde289938aba225bd1669b9d02a7ddc5a49e57cd6e5a`
- Actual SHA-256: `f12ba2e45e91077dbb3cfde289938aba225bd1669b9d02a7ddc5a49e57cd6e5a`
- Expected Size: `1,216,512 bytes`
- Actual Size: `1,216,512 bytes`
- DB Immutability: **100% PRESERVED**.

---

## 32. GITHUB STATE
- Default branch: `master`
- HEAD: `9b3eb1183eb705ad275024a55c8008f4d85de866`
- Mutations during G1: **NONE (G1 remains strictly local)**.

---

## 33. EC2 STATE
- Host Git: `/home/ubuntu/auto-trade-system` at `9b3eb1183eb705ad275024a55c8008f4d85de866`
- Container: `opb_bot` running image `ghcr.io/gaurav-kiyu/auto-trade-system:2.60.0-post-merge.1` (healthy)
- Safety: `ENVIRONMENT=PAPER`, `SIGNAL_ONLY`, `LIVE_TRADING_LOCKOUT=True`, 0 live orders, 0 positions, ₹0 capital at risk
- Database: `/data/db/signals_history.db` preserved as live PAPER state
- Mutations during G1: **NONE (G1 is strictly local-only)**.

---

## 34. FIRST NEW DORMANT FAILURE
**NONE**. All 199 authentication tests, security tests, and SemVer tests passed with 0 failures.

---

## 35. FINAL CERTIFICATION
**`CERTIFIED — ADVANCE`** (Local G1 Authentication Hardening Certified; strictly held locally).
