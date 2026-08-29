# OPB Auto-Trade System — Final Setup, Validation & Execution Guide

**Release:** 2.59.0  
**Audit date:** 2026-08-22  
**Purpose:** clean checkout → configuration → validation → paper execution → controlled live promotion

## 1. System boundary

The application is a modular monolith for NSE index/options and multi-asset trading. The intended authoritative path is:

```text
Market data
  → signal/strategy orchestration
  → risk authority + invariants + execution policy
  → idempotent order lifecycle
  → broker adapter / PaperBroker
  → broker-truth reconciliation
  → positions + event/audit store
  → dashboard / alerts / reporting
```

Supporting subsystems include backtesting, ML/AI governance, portfolio analytics, observability, incident response, recovery, Docker/Kubernetes deployment and release governance.

## 2. Environment

- Python: `>=3.10,<3.20`; CI matrix: 3.11–3.14.
- Primary desktop support: Windows; Linux/Docker supported.
- Timezone: Asia/Kolkata / IST.
- Secrets: environment variables or an external secret manager.
- `json/config.template.json` is the canonical checked-in configuration template.
- `json/config.json` is local/generated and must remain untracked.

## 3. Clean installation

### Windows

```bat
setup.bat
```

### Linux/macOS

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev,broker,dashboard,monitoring,ml]"
cp json/config.template.json json/config.json
```

For deterministic release builds, use `requirements-lock.txt` in an environment with package-index access.

## 4. Configuration precedence

```text
defaults
  ↓
json/config.json
  ↓
json/config.local.json
  ↓
OPBUYING_* environment variables
```

The optional project `.env` is loaded only as a local convenience and does **not** override explicit process environment variables.

Validate:

```bash
python scripts/validate_config_schema.py
python scripts/check_config_drift.py --ci
```

Never commit broker credentials, Telegram tokens, passwords, API keys, private keys, databases or local `.env` files.

## 5. Pre-release gates

```bash
python scripts/pre_implementation_check.py --ci
python scripts/check_architecture_compliance.py --ci
python scripts/gap_audit.py
python scripts/check_docker_security.py
python scripts/verify_release_bundle.py
python scripts/run_hygiene_scan.py --ci --json --no-html
```

Current audit results:

- Architecture compliance: PASS
- Gap audit: 20/20 + 6/6 PASS
- Docker security: 16/16 PASS
- Release-bundle check: PASS
- Python compilation: 805 files / 0 errors

## 6. Regression testing

The following targeted suites passed after the final code changes:

```bash
python -m pytest -q --tb=short   tests/test_services_risk_service.py   tests/test_risk_service.py   tests/test_domains_risk_model.py   tests/unit/test_signal_generator.py   tests/integration/test_risk_signal_portfolio.py   tests/integration/test_trading_loop_flow.py   tests/chaos/test_broker_outage.py   tests/chaos/test_partial_fill_disconnect.py   tests/chaos/test_restart_mid_session.py
```

The sandbox could not complete the complete regression matrix because:

1. `hypothesis` is unavailable;
2. `duckdb` is unavailable;
3. `yfinance` is unavailable;
4. package installation is blocked by DNS/network restrictions;
5. the unrestricted suite exceeded the available execution window.

The six affected collection modules are:
- `tests/test_async_db_writer_hypothesis.py`
- `tests/test_fuzz_data_parsing.py`
- `tests/test_property_based.py`
- `tests/test_property_based_risk.py`
- `tests/test_timeseries_db.py`
- `tests/test_yf_data_provider.py`

## 7. Paper execution

Paper mode is the required certification boundary:

```bash
python index_app/index_trader.py --paper
```

or:

```bat
scripts\run_paper_trading.bat
```

Verify that:

- execution mode resolves to PAPER/MANUAL;
- no real broker order is emitted;
- risk/invariant gates execute;
- order lifecycle events persist;
- broker truth is reconciled;
- positions and P&L remain internally consistent.

## 8. Live promotion

Unattended live capital requires all of:

- complete CI matrix green;
- production preflight green;
- paper-session evidence;
- broker contract certification;
- risk/invariant certification;
- security review;
- rollback/recovery verification;
- clean Git tree;
- remote GitHub synchronization;
- explicit operator approval.

Run:

```bash
python scripts/production_preflight_check.py --ci
python -m core.live_readiness_checker
```

The supplied sandbox intentionally fails production preflight because it has no live credentials, required local databases, Docker engine, or live market-data environment. This is an environment limitation, not a reason to manufacture fake production evidence.

## 9. Docker/Kubernetes

```bash
docker compose build
docker compose up -d
docker compose --profile test up -d
```

The audited Docker path uses non-root execution, dropped capabilities, `no-new-privileges`, read-only root filesystem, health checks and explicit resource ceilings. Kubernetes manifests are under `k8s/`.

## 10. CI/CD

`.github/workflows/ci.yml` provides:

- lint/type checks;
- Python 3.11–3.14 test matrix;
- coverage;
- pip-audit/Bandit/Semgrep;
- architecture/governance checks;
- configuration/hygiene/release checks;
- thread-safety analysis;
- certification reports.

The audit hardened CI so security/governance failures are no longer silently converted into successful steps.

## 11. Documentation map

- `README.md` — project overview and developer entry point
- `SYSTEM_SETUP_GUIDE.md` — detailed setup
- `USER_GUIDE.md` — user operation
- `SECURITY.md` — security controls
- `TECHNICAL_DEBT_REGISTER.md` — technical debt
- `docs/branch_strategy.md` — branching/release governance
- `docs/FINAL_SETUP_AND_EXECUTION_GUIDE.md` — end-to-end release execution
- `docs/DOCUMENTATION_SYNC_LOG.md` — synchronization evidence
- `docs/review/SYSTEM_REVIEW_SUMMARY.md` — current audit conclusion
- `docs/review/SYSTEM_REVIEW_SUMMARY.pdf` — management summary
- `docs/review/ARCHITECTURE_OVERVIEW.pptx` — architecture presentation

## 12. Release synchronization

```bash
git fetch origin
git status
git diff --check
git diff origin/main...HEAD
git log -1 --oneline
git push origin main
```

The audit environment cannot currently resolve `github.com`, so remote push could not be performed from this sandbox. The local repository can be committed and is ready for push when network/authentication are available.
