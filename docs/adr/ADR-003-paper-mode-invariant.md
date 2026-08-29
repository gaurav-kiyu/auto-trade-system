# ADR-003: Paper Mode Invariant

## Status
ACCEPTED — July 2026

## Context
The system must support risk-free paper trading for strategy validation. Under no circumstances should paper mode reach a real broker API. This is a safety-critical invariant.

## Decision
When `EXECUTION_MODE=PAPER` or `--paper` CLI flag is set:
1. `PaperBrokerAdapter` (from `core/adapters/broker_adapters.py`) handles all order fills
2. Real broker SDKs (Kite, Angel) are **never instantiated**
3. Fill price = mid-price ± slippage% with OI/volume liquidity filter
4. The broker factory (`index_app/domains/broker/factory.py`) enforces: if `paper_mode=True`, use `PaperBrokerAdapter` regardless of `BROKER_DRIVER` config
5. `ExecutionService` validates `execution_mode_allows_trading()` before any order submission

## Consequences
- **Positive:** Absolute safety guarantee — impossible to accidentally place real orders during paper trading. Clear separation of concerns.
- **Negative:** Paper fill simulation cannot perfectly match real broker behavior. Slippage model is an approximation.
- **Trade-off:** Safety over simulation accuracy. Acceptable because paper mode is for strategy validation, not production simulation.

## Enforcement
- CI pipeline validates `PAPER_MODE` safety in `test_broker_adapters.py`
- `core/auditor/auditor.py` has `_check_paper_mode_safety()` automated check
- `core/constitution_ai_gate.py` blocks AI agents from modifying paper mode logic

## Related
- `core/adapters/broker_adapters.py` (PaperBrokerAdapter)
- `index_app/domains/broker/factory.py` (broker selection)
- `core/services/paper_trader.py` (fill simulation)
