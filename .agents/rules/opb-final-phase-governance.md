# OPB FINAL-PHASE CHANGE GOVERNANCE

**Rule ID:** OPB-FINAL-PHASE-GOVERNANCE-001  
**Applies To:** Entire OPB Auto-Trade System  
**Lifecycle:** Mandatory for every change after final architecture baseline  
**Authority:** Highest-level engineering governance rule for change/update work  
**Status:** ACTIVE  
**Principle:** NO ASSUMPTION-BASED COMPLETION  

---

# 1. PURPOSE

The OPB Auto-Trade System is already in its final/hardened phase.

Therefore, this repository MUST NOT be treated as a normal development project where an agent can freely modify code and declare completion after a local test passes.

Every future change MUST follow a controlled engineering lifecycle:

```text
REQUEST
   ↓
PRE-CHANGE DISCOVERY
   ↓
RCA / ROOT-CAUSE ANALYSIS
   ↓
IMPACT ANALYSIS
   ↓
RISK ANALYSIS
   ↓
DEPENDENCY / BLAST-RADIUS ANALYSIS
   ↓
IMPLEMENTATION PLAN
   ↓
CONTROLLED IMPLEMENTATION
   ↓
POST-CHANGE VALIDATION
   ↓
DEEP REGRESSION
   ↓
DOCUMENTATION SYNCHRONIZATION
   ↓
REPOSITORY / RELEASE HYGIENE
   ↓
FINAL EVIDENCE REVIEW
   ↓
COMMIT
   ↓
PUSH
   ↓
REMOTE VERIFICATION
   ↓
ONLY THEN: COMPLETE
```

No step may be silently skipped.

---

# 2. GOLDEN RULE

## NEVER DECLARE COMPLETION BASED ON ASSUMPTION.

The agent MUST distinguish between:
```text
PROVEN
```
and:
```text
ASSUMED
```

Only PROVEN results may be used as evidence for completion.

Statements such as:
* "should work"
* "looks correct"
* "probably fixed"
* "tests should pass"
* "no impact expected"
* "this should not affect trading"
* "documentation is probably still valid"
* "GitHub should be synchronized"
* "the change is safe"
* "I don't see any issue"

MUST NOT be treated as completion evidence.

If something could not be verified, explicitly report:
```text
NOT VERIFIED
```
and explain why.

---

# 3. FINAL-PHASE CHANGE PRINCIPLE

Before changing ANY existing functionality, determine:
1. Why is this change required?
2. What existing behavior does it modify?
3. What modules depend on that behavior?
4. What APIs/contracts may change?
5. What data models may be affected?
6. What configuration may be affected?
7. What documentation becomes stale?
8. What tests should change or be added?
9. What production behavior could be affected?
10. What rollback path exists?

The agent MUST NOT begin implementation until the above has been analyzed. For trivial changes, the analysis may be concise, but it must still exist.

---

# 4. PRE-CHANGE DISCOVERY

Before editing files, inspect the repository sufficiently to understand the affected architecture.
At minimum inspect:
```text
VERSION
README.md
architecture documentation
configuration templates
CI/CD workflows
relevant tests
relevant scripts
deployment files
Docker/Kubernetes files
related documentation
related modules
dependent modules
```

Search for: callers, imports, interfaces, subclasses, configuration references, environment variables, API routes, database tables/models, event types, CLI commands, scripts, tests, documentation references, version references.

Do NOT modify code simply because the requested file appears to be the obvious location.

---

# 5. MANDATORY RCA

For bug fixes, regressions, unexpected behavior, failures, or defects, perform a formal Root Cause Analysis answering:
- **Symptom**: What exactly failed?
- **Reproduction**: How was the failure reproduced?
- **Root cause**: What exact technical condition caused it?
- **Contributing factors**: Were there additional conditions that allowed the problem to occur?
- **Why existing tests did not catch it**: Identify the missing coverage or ineffective guard.
- **Corrective action**: What was changed?
- **Preventive action**: What prevents recurrence?
- **Verification**: What evidence proves the fix?

Never confuse `symptom` with `root cause`.

---

# 6. MANDATORY IMPACT ANALYSIS

