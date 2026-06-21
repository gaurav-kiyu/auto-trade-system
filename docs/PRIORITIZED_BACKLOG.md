# Prioritized Backlog

> **Deliverable #19** — Remaining work items by priority
> **Date:** 2026-06-20 (Updated)
> **Overall Completion:** 29/29 Phases, 26/26 Capabilities, 8.7/10 Score

---

## Priority Legend

| Priority | Meaning | Action Required |
|----------|---------|-----------------|
| 🔴 **Critical** | Blocks production go-live | Must fix before any live trading |
| 🟠 **High** | Required for institutional readiness | Should complete this quarter |
| 🟡 **Medium** | Enhances operational excellence | Plan for next release |
| 🟢 **Low** | Nice-to-have | Add to roadmap |

---

## 🔴 Critical (0 items)

All critical items are resolved. No blocking issues remain.

## 🟠 High (1 item)

| # | Item | Phase | Effort | Notes |
|---|------|-------|--------|-------|
| 1 | **Generate 90 days paper trade data** | P6, P12 | 90d elapsed | Cannot validate replay/paper certifiers without trade data. Run bot in paper mode. |

## 🟡 Medium (0 items)

All medium items are resolved.

---

## Completed (v2.53 additions)

| Item | Delivered |
|------|-----------|
| SLO Metric Telemetry (Health -> SLO -> Prometheus) | `core/slo_governance.py`: ingest_health_report, _ingest_single_check, start_health_metrics_poller, wired into dashboard lifespan |
| Interactive Web Risk Dashboard UI | `templates/enterprise/dashboard.html`: SLO compliance table, risk limit utilization bars, trend indicators, alerts |
| Container Import Fixes | `index_app/domains/trading/container.py`: 15 missing port/adapter imports resolved |
| Broker Factory Defensive Fix | `index_app/domains/broker/factory.py`: log_fn handles non-callable Logger objects |
| performance_metrics load_trades Fix | `core/performance_metrics.py`: fallback from `trades` to `execution_orders` table |

## 🟢 Low (2 items)

| # | Item | Phase | Effort | Notes |
|---|------|-------|--------|-------|
| 4 | **Formal verification layer** | Add'l | 5-10 days | Type-level invariants for critical paths |
| 5 | **Market simulator enhancements** | P20 | 5-10 days | Full exchange emulation with configurable market conditions |

## Completed in v2.53

| Item | Delivered |
|------|-----------|
| Portfolio Optimization Engine | `core/portfolio/optimizer.py` |
| Self-Healing Framework | `core/self_healing/orchestrator.py` |
| Unified Certification Gate | `core/certification/gate.py` |
| Capacity Planning + Scaling Triggers | `core/capacity_planning.py` (9 scaling triggers, cooldown/alerting) |
| FinOps Cost Governance | `core/finops.py` |
| Version Compatibility Matrix | `core/version_compatibility.py` (14 components) |
| SLO/SLA Governance | `core/slo_governance.py` (15 SLOs, breach alerts, release blocking) |
| Global Risk Dashboard | `core/risk_dashboard.py` (CLI + JSON snapshot) |
| Regulatory Reporting | `core/regulatory_reporting.py` (SEBI compliance) |
| NTP Clock Sync | `core/time_provider.py` (NTPClockSync, drift detection, CLI) |
| Multi-Tenant Readiness | `core/multi_tenant.py` (tenant isolation, quotas, DI wiring) |
| Change Management Workflow | `core/change_management.py` (propose→approve→apply→rollback) |
| Historical Comparison | `scripts/historical_comparison.py` (auto release-to-release diff) |
| Change Mgmt API Endpoints | 5 admin endpoints in `core/enterprise_dashboard.py` |
| Risk/SLO API Endpoints | Risk snapshot, SLO compliance, risk alerts, risk limits |
| Runtime Wiring (all services) | Self-healing + SLO + Risk Dash + NTP + Multi-Tenant + Change Manager in startup |
| All Deliverable Reports | 12+ new reports + all 30 accounted for |
| Compliance Docs Updated | Scorecard 8.7/10, Backlog, Compliance Report, Prioritized Backlog |
