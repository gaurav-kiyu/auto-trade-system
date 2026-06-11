# Strike Selector

**Module:** `core/strike_selector.py`

Selects the optimal option strike for a new trade based on signal tier, VIX,
days-to-expiry (DTE), and config-driven mode. Works offline — no broker greeks
feed required.

## Strike Selection Modes

| Mode | Description | Best For |
|------|-------------|----------|
| `ATM` (default) | Always selects ATM strike | Zero change vs. current behaviour |
| `OTM` | Tier-driven OTM step offset | Aggressive directional plays |
| `DELTA` | Strike whose approximated delta is closest to target | Precise delta exposure targeting |

## OTM Step Offsets by Tier

| Tier | Steps OTM | Rationale |
|------|-----------|-----------|
| STRONG | 1 | Higher conviction → more leverage |
| MODERATE | 0 | Balanced risk/reward |
| WEAK | 0 | Stay ATM for safety |

## Strike Direction

- **CALL**: higher strike is OTM → `selected = ATM + N × step`
- **PUT**: lower strike is OTM → `selected = ATM - N × step`

## Safety Features

| Feature | Behaviour |
|---------|-----------|
| Max OTM steps | Capped at config value (default: 3) |
| Vega cap | Reduces OTM by 1 when VIX exceeds threshold (default: 30) |
| Min DTE gate | Blocks entry when DTE < min_dte_for_entry (default: 1) |
| Theta bleed warning | Logs warning when DTE ≤ warn threshold (default: 2) |

## Config Keys

See `index_config.defaults.json` for `strike_selection_*`, `otm_step_offset_*`,
`strike_target_delta`, `delta_per_step`, `max_otm_steps`, `min_dte_for_entry`,
`theta_bleed_warn_dte`, `vega_cap_vix_threshold`.

## Dependencies

- `core/option_premium_model.py` — ATM delta approximation for DELTA mode
