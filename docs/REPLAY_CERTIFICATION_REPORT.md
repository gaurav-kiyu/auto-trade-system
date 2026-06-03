# Replay Certification Report

**Phase:** 7 | **Date:** 2026-06-02 | **Score:** 9.5/10

## Summary
Replay determinism certified. Same input + same config → same output every run.

## Components Certified

| Component | File | Status |
|-----------|------|--------|
| Replay Certifier | `core/certification/replay_certifier.py` | ✅ SHA-256 hash comparison |
| Trade Replayer | `core/trade_replayer.py` | ✅ ASCII bar-chart replay |
| Replay Engine | `core/execution/replay_engine.py` | ✅ Deterministic state machine |
| Replay Tests | `tests/test_certification.py` | ✅ Dual-run hash verification |

## Determinism Guarantees
1. **Seeded randomness**: `random.seed(42)` in replay_trace()
2. **Deterministic execution IDs**: SHA-256 of params + time slot
3. **Write-ahead journal**: Ordered intent log for exact replay
4. **State machine**: VALIDATED → SUBMITTED → ACKNOWLEDGED → FILLED (no branching)

## Verification
- ✅ ReplayCertifier runs replay twice, compares SHA-256 hashes
- ✅ Any non-deterministic trade → certification FAILED
- ✅ CLI: `python -m core.certification.replay_certifier --db trades.db`
