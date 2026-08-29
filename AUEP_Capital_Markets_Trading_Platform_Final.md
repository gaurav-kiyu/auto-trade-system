# Autonomous Universal Engineering Protocol (AUEP)

## Capital Markets / Trading Platform Edition --- Consolidated Final Specification

**Document Type:** Engineering Governance & Autonomous Audit Protocol\
**Primary Use Case:** SBSGPES / Indian Capital Market Super-App\
**Protocol Purpose:** Safe repository discovery, architecture
reconstruction, domain-aware auditing, controlled remediation,
verification, evidence generation, and engineering certification.

------------------------------------------------------------------------

# 1. Purpose

The Autonomous Universal Engineering Protocol (AUEP) defines a
controlled, evidence-driven workflow for analyzing, testing, improving,
and maintaining large software systems.

For capital-market systems, AUEP is specifically designed to operate
under strict safety controls because defects can affect:

-   Orders and executions
-   Positions and holdings
-   Margin and leverage
-   Portfolio valuation
-   P&L
-   Financial calculations
-   Market data
-   Broker integrations
-   User funds and financial records
-   Security and authorization
-   Regulatory/audit trails
-   System availability and reliability

AUEP is an **engineering execution protocol**. It does not replace the
application's business requirements, architecture standards, regulatory
requirements, risk policy, or master product constitution.

For SBSGPES, AUEP should operate underneath the application's master
engineering/governance constitution.

------------------------------------------------------------------------

# 2. Protocol Hierarchy

The recommended governance hierarchy is:

``` text
MASTER CONSTITUTION / PRODUCT GOVERNANCE
│
├── Business Requirements
├── Capital-Market Rules
├── Architecture Standards
├── Security Requirements
├── Financial Correctness Rules
├── OMS / RMS Requirements
├── Market-Data Requirements
├── Performance / SRE Requirements
├── Testing Requirements
├── Evidence & Certification Requirements
│
└── AUEP — Engineering Execution Protocol
    ├── Discovery
    ├── Architecture Reconstruction
    ├── Domain Context Activation
    ├── Audit
    ├── Impact Analysis
    ├── Controlled Remediation
    ├── Verification
    ├── Cleanup
    └── Certification Evidence
```

AUEP controls **how engineering analysis and remediation are
performed**.

The master constitution controls **what the system must satisfy**.

------------------------------------------------------------------------

# 3. Core Operating Principles

The autonomous engineering agent MUST follow these principles:

1.  **Evidence before conclusions.**
2.  **Understand before modifying.**
3.  **Never guess unknown APIs, libraries, broker behaviour, schemas, or
    business rules.**
4.  **Never make production-critical financial changes automatically
    without explicit approval.**
5.  **Never delete files automatically.**
6.  **Never expand beyond the declared impact scope without
    justification.**
7.  **Prefer minimal, reversible changes.**
8.  **Verify every modification.**
9.  **Maintain traceability between finding, fix, test, and evidence.**
10. **Treat financial correctness as a higher priority than
    convenience.**
11. **Treat security, data integrity, order integrity, and risk controls
    as critical.**
12. **Do not claim verification unless actual evidence exists.**
13. **If repository context becomes uncertain, stop and re-index.**
14. **Preserve backward compatibility unless breaking change is
    explicitly approved.**
15. **Do not optimize code at the expense of correctness, auditability,
    or risk controls.**

------------------------------------------------------------------------

# 4. Safety Classification

Every affected component MUST be classified.

## CRITICAL

Examples:

-   Order execution
-   Risk engine
-   Margin calculation
-   Leverage
-   Position calculation
-   Portfolio ledger
-   Financial calculations
-   Broker/exchange adapters
-   Authentication
-   Authorization
-   Kill switch
-   Liquidation logic
-   Market-data normalization
-   Corporate-action processing
-   User financial balances

**Rule:** No autonomous production modification.

Explicit human approval is mandatory.

## HIGH

Examples:

-   Database schema
-   Transaction processing
-   Portfolio analytics
-   Market-data storage
-   API contracts
-   WebSocket processing
-   Security controls
-   Caching of financial data
-   Reconciliation processes

Changes require strong automated regression evidence and review.

## MEDIUM

Examples:

-   Non-critical business services
-   Reporting
-   Search
-   Notifications
-   Analytics
-   UI workflows

