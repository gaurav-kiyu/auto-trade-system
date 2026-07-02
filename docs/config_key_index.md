# Config Key Index — OPB v2.54

**File:** `index_config.defaults.json` (~904 keys)
**Purpose:** Quick-reference index for operational teams. Keys are grouped by functional category for easier discovery.

---

## 1. Risk Management (208 keys)

Capital limits, P&L thresholds, position sizing, trade constraints, mandate enforcement.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `MAX_DAILY_LOSS` | int | -600 | Hard max daily loss before halt |
| `INTRADAY_LOSS_LIMIT` | int | -300 | Intraday loss threshold |
| `MAX_DRAWDOWN` | float | 0.3 | Max drawdown fraction |
| `RISK_MODE` | string | "FIXED" | Risk allocation mode (FIXED/DYNAMIC) |
| `RISK_FIXED_AMOUNT` | int | 150 | Fixed risk per trade (INR) |
| `RISK_PER_TRADE` | float | 0.03 | Fraction of capital per trade |
| `MAX_LOT_CAPITAL_PCT` | float | 0.85 | Max capital deployed per lot |
| `MAX_OPEN` | int | 1 | Max concurrent open positions |
| `MAX_TRADES_DAY` | int | 3 | Max daily trades |
| `PORTFOLIO_MAX_SL_RISK_PCT` | float | 0.75 | Portfolio-level SL cap |
| `MANDATE_*` | various | various | Constitution mandate settings (50+ keys) |
| `CONSEC_LOSS_LIMIT` | int | 3 | Consecutive loss limit |
| `DRAWDOWN_SIZE_SCALE` | bool | true | Scale position size by drawdown |
| `VIX_SIZE_SCALE` | bool | true | Scale position size by VIX |
| `STRICT_OI_VALIDATION` | bool | true | Require OI data for backtest |
| `MAX_EXPOSURE_*_PCT` | float | 30-80 | Per-symbol/expiry/direction/strategy exposure caps |

**Sub-config:** `RECONCILE_*`, `CIRCUIT_BREAKER_*`, `SAFETY_*`, `API_DEGRADE_*`

---

## 2. Trading Parameters (5 keys)

Core trading brain settings.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `BASE_CAPITAL` | int | 5000 | Starting capital |
| `DAILY_TARGET` | int | 400 | Daily P&L target |
| `MIN_NET_RR` | float | 1.5 | Min risk/reward ratio |
| `BROKERAGE_PER_TRADE` | int | 40 | Brokerage cost per trade |
| `TAKE_PROFIT_AND_STOP` | bool | true | Enable TP/SL logic |

---

## 3. Entry/Exit Controls (33 keys)

SL, targets, trailing stops, partial exits, position age limits.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `SL_PCT` | float | 0.88 | Stop-loss as fraction of entry |
| `TARGET_PCT` | float | 1.30 | Profit target fraction |
| `TRAIL_PCT` | float | 0.95 | Trailing stop activation fraction |
| `TRAIL_ACTIVATE` | float | 1.08 | P&L multiplier to activate trailing |
| `PARTIAL_EXIT_MULT` | float | 1.10 | Partial exit trigger multiplier |
| `PARTIAL_EXIT_TRAIL` | float | 1.05 | Partial exit trailing stop |
| `SL_WARN_PCT` | float | 0.95 | SL warning threshold |
| `MIN_TRADE_DURATION_MINS` | int | 40 | Min trade hold time |
| `MAX_POSITION_AGE` | int | 100 | Max trade age (minutes) |
| `BREAKOUT_TIMEOUT` | int | 1800 | Breakout signal age limit (sec) |
| `SIGNAL_MAX_AGE` | int | 90 | Max signal age before discard |
| `DYNAMIC_SL_ATR_MULT` | float | 2.0 | ATR-based SL multiplier |
| `DYNAMIC_TARGET_ATR_MULT` | float | 3.5 | ATR-based target multiplier |
| `SLIPPAGE` | float | 0.002 | Slippage assumption |
| `EXIT_SPREAD_GUARD_MULT` | float | 1.5 | Spread guard exit multiplier |

---

## 4. ML/AI Settings (43 keys)

