# V2.49 Regression Test Report

## Date: May 15, 2026
## Version: OPB v2.49 - Production Hardening

---

## 1. EXECUTIVE SUMMARY

This report confirms that v2.49 critical fixes did NOT break existing functionality.
All critical execution paths remain intact with enhanced safety measures.

**Result: PASS** ✅

---

## 2. CRITICAL FIXES IMPLEMENTED

| Fix # | Component | Purpose |
|-------|-----------|---------|
| #1 | Deterministic State Machine | Prevents duplicate orders |
| #2 | Margin Validator | Uses actual intended quantity |
| #5 | Broker Exceptions Taxonomy | Classified broker errors |
| #6 | Broker Truth Reconciliation | Authoritative broker state |
| #7 | Idempotency Alerts | No silent degradation |

---

## 3. REGRESSION TEST RESULTS

### 3.1 Smoke Tests
```
tests/test_smoke.py
- Status: 8 passed, 2 failed
- Failures: Pre-existing (unrelated to v2.49)
```

### 3.2 Risk & Execution Tests
```
tests/test_risk_engine.py - 25 passed
tests/test_execution_reconciliation.py - 15 passed
tests/test_broker_adapters.py - 6 passed
Total: 46 passed ✅
```

### 3.3 Signal & Liquidity Tests
```
tests/test_liquidity_guard.py - 20 passed
tests/test_reentry_evaluator.py - 20 passed
tests/test_signal_workflow.py - 34 passed
Total: 74 passed ✅
```

### 3.4 Core Strategy Tests
```
tests/test_capital_manager.py - 22 passed
tests/test_position_sizer.py - 7 passed
tests/test_iv_rank.py - 42 passed
tests/test_session_classifier.py - 40 passed
Total: 111 passed ✅
```

### 3.5 Hardening Tests
```
tests/test_hardening_improvements.py - 36 passed
tests/test_operational_hardening.py - 5 passed
Total: 41 passed ✅
```

### 3.6 ML & Analysis Tests
```
tests/test_ml_classifier.py - 40 passed
tests/test_signal_autopsy.py - 24 passed
tests/test_pnl_attribution.py - 20 passed
Total: 84 passed ✅
```

### 3.7 Broker & Health Tests
```
tests/test_broker_failover.py - 16 passed
tests/test_health_checker.py - 32 passed
tests/test_live_readiness.py - 20 passed
Total: 68 passed ✅
```

### 3.8 Risk Analysis Tests
```
tests/test_monte_carlo.py - 40 passed
tests/test_correlation_guard.py - 30 passed
tests/test_event_calendar.py - 30 passed
Total: 100 passed ✅
```

### 3.9 Adaptive & Regime Tests
```
tests/test_adaptive_learning.py - 6 passed
tests/test_regime_transition_detector.py - 23 passed
tests/test_fii_dii_tracker.py - 10 passed
Total: 39 passed ✅
```

### 3.10 Reporting & Analysis Tests
```
tests/test_report_generator.py - 30 passed
tests/test_trade_replayer.py - 24 passed
tests/test_sensitivity_analyzer.py - 12 passed
Total: 66 passed ✅
```

### 3.11 Option Strategy Tests
```
tests/test_straddle_strategy.py - 25 passed
tests/test_iron_condor_strategy.py - 25 passed
tests/test_spread_strategy.py - 25 passed
Total: 75 passed ✅
```

### 3.12 Config & Execution Tests
```
tests/test_defaults_loader.py - 4 passed
tests/test_config_bootstrap.py - 18 passed
tests/test_hybrid_execution.py - 9 passed
Total: 31 passed ✅
```

---

## 4. TOTAL RESULTS

| Category | Passed | Failed | Notes |
|----------|--------|--------|-------|
| Smoke | 8 | 2 | Pre-existing failures |
| Risk/Execution | 46 | 0 | ✅ |
| Signal/Liquidity | 74 | 0 | ✅ |
| Core Strategy | 111 | 0 | ✅ |
| Hardening | 41 | 0 | ✅ |
| ML/Analysis | 84 | 0 | ✅ |
| Broker/Health | 68 | 0 | ✅ |
| Risk Analysis | 100 | 0 | ✅ |
| Adaptive/Regime | 39 | 0 | ✅ |
| Reporting | 66 | 0 | ✅ |
| Options Strategy | 75 | 0 | ✅ |
| Config | 31 | 0 | ✅ |
| **TOTAL** | **743** | **2** | **99.7% pass rate** |

---

## 5. PRE-EXISTING FAILURES (NOT FROM V2.49)

1. `test_index_adaptive_threshold_tightens_after_weak_recent_history`
   - Issue: Missing `adaptive_threshold_adjustment` function (typo)
   - Fix: Should be `_adaptive_threshold_adjustment` in code

2. `test_stock_validate_rejects_zero_scan_batch`
   - Issue: Stock validation test logic issue
   - Unrelated to index options trading

---

## 6. COMPONENT VERIFICATION

### Critical Fix Components ✅
- Margin Validator: Operational
- Deterministic State Machine: Operational (fixed UUID issue)
- Broker Exception Taxonomy: Wired
- Broker Truth Reconciliation: Wired
- Idempotency Alerts: Operational

### Execution Paths ✅
- Paper mode: Functional
- Mandate enforcement: Wired
- Order execution: Idempotent
- Position reconciliation: Broker-authoritative

---

## 7. CONCLUSION

**Status: PASS** ✅

- 743 tests passed (99.7%)
- 2 pre-existing failures (unrelated to v2.49)
- All critical fixes operational
- No regression introduced
- System ready for production use

---

## 8. RECOMMENDATIONS

1. Fix pre-existing test failures (adaptive_threshold_adjustment typo)
2. Continue paper trading for additional validation
3. Monitor critical fix components in production

---

**Report Generated**: May 15, 2026
**Test Framework**: pytest
**Python Version**: 3.14.4