Controlled automated remediation may be allowed.

## LOW

Examples:

-   Formatting
-   Documentation
-   Non-functional cleanup
-   Safe lint fixes
-   Unused imports

Automated remediation may be allowed when validated.

------------------------------------------------------------------------

# 5. Phase 0 --- Governance & Safety Lock

Before repository analysis or modification:

1.  Identify application type.
2.  Identify production-critical modules.
3.  Establish safety classification.
4.  Establish whether the requested task permits modifications.
5.  Establish approval requirements.
6.  Establish available build/test/lint commands.
7.  Establish repository boundaries.
8.  Establish excluded paths, if any.
9.  Establish whether external APIs or credentials are available.
10. Establish whether the environment is development, staging, or
    production.

The agent MUST NOT modify production-critical components merely because
a defect is detected.

------------------------------------------------------------------------

# 6. Phase 1 --- Deep Discovery & Indexing

## Mandatory First Step

No files may be modified, created, moved, renamed, or deleted during
this phase.

The entire workspace/repository MUST be scanned recursively, subject to
explicitly defined repository boundaries.

## Inventory

Produce a structured inventory of:

### Application

-   Entry points
-   Main applications
-   Services
-   Modules
-   Controllers
-   APIs
-   Background workers
-   Scheduled jobs
-   CLI tools
-   UI entry points

### Configuration

-   Application configuration
-   Environment configuration
-   Feature flags
-   Dependency injection
-   Build configuration
-   Deployment configuration
-   Infrastructure configuration
-   Secret references

### Business Logic

-   Domain models
-   Services
-   Managers
-   Engines
-   Rules
-   Calculators
-   Validators
-   State machines
-   Workflow handlers

### Data

-   Database contexts
-   Repositories
-   SQL scripts
-   Stored procedures
-   Migrations
-   Schemas
-   Caches
-   Queues
-   Event stores
-   File storage

### External Integrations

-   Broker APIs
-   Exchange APIs
-   Market-data providers
-   Payment systems
-   Notification providers
-   Authentication providers
-   Third-party services

### Testing

-   Unit tests
-   Integration tests
-   Contract tests
-   API tests
-   End-to-end tests
-   Performance tests
-   Security tests
-   Fixtures
-   Mock data
-   Test databases
-   Test utilities

### DevOps

-   CI/CD
-   Build scripts
-   Deployment manifests
-   Containers
-   Infrastructure-as-code
-   Monitoring
-   Alerting
-   Logging

### Documentation

-   Architecture documents
-   API specifications
-   Business rules
-   Runbooks
-   Operational documentation
-   ADRs
-   Developer documentation

### Cleanup Candidates

-   Build artifacts
-   Temporary files
-   Orphaned scripts
-   Duplicate files
-   Legacy modules
-   Unreferenced configuration
-   Deprecated code

------------------------------------------------------------------------

# 7. Repository Dependency Map

The agent MUST construct a logical dependency graph.

At minimum identify:

``` text
UI
 ↓
API
 ↓
Application Services
 ↓
Domain / Business Logic
 ↓
Data Access
 ↓
Database
```

For capital-market systems additionally identify:

``` text
Market Data
 ↓
Validation / Normalization
 ↓
Market Data Distribution
 ↓
Strategy / Analytics
 ↓
Signal Engine
 ↓
Order Manager
 ↓
Risk Engine
 ↓
OMS
 ↓
Broker Adapter
 ↓
Broker / Exchange
 ↓
Execution Events
 ↓
Portfolio / Position / Ledger
 ↓
Analytics / Reporting
```

The agent MUST identify direct and indirect dependencies.

------------------------------------------------------------------------

# 8. Phase 2 --- Architecture & Data-Flow Reconstruction

Before proposing significant changes, state the current understanding
of:

-   Application architecture
-   Service boundaries
-   Module responsibilities
-   Data flow
-   Control flow
-   State transitions
-   Database interactions
-   External API interactions
-   Authentication flow
-   Authorization flow
-   Market-data flow
-   Order flow
-   Position flow
-   Portfolio flow
-   Error-handling flow
-   Logging/audit flow
-   Deployment flow

The agent MUST explicitly distinguish:

``` text
CONFIRMED
INFERRED
UNKNOWN
```

Unknown behaviour MUST NOT be invented.

