# Quick Start: Equity Trading (Cash Market)

The OPB system supports trading NSE cash market equities alongside index options.
This guide covers how to enable and configure equity trading.

## Prerequisites

- OPB v2.54+ with `--equity` CLI flag support
- `EQUITY_MAP` entries in `config.json` (see `index_config.defaults.json` for examples)
- A price source (yfinance provides NSE equity data via `.NS` suffix)

## Step 1: Configure EQUITY_MAP

Add equity symbols to your `config.json`:

```json
{
  "EQUITY_MAP": {
    "RELIANCE": {
      "yf": "RELIANCE.NS",
      "nse": "RELIANCE",
      "sector": "ENERGY",
      "category": "LARGE_CAP",
      "lot": 1,
      "step": 0,
      "enabled": true
    },
    "TCS": {
      "yf": "TCS.NS",
      "nse": "TCS",
      "sector": "TECHNOLOGY",
      "category": "LARGE_CAP",
      "lot": 1,
      "step": 0,
      "enabled": true
    }
  }
}
```

Each entry requires:
- `yf`: Yahoo Finance symbol (use `.NS` suffix for NSE stocks)
- `nse`: NSE symbol name
- `sector` / `category`: Classification for risk aggregation
- `lot`: Minimum lot size (1 for cash equities)
- `enabled`: Set to `false` to skip without removing

## Step 2: Set EQUITY_PRIORITY (scan order)

Controls the order in which equities are scanned for signals:

```json
{
  "EQUITY_PRIORITY": [
    "RELIANCE",
    "TCS",
    "HDFCBANK",
    "ICICIBANK",
    "INFY"
  ]
}
```

Only symbols that exist in both `EQUITY_PRIORITY` and `EQUITY_MAP` (with `enabled: true`) will be tracked.

## Step 3: Configure Equity Risk Parameters

| Config Key | Default | Description |
|------------|---------|-------------|
| `EQUITY_SL_PCT` | 0.95 | Stop-loss threshold (95% of entry price) |
| `EQUITY_TARGET_PCT` | 1.05 | Profit target (105% of entry price) |
| `EQUITY_MAX_DAILY_TRADES` | 5 | Max equity trades per day |
| `EQUITY_DEFAULT_QTY` | 1 | Default quantity per equity entry |

## Step 4: Launch with Equity Trading

### Using the Launcher (recommended)

1. Open the launcher (`launcher.py` or `OPBuying_INDEX_Launcher.exe`)
2. Select your desired mode (PAPER or MANUAL)
3. **Check the "Enable Equity Trading" checkbox**
4. Click **Launch App**

The launcher will pass `--equity` to the app automatically.

### Using CLI directly

```bash
# Enable equity trading in paper mode
python index_app/index_trader.py --paper --equity

# Enable equity trading in manual mode
python index_app/index_trader.py --equity
```

## What Happens at Startup

When `--equity` is passed:

1. `index_trader.py` initializes the `EquityTrader` in `setup_di_container()`
2. It reads `EQUITY_MAP` and `EQUITY_PRIORITY` from config
3. A background monitoring loop starts for equity positions
4. Equity SL/Target conditions are checked on each scan cycle
5. Equity positions are tracked separately from index options positions

Without `--equity`, the equity trader is not started (no background thread, zero overhead).

## Risk Isolation

Equity trading follows the same risk infrastructure as index options:
- No shared reentry trackers (separate cooldown/score gates)
- No shared position tracking
- Separate `max_daily_trades` counter
- Uses the same `yfinance` data source for price discovery

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| `Equity trader not started` in log | `--equity` flag not passed | Add `--equity` to CLI args or check launcher checkbox |
| No symbols in equity trader | Empty `EQUITY_MAP` or `EQUITY_PRIORITY` | Check config.json for valid entries |
| Price fetch returns None | Symbol not in yfinance | Verify `yf` symbol uses `.NS` suffix for NSE stocks |
| Entry always blocked | Market closed or max daily trades reached | Check market hours (09:15-15:30 IST) |
