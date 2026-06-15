# Constitution Scoring Framework v1.0

**Authority:** Final Master System Constitution  
**Purpose:** Objective, evidence-based scoring across 23 categories  
**Update:** Versioned — every change increments the document version

---

## 1. Scoring Principles

1. **Evidence Required** — Scores above 8.0 require documented, objective evidence
2. **No Score Inflation** — Without evidence, no score may exceed 8.0
3. **9.0+ Requires Audit** — Architecture, security, risk, execution, testing, observability, DR, chaos, black swan audits
4. **10.0 is Perfection** — No system component may score 10.0; maximum achievable is 9.99
5. **Regressions Lower Score** — Any regression in a category automatically reduces score until remediated
6. **Continuous Scoring** — Scores are recalculated at every release

## 2. Scoring Rubric

| Score Range | Rating | Meaning |
|-------------|--------|---------|
| 9.5 – 9.99 | **Elite** | Institutional-grade, all audits passed, battle-tested |
| 9.0 – 9.49 | **Excellent** | All controls verified, minor improvements possible |
| 8.0 – 8.99 | **Strong** | All core controls in place, documented, tested |
| 7.0 – 7.99 | **Good** | Most controls in place, some gaps in documentation/tests |
| 6.0 – 6.99 | **Adequate** | Essential controls exist, significant gaps remain |
| 5.0 – 5.99 | **Weak** | Core controls present but incomplete |
| < 5.0 | **Failing** | Critical gaps — immediate remediation required |

## 3. 23 Scoring Categories

### Architecture (ARCH)

| ID | Criterion | Max Score | Evidence Required |
|----|-----------|-----------|-------------------|
| ARCH-01 | **Boundary enforcement** — Adapter pattern, no infra imports from core | 9.5 | Architecture compliance check at 0 violations |
| ARCH-02 | **Single responsibility** — Each module has one clear purpose | 9.0 | Module inventory with documented responsibilities |
| ARCH-03 | **Port/adapter separation** — Business logic isolated from I/O | 9.5 | Port definitions, adapter implementations, dependency injection |
| ARCH-04 | **No circular dependencies** — Clean import graph | 9.0 | Dependency graph analysis at 0 cycles |

### Security (SEC)

| ID | Criterion | Max Score | Evidence Required |
|----|-----------|-----------|-------------------|
| SEC-01 | **Authentication** — All admin endpoints require auth | 9.5 | Auth enforcement tests pass, no unprotected endpoints |
| SEC-02 | **Authorization/RBAC** — Role-based access control enforced | 9.5 | RBAC tests pass, permission matrix documented |
| SEC-03 | **Secret management** — No hardcoded secrets, env-based config | 9.5 | Secret scanner passes, env template documented |
| SEC-04 | **Audit trail** — All mutations logged with identity | 9.5 | Audit log tests pass, every mutation recorded |

### Risk (RSK)

| ID | Criterion | Max Score | Evidence Required |
|----|-----------|-----------|-------------------|
| RSK-01 | **Hard halt enforcement** — Kill switch blocks all entries | 9.9 | Hard halt tests pass, trip verification |
| RSK-02 | **Loss limits** — MAX_DAILY_LOSS, MAX_DRAWDOWN enforced | 9.9 | Risk engine tests verify limit enforcement |
| RSK-03 | **Position sizing** — VIX-scaled, Kelly-criterion aware | 9.0 | Position sizer tests, scaling verification |
| RSK-04 | **Fail-closed** — All errors default to trading blocked | 9.5 | Chaos tests verify fail-closed behavior |

### Execution (EXE)

| ID | Criterion | Max Score | Evidence Required |
|----|-----------|-----------|-------------------|
| EXE-01 | **Exactly-once semantics** — No duplicate orders | 9.9 | Exactly-once certification tests pass (9/9) |
| EXE-02 | **Idempotent retry** — Retries safe, no side effects | 9.5 | Retry safety tests pass |
| EXE-03 | **State machine correctness** — All transitions valid | 9.5 | State machine tests cover all transitions |
| EXE-04 | **Reconciliation** — Broker truth matches local state | 9.5 | Reconciliation tests pass |

### Testing (TST)