If architecture cannot be understood with reasonable confidence, stop
and request clarification or additional evidence.

------------------------------------------------------------------------

# 9. Phase 3 --- Domain-Specific Context Activation

Activate only the domain rules relevant to the detected application.

For SBSGPES, the following capital-market rules MUST be activated.

------------------------------------------------------------------------

# 10. Capital Markets / Trading Platform Rules

## 10.1 Order Integrity

Audit:

-   Order creation
-   Validation
-   Order state transitions
-   Idempotency
-   Duplicate-order prevention
-   Retry behaviour
-   Partial fills
-   Full fills
-   Rejections
-   Cancellations
-   Modifications
-   Expirations
-   Broker acknowledgement
-   Exchange acknowledgement
-   Execution events
-   Order reconciliation

A valid order lifecycle MUST be enforced.

Example:

``` text
NEW
 ↓
VALIDATING
 ↓
RISK_CHECK
 ↓
SUBMITTED
 ↓
ACKNOWLEDGED
 ↓
PARTIALLY_FILLED
 ↓
FILLED
```

Invalid transitions such as:

``` text
FILLED → NEW
```

MUST be prevented.

------------------------------------------------------------------------

# 11. OMS Safety Lock

The agent MUST NOT automatically modify:

-   Order routing
-   Order execution
-   Order quantity calculation
-   Order price calculation
-   Order retry rules
-   Order state machine
-   Broker routing
-   Exchange routing
-   Order cancellation logic
-   Order modification logic
-   Idempotency logic

without explicit human approval when the change can affect real
financial execution.

------------------------------------------------------------------------

# 12. RMS Safety Lock

The agent MUST NOT automatically modify:

-   Position limits
-   Exposure limits
-   Margin calculations
-   Leverage
-   Buying power
-   Capital allocation
-   Stop-loss logic
-   Liquidation logic
-   Risk checks
-   Circuit-limit protection
-   Maximum order quantity
-   Maximum order value
-   Broker risk rules
-   Kill-switch logic

without explicit approval.

For every proposed RMS modification, produce:

1.  Current behaviour
2.  Proposed behaviour
3.  Affected rules
4.  Affected modules
5.  Business impact
6.  Failure scenarios
7.  Test evidence
8.  Regression evidence
9.  Human approval requirement

------------------------------------------------------------------------

# 13. Market Data Integrity

Audit the complete market-data pipeline:

``` text
Provider / Exchange
 ↓
Connection
 ↓
Authentication
 ↓
Subscription
 ↓
Raw Data
 ↓
Validation
 ↓
Normalization
 ↓
Timestamp Validation
 ↓
Sequence / Ordering Validation
 ↓
Deduplication
 ↓
Storage / Cache
 ↓
Distribution
 ↓
Consumers
```

Check for:

-   Missing ticks
-   Duplicate ticks
-   Out-of-order ticks
-   Stale prices
-   Invalid timestamps
-   Timezone errors
-   Invalid OHLC values
-   Invalid volume
-   Negative or impossible values
-   Corporate-action adjustments
-   Trading-session boundaries
-   Market holidays
-   Feed interruptions
-   Sequence gaps
-   Reconnect behaviour
-   REST fallback
-   Feed failover
-   Data reconciliation

------------------------------------------------------------------------

# 14. WebSocket Integrity

Verify:

``` text
CONNECT
 ↓
AUTHENTICATE
 ↓
SUBSCRIBE
 ↓
HEARTBEAT
 ↓
RECEIVE
 ↓
VALIDATE
 ↓
SEQUENCE CHECK
 ↓
GAP DETECTION
 ↓
RECONNECT
 ↓
RESUBSCRIBE
 ↓
RECONCILE MISSED DATA
```

A simple reconnect is not sufficient.

The system MUST determine whether data was missed during disconnection.

------------------------------------------------------------------------

# 15. Financial Calculation Integrity

Audit:

-   Decimal precision
-   Rounding
-   Currency conversion
-   Brokerage
-   Taxes
-   Transaction charges
-   STT
-   GST
-   Stamp duty
-   Exchange charges
-   Realized P&L
-   Unrealized P&L
-   Average price
-   Quantity
-   Position valuation
-   Portfolio valuation
-   Corporate actions
-   Dividends
-   Splits
-   Bonuses
-   Rights issues
-   Mergers
-   Demergers

