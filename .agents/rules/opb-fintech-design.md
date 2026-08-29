# OPB Fintech & Institutional Trading Design Standards

## Institutional 5-Second Cockpit Standard
The Command Center and Cockpit views must provide instant clarity, answering these 7 core questions within 5 seconds:
1. **How much capital do I have?** (Capital Base KPI with available margin headroom)
2. **Am I making or losing money?** (Day Realized P&L, real-time tick flash, intraday equity trajectory)
3. **Is the trading system healthy?** (Latency dock, core loop status, NSE stock synchronization count)
4. **Is the risk engine safe?** (Daily Loss Circuit Breaker meter, Max Drawdown, Sharpe Ratio)
5. **What is the market regime?** (Trending Bullish, Range-bound Compression, Volatility Surge)
6. **What signals are currently active?** (Scored conviction radar, entry/target bounds, 1-click paper execution)
7. **Are there execution/data problems?** (Pending order queue depth, broker gateway status)

---

## Financial Typography & Tabular Numerals
- All monetary amounts (₹), quantities, percentages, strike prices, timestamps, and ratios **must** use tabular monospaced numbers:
  ```css
  font-family: var(--font-mono);
  font-feature-settings: "tnum" 1, "zero" 1, "cv01" 1;
  font-variant-numeric: tabular-nums;
  ```
- No number jitter or layout shifts during live data ticks.

---

## Market Semantic Palette (Indian Market Standards)
- **Market Buy / CE / Profit**: `--market-buy: #16a34a` (green with subtle background & border variants)
- **Market Sell / PE / Loss**: `--market-sell: #dc2626` (red with subtle background & border variants)
- **Delta Neutral / Spot**: `--market-neutral: #38bdf8`
- **Risk Warning / Near Limits**: `--market-warning: #d97706`