| ID | Criterion | Max Score | Evidence Required |
|----|-----------|-----------|-------------------|
| TST-01 | **Test coverage** — >80% line coverage on core modules | 9.0 | Coverage report, module-by-module breakdown |
| TST-02 | **Chaos testing** — Broker outage, DB corruption, network failures | 9.9 | Chaos scenario results (24/24 pass) |
| TST-03 | **Contract testing** — Broker contract certification | 9.5 | Contract tests pass (26/26) |
| TST-04 | **Regression testing** — Full suite passes before release | 9.0 | CI pipeline shows all tests passing |

### Observability (OBS)

| ID | Criterion | Max Score | Evidence Required |
|----|-----------|-----------|-------------------|
| OBS-01 | **Structured logging** — JSONL audit log, all events timestamped | 9.0 | Log format verification, completeness check |
| OBS-02 | **Metrics** — Prometheus metrics on configurable port | 9.0 | Metrics exporter test, endpoint verification |
| OBS-03 | **Health checks** — DB, ML, config, disk health | 9.0 | Health checker tests pass |
| OBS-04 | **Alerting** — Telegram alerts for CRITICAL/HIGH events | 9.0 | Alert routing tests pass |

### Governance (GOV)

| ID | Criterion | Max Score | Evidence Required |
|----|-----------|-----------|-------------------|
| GOV-01 | **Documentation sync** — README, architecture, runbooks current | 9.5 | Documentation sync log verified |
| GOV-02 | **Repository hygiene** — No build artifacts, test debris, stale files | 9.0 | .gitignore verified, clean tree |
| GOV-03 | **Technical debt tracking** — Register maintained, items resolved | 9.0 | Technical debt register updated |
| GOV-04 | **Release governance** — Reproducible, tagged, checksummed | 9.5 | Release pipeline verified |

### Disaster Recovery (DR)

| ID | Criterion | Max Score | Evidence Required |
|----|-----------|-----------|-------------------|
| DR-01 | **Database migration** — Schema versioning, forward/backward | 9.0 | DB migration tests pass |
| DR-02 | **State persistence** — trader_state.json survives restart | 9.0 | Restart recovery tests pass |
| DR-03 | **WAL journal** — Write-ahead intent journal for crash recovery | 9.5 | WAL journal tests pass |

## 4. Scoring Formula

```
category_score = min(
    max_score,
    base_score + evidence_score - regression_penalty
)

where:
  base_score = 5.0 (always starts at adequate)
  evidence_score = sum of verified evidence items × weight
  regression_penalty = 2.0 per open regression item
  category_score capped at max_score

overall_score = avg(all category_scores)
```

## 5. Evidence Weights

| Evidence Type | Weight | Description |
|---------------|--------|-------------|
| Automated test pass | 0.5 | Verified by CI pipeline |
| Manual test pass | 0.3 | Verified by operator |
| Code review | 0.2 | Reviewed by peer |
| Documentation | 0.1 | Documented in docs/ |
| Audit log | 0.4 | Verified from audit trail |
| Chaos scenario | 0.6 | Survived chaos injection |
| Production run | 0.8 | Verified in production (n sessions) |

## 6. Audit Requirements for 9.0+

To achieve a score of 9.0 or higher in any category, the following audits are required:

| Audit Type | Required For |
|------------|-------------|
| Architecture audit | Any 9.0+ category |
| Security audit | Any 9.0+ category |
| Risk audit | RSK categories |
| Execution audit | EXE categories |
| Testing audit | TST categories |
| Observability audit | OBS categories |
| Disaster recovery audit | DR categories |
| Chaos audit | Any 9.5+ category |
| Black swan audit | Any 9.5+ category |

## 7. Score Report Format

```json
{
  "timestamp": "2026-05-30T00:00:00Z",
  "version": "2.53.0",
  "categories": {
    "ARCH-01": {
      "score": 9.5,
      "max_score": 9.5,
      "evidence": [
        "Architecture compliance check: 0 violations",
        "Core modules: no infrastructure imports verified"
      ],
      "audits": ["architecture"],
      "regressions": []
    }
  },
  "overall_score": 8.7,
  "total_evidence_items": 42,
  "open_regressions": 1
}
```

---

*End of Constitution Scoring Framework — v1.0*
