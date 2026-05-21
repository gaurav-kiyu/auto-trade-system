# EXECUTION FORENSICS AUDIT — OPB v2.45

**Date:** 2026-05-20  
**Auditor:** Automated forensics engine  
**Scope:** `core/execution/`, `core/services/execution_service.py`, `index_app/index_trader.py`, `core/persistence/`, `core/safety_state.py`  
**Lines of code audited:** ~5,200  

---

## SUMMARY

| Severity | Count |
|----------|-------|
| BLOCKER  | 2     |
| CRITICAL | 5     |
| HIGH     | 7     |
| MEDIUM   | 6     |
| LOW      | 3     |

**Risk of financial loss:** REAL — at least 3 scenarios can cause duplicate orders, missed fills, or undetected position divergence in production.

---

## FINDINGS

### B-1: Dual idempotency key spaces — state machine creates non-overlapping entries

| Field       | Value |
|-------------|-------|
| Severity    | **BLOCKER** |
| Category    | IDEMPOTENCY |
| File        | `index_app/index_trader.py:932-934` + `core/services/execution_service.py:805,807` |
| Line        | 932–934, 805–807 |

**Issue:** The singleton `ExecutionStateMachineManager` is called twice for the same order using DIFFERENT `intent_id` values.  
- Call 1 (index_trader.py:934): `intent_id = f"{name}_{direction}_{qty}_{signal_uuid}"` — includes signal UUID  
- Call 2 (execution_service.py:805): `intent_id = f"{symbol}_{direction}_{strike_price}_{lot_size}"` — NO signal UUID  

These generate non-overlapping keys. The state machine creates two separate machines for the same physical order. The first machine is never transitioned past CREATED. The second machine drives the actual execution.

**Scenario:** Every order creates a zombie state machine entry. In-flight queries see entries that never complete. If a crash triggers recovery, the first machine (never transitioned) appears as an orphan and confuses reconciliation. This also defeats Level-1 idempotency because the first call never transitions the machine.

**Impact:** Loss of idempotency at the state-machine level. Reconciliation produces false orphans. Exact duplicate detection across restart requires both key spaces to be checked, which no code does.

**Fix:** Use identical `intent_id` in both calls. The deterministic state machine's `create_or_get` is intended to be the single idempotency gate — it must be called with the same ID from both places, or better, called only from one place (`execution_service`) and removed from `index_trader`.

---

### B-2: Signal UUID fallback to `str(uuid.uuid4())` makes Level-1 idempotency a no-op

| Field       | Value |
|-------------|-------|
| Severity    | **BLOCKER** |
| Category    | IDEMPOTENCY |
| File        | `index_app/index_trader.py:931-933` |
| Line        | 931–933 |

```python
signal_uuid = sig.get("uuid", sig.get("signal_id", str(_uuid.uuid4())))
idempotency_key = f"{name}_{direction}_{int(qty)}_{signal_uuid}"
```

**Issue:** When `sig` has no `uuid` or `signal_id` field (which can happen depending on signal source), `str(uuid.uuid4())` is used — a **different random value on every call**. This means every invocation of `enter_trade()` generates a unique idempotency key, so `create_or_get` always returns `is_new=True`. The idempotency block at line 941–944 **never fires** for repeated signals.

**Scenario:** The same signal processed twice (e.g., from Telegram commander + scan loop) will both get past the idempotency check and submit two orders.

**Impact:** REAL DUPLICATE ORDERS. Unhedged options bought twice the intended size.

**Fix:** Remove the `uuid.uuid4()` fallback. If no signal UUID exists, use a deterministic hash of the signal content (`name`, `direction`, `price`, `qty`, `signal_ts`). Better yet, enforce that all signal sources MUST provide a `signal_id`.

---

### C-1: Persistence callback persists OLD state, not NEW state

| Field       | Value |
|-------------|-------|
| Severity    | **CRITICAL** |
| Category    | PERSISTENCE |
| File        | `core/execution/deterministic_state_machine.py:124-136` |
| Line        | 124–136 |

