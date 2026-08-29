# ADR 0013: Monitoring & Observability Stack — Prometheus, Loki, Grafana, OpenTelemetry

## Status

Accepted (2026-07-18)

## Date

2026-07-18

## Context

The trading bot operates autonomously during market hours (09:15–15:20 IST) with real-time decision-making
and financial risk. A comprehensive monitoring and observability stack is needed to:

1. **Track system health** — detect failures before they cause financial loss
2. **Alert on anomalies** — circuit breaker trips, broker outages, data feed stalls
3. **Store and query logs** — audit trail for compliance and postmortem analysis
4. **Visualize metrics** — real-time dashboards for operators
5. **Trace requests** — end-to-end visibility across async execution paths
6. **SLO governance** — track and enforce service level objectives

## Decision

### Architecture Overview

We deploy a four-pillar observability stack alongside the trading application:

```
┌─────────────────────────────────────────────────────────────┐
│                     Docker Compose Stack                      │
│                                                               │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌────────┐  │
│  │ OPB Bot  │───→│Prometheus│───→│ Grafana  │    │  Loki  │  │
│  │(metrics) │    │(scrape)  │    │(visualize)│    │(logs)  │  │
│  └──────────┘    └──────────┘    └──────────┘    └────┬───┘  │
│       │                                                │      │
│       │    ┌──────────┐                                │      │
│       └───→│Promtail  │───────────────────────────────┘      │
│            │(log agent)│                                       │
│            └──────────┘                                       │
│                                                               │
│  ┌──────────────────┐  ┌─────────────────────────────────┐    │
│  │  OpenTelemetry   │  │  K8s (optional): HPA, liveness  │    │
│  │  (traces)        │  │  probes, prometheus-rules       │    │
│  └──────────────────┘  └─────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
```

### Components

#### 1. Prometheus — Metrics Collection
- **Port**: 9090
- **Config**: `deploy/prometheus/prometheus-config.yml`
- **Scrape targets**: OPB bot metrics endpoint (`:9090/metrics`)
- **Metrics exported**:
  - Trade counts, win rates, P&L by index
  - Signal scores, confidence, adjustments
  - Data provider health (total/connected/disconnected)
  - Broker latency, order success/failure rates
  - Circuit breaker state, hard halt status
  - ML model accuracy, drift detection status
- **Custom metrics**: Via `core/metrics_exporter.py` (Prometheus client)
- **Update interval**: 30 seconds for provider health, 5 minutes for SLO metrics

#### 2. Loki — Log Aggregation
- **Config**: `deploy/loki/loki-config.yml`
- **Retention**: 30 days (configurable)
- **Log sources**: Application logs via Promtail, audit logs (JSONL)
- **Audit log parsing**: Structured JSON audit logs parsed by Promtail for structured querying

#### 3. Grafana — Visualization
- **Dashboard**: Pre-built `opb_dashboard.json` in `deploy/grafana/`
- **Datasources**: Prometheus (metrics), Loki (logs)
- **Auto-provisioning**: Datasource configuration in `deploy/grafana/datasources/datasource.yml`
- **Dashboard widgets**:
  - Real-time P&L chart (last 24h)
  - Signal score distribution
  - Win rate over time (rolling 30-day)
  - Broker health grid
  - ML model accuracy + drift status
  - Open positions monitor
  - System resource utilization
  - Error rate and latency panels

#### 4. Promtail — Log Agent
- **Config**: `deploy/promtail/promtail-config.yml`
- **Log paths**: Application logs (`logs/*.log`), audit logs (`json/audit_trail.jsonl`)
- **Structured metadata**: Adds job, instance, level labels for Loki queries

#### 5. OpenTelemetry — Distributed Tracing
- **Module**: `core/observability/opentelemetry.py`
- **Auto-instrumentation**: Wired into DI container startup
- **Spans**: Trading cycles, signal generation, order execution, risk evaluation
- **Exporter**: OTLP (configurable endpoint)