ML classifier, score system, confidence, adaptive learning.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `AI_THRESHOLD` | int | 68 | Min signal score for entry |
| `HIGH_CONVICTION_ML_THRESHOLD` | float | 0.50 | Min ML prob for conviction mode |
| `STRONG_THRESHOLD` | int | 85 | Score threshold for STRONG tier |
| `MODERATE_THRESHOLD` | int | 72 | Score threshold for MODERATE tier |
| `ml_classifier_enabled` | bool | true | Enable LightGBM classifier |
| `ml_min_trades_to_train` | int | 50 | Min trades before ML training |
| `ml_model_path` | string | "models/signal_classifier.pkl" | ML model file |
| `ml_score_adj_cap` | int | 10 | Max ML score adjustment |
| `ml_high_prob_threshold` | float | 0.65 | High win-prob threshold |
| `ml_low_prob_threshold` | float | 0.45 | Low win-prob threshold |
| `ml_retrain_interval_hours` | float | 24.0 | ML model retrain interval |
| `shap_enabled` | bool | false | SHAP explainability |
| `drift_detector_enabled` | bool | true | Concept drift monitoring |
| `ADAPTIVE_THRESHOLD_ENABLED` | bool | true | Adaptive score thresholds |
| `ADAPTIVE_LEARNING_*` | various | various | Auto-learner settings |
| `AUTO_LEARNER_*` | various | various | Auto-learner config |
| `AUTO_TUNE_*` / `AUTO_TUNER_*` | various | various | Auto-tuner settings |
| `SCORE_*` / `QUALITY_MIN_SCORE` | various | various | Score system config |

---

## 5. Signal & Indicator Settings (nested in `indicator` block)

Technical indicator parameters: RSI, MACD, ADX, Bollinger, EMA, ATR, VWAP, volume, ORB, Fibonacci.

| Key | Default | Description |
|-----|---------|-------------|
| `indicator.rsi_period` | 14 | RSI calculation period |
| `indicator.rsi_overbought` | 75 | RSI overbought threshold |
| `indicator.rsi_oversold` | 25 | RSI oversold threshold |
| `indicator.macd_fast` | 12 | MACD fast EMA |
| `indicator.macd_slow` | 26 | MACD slow EMA |
| `indicator.macd_signal` | 9 | MACD signal line |
| `indicator.adx_period` | 14 | ADX period |
| `indicator.adx_trending_threshold` | 25 | ADX trending threshold |
| `indicator.adx_strong_threshold` | 35 | ADX strong trend threshold |
| `indicator.bb_period` | 20 | Bollinger Bands period |
| `indicator.bb_std_dev` | 2.0 | Bollinger Bands std dev |
| `indicator.ema_short` / `ema_long` | 9/21 | EMA periods |
| `indicator.atr_period` | 14 | ATR period |
| `indicator.volume_ratio_lookback` | 20 | Volume ratio lookback |
| `indicator.vwap_max_pts` | 20 | VWAP alignment max score |
| `indicator.tf_aligned_pts` | 20 | Timeframe alignment score |
| `indicator.soft_penalty_tf_mismatch` | 25 | TF mismatch penalty |
| `indicator.soft_penalty_choppy` | 18 | Choppy regime penalty |
| `indicator.conf_mult_tf_mismatch` | 0.50 | TF mismatch confidence mult |
| `indicator.conf_mult_choppy` | 0.60 | Choppy confidence mult |
| `indicator.orb_*` | various | Opening range breakout params |

---

## 6. Broker Configuration (23 keys)

Adapter selection, credentials, failover.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `EXECUTION_MODE` | string | "SIGNAL_ONLY" | Execution mode |
| `BROKER_NAME` | string | "My Broker" | Broker display name |
| `BROKER_DRIVER` | string | "GENERIC" | Broker driver type |
| `BROKER_BACKEND` | string | "KITE" | Broker backend (KITE/ANGEL) |
| `BROKER_API_ENABLED` | bool | false | Enable broker API |
| `BROKER_CONFIG` | dict | {} | Credentials block |
| `broker_failover_enabled` | bool | true | Enable broker failover |
| `failover_chain` | list | ["kite","angel"] | Failover order |
| `token_refresh_*` | various | various | Token refresh settings |
| `CIRCUIT_BREAKER_BROKER_*` | various | various | Broker circuit breaker |

---

## 7. Data & Market (83 keys)

