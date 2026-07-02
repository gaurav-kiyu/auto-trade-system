# Changelog

## v0.0.0-test (2026-07-02)

## v0.0.0 (2026-07-02)

## v0.0.0-test (2026-06-29)

## v0.0.0 (2026-06-29)

## v0.0.0-test (2026-06-29)

## v0.0.0 (2026-06-29)

## v0.0.0-test (2026-06-29)

## v0.0.0 (2026-06-29)

## v0.0.0 (2026-06-28)

## v0.0.0-test (2026-06-28)

## v0.0.0 (2026-06-28)

## v2.53.0 (2026-06-25)

- Comprehensive exception hardening: 9 pass-only except Exception blocks eliminated, 16 blocks narrowed to typed exceptions
- Certification gate vacuous pass fixes for replay, strategy, and paper certifiers
- OpenTelemetry auto_init() wired into DI container startup
- __all__ exports added across 387 core modules
- Zero bare except: blocks across entire codebase

## v0.0.0-test (2026-06-23)

## v0.0.0 (2026-06-23)

## v0.0.0-test (2026-06-23)

## v2.53.0 (2026-06-23)

**Institutional Hardening & Master Constitution Compliance — Final Cycle**

### New Features

#### Infrastructure & Operations
- **Kubernetes HPA Auto-Scaling** — 6 K8s manifests (deployment, service, HPA, configmap, PVC, kustomization) with Prometheus metrics scraping, health probes, and rolling update strategy
- **Observability Stack** — Loki + Promtail + Grafana Docker Compose stack with 30-day log retention, JSON audit log parsing, and auto-provisioned datasources

#### ML & Data Quality
- **Feature Quality SLA Monitor** — Automated freshness monitoring for 14 ML features with configurable per-feature max-age thresholds, quality scoring (age × anomaly rate), and background poller integration with SLO governance
- **Data Quality Integration** — FeatureQualitySLA bridges DataQualityMonitor, DataFreshnessGuard, MetricsExporter, and SLOGovernance into a unified freshness pipeline

#### Enterprise Dashboard
- **MTTR / Error Budget Pages** — 3 API endpoints with full dashboard widgets showing MTTR breakdown, P50/P90/P99, error budget consumption, burn rates, and at-risk flags
- **Cross-Asset Correlation Matrix** — Real-time correlation API with fallback to correlation guard, relative value Z-score analysis, and color-coded strength visualization

#### CI/CD
- **Walk-Forward in CI** — Walk-forward validation step added to Bitbucket Pipelines for main, develop, and release branches

### Architecture Changes
- `k8s/` directory added with Kustomize-based deployment framework
- `deploy/loki/`, `deploy/promtail/`, `deploy/grafana/datasources/` added
- `core/feature_quality_sla.py` — new module bridging 4 existing systems

### Bug Fixes
- K8s liveness probe fixed (was always-exit-0 no-op; now uses `health_checker`)
- `feature_quality_sla.py` lock scope fixed (`_emit_metrics` moved outside RLock)
- Empty feature SLA dict handled correctly (`is not None` vs truthiness bug)
- Promtail audit log path fixed to `/home/opb/` (matches Docker user)
- Grafana Prometheus datasource URL fixed to match Docker Compose service name
- Quality score weights promoted to named constants (`QUALITY_WEIGHT_AGE`, `QUALITY_WEIGHT_ANOMALY`)

### Documentation
- `RELEASE_NOTES.md` — replaced `v0.0.0-test` placeholder with comprehensive v2.53.0 notes
- `PRIORITIZED_BACKLOG.md` — P3/P6/P7/P8/P9/P10 moved to Completed
- `FINAL_EVIDENCE_BASED_SCORECARD.md` — updated scores and evidence

### Previous Versions
- **v2.44.0** — Enhancement pack: Liquidity Guard, News Sentinel, Health Checker, Trade Replay
- **v2.45.0** — Institutional: FII/DII, GEX, Kelly Sizer, Stress Testing, Greeks Engine
- **v2.50.0** — Architecture overhaul: Event system, DI container, deterministic state machine
- **v2.52.0** — Institutional hardening: 21 certification reports, chaos testing