**Issue:** The "Persist FIRST, then mutate" pattern has a fundamental flaw: the persistence callback is invoked with `self.state` still holding the **old** state. The callback in `execution_service.py:109-134` reads `machine.state` to determine what to persist. It always persists the pre-transition state.

**Flow:**
1. `validate_transition(new_state=ExecutionState.SUBMITTED)` called  
2. Callback invoked with `self.state = PERSISTED` (old)  
3. Callback persists `PERSISTED` to durable store  
4. `self.state = SUBMITTED` (new) — in-memory only  

**Scenario:** Crash between step 3 and 4. On restart, DB says `PERSISTED` (pre-transition). Recovery logic sees an order that hasn't been submitted and resubmits it to the broker.

**Impact:** DUPLICATE ORDER on every crash that occurs between lines 132 and 138 of any valid transition. This is a state-tearing bug that directly leads to double execution.

**Fix:** Pass the NEW state to the callback explicitly, e.g. `self._persistence_callback(self, new_state)`, and have the callback persist `new_state` not `self.state`.

---

### C-2: Circuit breaker bypass via alternating error types

| Field       | Value |
|-------------|-------|
| Severity    | **CRITICAL** |
| Category    | RETRY |
| File        | `core/execution_engine.py:108-130` |
| Line        | 108–130 |

**Issue:** The circuit breaker counts consecutive retryable errors **of the same exception type**. If errors alternate between different types (e.g., `TimeoutError` → `ConnectionError` → `TimeoutError` → `ConnectionError`), the counter resets each time. This permits unlimited retries as long as the error type alternates.

**Scenario:** Broker experiences a flapping failure where each call returns a different exception type (common during network degradation). The circuit breaker never trips. Retry storm continues until max retries are exhausted, but max retries × alternating types means far more than the intended 2+1 = 3 attempts. With `retries=3` (default), alternating types allows `2*3 = 6` attempts.

**Impact:** 2–3× more broker API calls than intended during degradation. Could worsen the degradation. Higher latency for the caller.

**Fix:** Use a second counter that counts ALL retryable errors regardless of type. Trip the circuit breaker when `_consecutive_retryable >= 2` (any type) OR `_total_retryable >= 5`.

---

### C-3: No hard halt check in ExecutionService::execute_order()

| Field       | Value |
|-------------|-------|
| Severity    | **CRITICAL** |
| Category    | SAFE_MODE |
| File        | `core/services/execution_service.py:296-430` |
| Line        | 296–430 |

**Issue:** `ExecutionService.execute_order()` performs no check on `safety_state.is_hard_halted()`. The hard halt check exists only upstream in `index_trader.py:enter_trade()` (line 769). Any code path that calls `execute_order()` directly bypasses the hard halt.

**Scenario:**  
1. Risk breach trips `_HARD_HALT`  
2. A different signal source (webhook, backtest replay, Telegram commander) calls `_execution_service.execute_order()` directly  
3. The order is placed against a hard-halted system  

**Impact:** Hard halt rendered ineffective for any entry path other than `enter_trade()`.

**Fix:** Add `from core.safety_state import is_hard_halted` and a check at the top of `execute_order()`:

```python
if is_hard_halted():
    return OrderResult(order_id="hard_halted", status=OrderStatus.REJECTED, 
                       reject_reason="System is hard halted")
```

---

### C-4: Lock released before broker API call — TOCTOU gap

| Field       | Value |
|-------------|-------|
| Severity    | **CRITICAL** |
| Category    | CONCURRENCY |
| File        | `core/services/execution_service.py:332-376` |
| Line        | 332, 363, 376 |

**Issue:** The `self._lock` (line 332) protects idempotency-check → persist → mark-in-flight, **but is released at line 363** before the actual broker call at line 376. Between releasing the lock and making the API call:  
- The in-flight marker IS in the DB (persisted at line 362)  
- But another connection/thread could query the broker directly and find no order, then attempt to submit itself  
- More critically, if the broker call hangs for 30+ seconds, no other thread blocks on it (lock is released)

