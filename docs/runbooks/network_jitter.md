# Runbook: Network Jitter / Packet Loss

| Field | Value |
|-------|-------|
| Runbook ID | `RB-005` |
| Severity | MEDIUM |
| Category | Network / Infrastructure |
| Status | 🚧 **Skeleton — Full content needed before Phase 4** |
| Phase Required | Phase 4+ |

## Trigger Condition
Packet loss > 1%, latency spikes > 2s, or TCP retransmission rate > 5%.

## Diagnosis
- Check broker API response times
- Check data feed latency
- Run `ping` / `tracert` to broker endpoints

## Resolution
- Switch to backup broker if primary latency exceeds 3s
- Switch to backup data feed (yfinance fallback)
- If both brokers affected → switch to SIGNAL_ONLY
- Log for ISP escalation if persistent

## Runbook Status
⏳ **This runbook needs a detailed procedure before Phase 4 certification.**

## Related Runbooks
- RB-001: Broker Outage
- RB-007: Config Corruption
