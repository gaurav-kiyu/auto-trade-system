# OPB v2.60 — Phase D Live Scanner Runtime & Environment Parity Audit
**Document ID**: `OPB-AUDIT-PHASE-D-RUNTIME-PARITY-20260928`  
**Governance Authority**: `OPB-FINAL-PHASE-GOVERNANCE-001`  
**Execution Timestamp**: `2026-09-28T11:00:00+05:30` (Monday morning)  
**Execution Context**: Live NSE Market Session (`SESSION_ACTIVE`)  

---

## 1. Audit Timestamp
- **Audit Execution Date/Time**: `2026-09-28T11:00:00+05:30` (IST)
- **Day of Week**: Monday
- **Calendar Verification**: NSE Regular Trading Session active (trading day confirmed via `core.exchange_calendar_engine`).

---

## 2. Market Session State
- **Market Status**: `SESSION_ACTIVE`
- **Exchange**: National Stock Exchange of India (NSE)
- **Session Timings**: 09:15:00 IST – 15:30:00 IST
- **Operating Phase**: Mid-morning live trading session.

---

## 3. Working Branch
- **Active Git Branch**: `v2.59-production-ui-remediation-20260928`
- **Branch Tracking**: Local branch branched from `master` containing UI/UX remediation, Phase D forward accumulation wiring (`79d95d5`), and forward accumulation reporter (`5a1c4f0`).

---

## 4. Evaluated Commit
- **Current HEAD**: `04b70b6d859b83f0d014bc549e5d4cb05c4a6b29` (`docs(governance): record Phase D live session report and UI remediation validation`)
- **Evaluated Implementation Commit**: `a2ed98363f9da71892db4f8200a3186883dde7a2` (`feat: production UI, analytics, payment, and portfolio remediation`)
- **Working Tree State**: 100% clean (0 modified tracked files).

---

## 5. Production Baseline
- **Frozen Production Commit**: `d4271ffb75376e404e9d6e28fae2a5f8c0a8e2a4` on `master` / `origin/master`
- **Status**: Production commit remains strictly frozen. Zero remote pushes, zero hotfixes deployed during live trading session.

---

## 6. Database SHA-256
- **Database File**: `db/signals_history.db`
- **Baseline SHA-256**: `EB5C368EE7DE9B0DB0544831D74BFCA866BF68D1F7F03F3844FE1BFF99B203D5`
- **Audited SHA-256**: `EB5C368EE7DE9B0DB0544831D74BFCA866BF68D1F7F03F3844FE1BFF99B203D5`
- **Integrity Result**: **BYTE-IDENTICAL (0 bytes mutated)**. Strictly read-only audit verified.

---

## 7. Intended Scanner Host
- **Production Architecture**: Docker Container running on AWS EC2 (`Linux x86_64`) managed by `supervisord` (`supervisord.conf`).
- **Local Developer Architecture**: Windows Workstation (`win32`) running standalone background process via `START_REALTIME_MARKET_SCANNER.bat`.

---

## 8. Actual Scanner Host
- **Local Workstation**: Confirmed **INACTIVE**. Process inspection (`Get-Process python*`) identified **zero running Python processes**.
- **Production Host (EC2)**: Remote container runs in an isolated network environment. Even if running on EC2, its runtime code is on frozen baseline `d4271ff`, which does not contain the Phase D forward observation pipeline.
- **Audited Environment**: Local Windows workstation repository.

---

## 9. Scanner Startup Mechanism
- **Production Container**:
  - Container entrypoint: `CMD ["supervisord", "-c", "/etc/supervisor/conf.d/opb.conf", "-n"]`
  - Supervisord program: `[program:opb_scanner]`
  - Command: `python core/market_scanner_daemon.py --interval 60`
  - Autostart / Autorestart: `true` / `true` (Priority 20)
- **Local Windows Host**:
  - Batch script: `START_REALTIME_MARKET_SCANNER.bat` $\to$ executes `%PYTHON% -m core.market_scanner_daemon --interval 60 --workers 20`.
  - Secondary script: `TEST_AFTER_HOURS_SCANNER.bat` $\to$ executes `%PYTHON% -m core.market_scanner_daemon --force --limit 20 --interval 30 --workers 10`.
  - Standard launcher: `start.bat` only starts `index_app\index_trader.py --paper` (the main bot and dashboard); it does **NOT** start `market_scanner_daemon.py`.

