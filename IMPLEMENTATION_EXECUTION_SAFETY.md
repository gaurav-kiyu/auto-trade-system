# Implementation Plan: Execution Safety (Idempotency & State Machine)

Date: 2026-05-13

Goal: Harden order execution so that orders are idempotent, resumable after crashes, and follow a minimal state machine to avoid duplicate fills or missed reconciliation.

Scope:
- `core/services/execution_service.py` (primary)
- `core/execution/idempotency/manager.py` (support)
- `core/execution/order_submission/manager.py` (support)
- `infrastructure/adapters/brokers/*` (broker ports; paper adapter already present)
- tests: `tests/unit/services/test_execution_service.py`

Design highlights:

1) Idempotency
- Each execution request must carry an `idempotency_key` (client-supplied or generated deterministically).
- `IdempotencyManager` provides in-memory LRU cache + expiry and optional persistent backend (file/SQLite).
- On submit: check `IdempotencyManager.is_duplicate(key)` → if duplicate, return cached `OrderResult`.
- After final fill (FILLED/PARTIALLY_FILLED) or terminal REJECTED, store the `OrderResult` in idempotency cache.

2) Execution State Machine (per-order)
States: CREATED -> SUBMITTED -> PENDING -> PARTIALLY_FILLED -> FILLED | REJECTED | CANCELLED
- Transitions are driven by broker responses + reconciliation.
- ExecutionService keeps a small audit trail (in-memory + persistence) with state updates and timestamps.
- On startup, ExecutionService reconciles any non-terminal orders (SUBMITTED/PENDING) by querying broker or persistence and marks them terminal if needed.

3) Retry and Backoff
- `RetryPolicy` encapsulates retry counts and exponential backoff.
- Only retry on transient errors (connection errors, rate limits) or statuses like PARTIALLY_FILLED where follow-up is necessary.
- Do not retry if broker returned REJECTED with explicit reason.

4) Persistence & Reconciliation
- Persist audit trail entries for terminal orders to `trades.db` via `trade_persistence.save_trade` (already present).
- Persist idempotency keys optionally to a small SQLite table for crash-resume safety (opt-in via config).
- On startup, rebuild in-memory idempotency cache from persisted entries (last N hours/days based on config).

5) Threading & Locks
- ExecutionService uses a single `_lock` to protect internal structures: `_idempotency_cache`, `_executions`, counters.
- IdempotencyManager is thread-safe with its own lock.

6) Observability
- Log when idempotency prevents duplicate submission.
- Add metrics: `execution_attempts`, `execution_duplicates`, `execution_retries`, `execution_failures`.

Minimal Implementation Tasks (this sprint):
1. Fix `IdempotencyManager` to import `Any` and ensure robust get/store semantics. (done)
2. Add optional file-backed idempotency persistence (small SQLite table) behind a config flag. (opt-in)
3. Ensure `ExecutionService.execute_order()` uses `IdempotencyManager` APIs exclusively (instead of local cache duplication). Convert existing `_idempotency_cache` to delegate where appropriate.
4. Add reconciliation on startup: scan non-terminal persistence rows and query broker for status; update idempotency/persistence accordingly.
5. Add/adjust unit tests in `tests/unit/services/test_execution_service.py` to validate idempotency behaviour and retry logic.

Safety gates before merging to `main`:
- All unit tests pass
- Manual dry-run: run a small script exercising duplicate submissions
- Add log entry and alert on first 1% duplicate rate

Next steps (I will perform now):
- Create a small design doc file (this file) (done)
- Make minimal code fixes needed to ensure idempotency manager imports `Any` (if missing)
- Replace ExecutionService local idempotency dict usage with calls to `IdempotencyManager` where straightforward
- Run unit tests (or run subset) and report failures

If you approve, I will proceed to update `IdempotencyManager` (import fixes) and refactor `ExecutionService` to use it, then run the tests.
