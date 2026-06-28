# Finance Section Report — OPB v2.53.0

**Report Date:** 2026-06-28
**Classification:** Internal — Financial Architecture & Capital Management

---

## 1. Capital Structure

### 1.1 Capital Allocation Model

The platform uses a multi-layered capital allocation system:

```
Total Capital
├── Reserved Capital (risk-service locked)
│   ├── Active Position Margin
│   └── Pending Order Margin
├── Available Capital
│   ├── Intraday Trading Budget
│   └── Buffer (default: 20%)
└── Loss Reserve (daily loss limit)
```

### 1.2 Capital Configuration

| Key | Default | Description |
|-----|---------|-------------|
| `TOTAL_CAPITAL` | 100000 (₹1L) | Total trading capital |
| `MAX_DAILY_LOSS` | 0.05 (5%) | Maximum daily loss as fraction of capital |
| `MAX_DRAWDOWN` | 0.15 (15%) | Maximum drawdown as fraction of capital |
| `CAPITAL_RESERVATION_FACTOR` | 0.8 | Fraction of capital available for trading |
| `MIN_CAPITAL_THRESHOLD` | 50000 (₹50K) | Minimum capital to continue trading |

### 1.3 Capital Reservation Lock

A critical safety mechanism prevents double-spending across concurrent entries:

```python
# core/capital_manager.py
self._reservation_lock = threading.Lock()
```

On each entry, the system reserves capital:
- `reserved_capital += entry_price * lots * lot_size * margin_fraction`
- Released on exit (SL hit or target reached)
- Blocked if `reserved_capital > TOTAL_CAPITAL * CAPITAL_RESERVATION_FACTOR`

---

## 2. Risk-Adjusted Capital Allocation

### 2.1 Position Sizing Methods

| Method | Module | When Active | Description |
|--------|--------|-------------|-------------|
| Fixed Fractional | `core/services/risk_service.py` | Always (baseline) | Risk% × capital per trade |
| Kelly Criterion | `core/kelly_sizer.py` | Config: `use_kelly_sizing=true` | Half-Kelly from historical win/loss |
| VIX-Adjusted | `core/vix_adaptive_threshold.py` | Always | Reduces size when VIX elevated |
| Volatility-Adjusted | `core/risk/sizing/manager.py` | Always | Scales by ATR/volatility |
| Warmup Scaling | `core/market_warmup.py` | First N minutes | `warmup_size_mult` multiplier |
| Intraday Adaptive | `core/intraday_performance_monitor.py` | Config-driven | Adjusts on session win rate |
| Event Calendar | `core/event_calendar.py` | Budget/RBI/FOMC days | `size_mult` per event type |

### 2.2 Position Sizing Formula

```
Base Size = floor(CAPITAL * RISK_PER_TRADE / (ENTRY_PRICE * SL_PCT * LOT_SIZE))

Adjustments applied in order:
1. VIX multiplier (VIX > threshold → reduce)
2. Kelly fraction (if enabled)
3. Regime multiplier (BULL/BEAR/NEUTRAL/CRISIS)
4. Warmup multiplier (first N minutes)
5. Event calendar multiplier (event days)
6. Intraday performance adjustment
7. Correlation guard (cross-index position reduction)
```

### 2.3 Capital Scaling Scenarios

| Capital Range | Mode | Certification Status |
|---------------|------|---------------------|
| ₹10K–₹1L | Paper / Small Capital | ✅ APPROVED |
| ₹1L–₹10L | Small Capital Live | ✅ CONDITIONAL |
| ₹10L–₹50L | Medium Capital Live | ⚠️ NOT YET CERTIFIED |
| ₹50L+ | Full Autonomous | ❌ NOT YET CERTIFIED |

---

## 3. Risk Limits

### 3.1 Hard Limits (Cannot Be Bypassed)

| Limit | Config Key | Default | Enforcement |
|-------|-----------|---------|-------------|
| Max Daily Loss | `MAX_DAILY_LOSS` | 5% | `_trip_hard_halt()` — blocks all entries |
| Max Drawdown | `MAX_DRAWDOWN` | 15% | `_trip_hard_halt()` — blocks all entries |
| Max Exposure | `MAX_EXPOSURE` | 3× capital | RiskService position validation |
| Max Positions | `MAX_POSITIONS` | 10 | Portfolio-level cap |
| Per-Index Max | `MAX_POSITIONS_PER_INDEX` | 5 | Per-index cap |
| Portfolio SL Risk | `PORTFOLIO_MAX_SL_RISK_PCT` | 2% | Aggregate SL exposure |

### 3.2 Soft Limits (Configurable, Adjustable)

| Limit | Config Key | Default | Notes |
|-------|-----------|---------|-------|
| Max Position Size | `max_position_size` | 100 lots | Absolute cap per position |
| Min Position Size | `min_position_size` | 1 lot | Minimum trade size |
| Event Day Multiplier | `event_calendar[].size_mult` | 0.5 | Event-based reduction |
| Correlation Guard | `CORRELATION_THRESHOLD` | 0.85 | Blocks same-direction entries |

---

## 4. P&L Tracking

### 4.1 Realized P&L

Tracked per-trade in `trades.db`:
- Entry price, exit price
- Quantity, direction
- Entry time, exit time
- Exit reason (SL/TARGET/TRAIL/MANUAL/EXPIRY)
- Slippage
- Broker fees (STT, exchange, SEBI, GST)

### 4.2 Unrealized P&L