Critical monetary calculations MUST use appropriate fixed-precision
decimal handling.

Floating-point representations MUST NOT be used for critical financial
values unless explicitly justified and proven safe.

------------------------------------------------------------------------

# 16. Position & Portfolio Integrity

Verify:

-   Position creation
-   Position increase
-   Position reduction
-   Position closure
-   Average price
-   Realized P&L
-   Unrealized P&L
-   Holdings
-   Cash balance
-   Margin
-   Collateral
-   Exposure
-   Portfolio valuation
-   Reconciliation

The system MUST prevent silent divergence between:

``` text
Orders
Executions
Positions
Holdings
Ledger
Cash
Portfolio
Broker State
```

------------------------------------------------------------------------

# 17. Reconciliation

The platform MUST support reconciliation where applicable between:

``` text
Internal OMS
        ↕
Broker
        ↕
Exchange / External Source
```

Audit:

-   Missing executions
-   Duplicate executions
-   Unknown executions
-   Quantity mismatches
-   Price mismatches
-   Position mismatches
-   Cash mismatches
-   Order-state mismatches

All reconciliation failures MUST be traceable and auditable.

------------------------------------------------------------------------

# 18. Security Rules

Audit:

### Authentication

-   Login
-   MFA
-   Token handling
-   Session management
-   Token expiry
-   Refresh mechanisms
-   Logout
-   Device/session controls

### Authorization

-   RBAC
-   Permissions
-   Resource-level authorization
-   Privilege escalation
-   Administrative access
-   API authorization

### Application Security

-   Input validation
-   SQL injection
-   XSS
-   CSRF
-   SSRF
-   Command injection
-   Path traversal
-   Deserialization risks
-   Dependency vulnerabilities
-   Rate limiting

### Secrets

API keys, broker credentials, database credentials, certificates, and
tokens MUST NOT be hardcoded.

Secrets MUST be retrieved through approved secret/environment
configuration mechanisms.

Never expose secrets through:

-   Source code
-   Logs
-   Error messages
-   Client-side code
-   Test fixtures
-   Public configuration

------------------------------------------------------------------------

# 19. Database Integrity

Audit:

-   Schema integrity
-   Foreign keys
-   Primary keys
-   Unique constraints
-   Duplicate records
-   Indexes
-   Missing indexes
-   Query plans
-   Long-running queries
-   Deadlocks
-   Race conditions
-   Transactions
-   Isolation levels
-   Connection pooling
-   Migration safety
-   Backup/recovery
-   Data retention
-   Audit history

Financial records MUST NOT be silently overwritten without appropriate
auditability.

------------------------------------------------------------------------

# 20. Transaction Integrity

For financial operations verify:

``` text
BEGIN
 ↓
VALIDATE
 ↓
EXECUTE
 ↓
PERSIST
 ↓
AUDIT
 ↓
COMMIT
```

Failure scenarios MUST be tested.

If a partial operation occurs, the system MUST define whether to:

-   Roll back
-   Compensate
-   Retry
-   Reconcile
-   Flag for manual intervention

------------------------------------------------------------------------

# 21. API Integrity

Audit:

-   API contracts
-   Request validation
-   Response validation
-   Authentication
-   Authorization
-   Versioning
-   Idempotency
-   Pagination
-   Rate limiting
-   Error handling
-   Timeout handling
-   Retry handling
-   Backward compatibility

External APIs MUST NOT be assumed to behave in undocumented ways.

If an API method or broker behaviour is unknown, flag it for manual
verification.

------------------------------------------------------------------------

# 22. Performance & SRE

Audit:

-   API latency
-   Database latency
-   Market-data latency
-   Order submission latency
-   WebSocket processing latency
-   CPU
-   Memory
-   Thread pool
-   Connection pools
-   Cache hit ratio
-   Queue depth
-   Throughput
-   Garbage collection
-   Lock contention
-   Deadlocks
-   Network calls
-   Blocking operations

Where possible measure:

``` text
P50
P95
P99
P99.9
```

Do not claim that a system is "fast" without measurable evidence.

------------------------------------------------------------------------

# 23. Latency Protection

Identify:

-   Blocking network calls
-   Synchronous I/O
-   Unbounded retries
-   Excessive serialization
-   N+1 queries
-   Repeated database calls
-   Inefficient loops
-   Lock contention
-   Excessive allocations
-   Unnecessary polling