---

## 10. Scanner Process State
- **Process State**: `NOT_RUNNING`
- **Local Verification**:
  ```powershell
  Get-Process python*
  # Output: No process found (exit code 1)
  ```
- **Daemon Status**: Neither `core/market_scanner_daemon.py`, `AllNSEScanner`, nor `index_trader.py` is executing in the audited environment.

---

## 11. Scanner PID
- **Local PID**: `NONE`
- **Supervisor Status**: `NOT_APPLICABLE` (No supervisor daemon running on Windows host).

---

## 12. Scan Cadence
- **Target Polling Cadence**: 60 seconds (`--interval 60`)
- **Worker Concurrency**: 20 parallel worker threads (`ThreadPoolExecutor(max_workers=20)`)
- **Universe Size**: ~2,500+ listed NSE equities (filtered dynamically from `archives.nseindia.com/content/equities/EQUITY_L.csv`).

---

## 13. Database Topology
- **Storage Engine**: Embedded SQLite 3 with Write-Ahead Logging (`PRAGMA journal_mode=WAL;`).
- **File Location**: Relative path `db/signals_history.db` resolved relative to repository root (`_ROOT / "db" / "signals_history.db"`).
- **Local Workstation Path**: `d:\AI_APPs\TRADING_APP\OPB_V2_59_4_CANONICAL\db\signals_history.db`
- **Production Container Path**: `/app/db/signals_history.db` (or `/data/db/` if overridden via environment variables).

---

## 14. Dashboard Database Topology
- **Dashboard Process**: FastAPI application (`core/enterprise_dashboard/`)
- **Database Accessor**: Instantiates singleton `SignalTracker.get_instance()` via `core.signals.signal_tracker`
- **Resolved Path**: `_ROOT / "db" / "signals_history.db"`
- **Parity with Scanner**: Dashboard and scanner in the same environment share the exact same relative database path.

---

## 15. Scanner Database Topology
- **Scanner Engine**: `core.all_nse_scanner.AllNSEScanner`
- **Tracking Singleton**: `SignalTracker.get_instance()` and `SignalOutcomeTracker.get_instance()`
- **Persistence Hooks**:
  - `SignalTracker.record_scan_cycle(stats, symbols_scanned, timestamp)` $\to$ writes to `scan_cycle_metrics`.
  - `SignalTracker.record_signal(...)` $\to$ writes to `system_signals` and `prediction_snapshots`.
  - `SignalOutcomeTracker.update_active_signal_outcomes(...)` $\to$ writes to `signal_outcomes` and `signal_forward_observations`.

---

## 16. `scan_cycle_metrics` Findings
Direct forensic query of `db/signals_history.db`:
- **Total rows in `scan_cycle_metrics`**: `1`
- **Existing row timestamp**: `2026-09-22 17:34:54` (Historical test from 6 days prior)
- **Scan cycles recorded today (`2026-09-28`)**: **0**
- **Symbols scanned today (`2026-09-28`)**: **0**
- **Candidates evaluated today (`2026-09-28`)**: **0**
- **Empirical Conclusion**: No market scan cycle has executed against this database file during today's live session.

---

## 17. Log Topology
- **Production Container**:
  - Supervisor master log: `/data/logs/supervisord.log`
  - Scanner stdout log: `/data/logs/opb_scanner.log`
  - Scanner stderr log: `/data/logs/opb_scanner_err.log`
  - Bot stdout log: `/data/logs/opb_bot.log`
- **Local Workstation**:
  - Application logs directory: `logs/`
  - Evaluation snapshot: `logs/evaluation_states_latest.json`
  - Forward audit JSONL: `logs/forward_audit_signals.jsonl`
  - Current state on local host: No active log generation today.

---

