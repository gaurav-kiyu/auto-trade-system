# Runbook: Simultaneous Broker Failover

| Field | Value |
|-------|-------|
| Runbook ID | `RB-009` |
| Severity | CRITICAL |
| Category | Broker / Execution |
| Status | 🚧 **Skeleton — Full content needed before Phase 4** |
| Phase Required | Phase 4+ |

## Trigger Condition
Both primary and backup brokers are unreachable simultaneously.

## Expected Symptoms
- CRITICAL alert: "All brokers exhausted"
- Circuit breaker engaged for all brokers
- No trading possible
- System switches to HARD_HALT automatically

## Initial Diagnosis
```bash
python -m core.health_checker --format json | python -c "import sys,json; d=json.load(sys.stdin); print(json.dumps(d.get('broker',{}),indent=2))"
```

## Resolution
1. **Do NOT attempt to trade** — system should auto-halt
2. Verify network connectivity: check internet, VPN, firewall
3. Check broker status pages/dashboards for maintenance
4. If network issue → fix network
5. If broker maintenance → wait for recovery
6. If both brokers permanently down → reconfigure with new broker

## Verification
- [ ] Both brokers reachable individually
- [ ] Broker failover can complete cycle
- [ ] System resets circuit breaker
- [ ] No positions lost during outage

## Runbook Status
⏳ **This runbook needs a detailed procedure before Phase 4 certification.**

## Related Runbooks
- RB-001: Broker Outage
- RB-005: Network Jitter