Yahoo Finance, NSE, OI, PCR, IV, VIX, data source URLs.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `VIX_HALT_THRESHOLD` | float | 30.0 | VIX halt threshold |
| `VIX_BLOCK_THRESHOLD` | float | 40.0 | VIX block new entries |
| `VOL_RATIO_MIN` | float | 1.3 | Min volume ratio for entry |
| `IV_SPIKE_THRESHOLD` | float | 60.0 | IV spike block |
| `VOLATILITY_CONFIRMATION_ENABLED` | bool | true | Require vol confirmation |
| `DATA_PROVIDER_PRIORITY` | list | [...] | Data source priority order |
| `DATA_CROSS_VALIDATE` | bool | true | Cross-validate data sources |
| `oi_snapshot_*` | various | various | OI snapshot config |
| `iv_rank_*` | various | various | IV rank config |
| `fii_dii_enabled` | bool | true | FII/DII flow tracking |
| `gex_*` | various | various | Gamma exposure config |
| `data_source_urls` | dict | {...} | NSE API URLs |
| `market` | dict | {...} | Market timings, timezone |

---

## 8. Notifications (26 keys)

Telegram alerts, bot token, chat ID, heartbeat, signal alerts.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `BOT_TOKEN` | string | "YOUR_..." | Telegram bot token |
| `CHAT_ID` | string | "YOUR_..." | Telegram chat ID |
| `TG_MAX_PER_MIN` | int | 20 | Rate limit (/min) |
| `TG_QUIET_MODE` | bool | true | Suppress non-critical |
| `TG_TRADE_ALERTS_STRICT` | bool | true | Strict trade alerts |
| `TG_SIGNAL_COOLDOWN` | int | 900 | Signal dedup cooldown (sec) |
| `TG_ALERT_*` | various | various | Alert filter thresholds (10+ keys) |
| `TG_PERIODIC_SUMMARY_TELEGRAM` | bool | false | Periodic summary |
| `INCIDENT_ALERTING_ENABLED` | bool | true | Incident alerting service |
| `config_audit_*` | various | various | Config change audit alerts |

---

## 9. Dashboard/UI (31 keys)

Web dashboard, GUI theme, window config.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `REAL_TIME_DASHBOARD_ENABLED` | bool | false | Enable web dashboard |
| `REAL_TIME_DASHBOARD_PORT` | int | 8765 | Dashboard port |
| `web_dashboard_*` | various | various | Web dashboard config |
| `GUI_THEME` | dict | {...} | Color theme (38 colors) |
| `GUI_WINDOW` | dict | {...} | Window geometry, layout |
| `GUI_UX` | dict | {...} | UX behavior settings |
| `SHUTDOWN_ON_UI_CLOSE` | bool | true | Exit when window closes |
| `GUI_REFRESH_MS` | int | 2000 | GUI refresh interval |

---

## 10. Operational (10 keys)

Environment, directories, retention, backup.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `ENVIRONMENT` | string | "dev" | Deployment env |
| `environment_block_on_violation` | bool | true | Block on prod violations |
| `data_dir` | string | "data" | Data directory |
| `models_dir` | string | "models" | ML models directory |
| `reports_dir` | string | "reports" | Reports directory |
| `log_dir` | string | "logs" | Log directory |
| `db_migration_enabled` | bool | true | Auto DB migration |
| `cleanup_scheduler_enabled` | bool | true | Auto cleanup scheduler |
| `cleanup_scheduler_interval_hours` | int | 24 | Cleanup interval |
| `data_retention_*` | various | various | Per-category retention (12 keys) |

---

## 11. System/Performance (42 keys)

Scan loops, timeouts, threads, logging, health checks.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `SCAN_INTERVAL` | int | 60 | Market scan interval (sec) |
| `SUMMARY_INTERVAL` | int | 600 | Summary interval (sec) |
| `COOLDOWN` | int | 300 | Post-trade cooldown (sec) |
| `WATCHDOG_TIMEOUT` | int | 300 | Watchdog timeout (sec) |
| `LATENCY_BUDGET_MS` | int | 2000 | Loop latency budget |
| `LOOP_SLOW_CYCLE_MS` | int | 2000 | Slow cycle warning |
| `LOG_*` | various | various | Log rotation config |
| `RETENTION_*` | various | various | File retention policies |
| `health_check_*` | various | various | Health check thresholds |
| `METRICS_BIND` / `METRICS_PORT` | various | "127.0.0.1"/9090 | Prometheus metrics |
| `system` | dict | {...} | System block: watchdog, heartbeat, WAL, ports |

---

## 12. Strategy Specific (7 keys)

Spread, straddle, strangle, iron condor, scale-in, limit orders.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `spread_strategy_enabled` | bool | false | Debit spread engine |
| `straddle.enabled` | bool | false | Straddle/strangle engine |
| `iron_condor.enabled` | bool | false | Iron condor engine |
| `scalein_enabled` | bool | true | Scale-in manager |
| `limit_order_enabled` | bool | true | Limit order engine |
| `strategies` | dict | {...} | Strategy-specific config blocks |
| `spread_*` | various | various | Spread-specific params |