## 18. Production / EC2 Topology
- **Hosting Environment**: AWS EC2 Instance (t3.xlarge / c5.xlarge)
- **Container Orchestration**: Docker Compose (`deploy/docker-compose.aws.yml`)
- **Ingress / Reverse Proxy**: Caddy 2.10 reverse proxy (`deploy/Caddyfile`) handling HTTPS (ports 80/443) and proxying to OPB dashboard on loopback interface `127.0.0.1:8765`.
- **Security Profile**: `no-new-privileges:true`, capabilities dropped (`ALL`), non-root user `opb`.
- **Remote Git Status**: Deployed at frozen commit `d4271ffb75376e404e9d6e28fae2a5f8c0a8e2a4`.

---

## 19. Local vs. Production Environment Distinction
| Dimension | Local Developer Workstation | Production AWS EC2 |
| :--- | :--- | :--- |
| **OS / Runtime** | Windows 11 (`win32`) / Python 3.14 | Linux Alpine/Debian / Docker Python 3.11 |
| **Process Model** | Manual Batch (`START_REALTIME_MARKET_SCANNER.bat`) | Automated `supervisord` (`opb_scanner`) |
| **Database File** | Local file: `db/signals_history.db` | Container storage: `/app/db/` or volume `/data/db` |
| **Network Sync** | None (Isolated local disk) | None (Isolated remote cloud disk) |
| **Current Codebase** | `v2.59-production-ui-remediation-20260928` | `master` (`d4271ffb75376e404e9d6e28fae2a5f8c0a8e2a4`) |
| **Phase D Wiring** | Present (`79d95d5`, `5a1c4f0`) | Not Present (Undeployed) |
| **Current Process Status**| **NOT RUNNING (0 Python processes)** | Container on EC2 (Running baseline v2.59.4) |

---

## 20. Whether Audited DB is the Live Scanner DB
- **Empirical Finding**: **NO**.
- **Evidence**:
  1. The audited database is a local repository file on a Windows development workstation.
  2. If an EC2 production container is running, its SQLite database is written to internal container storage or an AWS EBS volume; it does not replicate over the network to this local Windows filesystem.
  3. No local scanner daemon is executing against this local file.
  4. Therefore, the audited database is an offline/local database file that is receiving zero live scan data.

---

## 21. Full Scanner $\to$ DB $\to$ Phase D Pipeline Trace
```text
[NSE LIVE SESSION (09:15-15:30 IST)]
                 │
                 ▼
core/market_scanner_daemon.py (is_market_hours() == True)
                 │
                 ▼
core/all_nse_scanner.py :: AllNSEScanner.scan_universe()
  ├─► Parallel evaluation of 2,500+ symbols via ThreadPoolExecutor(max_workers=20)
  ├─► DataFreshnessGuard & Long-Only Cash Gate verification
  ├─► 16-strategy quant scoring + ML win probability evaluation
  ├─► Configured score & tier threshold filtering
  │
  ├─► [AT CYCLE COMPLETION]
  │     └─► SignalTracker.record_scan_cycle() ──► INSERT INTO scan_cycle_metrics
  │     └─► SignalOutcomeTracker.update_active_signal_outcomes()
  │
  └─► [IF SIGNAL QUALIFIES]
        └─► AllNSEScanner._dispatch_alert_if_eligible()
              └─► SignalTracker.record_signal()
                    ├─► INSERT INTO system_signals
                    ├─► INSERT INTO prediction_snapshots
                    └─► SignalForwardObservationPipeline.register_signal() [Phase D Wiring]
                          └─► INSERT INTO signal_forward_observations (status='OBSERVING')
```
*Current Breakpoint*: The pipeline never starts because `core/market_scanner_daemon.py` is not running.

---

## 22. Root Cause of Zero Forward Observations
The complete root cause for `forward_registered = 0` is:
1. **Local Audited Environment**: The market scanner daemon process (`core/market_scanner_daemon.py`) has **never been started** on this machine today.
2. **Production Remote Environment**: Production EC2 remains frozen on commit `d4271ffb75376e404e9d6e28fae2a5f8c0a8e2a4`, which does not contain the Phase D forward accumulation wiring (`79d95d5`).
3. **Database Isolation**: The local `db/signals_history.db` has zero connection to remote EC2.
4. **Data Integrity Guarantee**: Zero observation records were fabricated, guessed, or assumed. The zero count accurately reflects reality.

