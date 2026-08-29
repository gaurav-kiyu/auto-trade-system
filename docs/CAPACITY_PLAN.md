# Capacity Plan

> **Mandatory Deliverable #25** — MASTER CONSTITUTION PROMPT v2.56.0  
> *Target: Capacity forecasting for ticks/sec, orders/sec, events/sec, signals/sec, memory, CPU, DB growth*

---

## 1. Current Capacity Baseline

### 1.1 Current Workload Profile (Single Index, Paper Mode)

| Metric | Current Value | Peak Observed |
|--------|--------------|---------------|
| Ticks/sec (yfinance poll) | 0.2/sec (5s interval) | 1/sec (burst) |
| Signals evaluated/min | 6-12 (every 5-10s) | 20/min (high volatility) |
| Orders/day | 0-30 (paper) | 50/day (max) |
| DB writes/day | ~500 (trades + ML + OI) | ~2000 (backtest) |
| Memory (RSS) | ~180 MB | ~250 MB |
| CPU (single core) | ~15% average | ~60% (backtest) |
| Log volume/day | ~10 MB | ~50 MB (debug mode) |
| DB size (db/trades.db) | ~2 MB | ~10 MB (6 months) |

### 1.2 Current Resource Limits

| Resource | Current | Bottleneck |
|----------|---------|------------|
| RAM | 512 MB (Docker limit) | Python object overhead (pandas DataFrames) |
| CPU | 1 vCPU | Single-threaded strategy loop |
| Disk | 10 GB | Log retention, backup accumulation |
| Network | N/A (polling-based) | yfinance rate limits (2000 req/hr) |

---

## 2. Growth Forecast (12 Months)

### 2.1 Scenario: Single Index, Production Live

| Metric | Current | 3 Months | 6 Months | 12 Months |
|--------|---------|----------|----------|-----------|
| Trades/day | 10 | 20 | 50 | 100 |
| Broker API calls/day | 100 | 200 | 500 | 1000 |
| DB size | 2 MB | 5 MB | 15 MB | 40 MB |
| Memory | 180 MB | 220 MB | 300 MB | 400 MB |
| CPU | 15% | 20% | 30% | 45% |

### 2.2 Scenario: Multi-Index (3 indices), Live

| Metric | Current | 3 Months | 6 Months | 12 Months |
|--------|---------|----------|----------|-----------|
| Trades/day | 10 | 60 | 150 | 300 |
| Signals/min | 12 | 36 | 90 | 180 |
| DB writes/day | 500 | 3000 | 7500 | 15000 |
| DB size | 2 MB | 15 MB | 50 MB | 150 MB |
| Memory | 180 MB | 300 MB | 500 MB | 800 MB |
| CPU (cores) | 0.15 | 0.3 | 0.6 | 1.2 |

### 2.3 Scenario: Full Platform (Equities + F&O + All Indices)

| Metric | Current | 3 Months | 6 Months | 12 Months |
|--------|---------|----------|----------|-----------|
| Trades/day | 10 | 200 | 1000 | 5000 |
| API calls/day | 100 | 2000 | 10000 | 50000 |
| DB size | 2 MB | 100 MB | 500 MB | 2 GB |
| Memory | 180 MB | 500 MB | 1 GB | 2 GB |
| CPU (cores) | 0.15 | 0.5 | 2 | 4 |
| Logs/day | 10 MB | 50 MB | 200 MB | 500 MB |

---

## 3. Scaling Strategy

### 3.1 Vertical Scaling (Current, Months 1-6)

```yaml
# docker-compose resource increase at 6 months
resources:
  limits:
    memory: 2GB
    cpus: '2.0'
  reservations:
    memory: 512MB
```

- Increase Docker memory limit from 512 MB → 2 GB
- CPU allocation from 1 → 2 cores
- Disk from 10 GB → 50 GB
- Target: Supports multi-index + streaming WebSocket

### 3.2 Horizontal Scaling (Months 6-12)

| Component | Scaling Strategy |
|-----------|-----------------|
| Strategy execution | Per-index worker processes (NIFTY, BANKNIFTY, etc.) |
| WebSocket feeds | Dedicated feed collector per index |
| API gateway | Load-balanced instances behind reverse proxy |
| DB | Read replicas for analytics queries |
| ML inference | Batch processing on dedicated worker |

```yaml
# docker-compose at 12 months (horizontal scale)
services:
  strategy-nifty:
    build: .
    command: python index_app/index_trader.py --indices NIFTY
  strategy-banknifty:
    build: .
    command: python index_app/index_trader.py --indices BANKNIFTY
  feed-collector:
    build: .
    command: python -m core.ws_feed_manager
  api-gateway:
    build: .
    command: python -m core.enterprise_dashboard
  redis:
    image: redis:7-alpine
```

### 3.3 Database Growth Management

| Database | 6-Month Size | Index Strategy | Archival Policy |
|----------|-------------|----------------|-----------------|
| `db/trades.db` | 15 MB | Trade date + instrument | Archive trades > 1 year |
| `db/trade_journal.db` | 50 MB | Timestamp + symbol | Archive > 6 months |
| `db/ml_tracker.db` | 30 MB | Timestamp + model_id | Archive > 3 months |
| `db/oi_snapshots.db` | 200 MB | Instrument + expiry | Purge > 2 years old |

**Archival Command:**
```bash
# Monthly archival job (Python script, uses sqlite3)
python -c "
import sqlite3, os
from pathlib import Path
src = Path('db/trades.db')
if src.exists():
    # Create archive by copying and purging old records
    archive = Path(f'backups/trades_archive_{src.stat().st_mtime:.0f}.db')
    import shutil
    shutil.copy2(src, archive)
    conn = sqlite3.connect(str(src))
    conn.execute('DELETE FROM trades WHERE entry_time < date(\'now\', \'-1 year\')')
    conn.commit()
    conn.execute('VACUUM')
    conn.close()
    print(f'Archived to {archive}, purged records older than 1 year')
else:
    print('No db/trades.db found')
"
```

---

## 4. Resource Budget

### 4.1 Production Instance (Single Index)

| Resource | Budget | Alert Threshold | Critical Threshold |
|----------|--------|-----------------|-------------------|
| Memory | 1 GB | 75% (768 MB) | 90% (920 MB) |
| CPU | 1 core | 60% (30s avg) | 80% (10s avg) |
| Disk | 20 GB | 80% (16 GB) | 95% (19 GB) |
| Network out | 1 GB/month | 500 MB | 800 MB |

### 4.2 Monitoring

```bash
# Daily capacity check via health checker
python -m core.health_checker --format json | jq '.capacity'
# Prometheus metrics on :9090/metrics
```

---

## 5. Cost Projection

| Resource | Monthly Cost (Single Index) | Monthly Cost (Full Platform) |
|----------|---------------------------|------------------------------|
| Compute (VPS) | $10-20 | $50-100 |
| Storage | $2-5 | $10-20 |
| Bandwidth | $1-3 | $5-15 |
| Broker API (Zerodha) | ₹0 (brokerage per trade) | ₹0 (brokerage per trade) |
| **Total** | **$13-28** | **$65-135** |

---

## 6. Verification

This capacity plan is verified by:
- `core/capacity_planning.py` — automated capacity planner module
- `core/health_checker.py` — resource monitoring
- `tests/test_capacity_planning.py` — capacity planning unit tests
- Prometheus metrics (`:9090/metrics`) — real-time resource tracking