#### 6. Metrics Exporter — Application Metrics
- **Module**: `core/metrics_exporter.py`
- **Port**: Configurable (default 9090)
- **Endpoint**: `GET /metrics` (Prometheus text format)
- **Gauges**:
  - `data_providers_total`, `data_providers_connected`, `data_providers_disconnected_pct`
  - `data_providers_worst_state` (0=healthy, 1=degraded, 2=critical)
- **Update**: Background thread updates Prometheus gauges every 30 seconds

### Health Checks

#### Application Health (`/api/system/health/docker`)
- **No auth required** — for Docker/K8s liveness probes
- **Checks**: Database connectivity (db/trades.db + db/auth.db), hard halt state, pause state
- **Response**: `{"status": "healthy"|"degraded", "version": "2.54.0", ...}`

#### K8s Probes
- **Liveness**: Uses `health_checker.run_full_health_check()` 
- **Readiness**: Checks DB connectivity and broker status
- **Startup**: Initial delay 30 seconds, period 10 seconds

### SLO Governance

- **Module**: `core/slo_governance.py`
- **Metrics tracked**:
  - Uptime (target: 99.9% during market hours)
  - Trade execution latency (target: <500ms P95)
  - Signal generation coverage (target: 100% of indices)
  - Data feed freshness (target: <5s lag)
- **Poller**: Background thread checks SLO compliance every 5 minutes
- **Integration**: Health check results feed into SLO governance for compliance tracking

### Kubernetes Integration (Optional)

| Manifest | Purpose |
|----------|---------|
| `deployment.yaml` | Container spec with resource limits, probes, rolling update |
| `service.yaml` | Internal cluster service on port 8765 |
| `hpa.yaml` | Horizontal Pod Autoscaler (CPU-based, min=1, max=5) |
| `configmap.yaml` | Application config injected as environment variables |
| `secret.yaml` | K8s Secret for sensitive values (broker tokens, API keys) |
| `pvc.yaml` | Persistent volume for SQLite databases |
| `prometheusrule.yaml` | Alerting rules for broker outage, high loss rate, circuit breaker |
| `kustomization.yaml` | Kustomize overlay for environment-specific configs |

### Alerting Rules (Prometheus)

| Alert | Condition | Severity |
|-------|-----------|----------|
| `BrokerOutage` | Broker health check fails for 5m | CRITICAL |
| `HighLossRate` | Daily loss > 50% of max | WARNING |
| `CircuitBreakerTripped` | Circuit breaker open for > 1m | CRITICAL |
| `DataFeedStall` | No data update for 60s | WARNING |
| `HighTradeLatency` | Order execution > 2s | WARNING |

## Consequences

### Positive
- **Full observability**: Metrics + logs + traces from a single stack
- **Quick diagnosis**: Grafana dashboards provide real-time system state
- **Audit compliance**: Structured logs with 30-day retention
- **Auto-scaling**: K8s HPA scales based on real metrics
- **SLO enforcement**: Automatic health → governance feedback loop

### Negative
- **Resource overhead**: Monitoring stack requires ~1GB RAM and ~1 CPU core
- **Setup complexity**: Docker Compose with 4+ services (Prometheus, Loki, Grafana, Promtail)
- **Storage costs**: 30-day log retention requires ~10GB disk
- **Maintenance**: Prometheus/Loki configs need updates as metrics change

### Neutral
- **Optional**: Monitoring stack is opt-in via `docker-compose.observability.yml`
- **Swappable**: Metrics exposed in standard Prometheus format — compatible with any monitoring backend (DataDog, New Relic, etc.)

## References

- `core/metrics_exporter.py` — Prometheus metrics endpoint
- `core/observability/opentelemetry.py` — OpenTelemetry tracing
- `core/health_checker.py` — System health checks
- `core/slo_governance.py` — SLO tracking and enforcement
- `deploy/prometheus/prometheus-config.yml` — Prometheus config
- `deploy/loki/loki-config.yml` — Loki config
- `deploy/grafana/opb_dashboard.json` — Pre-built dashboard
- `deploy/docker-compose.observability.yml` — Stack deployment
- `k8s/` — Kubernetes deployment manifests
