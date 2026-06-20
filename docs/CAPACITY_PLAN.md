# Capacity Plan — OPB Institutional Platform v2.53.0

**Generated:** 2026-06-20  
**Classification:** INTERNAL — Infrastructure Planning

---

## 1. Executive Summary

This capacity plan defines the compute, memory, storage, network, and broker API budgets required to operate the OPB Index Options Buying Bot across five deployment tiers — from single-user paper trading to multi-strategy institutional deployment.

| Tier | Capital Range | Users | Strategies | Target Coverage |
|------|--------------|-------|------------|-----------------|
| **Paper** | ₹0–₹1L | 1 | 1–2 | 1 index, 2 equities |
| **Small Live** | ₹1L–₹5L | 1–2 | 2–4 | 3 indices, 5 equities |
| **Medium Live** | ₹5L–₹25L | 2–5 | 4–8 | 5 indices, 10 equities |
| **Large Live** | ₹25L–₹1Cr | 5–20 | 8–16 | Full market coverage |
| **Institutional** | ₹1Cr+ | 20+ | 16+ | Multi-strategy, multi-broker |

**Key recommendation:** Current architecture supports ₹1L–₹25L without modification. ₹25L+ requires the horizontal scaling enhancements described in §5.

---

## 2. Current Resource Profile

### 2.1 Compute (CPU)

| Component | Threads | CPU per Cycle | Frequency |
|-----------|---------|--------------|-----------|
| Main trading loop | 1 | 2–5 ms | Every 15–30s |
| Data fetching (yfinance) | 1 per symbol | 500–2000 ms | Every 15–30s |
| ML inference | 1 | 50–150 ms | Per signal |
| OI snapshot recording | 1 | 200–500 ms | Every 60s |
| WebSocket feed | 1 | 1–5 ms | Continuous |
| Telegram dispatch | Pool (4) | 10–50 ms | On demand |
| GUI/LCD display | 1 | 5–20 ms | Every 2s |
| Web dashboard (opt-in) | 1 | 10–50 ms | On demand |
| Health check scheduler | 1 | 100–500 ms | Sunday EOD |
| **Total steady-state** | **~8–12 threads** | **~1–3s/cycle** | |

### 2.2 Memory (RAM)

| Component | Current Usage | Peak |
|-----------|--------------|------|
| Python runtime | 40–60 MB | 80 MB |
| Intraday data cache (1m/5m/15m × 5 indices) | 15–30 MB | 50 MB |
| ML model (LightGBM) | 50–100 MB | 150 MB |
| Trade database (SQLite cache) | 5–20 MB | 50 MB |
| Event store (SQLite) | 2–10 MB | 30 MB |
| Web dashboard (FastAPI) | 30–50 MB | 80 MB |
| Tkinter GUI | 10–20 MB | 30 MB |
| **Total** | **~150–290 MB** | **~470 MB** |

### 2.3 Storage (Disk)

| Resource | Current Size | Growth Rate | Retention |
|----------|-------------|-------------|-----------|
| `trades.db` | 5–20 MB | ~1 MB/day | 90 days |
| `trade_journal.db` | 2–5 MB | ~0.2 MB/day | 90 days |
| `ml_tracker.db` | 1–3 MB | ~0.1 MB/day | 180 days |
| `oi_snapshots.db` | 10–50 MB | ~2 MB/day | 90 days (cold start) |
| Event store (SQLite) | 5–15 MB | ~0.5 MB/day | 30 days |
| Log files | 10–50 MB | ~5 MB/day | 7 days (rotated, gzip) |
| Audit trail (JSONL) | 1–5 MB | ~0.1 MB/day | 90 days |
| **Total growth** | | **~8.9 MB/day** | |

### 2.4 Network

| Source | Bandwidth per Call | Frequency | Daily Volume |
|--------|-------------------|-----------|-------------|
| yfinance (OHLCV) | 5–50 KB | ~3,000 calls/day | ~15–150 MB |
| NSE website (option chain) | 10–100 KB | ~480 calls/day | ~5–48 MB |
| Broker API (order placement) | 1–5 KB | ~20 calls/day | ~20–100 KB |
| Telegram notifications | 1–10 KB | ~100–500 msgs/day | ~0.1–5 MB |
| VIX fetch | 5–20 KB | ~480 calls/day | ~2–10 MB |
| **Total egress** | | | **~22–213 MB/day** |

---

## 3. Scaling Limits

### 3.1 Broker API Rate Limits

| Broker | Endpoint | Limit | Headroom at ₹5L |
|--------|----------|-------|-----------------|
| **Kite (Zerodha)** | Place order | 10/sec, 100/min | ✅ Sufficient |
| | Historical data | 3/sec | ⚠️ Near limit with 5 symbols |
| | WebSocket ticks | Unlimited (own feed) | ✅ |
| **Angel One** | Place order | 5/sec, 50/min | ✅ Sufficient |
| | Historical data | 2/sec | ⚠️ May throttle |
| **Yahoo Finance** | Download | ~2,000/hr (unauthenticated) | ⚠️ May throttle at scale |

### 3.2 SQLite Concurrency Limits

| Database | Write Pattern | Concurrent Readers | Bottleneck |
|----------|--------------|-------------------|------------|
| `trades.db` | Append-only trades | 1 writer, unlimited readers | WAL mode mitigates |
| `event_store.db` | Append-only events | 1 writer, unlimited readers | Sequential append |
| `oi_snapshots.db` | Batch insert | 1 writer | Unlikely to bottleneck |
| `ml_tracker.db` | Occasional write | 1 writer | Negligible load |