---

## 13. Security/Auth (12 keys)

Secrets, encryption, SSO, MFA, RBAC.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `webhook_auth_token` | string | "" | Webhook auth token |
| `admin_control_plane_*` | various | various | Admin control plane config |
| `db_encryption_enabled` | bool | false | DB at-rest encryption |
| `db_encryption_key` | string | "" | Encryption key |
| `sso_*` | various | various | SSO/OAuth2 config |
| `SECRET_HYGIENE_ENABLED` | bool | true | Secret scan on startup |

---

## 14. Index Config (21 keys)

Index definitions, NSE timings, expiry rules.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `INDEX_MAP` | dict | {...} | Index name → YF/NSE mapping |
| `INDEX_PRIORITY` | list | [...] | Scan order |
| `EXPIRY_CUTOFF_HOUR` | int | 13 | Expiry day cutoff hour |
| `EXPIRY_CUTOFF_MIN` | int | 30 | Expiry day cutoff minute |
| `EXPIRY_MAX_TRADES` | int | 2 | Max trades on expiry day |
| `NSE_*_HOUR`/`MINUTE` | various | various | NSE session timings (10+ keys) |
| `instruments` | dict | {...} | Per-instrument config (NIFTY, BANKNIFTY, etc.) |

---

## 15. Backtest Settings

| Key | Default | Description |
|-----|---------|-------------|
| `BACKTEST_INITIAL_CAPITAL` | 5000 | Starting capital |
| `BACKTEST_TRADE_SIZE` | 1 | Position size in lots |
| `BACKTEST_FALLBACK_STOP_PCT` | 0.01 | Fallback SL |
| `BACKTEST_FALLBACK_TARGET_PCT` | 0.02 | Fallback TP |
| `BACKTEST_MAX_BARS_IN_TRADE` | 20 | Max bars per trade |
| `REPLAY_*` | various | Replay column mapping |

---

## 16. Other (289 keys)

Keys that don't fit the above categories. Many are utility/feature flags.

| Key | Description |
|-----|-------------|
| `EXECUTION_ROUTER_PAPER_USES_ADAPTER` | Flag for paper router mode |
| `MANUAL_SIGNALS_ONLY` | Manual-only mode flag |
| `ALLOW_ZERO_PRICE` | Allow zero-price edge case |
| `CONFIG_STRICT_SCHEMA_ENFORCEMENT` | Schema validation strict mode |
| `SOVEREIGNTY_BROKER_BLOCK` | Sovereignty broker lockdown |
| `MARGIN_*` | Margin safety/warning thresholds |
| `NSE_HOLIDAYS` | Empty (fetched from NSE API) |
| `NSE_SATURDAY_ALLOWED` | Saturday trading flag |
| `PAPER_TRACK_CAPITAL` | Track capital in paper mode |
| `KILL_FILE` | "STOP_TRADING" | Kill file name |
| `CRASH_RECOVERY_LOG` | Crash recovery log path |
| `STRUCTURED_EVENTS_*` | Structured events JSONL |
| `market_data_*` | Secondary provider, mismatch threshold |
| `db_wal_mode` | (in `system` block) WAL mode for SQLite |

---

## Quick Reference: Nested Config Blocks

| Block | Keys | Purpose |
|-------|------|---------|
| `BROKER_CONFIG` | 7 | Broker API credentials |
| `INDEX_MAP` | 5 indices × 4 fields | Index symbol mapping |
| `EQUITY_MAP` | 5 stocks × 7 fields | Equity symbol mapping |
| `FUTURES_MAP` | 3 × 8 fields | Futures contract mapping |
| `GUI_THEME` | 38 | Color theme for Tkinter GUI |
| `GUI_WINDOW` | 14 | Window geometry/layout |
| `GUI_UX` | 14 | UX behavior settings |
| `indicator` | 73 | Technical indicator parameters |
| `market` | 25 | Market timings, sessions |
| `financial` | 12 | Tax/brokerage/fee rates |
| `instruments` | 7 × 9 fields | Per-instrument settings |
| `data_source_urls` | 12 | External API URLs |
| `strategies` | 4 strategy blocks | Strategy-specific config |
| `system` | 9 | System-level settings |
| `health_check_db_warn_mb` | 4 | Per-DB size warnings |

---

*Generated: July 1, 2026 | OPB v2.54*
