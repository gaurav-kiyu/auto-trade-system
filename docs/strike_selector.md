# `core/strike_selector.py` — Greeks-Aware Strike Selector (Phase 4)

## What it does

Selects the option strike to trade based on signal tier, VIX, and days-to-
expiry (DTE), using config-driven mode. Works entirely offline — no live
broker Greeks feed is required, it uses the same delta approximations as
`core/option_premium_model.py`.

## Wiring status (important)

This module is fully implemented but **opt-in and off by default**
(`strike_selector_enabled: false`). When disabled (the default), live
entries use the raw underlying index price as the "strike" — legacy
behavior, unchanged. When enabled, `core/position_service.py::enter_trade()`
calls `select_strike()`/`dte_entry_check()` to compute a real strike and
store it as `pos["strike"]`. SL/target/trail exit logic still operates on
underlying % move either way — there is no live/paper option-premium feed
to drive premium-based exits yet (`core/option_premium_model.py` is
backtest-only).

## Modes (`strike_selection_mode`)

| Mode | Behavior |
|---|---|
| `ATM` (default) | Always ATM — zero change vs. legacy behavior |
| `OTM` | Tier-driven OTM step offset (STRONG tier = 1 step OTM, others = 0) |
| `DELTA` | Selects the strike whose approximated delta is closest to `strike_target_delta` |

Offset direction: for a CALL, a higher strike is OTM (`selected = ATM + N × step`);
for a PUT, a lower strike is OTM (`selected = ATM - N × step`).

## Key config keys (all optional, safe defaults)

`strike_selection_mode` (`"ATM"`), `otm_step_offset` (0),
`otm_step_offset_strong` (1), `otm_step_offset_moderate` (0),
`otm_step_offset_weak` (0), `strike_target_delta`, `strike_selector_enabled`
(`false`). See `json/index_config.defaults.json` for the authoritative
current values.

## Public API

`select_strike()`, `dte_entry_check()` — see the module's own docstring for
exact signatures.

## Tests

`tests/test_strike_selector.py`.
