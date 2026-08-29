# 🛡️ MANDATORY LIVE TESTING & PRE/POST-GUARD GOVERNANCE SKILL PROTOCOL

**Protocol Name:** `mandatory-live-testing-governance`  
**Version:** 1.0.0 (Strict Execution Standard)  
**Scope:** Applies unconditionally to every task, feature update, bug fix, or delivery request across the GAURAV™ Super-Platform codebase.

---

## 🛑 MANDATORY STEP 1: PRE-IMPLEMENTATION GUARD & ANALYSIS
Before modifying any source file or declaring analysis complete:
1. Run pre-implementation compliance check:
   ```bash
   python scripts/pre_implementation_check.py --verify-analysis
   ```
2. Verify zero architecture or release state violations before making edits.

---

## 🧪 MANDATORY STEP 2: REAL-TIME ENDPOINT & ROUTE AUDIT
After making code edits:
1. Execute full live route and navigation link verification:
   ```bash
   python scratch/test_page_routes_only.py
   ```
2. Verify that **100% of tested routes (25/25)** return HTTP 200/303/307 status codes.
3. Verify that **no card or table displays empty hyphens (`-`), zeroes (`0.0`), or blank unpopulated placeholders**.

---

## 🪵 MANDATORY STEP 3: LOG INSPECTION & WARNING RESOLUTION
1. Fetch and inspect live terminal server logs (`logs/index_trader.log`, `logs/enterprise_dashboard.log`, Uvicorn output).
2. Ensure **zero attribute errors, missing SQL column exceptions, or silent warnings** are emitted during request lifecycles.
3. Every log warning must be traced to root cause (RCA) and fixed before proceeding.

---

## 🔍 MANDATORY STEP 4: POST-EXECUTION MULTI-TIER AUDIT
Before presenting work to the user:
1. **Database Integrity Check:**
   ```bash
   python scripts/check_db_integrity.py
   ```
   *Requirement:* Must return `Summary: 17/17 healthy (100% OK)`.
2. **PR Audit Quality Gate:**
   ```bash
   python scripts/run_pr_audit.py
   ```
   *Requirement:* Must return `Overall Score: 100.0/100` with `0 Findings`.
3. **Ruff Lint & Syntax Check:**
   ```bash
   python -m ruff check core/
   ```
   *Requirement:* 0 lint errors.

---

## 🚫 MANDATORY RULE: NO PREMATURE "100% DONE" DECLARATIONS
The AI assistant must NEVER state that a task is "100% Complete", "Fully Verified", or "Delivered" without attaching concrete, empirical log evidence from all 4 mandatory steps above.
