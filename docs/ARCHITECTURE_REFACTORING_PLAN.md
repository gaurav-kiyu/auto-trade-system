# ARCH-02 Refactoring Plan — `index_trader.py` Service Extraction

**Target:** Split `index_trader.py` (225K chars, 4,924 lines) into domain services  
**Current ARCH-02 Score:** 9.0/9.0 (capped at 9.0 due to monolith)  
**Target ARCH-02 Score:** 9.5/9.5  
**Risk Level:** HIGH — requires careful dependency analysis and test coverage

---

## Current State Analysis

### File Statistics
| Metric | Value |
|--------|-------|
| Total chars | 225,646 |
| Total lines | 4,924 |
| Module-level functions | ~40 |
| Classes | 4 (`_DecisionLog`, `_LegacyBrokerShim`, `StateProxy`, `PositionProxy`) |
| Module-level imports | ~36 |
| Module-level global variables | ~30+ |

### Duplicate Section
The file contains a **near-duplicate section**:
- **Section 1**: Lines 427-2425 (1,999 lines) — first set of function definitions
- **Section 2**: Lines 2873-4924 (2,052 lines) — second set, overwrites first
- **Middle section**: Lines 2426-2872 (447 lines) — initialization code

**Important:** The two sections are NOT identical. Section 2 has 53 more lines and contains different code in `_stale_detector` initialization and `_check_hard_stops_via_risk`. This means the second copy is the "active" one at runtime (Python's later `def` wins).

### External Dependencies
Files that import from `index_trader`:
| File | Import Style |
|------|-------------|
| `core/execution/broker_truth_reconciliation.py` | `import index_app.index_trader as it` |
| `core/morning_checklist.py` | `import index_app.index_trader as m` |
| `core/services/risk_service.py` | `import index_app.index_trader as m` |
| `index_app/gui/trader_desk.py` | `import index_app.index_trader as mod` |
| `index_app/index_trader_interface.py` | `from index_app.index_trader import container, setup_di_container` |
| `index_app/orchestrator_facade.py` | `import index_app.index_trader as m` |
| `tests/test_trader_exit.py` | `from index_app.index_trader import _exit_position, _monitor_positions` |

---

## Phase 1: Remove Dead Duplicate (Low Risk)

### Steps
1. Analyze exact diff between Section 1 and Section 2
2. Remove Section 1 (lines 427-2425) — it's overwritten by Section 2 at runtime
3. Move any unique code from Section 1 into Section 2's definitions
4. Remove the middle section (lines 2426-2872) — merge into Section 2's setup
5. Result: single copy of all functions, ~2,800 lines

### Verification
- All 479 tests must pass
- Paper mode dry run must work
- All external imports must still resolve

### Risk Level: MEDIUM
The sections differ in 53 lines. Each difference must be analyzed to determine which version is correct.

---

## Phase 2: Strategy Service Extraction (Medium Risk)

### Extract: `index_app/services/signal_fetcher.py`
**Functions to move:**
- `_fetch_intraday_data()` (self-contained yfinance wrapper)
- `_fetch_intraday_data_cached()` (thin caching layer on top)
- `_yf_fetch_vix()` (self-contained)

**Dependencies to inject:**
- `INDEX_MAP` (dict)
- `_yf_data_cache` (module-level dict → pass as param or use class)

**Result:** Clean data access layer, 60 lines removed from main file.

### Extract: `index_app/services/position_manager.py`
**Functions to move:**
- `_exit_position()` (exit logic)
- `_monitor_positions()` (SL/target monitoring)

**Dependencies to inject:**
- `_execution_service` (ExecutionPort interface)
- `_pos_lock` (threading.Lock)
- `positions` (dict)
- `_CFG` (config dict)
- `get_underlying_ltp` (callable)
- `_portfolio_service` (interface)
- `_reentry_trackers` (dict)
- `_trip_hard_halt` (callable)
- `send` (callable)

**Result:** Position lifecycle management, ~180 lines removed.

---

## Phase 3: Trading Loop Extraction (High Risk)

### Extract: `index_app/services/trading_loop.py`
**Functions to move:**
- `_run_trading_loop()` (main loop)
- `_on_ws_tick()` (WS callback)

**Dependencies to inject:**
- All module-level state references
- All other service references

**Result:** Trading orchestration, ~150 lines removed.

---

## Phase 4: Entry Gate Extraction (High Risk)

### Extract: `index_app/services/entry_service.py`
**Functions to move:**
- `enter_trade()` (entry gate with risk checks)
- `_telegram_action_quality()` (signal quality check)
- `_telegram_action_body()` (message formatting)

**Dependencies to inject:**
- All risk, portfolio, execution, and notification services
- ~10 module-level globals

**Result:** Complete entry lifecycle, ~220 lines removed.

---

## Phase 5: Config & Mandate Extraction (Medium Risk)

### Extract: `index_app/services/config_service.py`
- `_load_config()`, `_set_config_fail_safe()`, `_notify_config_failure()`

### Extract: `index_app/services/mandate_service.py`
- `check_mandate_trade_allowed()`, `get_mandate_status()`, `validate_signal_pillars()`

---

## Phase 6: Final Cleanup

After all extractions, `index_trader.py` becomes a thin coordinator:
- Imports
- Module-level state (locks, globals)
- `main()` function
- `setup_di_container()` function
- Stub exports for backward compatibility

**Target size:** ~800-1,000 lines

---

## Dependency Visualization

```
index_trader.py (coordinator)
  ├── → yf_data_provider.py (data fetching)
  ├── → position_manager.py (exit + monitor)
  ├── → trading_loop.py (main loop)
  ├── → entry_service.py (enter trade)
  ├── → config_service.py (config loading)
  └── → mandate_service.py (trade allow/block)
  
  Also depends on:
  ├── core/safety_state.py (halt, shutdown)
  ├── core/portfolio_service.py (PnL, capital)
  ├── core/risk_service.py (risk evaluation)
  ├── core/execution_service.py (order execution)
  └── core/notification_service.py (Telegram)
```

---

## Success Criteria

| Criterion | Target | Verification |
|-----------|--------|-------------|
| ARCH-02 max_score | 9.5 | Constitution scoring |
| Total tests | 479 pass | `python -m pytest tests/` |
| File size | <1,000 lines | Line count |
| External imports | All working | `grep -r "index_trader"` |
| Paper mode | Trading loop functional | `--paper --dry-run` |
| Institutional challenge | 8/8 PASS | `python scripts/institutional_challenge.py` |

---

## Estimated Effort

| Phase | Effort | Risk | Dependencies |
|-------|--------|------|-------------|
| Phase 1 (Remove duplicate) | 30 min | MEDIUM | Diff analysis, test verification |
| Phase 2 (Data provider) | 30 min | LOW | None — self-contained |
| Phase 3 (Position mgr) | 1 hr | MEDIUM | Entry + loop must be updated too |
| Phase 4 (Trading loop) | 1 hr | HIGH | All services must exist first |
| Phase 5 (Entry gate) | 1 hr | HIGH | Position + loop must exist |
| Phase 6 (Config/mandate) | 30 min | MEDIUM | None |
| Phase 7 (Cleanup) | 30 min | LOW | All extractions complete |
| **Total** | **~5 hours** | | |

---

## Notes

- Each phase should be implemented as a separate git commit for traceability
- Run the full test suite after each phase
- Paper mode dry-run after each phase to catch runtime errors
- The DI container (`core/di_container.py`) should be used to wire dependencies
- After all phases, `index_trader.py` becomes a thin bootstrap file