Optimization MUST NOT compromise correctness, risk controls, or
auditability.

------------------------------------------------------------------------

# 24. Reliability & Recovery

Verify:

-   Timeout handling
-   Retry policy
-   Exponential backoff
-   Circuit breakers
-   Connection recovery
-   Service restart
-   State recovery
-   Queue recovery
-   Database recovery
-   Broker recovery
-   Market-data recovery
-   Graceful degradation
-   Disaster recovery

For every external dependency determine:

``` text
Normal
Timeout
Failure
Partial Failure
Recovery
Reconciliation
```

------------------------------------------------------------------------

# 25. Phase 4 --- Testing & Quality Assurance

Testing MUST be risk-based.

Required test categories where applicable:

``` text
Unit
Integration
Contract
API
Database
Market Data
OMS
RMS
Broker
WebSocket
End-to-End
Regression
Performance
Load
Stress
Chaos
Security
Recovery
```

Critical financial functionality SHOULD additionally have:

-   Positive tests
-   Negative tests
-   Boundary tests
-   Concurrency tests
-   Failure-injection tests
-   Replay tests
-   Idempotency tests
-   Recovery tests

------------------------------------------------------------------------

# 26. Flakiness Audit

Identify:

-   Hardcoded delays
-   Arbitrary sleeps
-   Fixed browser waits
-   Timing-sensitive assertions
-   Shared test state
-   Random test dependencies
-   Order-dependent tests
-   Environment-dependent tests

Prefer:

-   Event-based waits
-   Dynamic polling
-   Explicit readiness checks
-   Deterministic fixtures

------------------------------------------------------------------------

# 27. Test Resource Recovery

Every test suite MUST properly clean up:

-   Browser contexts
-   Database connections
-   Transactions
-   Temporary files
-   Test users
-   Sessions
-   Network connections
-   WebSockets
-   Logs
-   Containers
-   Queues
-   Test data

No test should contaminate another test through shared state.

------------------------------------------------------------------------

# 28. Test State Isolation

Verify:

-   Cookies
-   Authentication sessions
-   Database state
-   Cache state
-   Local storage
-   Temporary files
-   Mock state
-   Environment variables
-   Queues

Tests MUST be independently executable unless intentional dependency is
explicitly documented.

------------------------------------------------------------------------

# 29. Phase 5 --- Deep Impact Analysis

For every requested change or detected anomaly, map:

-   Direct dependencies
-   Indirect dependencies
-   Imported modules
-   Consumers
-   State changes
-   Database changes
-   API changes
-   External API effects
-   Cache effects
-   Queue effects
-   Security effects
-   Performance effects
-   Test effects

Produce a Change Impact Matrix.

Example:

  Area             Impact     Risk       Evidence Required
  ---------------- ---------- ---------- -------------------
  Order Manager    Direct     Critical   Mandatory
  Risk Engine      Indirect   Critical   Mandatory
  Database         None       Low        Verification
  API              Direct     High       Mandatory
  UI               None       Low        Verification
  Broker Adapter   Indirect   High       Mandatory
  Tests            Direct     Medium     Mandatory

------------------------------------------------------------------------

# 30. Impact Scope Rule

The agent MUST NOT modify files outside the declared impact scope
unless:

1.  A dependency is discovered.
2.  The dependency is documented.
3.  The expanded impact is explained.
4.  The additional change is necessary.
5.  The additional risk is evaluated.

Unrelated cleanup MUST NOT be mixed into a functional fix.

------------------------------------------------------------------------

# 31. Phase 6 --- Root Cause Analysis

Do not treat symptoms as root causes.

For every significant defect:

``` text
Observed Problem
 ↓
Reproduction
 ↓
Failure Point
 ↓
Root Cause
 ↓
Contributing Factors
 ↓
Business Impact
 ↓
Technical Impact
 ↓
Corrective Action
 ↓
Regression Protection
```

Use evidence from:

-   Source code
-   Tests
-   Logs
-   Database
-   Configuration
-   Runtime behaviour
-   Metrics
-   API traces
-   Historical changes

------------------------------------------------------------------------

# 32. Phase 7 --- Controlled Auto-Healing

Fixes MUST be incremental.

For each module:

1.  Understand.
2.  Identify defect.
3.  Determine impact.
4.  Create minimal fix.
5.  Validate syntax.
6.  Run targeted tests.
7.  Run relevant integration tests.
8.  Run regression tests.
9.  Review diff.
10. Record evidence.

Do not modify multiple unrelated modules in a single uncontrolled
operation.

------------------------------------------------------------------------

# 33. Auto-Fix Permission Matrix

## Automatically Fixable

Generally safe when validated:

-   Formatting
-   Lint violations
-   Unused imports
-   Documentation
-   Safe test cleanup
-   Non-functional refactoring
-   Clearly unused local variables
-   Safe static-analysis fixes

## Approval Required

Always require human approval when modifying:

-   OMS
-   RMS
-   Order execution
-   Financial calculations
-   Portfolio ledger
-   Position calculation
-   Broker integration
-   Exchange integration
-   Authentication
-   Authorization
-   Database schema
-   Market-data normalization
-   Corporate-action logic
-   Margin
-   Leverage
-   Kill switch
-   Liquidation
-   Security boundaries

------------------------------------------------------------------------

# 34. Verification After Every Fix

At minimum verify:

``` text
Syntax
 ↓
Compilation / Build
 ↓
Targeted Unit Tests
 ↓
Integration Tests
 ↓
Regression Tests
 ↓
Static Analysis
 ↓
Security Checks
 ↓
Performance Checks where applicable
```

For critical components, add failure-injection and boundary tests where
practical.

------------------------------------------------------------------------

# 35. Before/After Behaviour

Every significant fix MUST document:

``` text
Before
- Existing behaviour
- Failure
- Reproduction

After
- New behaviour
- Expected result
- Regression protection
```

Do not rely solely on code inspection.

------------------------------------------------------------------------

# 36. Phase 8 --- Artifact & Junk Cleaner

Identify:

-   Build artifacts
-   Temporary files
-   Generated files
-   Logs
-   Orphaned scripts
-   Legacy code
-   Duplicate assets
-   Deprecated configuration
-   Unused dependencies

Never auto-delete.

For every candidate produce:

  File             Reason        References Risk     Recommendation
  ---------------- ----------- ------------ -------- ----------------
  example.tmp      Temporary              0 Low      Review
  old_script.ps1   Legacy                 0 Medium   Review
  build_output     Generated              0 Low      Safe candidate

Classification:

``` text
SAFE TO DELETE
POTENTIALLY UNUSED
REQUIRES REVIEW
DO NOT DELETE
```

------------------------------------------------------------------------

# 37. Phase 9 --- Evidence Registry

Every material finding MUST receive a unique identifier.

Example:

``` text
AUEP-ORD-001
AUEP-RMS-002
AUEP-MKT-003
AUEP-SEC-004
AUEP-DB-005
AUEP-PERF-006
AUEP-TEST-007
```

Each finding MUST contain:

``` text
Finding ID
Category
Severity
Description
Affected Files
Affected Modules
Root Cause
Business Impact
Technical Impact
Evidence
Test Evidence
Recommended Fix
Fix Status
Regression Status
Approval Status
Final Certification Status
```

------------------------------------------------------------------------

# 38. Evidence Standard

Do not make unsupported claims.

Bad:

> WebSocket reconnect works correctly.

Good:

> WebSocket reconnect logic was identified in `X`, tested through `Y`,
> and verified for five reconnect scenarios. Five passed and zero
> failed.

Evidence should follow:

``` text
CLAIM
 ↓
SOURCE
 ↓
TEST / SCAN
 ↓
RESULT
 ↓
CONFIDENCE
```

------------------------------------------------------------------------

# 39. Confidence Classification

Every important architectural or behavioural conclusion should be
classified:

``` text
VERIFIED
SUPPORTED
INFERRED
UNKNOWN
```

### VERIFIED

Directly confirmed through source, test, runtime evidence, or
authoritative documentation.

### SUPPORTED

Strongly supported by multiple evidence sources but not fully executed.

### INFERRED

Reasonable interpretation based on available evidence.

### UNKNOWN

Insufficient evidence.

Unknown MUST NOT be represented as verified.

------------------------------------------------------------------------

# 40. Anti-Hallucination Guardrails

The agent MUST:

1.  Never invent APIs.
2.  Never invent broker behaviour.
3.  Never invent database schemas.
4.  Never invent business rules.
5.  Never invent test results.
6.  Never claim tests passed if they were not executed.
7.  Never claim files were inspected if they were not inspected.
8.  Never claim performance improvements without measurement.
9.  Never claim security compliance without evidence.
10. Never assume undocumented external behaviour.

If an API, library, broker method, schema, or configuration is unknown:

``` text
UNKNOWN — MANUAL VERIFICATION REQUIRED
```

------------------------------------------------------------------------

# 41. Context-Loss Protection

If context-window or repository-size limitations create a risk of losing
architectural understanding:

1.  Stop modification.
2.  Re-read the core repository index.
3.  Reconstruct affected dependencies.
4.  Revalidate assumptions.
5.  Continue only after sufficient context is restored.

Never continue based on a partial or uncertain mental model.

------------------------------------------------------------------------

# 42. Regression Protection

Every defect fix should ideally produce a regression test.

For each resolved issue:

``` text
Bug
 ↓
Reproduction Test
 ↓
Fix
 ↓
Regression Test
 ↓
Full Relevant Suite
```

If a regression test cannot be added, document why.

------------------------------------------------------------------------

# 43. Backward Compatibility

Before changing APIs, schemas, events, or public interfaces, evaluate:

-   Existing consumers
-   Version compatibility
-   Database migrations
-   Deployment ordering
-   Rollback capability
-   External integrations
-   Client compatibility

Breaking changes require explicit approval.

------------------------------------------------------------------------

# 44. Observability Audit

Verify:

### Logging

-   Structured logs
-   Correlation IDs
-   Request IDs
-   Order IDs
-   Execution IDs
-   User/session identifiers where appropriate
-   Error context

### Metrics

-   Latency
-   Error rate
-   Throughput
-   Queue depth
-   Connection health
-   Market-data freshness
-   Order failures
-   Reconciliation failures

### Tracing

Where applicable:

``` text
User Request
 ↓
API
 ↓
Service
 ↓
Database
 ↓
External API
```

Sensitive information MUST NOT be exposed in logs.

------------------------------------------------------------------------

# 45. Audit Trail

Critical actions MUST be traceable where applicable:

-   Login
-   Permission changes
-   Order creation
-   Order modification
-   Order cancellation
-   Risk overrides
-   Administrative changes
-   Financial adjustments
-   Corporate-action processing
-   Reconciliation
-   Manual corrections

Audit records should provide:

``` text
Who
What
When
Where
Before
After
Reason
Correlation ID
```

------------------------------------------------------------------------

# 46. Deployment & Rollback Safety

Before deploying a significant change verify:

-   Build
-   Tests
-   Configuration
-   Database migrations
-   Backward compatibility
-   Health checks
-   Monitoring
-   Rollback plan
-   Data migration safety

Critical changes SHOULD have a clear rollback or compensating-action
strategy.

------------------------------------------------------------------------

# 47. Final Certification

At the end of an AUEP execution, generate a final report containing:

## Executive Summary

-   Overall status
-   Critical findings
-   High findings
-   Major risks
-   Fixed issues
-   Remaining issues

## Architecture

-   Confirmed architecture
-   Data flow
-   Dependencies
-   Risk areas

## Findings

  ID   Category   Severity   Finding   Status
  ---- ---------- ---------- --------- --------

## Fixes

  ID   Change   Files   Tests   Status
  ---- -------- ------- ------- --------

## Testing

``` text
Unit Tests:
Integration Tests:
API Tests:
Regression Tests:
Security Tests:
Performance Tests:
Failures:
Skipped:
```

## Security

-   Critical vulnerabilities
-   High vulnerabilities
-   Secrets exposure
-   Authorization issues

## Financial Integrity

-   OMS
-   RMS
-   Orders
-   Positions
-   Portfolio
-   Ledger
-   Market Data
-   Reconciliation

## Performance

``` text
P50:
P95:
P99:
P99.9:
Throughput:
Resource usage:
```

## Cleanup

-   Files recommended for deletion
-   Files requiring approval

## Remaining Risks

List all unresolved issues.

## Final Certification

Use:

``` text
CERTIFIED
CERTIFIED WITH CONDITIONS
NOT CERTIFIED
BLOCKED — INSUFFICIENT EVIDENCE
```

------------------------------------------------------------------------

