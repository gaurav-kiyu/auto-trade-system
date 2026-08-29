# `core/adaptive_signal.py` — Adaptive Signal Evaluator

## What it does

Soft-rejection wrapper around `evaluate_index_signal_partial()` (in
`core/pure_index_signal.py`). Instead of returning `None` on certain
borderline conditions, it converts them to a score penalty and a confidence
reduction — so the tiered position-sizing system can still trade a partial
setup at reduced size rather than skip it entirely.

## Hard blocks vs soft-converted blocks

Genuine data gaps still hard-reject (return `None`):
`1m_short`, `5m_short`, `15m_short`, `partial_drop`, `bad_price`, `iv_spike`.

Borderline conditions are soft-converted (traded with a penalty) instead of
rejected outright:

| Condition | Score penalty | Confidence multiplier |
|---|---|---|
| `tf_mismatch` (timeframe disagreement) | -20 | × 0.60 |
| `choppy` (choppy regime) | -15 | × 0.70 |

## Output

Returns an `AdaptiveSignal` (see the dataclass in this module), which:
- Drives position sizing via `core/position_sizer.py::PositionSizer`.
- Carries the tier (`STRONG`/`MODERATE`/`WEAK`/`IGNORE`) and its associated
  `TierRules` (risk/execution parameters) from `core/tier_engine.py`.
- The tier boundaries (`TIER_STRONG_MIN`/`TIER_MODERATE_MIN`/`TIER_WEAK_MIN`)
  are config-driven as of 2026-08-21 — see
  `.claude/skills/trading-bot-governance/references/lessons-learned.md` for
  the history (they were hardcoded module constants for a long time).

## Related score adjusters (applied inside this pipeline)

Session classifier, ML classifier win-probability, FII/DII flow, implied
move, GEX regime, regime transition, mean reversion, MA crossover — all
implemented in `core/adaptive_signal_score_adjusters.py` and applied in
sequence before final tier classification. See CLAUDE.md's "Key Core
Modules" table for the full list of Enhancement Phase modules this pipeline
integrates.

## Public API

`evaluate_adaptive_signal()`, `compute_confidence_band()`,
`compute_timeframe_agreement()` — see the module's own docstrings for exact
signatures; `__all__` lists the full public surface.

## Tests

`tests/test_adaptive_signal.py`.