**SQLite limitation:** At >50 concurrent readers or >1,000 writes/sec, SQLite becomes a bottleneck. For institutional scale, migrate to PostgreSQL.

### 3.3 Memory Scaling

| Tier | RAM Budget | Headroom |
|------|-----------|----------|
| Paper | 256 MB | ❌ Insufficient |
| Small Live | 512 MB | ⚠️ Tight |
| Medium Live | 1 GB | ✅ Comfortable |
| Large Live | 2 GB | ✅ Comfortable |
| Institutional | 4 GB+ | ✅ Required for PostgreSQL |

---

## 4. Capacity Thresholds & Alerts

| Metric | Warning | Critical | Action |
|--------|---------|----------|--------|
| CPU > 70% for 5 min | ⚠️ Log warning | 🚨 Reduce scan frequency | Increase SCAN_INTERVAL |
| RAM > 80% | ⚠️ Log warning | 🚨 Alert operator | Restart or scale up |
| Disk > 85% | ⚠️ Log warning | 🚨 Trigger log rotation | Archive/delete old logs |
| yfinance rate limit hits | ⚠️ Log warning | 🚨 Switch to broker API | Implement fallback chain |
| SQLite WAL size > 100 MB | ⚠️ Log warning | 🚨 Run checkpoint | `PRAGMA wal_checkpoint(TRUNCATE)` |
| Trade count > 10,000 | ⚠️ Log warning | 🚨 Archive old trades | Export + VACUUM |

---

## 5. Scaling Recommendations

### 5.1 Immediate (No Code Changes)
1. Increase `SCAN_INTERVAL` from 15s to 30s for ₹25L+ to reduce yfinance rate limit risk
2. Enable log compression: `LOG_ROTATE_GZIP: true` (default in config)
3. Set `METRICS_PORT: 9090` to enable Prometheus monitoring for capacity planning
4. Schedule weekly SQLite VACUUM via cron/systemd timer

### 5.2 Short-term (Code Changes, 1-2 Days)
1. Implement data fetch caching with TTL to reduce yfinance calls by ~60%
2. Add connection pooling for SQLite (currently implicit via WAL mode)
3. Implement adaptive scan interval: increase interval when CPU > 50%
4. Add in-memory LRU cache for frequently accessed trade records

### 5.3 Medium-term (2-5 Days)
1. **PostgreSQL migration** for trade/event/audit storage at >₹25L scale
2. **Horizontal sharding** by index for data fetching workers
3. **Redis caching layer** for frequently accessed market data
4. **Async broker API calls** to reduce main loop blocking

### 5.4 Long-term (Future Release)
1. **Microservices decomposition**: signal generation, risk, execution as separate services
2. **Event-streaming** (Kafka/NATS) for decoupled data pipelines
3. **Kubernetes deployment** for auto-scaling at institutional scale
4. **Read-replica databases** for dashboard/analytics queries

---

## 6. Cost Projection (Cloud/Hosting)

| Tier | Compute | Storage | Network | Estimated Monthly |
|------|---------|---------|---------|-------------------|
| Paper | Free tier (0.5 vCPU, 512 MB) | 10 GB HDD | 100 GB transfer | ₹0–500 |
| Small Live | ₹1,000 VM (1 vCPU, 1 GB) | 20 GB SSD | 500 GB transfer | ₹1,000–1,500 |
| Medium Live | ₹3,000 VM (2 vCPU, 2 GB) | 50 GB SSD | 1 TB transfer | ₹3,000–4,000 |
| Large Live | ₹8,000 VM (4 vCPU, 4 GB) | 100 GB SSD | 2 TB transfer | ₹8,000–10,000 |
| Institutional | Custom (8+ vCPU, 16+ GB) | 500 GB SSD + DB | 5+ TB transfer | ₹50,000+ |

**Recommendation:** For ₹25L+ trading, budget at least ₹8,000/month for infrastructure. This is <0.5% of deployed capital and provides professional-grade reliability.

---

## 7. Monitoring & Observability

Enable the following dashboards and alerts at each tier:

| Tier | Monitoring Stack | Key Metrics |
|------|-----------------|-------------|
| Paper | Local logs | CPU, RAM, disk |
| Small Live | Prometheus + local | + yfinance rate limit, trade latency |
| Medium Live | Prometheus + Grafana | + Broker API latency, SQLite WAL size |
| Large Live | + Sentry/DataDog | + Error budgets, SLO tracking |
| Institutional | Full observability stack | + Distributed tracing, cost attribution |

---

## 8. Appendix: Key Config Parameters Affecting Capacity

| Config Key | Default | Capacity Impact |
|-----------|---------|-----------------|
| `SCAN_INTERVAL` | 30 | Lower = more CPU/data fetches |
| `MAX_OPEN` | 2 | Higher = more positions to monitor |
| `MAX_TRADES_DAY` | 5 | Higher = more broker API calls |
| `OI_RECORD_INTERVAL` | 60 | Lower = more DB writes |
| `DATA_CACHE_TTL` | 15 | Lower = more yfinance calls |
| `LOG_ROTATE_MB` | 50 | Lower = more frequent compression |
| `METRICS_PORT` | 0 (disabled) | Enable for capacity monitoring |
| `WEB_DASHBOARD_ENABLED` | false | Enable adds ~50 MB RAM |

---

*This capacity plan should be reviewed quarterly and updated when capital deployment exceeds 75% of the current tier's upper bound.*