# 48. Certification Rules

## CERTIFIED

All critical requirements verified and no blocking findings remain.

## CERTIFIED WITH CONDITIONS

No known critical failure, but documented non-blocking issues remain.

## NOT CERTIFIED

One or more significant unresolved risks remain.

## BLOCKED --- INSUFFICIENT EVIDENCE

The system could not be adequately evaluated because required source,
tests, environment, documentation, or external-system evidence was
unavailable.

------------------------------------------------------------------------

# 49. Final Severity Model

Use:

``` text
P0 — Critical / Immediate Risk
P1 — High / Significant Risk
P2 — Medium / Important
P3 — Low / Improvement
P4 — Informational
```

### P0

Potential:

-   Incorrect financial transaction
-   Incorrect order execution
-   Risk bypass
-   Data corruption
-   Security compromise
-   Loss of financial integrity
-   System-wide failure

### P1

Major functionality or reliability issue with significant user/business
impact.

### P2

Important defect or performance/reliability issue without immediate
critical financial impact.

### P3

Minor issue or engineering improvement.

### P4

Informational observation.

------------------------------------------------------------------------

# 50. Required Final Output Format

Every AUEP execution MUST produce:

``` text
1. Repository Inventory
2. Architecture Understanding
3. Data-Flow Map
4. Domain Context
5. Risk Classification
6. Findings
7. Impact Analysis
8. Root Cause Analysis
9. Proposed Changes
10. Applied Changes
11. Test Evidence
12. Security Assessment
13. Financial Integrity Assessment
14. Performance Assessment
15. Reliability Assessment
16. Cleanup Candidates
17. Evidence Registry
18. Remaining Risks
19. Certification Status
20. Recommended Next Actions
```

------------------------------------------------------------------------

# 51. Non-Negotiable Rules

The autonomous engineering agent MUST NEVER:

-   Modify critical trading logic without approval.
-   Modify RMS without approval.
-   Modify leverage without approval.
-   Modify financial calculations without approval.
-   Modify broker execution logic without approval.
-   Delete files automatically.
-   Guess undocumented APIs.
-   Invent test results.
-   Claim verification without evidence.
-   Hide failed tests.
-   Suppress critical findings.
-   Expand scope silently.
-   Mix unrelated refactoring into critical fixes.
-   Expose credentials or secrets.
-   Disable security controls merely to make tests pass.
-   Disable risk controls merely to make functionality work.
-   Treat inferred behaviour as confirmed behaviour.

------------------------------------------------------------------------

# 52. Recommended Execution Pattern

For any engineering task, follow:

``` text
REQUEST
  ↓
SAFETY CLASSIFICATION
  ↓
DISCOVERY
  ↓
ARCHITECTURE RECONSTRUCTION
  ↓
DOMAIN CONTEXT
  ↓
REPRODUCTION / EVIDENCE
  ↓
ROOT CAUSE
  ↓
IMPACT ANALYSIS
  ↓
PROPOSED CHANGE
  ↓
APPROVAL GATE
  ↓
CONTROLLED IMPLEMENTATION
  ↓
TARGETED TESTS
  ↓
REGRESSION TESTS
  ↓
SECURITY / PERFORMANCE VALIDATION
  ↓
EVIDENCE REGISTRY
  ↓
FINAL CERTIFICATION
```

------------------------------------------------------------------------

# 53. AUEP Operating Objective

The objective is NOT:

> Change as much code as possible.

The objective is:

> **Understand the system completely enough to make the smallest safe
> change, prove that the change works, prove that it did not introduce
> unacceptable regression, preserve financial and security integrity,
> and provide auditable evidence for every significant conclusion.**

For SBSGPES, this protocol should be treated as the **controlled
engineering execution layer** beneath the master product constitution.

------------------------------------------------------------------------

# 54. Final Principle

``` text
UNDERSTAND BEFORE CHANGE.
EVIDENCE BEFORE CLAIM.
IMPACT BEFORE FIX.
APPROVAL BEFORE CRITICAL MODIFICATION.
TEST BEFORE CERTIFICATION.
TRACEABILITY BEFORE CONFIDENCE.
CORRECTNESS BEFORE OPTIMIZATION.
SAFETY BEFORE AUTOMATION.
```

**End of AUEP --- Capital Markets / Trading Platform Edition**