Before implementation, determine the blast radius (NONE / LOW / MEDIUM / HIGH / CRITICAL) across:
- **Application**: UI, API, business logic, services, domain models, background jobs
- **Trading**: Market data, signals, strategies, risk, order creation, execution, broker adapters, reconciliation, positions, P&L
- **Data**: Database schema, migrations, persistence, event store, cache, historical data, configuration
- **Security**: Authentication, authorization, secrets, CSRF, sessions, permissions, admin operations
- **Operations**: Logging, metrics, alerts, health checks, monitoring, backup, recovery
- **Deployment**: Docker, Kubernetes, CI/CD, environment variables, scripts, `.bat`, startup/shutdown
- **Documentation**: README, guides, architecture, setup, runbooks, release notes

---

# 7. RISK ANALYSIS

Every non-trivial change MUST include:
```text
Risk:
Likelihood:
Impact:
Risk Level:
Mitigation:
Rollback:
Verification:
```

Trading-critical changes affecting risk, order execution, broker integration, capital, position calculation, reconciliation, market data, or strategy execution MUST be treated as HIGH or CRITICAL until evidence proves otherwise.

---

# 8. CONTRACT PRESERVATION

Identify contracts (public APIs, signatures, return types, schemas, configs, env vars, CLI args, route names, broker/persistence interfaces, test assumptions). Do not break an existing contract unintentionally.

---

# 9. IMPLEMENTATION RULE

Make the smallest safe change that completely solves the identified problem. Prefer targeted fixes over unnecessary refactors. Avoid speculative abstractions, unnecessary rewrites, broad dependency upgrades, or removing code without evidence.

---

# 10. TEST-FIRST & REGRESSION EXPECTATIONS

Every behavior change MUST have verification:
```text
Existing test + Regression test + Edge-case test + Integration test
```
Bug fixes must follow: `FAIL BEFORE FIX -> APPLY FIX -> PASS AFTER FIX`.

---

# 11. DEEP REGRESSION REQUIREMENT

Regression MUST be based on the actual blast radius across all affected layers (Risk, Signal, Portfolio, Execution, Trading Loop, Broker/Reconciliation, UI themes/responsive/console).

---

# 12. FAILURE-INJECTION REQUIREMENT

For critical paths, test appropriate failure scenarios (network, broker unavailable, delay, malformed payload, timeout, partial fill, duplicates, restart, database down, invalid inputs).

---

# 13. CONFIGURATION & DOCUMENTATION SYNCHRONIZATION

Verify version numbers, config templates, env vars, Docker/K8s/CI, startup scripts, and documentation agree across the entire codebase. Eliminate stale references.

---

# 14. CODE HYGIENE & SECURITY GATE

- Remove only artifacts proven to be dead (no caller, no import, no runtime, CLI, config, test, or contract dependency).
- Verify zero committed secrets (`.env`, credentials, tokens, private keys, passwords, database dumps).

---

# 15. FINAL EVIDENCE PACKAGE & COMPLETION GATE

The agent may say `COMPLETE` ONLY when ALL applicable gates are satisfied:
```text
[✓] Requested change implemented
[✓] RCA completed where applicable
[✓] Impact analysis completed
[✓] Risk analysis completed
[✓] Dependencies/blast radius reviewed
[✓] Regression coverage executed
[✓] Relevant tests PASS
[✓] Security checks completed
[✓] Configuration synchronized
[✓] Documentation synchronized
[✓] Scripts synchronized
[✓] Repository hygiene verified
[✓] No known unexplained regression
[✓] Git diff reviewed
[✓] Commit created
[✓] Push completed
[✓] Remote repository verified
```

If any mandatory gate is incomplete, the status MUST be `INCOMPLETE` or `PARTIALLY VERIFIED`.

---

# 16. FINAL RESPONSE FORMAT

When reporting completion, use this structure:
```text
CHANGE SUMMARY

RCA:
<result>

IMPACT:
<result>

RISK:
<result>

IMPLEMENTATION:
<result>

REGRESSION:
<actual numbers>

SECURITY:
<actual result>

DOCUMENTATION:
<actual result>

HYGIENE:
<actual result>

COMMIT:
<SHA>

PUSH:
<actual result>

REMOTE:
<actual verification>

FINAL STATUS:
COMPLETE / PARTIALLY VERIFIED / INCOMPLETE
```

---

# 17. ABSOLUTE PROHIBITION

Never claim tests passed, production validation, or GitHub synchronization without actual verification evidence. Never green-wash.

**Evidence over assumption.  
Regression over confidence.  
Traceability over convenience.  
Verified remote state over local state.**