Mark-to-market tracked in `trader_state.json`:
- Current position MTM
- Day P&L
- Total P&L
- Max drawdown (peak-to-trough)

### 4.3 Performance Metrics

| Metric | Source | Description |
|--------|--------|-------------|
| Win Rate | `core/performance_metrics.py` | Fraction of profitable trades |
| Sharpe Ratio | `core/performance_metrics.py` | Risk-adjusted return |
| Sortino Ratio | `core/performance_metrics.py` | Downside risk-adjusted return |
| Calmar Ratio | `core/performance_metrics.py` | Return / max drawdown |
| Profit Factor | `core/performance_metrics.py` | Gross profit / gross loss |
| Avg Win / Avg Loss | `core/performance_metrics.py` | Win-loss ratio |
| Maximum Drawdown | `core/performance_metrics.py` | Peak-to-trough decline |
| Monte Carlo Simulation | `core/monte_carlo.py` | Trade shuffle simulation |
| P&L Attribution | `core/pnl_attribution.py` | By direction/regime/session/day |

---

## 5. Fee Structure

### 5.1 Brokerage & Transaction Costs

| Charge | Rate | Applied By |
|--------|------|------------|
| Brokerage | ₹20/executed order (Zerodha) or 0.1% (Angel) | Broker adapter |
| STT | 0.05% (options sell) | `core/stt_cost_model.py` |
| Exchange Transaction Charge | ₹3500/crore (options) | Exchange |
| SEBI Turnover Fees | ₹10/crore | SEBI |
| GST | 18% on brokerage + TC | Tax |
| Stamp Duty | 0.003% (options) | State Gov |

### 5.2 Slippage Model

Auto-calibrated via `core/slippage_model.py`:
- Linear regression on trade journal data
- Separate model per index (NIFTY/BANKNIFTY/FINNIFTY)
- Factors: order size, spread, volume, time of day
- Paper mode uses mid-price ± slippage% with OI/volume liquidity filter

---

## 6. Drawdown & Recovery Analysis

### 6.1 Drawdown Limits

| Level | Threshold | Action |
|-------|-----------|--------|
| Warning | 70% of MAX_DRAWDOWN | Telegram alert, reduced position size |
| Critical | 90% of MAX_DRAWDOWN | Stop new entries, monitor existing |
| Hard Halt | 100% of MAX_DRAWDOWN | Kill switch, all positions closed |

### 6.2 Recovery Strategy

After drawdown:
1. Scale position size proportionally to remaining capital
2. Increase minimum signal score threshold
3. Enable conservative regime detection
4. Resume trading only after 1 session of positive P&L

---

## 7. Financial Governance

### 7.1 Audit Trail

All financial transactions recorded in:
- `trades.db` — Trade log (SQLite, WAL mode)
- `trade_journal.db` — Execution quality (slippage, delay)
- `trader_state.json` — Capital, PnL, flags (survives restarts)
- `core/wal/journal.py` — Write-Ahead Intent Journal (exactly-once guarantee)

### 7.2 Reconciliation

`core/execution/broker_truth_reconciliation.py`:
- Compares local state vs broker state
- Detects orphan fills, missing fills, quantity mismatches
- Resolves via oldest-timestamp reconciliation

---

## 8. Tax Reporting

### 8.1 Capital Gains Tracking

Per-trade tracking enables:
- Short-term capital gains (held < 12 months)
- Long-term capital gains (held ≥ 12 months) — applicable for equity delivery
- F&O settlements — business income treatment

### 8.2 Required Reports

| Report | Frequency | Generated By |
|--------|-----------|-------------|
| Trade Statement | Daily | `core/report_generator.py` |
| P&L Summary | Daily | `core/report_generator.py` |
| Tax Lot Report | End of Year | Manual export from trades.db |
| Contract Notes | Per Trade | Broker-provided |

---

## 9. Capital Adequacy

### 9.1 VaR Analysis

`core/var_calculator.py` — Parametric VaR:
- **95% confidence**: Daily loss ≤ 2.5% of capital
- **99% confidence**: Daily loss ≤ 5.0% of capital
- Uses historical return distribution with mean and standard deviation

### 9.2 Stress Test Scenarios

`core/stress_tester.py` — 4 standard scenarios:
1. **FLASH_CRASH**: -8% index move, 3× VIX, 10-min timeframe
2. **SLOW_GRIND**: -0.5% per day for 20 days
3. **GAP_UP**: +3% open gap
4. **EXPIRY_CRUSH**: -15% option value on expiry

---

## 10. Financial KPIs

| KPI | Current | Target | Source |
|-----|---------|--------|--------|
| Sharpe Ratio | N/A (no live data) | >1.5 | `core/performance_metrics.py` |
| Win Rate | N/A (no live data) | >55% | `core/performance_metrics.py` |
| Profit Factor | N/A (no live data) | >1.5 | `core/performance_metrics.py` |
| Max Drawdown | N/A (no live data) | <15% | `trader_state.json` |
| Daily Loss Limit | 5% | ≤5% | `MAX_DAILY_LOSS` |
| Capital Utilization | N/A (no live data) | <80% | RiskService |
| Fill Rate | N/A (no live data) | >90% | `trade_journal.db` |

**Note:** KPIs marked "N/A (no live data)" require paper trading runtime to populate `trades.db`. Run `python index_app/index_trader.py --paper` to accumulate trade history.

---

*Generated by Codebuff AI — June 28, 2026*
*Based on actual code analysis of capital management, risk service, and financial governance modules.*
