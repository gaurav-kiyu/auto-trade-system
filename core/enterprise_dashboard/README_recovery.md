# Enterprise Dashboard Recovery Artifact

## Status: ✅ RESOLVED

The orphaned file `_recovered_methods.py` has been **deleted** (June 29, 2026).

### Background

`_recovered_methods.py` was a 1,664-line recovery artifact containing dashboard API endpoint methods that were extracted during decomposition of the monolithic `enterprise_dashboard.py`.

### Analysis Result

After comparing all methods against the proper route files in `core/enterprise_dashboard/routes/`:

- **Every method** had a working equivalent in the proper route files
- **Zero imports** referenced this file (verified via code search)
- **All enterprise dashboard tests passed** after deletion

### Routes Directory Structure

All dashboard API endpoints now live in the proper route modules:

| Route Module | Handles |
|-------------|---------|
| `routes/admin.py` | Config management, kill switch, pause/resume, change management, self-test |
| `routes/system.py` | System state, trades, health, signals, WS status, Docker health, OI, invariants, uptime, diagnostics |
| `routes/monitoring.py` | Notifications (SSE + REST), broker info, ML status, data providers, performance comparison |
| `routes/risk.py` | Risk snapshot, SLO compliance, alerts, limits, concentration, portfolio allocation, CSV export |
| `routes/webhooks.py` | Signal injection, options chain visualization |
| `routes/pages.py` | Page rendering |
| `routes/fundamentals.py` | Fundamentals analysis API |

### Verification

```
$ python -m pytest tests/test_enterprise_dashboard.py -q
........................................................................ [100%]
✅ All tests pass
```

*Generated: June 29, 2026 | Updated: File deleted, issue resolved*
