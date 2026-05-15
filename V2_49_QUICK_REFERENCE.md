# OPB v2.49 Quick Reference Guide

## Before Every Trade - MUST CALL

```python
from index_app.index_trader import check_mandate_trade_allowed, validate_signal_pillars

# 1. Mandate Check (hard stops, windows, scores)
allowed, reason = check_mandate_trade_allowed(
    regime='TRENDING',  # TRENDING/SIDEWAYS/RANGE
    score=75,          # Min: 68/73/78 by regime
    iv_rank=25.0       # Min 20%
)
if not allowed:
    print(f'BLOCKED: {reason}')
    return

# 2. Signal Pillar Validation (independence)
pillar_ok, pillar_reason = validate_signal_pillars(
    rsi=60, macd='BULLISH', adx=25,
    iv_rank=30, oi_change=5, pcr=0.9,
    fii_net=1000000, dii_net=500000
)
if not pillar_ok:
    print(f'BLOCKED: {pillar_reason}')
    return

# 3. Position Sizing (risk-based, not fixed)
from core.mandate_enforcer import get_mandate_enforcer
me = get_mandate_enforcer()
lots = me.get_position_size(entry_price=150, regime='TRENDING', sl_pct=0.12)
print(f'Position size: {lots} lots')

# 4. Cost-Adjusted PnL
from core.cost_accountant import get_cost_accountant
ca = get_cost_accountant()
result = ca.calculate_net_pnl(entry_premium=150, exit_premium=170, qty=lots)
print(f'Gross PnL: {result[\"gross_pnl\"]}, Net PnL: {result[\"net_pnl\"]}')
```

## Risk Rules (Non-Negotiable)

| Rule | Value | Action |
|------|-------|--------|
| Per-trade risk | 1.5% | Auto-exit at stop |
| Daily hard stop | 2.5% | No more trades |
| Weekly circuit | 5% | 0.75× sizing |
| Max drawdown | 12% | Paper mode |
| Loss streak | 3 losses | 2hr cooldown |
| VIX hard block | >30 | Zero entries |
| Data staleness | >30s | No new entries |

## Score Thresholds

| Regime | Min Score |
|--------|-----------|
| TRENDING | 68 |
| SIDEWAYS | 73 |
| RANGE | 78 |

## Signal Pillars

- **PILLAR 1**: Price/Momentum (RSI+MACD+ADX = 1 pillar, NOT 3)
- **PILLAR 2**: Options Market (IV+OI+PCR)
- **PILLAR 3**: Institutional Flow (FII+DII+GEX)

**REQUIREMENT**: At least 2 pillars must agree

## Trading Windows (IST)

- Morning: 9:20 - 11:30
- Afternoon: 13:00 - 14:45
- Skip first 20 min, last 45 min

## Cost Breakdown (Per Trade)

| Cost | Amount |
|------|--------|
| Brokerage | ₹20 |
| GST (18%) | ₹3.60 |
| STT (sell) | 0.05% |
| Stamp Duty | 0.02% |
| Bid-Ask | ~₹3/lot |

Total ~₹140/trade (~2.8% of ₹5k capital)

## Observability

```python
from index_app.index_trader import get_mandate_status

status = get_mandate_status()
print(status)
# {'capital': 5000, 'equity_peak': 5000, 'drawdown_pct': 0.0, 
#  'daily_pnl': 0, 'loss_streak': 0, 'vix': 20.0, 'hard_halted': False, 
#  'trades_today': 0}
```

## Run Paper Mode

```bash
python -m index_app.index_trader --paper
```

Or use `run_low_capital.bat` for Rs.5,000 testing.

## Version History

- v2.47: Base version with mandate config
- v2.48: Mandate presentation (not wired)
- v2.49: Production hardened - all fixes applied

v2.49 is the first version with ACTUAL mandate enforcement.