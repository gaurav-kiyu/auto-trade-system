# AI Governance Guide v1.0

**Authority:** Final Master System Constitution, Article: AI Governance  
**Purpose:** Mandatory pre-implementation protocol for all AI agents, models, and automation systems  
**Enforcement:** `core/constitution_ai_gate.py` — validates acknowledgment before changes are allowed

---

## 1. Preamble

Every AI agent, model, assistant, automation system, or contributor interacting with this codebase MUST:

1. **Read this guide** before making any changes
2. **Acknowledge the Constitution** by reading core documents
3. **Validate understanding** through the AI governance gate
4. **Proceed only after validation** — no exceptions

## 2. Mandatory Reading Order

Before ANY change, the AI MUST read these documents in order:

| # | Document | Purpose |
|---|----------|---------|
| 1 | `CLAUDE.md` | Project overview, conventions, entry points, risk rules |
| 2 | `FINAL_MASTER_SYSTEM_CONSTITUTION` (session context) | Governing principles and mandates |
| 3 | `docs/constitution_scoring_framework.md` | Evidence-based scoring criteria |
| 4 | `docs/technical_debt.md` | Known technical debt and open items |
| 5 | `docs/ownership_matrix.md` | Module ownership responsibilities |
| 6 | `docs/REMEDIATION_REPORT.md` | Recent fixes and remaining gaps |

## 3. Acknowledgment Protocol

Before implementing any change, the AI must:

```
STEP 1: ACKNOWLEDGE
  "I have read the Final Master System Constitution."
  "I acknowledge that CORRECTNESS > FEATURES and SAFETY > SPEED."
  "I will follow the Mandatory Change Pipeline: Review → Impact → Design → Implement → Test → Validate → Doc → Audit → Accept → Release."

STEP 2: GATHER CONTEXT
  "I have read CLAUDE.md and understand the project conventions."
  "I have reviewed the relevant architecture documents."
  "I have reviewed the technical debt register."

STEP 3: IMPACT ANALYSIS
  "I have identified all files that will be affected by this change."
  "I have verified no risk controls will be bypassed."
  "I have verified no safety invariants will be violated."

STEP 4: PROCEED
  → Only after Steps 1-3 are complete.
  → If any step fails: STOP, ask for clarification.
```

## 4. Forbidden Actions

AI agents MUST NEVER:

1. **Bypass risk controls** — Never modify `_trip_hard_halt()`, `MAX_DAILY_LOSS`, `MAX_DRAWDOWN`, `SL_PCT`, `TARGET_PCT`, `TRAIL_PCT`
2. **Remove safety invariants** — Never disable hard halt, circuit breaker, kill file, capital reservation lock
3. **Direct broker SDK calls outside adapters** — All broker calls go through `core/adapters/broker_adapters.py`
4. **Break paper mode invariant** — Real broker SDK must never be instantiated in paper mode
5. **Use `datetime.now()` directly** — Always use `core.datetime_ist.now_ist()`
6. **Hardcode config values** — All values go through the 3-layer config merge
7. **Delete tests** — Unless replaced by equivalent or better coverage
8. **Commit without full test suite passing** — All 2442+ tests must pass
9. **Skip documentation updates** — Every code change requires doc sync
10. **Modify this guide** — Only human operators may update AI governance rules

## 5. Change Pipeline Validation

Every change MUST follow this 10-step pipeline. The AI governance gate validates each step:

```
┌─────────────┐
│ 1. Review   │  Read constitution, CLAUDE.md, architecture, audit history
├─────────────┤
│ 2. Impact   │  Analyze all affected files, modules, config, tests
├─────────────┤
│ 3. Design   │  Plan the change with consideration for risk and safety
├─────────────┤
│ 4. Implement│  Write code following project conventions
├─────────────┤
│ 5. Test     │  Run tests, verify no regressions
├─────────────┤
│ 6. Validate │  Code review, architecture compliance check
├─────────────┤
│ 7. Doc Sync │  Update README, architecture docs, runbooks
├─────────────┤
│ 8. Audit    │  Record the change in audit trail
├─────────────┤
│ 9. Accept   │  Final verification and sign-off
├─────────────┤
│10. Release  │  Commit, tag, push, generate release notes
└─────────────┘
```

## 6. Evidence Requirements

| Score Range | Evidence Required | Validation |
|-------------|-------------------|------------|
| Any change | Context gathering completed | AI gate check |
| Score-critical change | Evidence attached to change | Manual review |
| Risk-sensitive change | Risk impact statement | Manual approval |
| Security-sensitive change | Security impact statement | Security review |
| Breaking change | Migration guide included | Architecture review |

## 7. Enforcement

The AI governance gate (`core/constitution_ai_gate.py`) enforces:

1. **Constitution acknowledgment** — AI must acknowledge reading the constitution
2. **Context gathering** — AI must read relevant files before changes
3. **Evidence attachment** — Score changes require evidence
4. **Pipeline validation** — Each step must be completed before proceeding

If the gate validation fails, the AI MUST stop and report the failure. No changes may proceed through a failed gate.

## 8. Escalation

If the AI encounters:

- **Ambiguous requirements** — Ask for clarification before proceeding
- **Conflicting rules** — Safety > Feature > Convenience > Governance
- **Missing context** — Read more files before deciding
- **Risk violation** — Stop immediately, report the violation
- **Gate failure** — Stop, explain the failure, seek human intervention

---

*End of AI Governance Guide — v1.0*
