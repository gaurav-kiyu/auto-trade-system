# OPB Bot — Kubernetes Deployment Guide

## Overview

Kubernetes manifests for deploying the OPB Index Options Buying Bot in a containerized environment with HPA auto-scaling, Prometheus metrics scraping, and persistent storage.

## Prerequisites

- Kubernetes cluster (1.24+ recommended)
- `kubectl` configured
- Prometheus Operator or Prometheus Adapter for HPA custom metrics (optional — CPU/memory HPA works without it)

## Quick Start

```bash
# 1. Create namespace (optional — namespace.yaml creates it automatically)
kubectl create namespace opb-trading

# 2. Create secrets (edit with your actual credentials)
# ⚠️ Edit k8s/secret.yaml with your credentials first, then apply
kubectl apply -f k8s/secret.yaml --namespace opb-trading

# 3. Apply all manifests via kustomization
kubectl apply -k k8s/

# 4. Verify deployment
kubectl get pods -n opb-trading -w
kubectl get hpa -n opb-trading
kubectl get svc -n opb-trading

# 5. Check metrics
kubectl port-forward svc/opb-service 9090:9090 -n opb-trading
# Visit http://localhost:9090/metrics

# 6. Check logs
kubectl logs -n opb-trading -l app=opb-bot --tail=100
```

## Manifests

| File | Purpose |
|------|---------|
| `configmap.yaml` | Non-sensitive env vars (mode, paths, ports) |
| `secret.yaml` (create manually) | Broker keys, Telegram tokens |
| `deployment.yaml` | Pod spec with probes, resource limits, volumes |
| `service.yaml` | ClusterIP service exposing :9090 (metrics) and :8765 (dashboard) |
| `hpa.yaml` | HorizontalPodAutoscaler — CPU/memory based, 1–5 replicas |
| `pvc.yaml` | 10GB PersistentVolumeClaim for SQLite DBs, models, reports, logs |

## HPA Auto-Scaling

The HPA currently scales on CPU (70% target) and memory (80% target). For custom Prometheus-based scaling:

1. Install [Prometheus Adapter](https://github.com/kubernetes-sigs/prometheus-adapter)
2. Configure a custom metric rule in `prometheus-adapter` config:
   ```yaml
   rules:
     - seriesQuery: 'opb_trades_total'
       resources:
         overrides:
           namespace: {resource: "namespace"}
           pod: {resource: "pod"}
       name:
         matches: 'opb_trades_total'
         as: 'opb_trades_per_second'
       metricsQuery: 'rate(opb_trades_total[1m])'
   ```
3. Add a Pods metric to `opb-hpa.yaml`:
   ```yaml
   - type: Pods
     pods:
       metric:
         name: opb_trades_per_second
       target:
         type: AverageValue
         averageValue: "0.5"
   ```

## Prometheus Scraping

The deployment includes annotations for Prometheus auto-discovery:
- `prometheus.io/scrape: "true"`
- `prometheus.io/port: "9090"`
- `prometheus.io/path: "/metrics"`

Metrics are available at `http://<pod-ip>:9090/metrics` in Prometheus text format.

## Production Considerations

1. **Resource Tuning**: Adjust `resources.requests/limits` in `deployment.yaml` based on observed usage
2. **Storage Size**: Adjust `pvc.yaml` `storage` size based on growth forecasts
3. **Secrets Management**: Use a proper secret store (Vault, External Secrets Operator) instead of plain k8s secrets for production
4. **Network Policies**: Restrict pod-to-pod communication to only necessary ports
5. **Pod Disruption Budget**: Add a PDB to prevent all replicas from being evicted simultaneously
6. **Monitoring**: Deploy the full observability stack (see `deploy/docker-compose.observability.yml`)

## Rollout & Rollback

```bash
# Rolling update (when image tag changes)
kubectl set image deployment/opb-deployment opb-bot=opb-bot:2.54.0 -n opb-trading

# Rollback
kubectl rollout undo deployment/opb-deployment -n opb-trading
kubectl rollout status deployment/opb-deployment -n opb-trading
```