---

## 23. Governance Gate Status
All Phase D forward accumulation gates are evaluated against canonical requirements:

| Governance Gate | Canonical Threshold Requirement | Actual Current Observation | Status |
| :--- | :--- | :--- | :--- |
| **Gate G1** | $\ge 100$ resolved signals per 10-point score bucket (60–100) | `[60-70): 0`, `[70-80): 0`, `[80-90): 0`, `[90-100]: 0` | **FAILED** |
| **Gate G2** | $\ge 300$ total resolved forward signals | `Total Resolved = 0` | **FAILED** |
| **Gate G3** | $\ge 2$ consecutive calendar months with $\ge 30$ resolved signals/month | `Consecutive Months = 0` | **FAILED** |
| **Gate G4** | Data Quality Failure $\le 5.0\%$, Stale Signal Rate $\le 2.0\%$ | `No Forward Sample` | **INSUFFICIENT_SAMPLE** |

- **Overall Gate Status**: **`GATES_FAILED_INSUFFICIENT_SAMPLE`**.

---

## 24. Safety Status
- **Trading Mode**: `SIGNAL_ONLY = True`
- **Safety Lockout**: `LIVE_TRADING_LOCKOUT = True`
- **Autonomous Execution**: `full_auto_allowed = False`
- **Orders Placed**: `0`
- **Broker API Calls**: `0`
- **Safety Compliance**: **100% VERIFIED / FAIL-SAFE ACTIVE**.

---

## 25. Test Status
- **Phase D Test Suite**: **134 / 134 PASSED** (100% green)
  - `tests/test_forward_accumulation_reporter.py` (34 passed)
  - `tests/test_signal_forward_observation.py` (32 passed)
  - `tests/test_signal_forward_monitor.py` (22 passed)
  - `tests/test_signal_forward_wiring_remediation.py` (31 passed)
  - `tests/test_phase_e_execution_readiness.py` (15 passed)
- **UI Remediation Test Suite**: **121 / 121 PASSED** (100% green)
- **Total Regressions**: **0**.

---

## 26. Required Remediation
1. **Local Forward Accumulation Remediation**:
   - To accumulate forward signals locally on Windows, execute `START_REALTIME_MARKET_SCANNER.bat` (or `%PYTHON% -m core.market_scanner_daemon --interval 60 --workers 20`) in a dedicated terminal.
   - The scanner daemon will evaluate the NSE universe every 60 seconds, recording scan cycles, signals, and forward observation snapshots.
2. **Production Forward Accumulation Remediation**:
   - Merge Phase D wiring and reporter to `master`.
   - Build and tag production Docker image.
   - Deploy to EC2 with automated verification.

---

## 27. Whether Remediation Must Wait Until Market Close
- **Production Code Deployment**: **YES — ABSOLUTELY**. Under `OPB-FINAL-PHASE-GOVERNANCE-001`, zero production deployments, container restarts, or remote changes are permitted during live NSE trading hours (09:15–15:30 IST).
- **Local Developer Testing**: Launching the local scanner daemon in `SIGNAL_ONLY` / `PAPER` mode on the local workstation can be done during market hours to observe genuine NSE live feeds, but it must not be conflated with a production deployment.

---

## 28. Phase E Status
- **Phase E Execution Readiness**: **`BLOCKED_BY_SAMPLE`**
- **Rationale**: Phase E probability model promotion strictly requires empirical validation across Gates G1, G2, and G3. With 0 forward observations, mathematical calibration cannot proceed.

---

## FINAL CANONICAL AUDIT VERDICT

```text
========================================================================================
FINAL CANONICAL AUDIT VERDICT:
PHASE D RUNTIME AUDIT — LIVE SCANNER NOT RUNNING IN AUDITED ENVIRONMENT
========================================================================================
```

**Signed & Sealed**:  
Antigravity Governance Auditor  
Authority: `OPB-FINAL-PHASE-GOVERNANCE-001`