**Scenario:**  
- Thread 1: acquires lock, marks in-flight, releases lock, starts broker call  
- Thread 2: acquires lock, checks idempotency → in-flight found → blocked correctly  
- But: Thread 2's idempotency check happens while Thread 1 is IN the broker call. If the broker returns success to Thread 1 but crashes before `confirm_execution()`, Thread 2 is blocked for the stale in-flight timeout (1 hour).

**Impact:** Orphan in-flight markers on crash that block legitimate retries for up to 1 hour.

**Fix:** Keep the lock held through the broker call, or use a two-phase commit with broker-native idempotency. If latency is a concern, use a separate per-order lock (one per intent_id) instead of a single global lock.

---

### C-5: RECONCILING → UNKNOWN cycle creates infinite loop

| Field       | Value |
|-------------|-------|
| Severity    | **CRITICAL** |
| Category    | STATE_MACHINE |
| File        | `core/execution/deterministic_state_machine.py:79-80` |
| Line        | 79–80 |

**Issue:** The valid transitions allow `UNKNOWN → RECONCILING → UNKNOWN`:
```python
ExecutionState.UNKNOWN: [ExecutionState.RECONCILING],
ExecutionState.RECONCILING: [..., ExecutionState.UNKNOWN],
```

If reconciliation fails (can't determine state), it transitions back to UNKNOWN, which can transition back to RECONCILING. Nothing prevents this cycle from spinning forever.

**Scenario:** A stuck order in UNKNOWN state. Reconciliation runs every 30 seconds (continuous_reconciliation.py:75). Each cycle: UNKNOWN → RECONCILING → (attempt to resolve, fails) → UNKNOWN. Infinite loop.

**Impact:** Wasted CPU, log spam, delayed processing of other orders. Maybe not directly dangerous but masks the underlying problem and can hide a real issue.

**Fix:** Remove `UNKNOWN` from RECONCILING's valid target list. Add a `reconciliation_attempt_count` and fail permanently after N attempts.

---

### H-1: News sentinel failure is fail-OPEN

| Field       | Value |
|-------------|-------|
| Severity    | **HIGH** |
| Category    | SAFE_MODE |
| File        | `index_app/index_trader.py:786-787` |
| Line        | 786–787 |

```python
except Exception:
    pass  # Fail-open: allow entry if news sentinel unavailable
```

**Scenario:** News sentinel crashes or times out (e.g., RSS feed unavailable). Trading continues uninterrupted during a potential news-driven event.

**Issue:** Fail-open for a safety system. If the news sentinel is unavailable, the system should default to blocking entries, not allowing them.

**Fix:** Change to fail-closed: `on_news_sentinel_error = config.get("news_sentinel_fail_behavior", "block")`. On exception, block entry and log CRITICAL.

---

### H-2: ExecutionService reconciliation freeze is RAM-only, lost on restart

| Field       | Value |
|-------------|-------|
| Severity    | **HIGH** |
| Category    | PERSISTENCE |
| File        | `core/services/execution_service.py:169,244-248` |
| Line        | 169, 244–248 |

**Issue:** `_is_reconciliation_frozen` is a boolean in RAM. If the process restarts (crash or deploy), the frozen state is lost. The reconciliation that detected the problem (orphan positions, quantity mismatch) would not re-evaluate on restart because `reconcile_pending_orders()` (line 250) is called but its freeze outcome is only logged, not persisted.

**Scenario:** Orphan position detected before crash → trading frozen → crash → restart → `reconcile_pending_orders()` runs, finds the orphan again, re-freezes (if ambiguity is detected). But:
- The orphan order's existence is what triggered the freeze, and  
- No manual review was done between restart and reconciliation run

So the system MIGHT re-freeze, but there's no guarantee (depends on broker state).

**Impact:** Restart could silently unfreeze the system when it should remain frozen until manual review.

**Fix:** Persist freeze state to the durable store. Load on startup. Don't auto-clear.

---

### H-3: No strict ordering of lock acquisition — deadlock potential

| Field       | Value |
|-------------|-------|
| Severity    | **HIGH** |
| Category    | CONCURRENCY |
| File        | `index_app/index_trader.py:886` + `core/execution/` (19 lock sites) |
| Line        | Multiple |

**Issue:** At least 12 distinct `threading.Lock()` / `threading.RLock()` objects exist. There is no documented lock hierarchy. Code paths that acquire multiple locks (e.g., `enter_trade` acquires `_state_lock`, then calls `execution_service` which acquires `self._lock`) could deadlock if different threads acquire them in different order.

**Files with locks:** `execution_state.py:127,306`, `deterministic_state_machine.py:111,246`, `order_manager.py:44`, `durable_state.py:69`, `reconciliation/service.py:88`, `continuous_reconciliation.py:84`, `event_system.py:321`, `idempotency/manager.py:46`, `execution_service.py:145`, `index_trader.py:432-434`.

**Scenario:** Thread A: `_state_lock` → `_lock` (execution_service). Thread B: `_lock` (execution_service) → `_state_lock`. Deadlock. Process hangs, no new entries accepted.

**Impact:** Complete system freeze until watchdog kills process.

**Fix:** Document strict lock ordering. Use `threading.RLock` everywhere or a single coordinator lock. Add deadlock detection (e.g., `acquire(timeout=5)` with retry).

---

### H-4: Two separate order-state databases can diverge

| Field       | Value |
|-------------|-------|
| Severity    | **HIGH** |
| Category    | PERSISTENCE |
| File        | `core/execution/durable_state.py:67`, `core/execution/reconciliation/service.py:81`, `core/execution/order_manager.py:37` |
| Line        | 67, 81, 37 |

**Issue:** Three separate SQLite databases track overlapping concepts:
- `execution_state.db` — DurableExecutionStore  
- `trades.db` (execution_orders table) — ReconciliationService  
- `order_state.db` — OrderManager  

There is no consistency check between them. A write to one could succeed while another fails. On recovery, which is the source of truth?

**Scenario:** `DurableExecutionStore.save_execution()` succeeds but `ReconciliationService.record_order()` fails (or vice versa). The durable store says the order was submitted; reconciliation says it doesn't exist. This triggers a false orphan detection and trading freeze.

**Impact:** False positives (trading frozen when nothing is wrong), or worse, false negatives (no freeze when a real divergence exists).

**Fix:** Consolidate into a single state table in one database. Or implement a write-all-atomic pattern: if any write fails, roll back all.

---

### H-5: `run_ack_watchdog` acquires machine locks one at a time — no atomicity

| Field       | Value |
|-------------|-------|
| Severity    | **HIGH** |
| Category    | CONCURRENCY |
| File        | `core/services/execution_service.py:189-230` |
| Line        | 189–230 |

**Issue:** `run_ack_watchdog()` iterates over all machines from `manager.get_all()` and acquires each machine's `_lock` individually. Between iterations:
- A machine check could be stale (machine state changed between release and next iteration)  
- If `manager.get_all()` returns a list that's a snapshot (line 293-294 in deterministic_state_machine.py: `list(self._machines.values())`), this is safe  
- BUT: between machine iteration, new machines can be added to the manager dict without the watchdog seeing them this cycle

More critically: on line 190, `with machine._lock:` is acquired, then at line 203 `result["checked"] += 1` is OUTSIDE the lock. The lock is only around reading `machine.state` and `machine.submitted_at`. The broker query (line 209) is OUTSIDE the lock.

**Scenario:** Machine state changes between lock release (line 203) and broker query (line 209). The broker says FILLED, but the machine might have already transitioned to CANCEL_PENDING from another thread. The watchdog then tries to transition to ACKNOWLEDGED → FILLED, which would be an invalid transition from CANCEL_PENDING.

**Impact:** Failed state transitions logged as errors. State machine enters unexpected state.

**Fix:** Hold the lock through the entire check + transition. Or at minimum, re-check `machine.state` after acquiring the lock inside the broker-query block.

---

### H-6: Broker position staleness check uses pre-fetch age

| Field       | Value |
|-------------|-------|
| Severity    | **HIGH** |
| Category    | RECONCILIATION |
| File        | `core/execution/broker_truth_reconciliation.py:91-98,112-117` |
| Line        | 91–98, 112–117 |

**Issue:** The `cache_age` variable is computed before the `if cache_age is None or cache_age > max_staleness` block. At line 112, the staleness check uses the **pre-refresh** `cache_age`. If cache was stale and got refreshed at lines 96-98, the result reports STALE even though data was just fetched.

**Scenario:** First call after startup always reports STALE for max_staleness seconds, even with fresh data. Risk engine sees STALE and may reject trades unnecessarily.

**Impact:** Spurious STALE warnings and potential trade blocks for max_staleness seconds on startup.

**Fix:** Recompute cache_age after the refresh block.

---

### H-7: Continuous reconciliation triggers manual_intervention alerts but takes no action

| Field       | Value |
|-------------|-------|
| Severity    | **HIGH** |
| Category    | RECONCILIATION |
| File        | `core/execution/continuous_reconciliation.py:125-126,193-222` |
| Line        | 125–126, 193–222 |

**Issue:** `ContinuousReconciliation._run_loop()` calls `_handle_issue()` for each detected issue (line 125-126), but `_handle_issue()` only logs to audit journal and calls a callback. There is NO action to freeze trading, trip hard halt, or block entries.

**Scenario:** Continuous reconciliation detects an orphan position (broker has a position that local state doesn't know about). The issue is logged. Trading continues. The bot opens a new trade that conflicts with the orphan position, creating a double exposure.

**Impact:** Unhedged double position. Unlimited downside risk if the orphan + new position both go against the bot.

**Fix:** Add freeze_trading() call when `requires_manual_intervention=True` issues are detected. Optionally trip hard halt if orphan positions are confirmed.

---

### M-1: `EventBus.publish()` silently swallows handler exceptions

| Field       | Value |
|-------------|-------|
| Severity    | **MEDIUM** |
| Category    | STATE_MACHINE |
| File        | `core/execution/event_system.py:357-361` |
| Line        | 357–361 |

```python
for handler in handlers:
    try:
        handler(event)
    except Exception as e:
        _log.error(f"Event handler failed for {event.event_type.value}: {e}")
```

**Issue:** If a critical event handler (e.g., risk breach handler, fill handler) throws, the exception is caught and logged but other handlers are still executed. The failing event is stored in the event store (written at line 346 before handler dispatch). System continues as if everything is fine.

**Scenario:** The FILL_RECEIVED handler fails (e.g., DB write error). The fill event is stored but not processed. Position tracking is out of sync. The system thinks it has a different position than it actually does.

**Impact:** Silent position divergence. Next trade opens against stale positions.

**Fix:** At minimum, publish a CRITICAL event when a handler fails. Consider freezing trading when order-lifecycle handlers fail.

---

### M-2: `OrderManager` uses separate persistence — diverges from deterministic state machine

| Field       | Value |
|-------------|-------|
| Severity    | **MEDIUM** |
| Category    | PERSISTENCE |
| File        | `core/execution/order_manager.py:50-48,102-134` |
| Line        | 50–48, 102–134 |

**Issue:** `OrderManager` maintains its own SQLite persistence (`order_state.db`) separate from `DurableExecutionStore` (`execution_state.db`). Both track overlapping state. `OrderManager._load_orders_from_disk()` runs on startup and loads in-flight orders from its own DB, but `DurableExecutionStore.get_non_terminal_executions()` also runs and loads from its own DB. There is no reconciliation between the two.

**Scenario:** If one store has a different state for the same intent (e.g., one says SUBMITTED, other says PENDING), the system loads conflicting state. Which one wins is undefined.

**Impact:** State recovery is non-deterministic after restart.

**Fix:** Either eliminate `OrderManager` in favor of the deterministic state machine + durable store, or make `OrderManager` the single source of truth and remove the duplicative state in `DurableExecutionStore`.

---

### M-3: Broker gateway singleton can be silently swapped at runtime

| Field       | Value |
|-------------|-------|
| Severity    | **MEDIUM** |
| Category    | SAFE_MODE |
| File        | `core/execution/broker_gateway.py:83-86` |
| Line        | 83–86 |

```python
def switch_broker(self, new_broker_name: str, credentials: dict[str, Any]) -> bool:
    log.info(f"Switching broker from {self._current_broker_name} to {new_broker_name}...")
    return self.connect(new_broker_name, credentials)
```

**Issue:** No safety check before switching broker mid-session. No check for pending orders on the old broker. No state transfer or order migration.

**Scenario:** Admin calls `switch_broker()`. Pending orders on the old broker are orphaned. The new broker has no knowledge of them. The system continues thinking those orders are still being monitored.

**Impact:** Orphan orders on old broker. If they fill, the position is untracked. If they fail, the bot waits indefinitely.

**Fix:** Before switching, verify no pending orders exist on current broker, or at minimum emit CRITICAL warning. Add a mandatory reconciliation cycle after switch.

---

### M-4: `_execute_paper_order` generates random order ID — breaks idempotency cross-restart

| Field       | Value |
|-------------|-------|
| Severity    | **MEDIUM** |
| Category    | IDEMPOTENCY |
| File        | `core/services/execution_service.py:1017-1018` |
| Line        | 1017–1018 |

```python
order_id = f"paper_{int(time.time()*1000)}_{hash(order_request.symbol) % 10000}"
```

**Issue:** Paper order IDs are time-based + symbol hash. If two paper orders have different symbol hashes but same timestamp (possible in fast succession), they could collide. Also, on crash/restart, the same signal replayed would get a different order ID, defeating cross-restart idempotency.

**Scenario:** Two paper orders for different symbols at the same millisecond. The hash modulo 10000 could collide (1 in 10000 chance, but with repeated submissions the birthday paradox applies).

**Impact:** Rare order-id collision leads to state confusion.

**Fix:** Use UUID4 or a deterministic hash of the full order request.

---

### M-5: `EventBus.publish()` writes to event store BEFORE handler dispatch — inconsistency on crash

| Field       | Value |
|-------------|-------|
| Severity    | **MEDIUM** |
| Category    | PERSISTENCE |
| File        | `core/execution/event_system.py:346-361` |
| Line        | 346–361 |

```python
def publish(self, event: TradingEvent) -> bool:
    self._event_store.append(event)  # Written to DB first
    # ... acquire lock, dispatch handlers ...
```

**Issue:** The event is persisted to the event store BEFORE handlers are dispatched. If a handler crashes (e.g., during FILL_RECEIVED processing), the event is recorded in the event store but the handler's side effects never happened. On replay, the event would be replayed and the handler re-executed — but the system might be in a different state, causing duplicate side effects.

**Scenario:** FILL_RECEIVED event stored → handler fails (DB write error for position update) → crash → restart → replay fills again → position updated twice.

**Impact:** Double position count on replay.

**Fix:** Implement exactly-once handler semantics: track which events have been processed. Or store events only AFTER all handlers succeed.

---

### M-6: `ShadowModeEngine` uses `int(time.time())` for signal IDs — collisions likely

| Field       | Value |
|-------------|-------|
| Severity    | **MEDIUM** |
| Category    | IDEMPOTENCY |
| File        | `core/execution/shadow_mode.py:136-137` |
| Line        | 136–137 |

```python
signal_id = f"SHADOW-{strategy_name}-{int(time_provider.get_ts())}"
```

**Issue:** `int(time.time())` has 1-second resolution. Multiple signals from the same strategy within the same second get the same ID.

**Fix:** Append a counter or use UUID.

---

### L-1: `FormalOrderState.can_retry()` says REJECTED is retryable but REJECTED is terminal

| Field       | Value |
|-------------|-------|
| Severity    | **LOW** |
| Category    | STATE_MACHINE |
| File        | `core/execution/execution_state.py:248-249` |
| Line        | 248–249 |

```python
def can_retry(self) -> bool:
    return self.state in [ExecState.FAILED_FINAL, ExecState.REJECTED]
```

But `is_terminal()` (line 82-83) includes REJECTED. REJECTED is both terminal AND retryable — contradictory.

**Fix:** Remove REJECTED from can_retry() or remove from is_terminal().

---

### L-2: `BrokerErrorClassifier` uses substring matching — false positives

| Field       | Value |
|-------------|-------|
| Severity    | **LOW** |
| Category    | RETRY |
| File        | `core/execution/retry_policy/classifier.py:71-104` |
| Line        | 71–104 |

**Issue:** Error classification uses `pattern in error_str` (substring check). Error message "Authentication token invalid" matches "auth" pattern → classified as PERMANENT. But many error messages contain "auth" in context like "/api/v3/auth/session" which would also match. Very broad matching.

**Scenario:** A network timeout message from the broker's auth endpoint contains the string "auth" in the URL path. The error is classified as PERMANENT and not retried, even though it's a network issue.

**Impact:** Reduced reliability; some retryable errors are not retried.

**Fix:** Use word-boundary regex matching: `r'\bauth\b'` not `'auth'`.

---

### L-3: No unique constraint on `execution_state` table's `broker_order_id`

| Field       | Value |
|-------------|-------|
| Severity    | **LOW** |
| Category    | PERSISTENCE |
| File        | `core/execution/durable_state.py:77-94` |
| Line        | 77–94 |

**Issue:** The `execution_state` table has `intent_id TEXT PRIMARY KEY` but no UNIQUE constraint on `broker_order_id`. Two different intent_ids could theoretically map to the same broker_order_id (shouldn't happen in practice, but the schema doesn't enforce it).

**Fix:** Add `UNIQUE(broker_order_id)` constraint.

---

## SUMMARY OF RISK ASSESSMENT

### Will cause real-money loss today:
1. **B-1**: Dual key spaces make state machine idempotency non-functional  
2. **B-2**: Random UUID fallback defeats level-1 idempotency → duplicate orders  
3. **C-1**: Persist-before-mutate persists OLD state → crash leads to re-submission  
4. **C-2**: Circuit breaker bypass → unbounded retries during flapping failure  
5. **C-4**: Lock released before broker call → TOCTOU → potential double submission  
6. **H-7**: Orphan positions detected but no freeze → double exposure  

### Will cause operational failures:
7. **C-3**: Hard halt bypass via direct execute_order() call  
8. **H-3**: No lock ordering → deadlock risk  
9. **H-2**: Freeze state lost on restart → silent un-freeze  
10. **H-4**: Three databases can diverge → reconciliation confusion  
11. **H-5**: Watchdog state-tearing between machine lock release and broker query  

### Urgent fixes (order of priority):
| # | Finding | Risk | Effort |
|---|---------|------|--------|
| 1 | B-1: Align intent_id across both call sites | Duplicate orders | 1 line |
| 2 | B-2: Remove uuid4() fallback | Duplicate orders | 1 line |
| 3 | C-1: Pass new_state to persistence callback | Duplicate on crash | 5 lines |
| 4 | C-4: Keep lock through broker call | TOCTOU | 2 lines |
| 5 | C-3: Add hard-halt check in execute_order | Halt bypass | 3 lines |
| 6 | H-7: Freeze on orphan detection | Double exposure | 10 lines |
| 7 | C-2: Total retry counter | Retry storm | 3 lines |
| 8 | H-3: Add deadlock-safe acquire | System freeze | 15 lines |
