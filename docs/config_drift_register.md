# Configuration Drift Register

**Authority:** Final Master System Constitution — Mandatory Technical Debt Governance  
**Purpose:** Track configuration drift between environments, config files, and documented defaults  
**Last Updated:** 2026-10-16 (v2.61.4 Technical Debt Remediation)  
**Review Cycle:** Every release  

---

## Active Entries (Confirmed Active Debt)

| ID | Cluster | Verdict | Real live key(s) | Dead/decorative key(s) | Note |
|----|---------|---------|-------------------|--------------------------|------|
| CDR-013 | Data-staleness gates | MANDATE_DATA_STALENESS_SEC flows into MandateConfig but staleness value check not in code. | SIGNAL_MAX_AGE (real) | EXIT_RECON_MAX_AGE_SEC, SAFETY_MAX_STALE_DATA_SEC, MANDATE_DATA_STALENESS_SEC (inert) | Safety-relevant; requires design decision. |
| CDR-014 | Retention policy | Old key set has no live reader; real system is data_retention_*. | data_retention_* | AUDIT_RETENTION_DAYS, RETENTION_* | Safe to deprecate/remove; deferred to avoid unreviewed bulk deletion. |
| CDR-018 | Adaptive-learning bonus/discount | ADAPTIVE_LEARNING_MAX_BONUS/MAX_DISCOUNT have zero readers. | LEARNING_SCORE_ADJ (wired but 0) | ADAPTIVE_LEARNING_* | Feature gap, not duplicate-value bug. |
| CDR-019 | Brokerage cost | MANDATE_COST_BROKERAGE real/live. default_brokerage_per_order has zero readers. | MANDATE_COST_BROKERAGE, BROKERAGE_PER_TRADE | default_brokerage_per_order | Needs confirmation of per-trade/per-order semantic. |
| CDR-020 | Reconciliation intervals | RECONCILIATION_ACTIVE_INTERVAL_SEC real/live. RECONCILE_INTERVAL and RECONCILIATION_INTERVAL_SEC zero live readers. | RECONCILIATION_ACTIVE/IDLE_INTERVAL_SEC | RECONCILE_INTERVAL, RECONCILIATION_INTERVAL_SEC | Safe to deprecate/remove; deferred. |
| CDR-021 | Session-scoring systems | session_classifier_enabled real/live. TIME_OF_DAY_FILTER_ENABLED has zero live callers. | session_classifier_enabled | TIME_OF_DAY_* | TIME_OF_DAY_* needs either real wiring or removal. |
| CDR-022 | Walk-forward bars | Neither walkforward_train_bars nor WALKFORWARD_TRAIN_BARS has live reader. | -- (CLI flags) | both key sets | Low priority; both inert. |
| CDR-023 | ADX thresholds | ADX_PENALTY_THRESHOLD is real/live. indicator.adx_trending_threshold has zero readers. | ADX_PENALTY_THRESHOLD | indicator.adx_trending_threshold, adx_strong_threshold | Low priority; harmless dead pair. |
| CDR-024 | Spread-strategy config | Flat-key-wins precedence implemented correctly; nested copies identical. | spread_strategy_enabled + flat siblings | indicator.spread_* (identical values) | No fix needed; harmless duplicate. |

---

## Resolved Audit Trail (Historical Resolutions Retained with Evidence)

### Batch 2: v2.61.4 Maintenance Remediation (2026-10-16)

- **CD-RES-015** (Original Finding: AUTO_TUNER vs AUTO_TUNE):
  - *Finding*: 6 dead configuration keys (`AUTO_TUNER_COOLDOWN_DAYS`, `AUTO_TUNER_DRY_RUN`, `AUTO_TUNER_ENABLED`, `AUTO_TUNER_MIN_TRADES`, `AUTO_TUNER_MIN_WIN_RATE_POST_TUNE`, `AUTO_TUNER_POST_TUNE_VALIDATION_DAYS`) existed in `json/index_config.defaults.json` and `json/config.template.json`. Live tuner in `core/auto_tuner/tuner.py` exclusively reads `AUTO_TUNE_*`.
  - *Fix Applied*: Removed all 6 dead `AUTO_TUNER_*` keys from defaults and template.
  - *Files*: `json/config.template.json`, `json/index_config.defaults.json`, `schemas/index_config.schema.json`.
  - *Verification*: `generate_config_schemas.py --check` and `validate_config_schema.py --all` passed cleanly.

- **CD-RES-016** (Original Finding: Corp-action / Underlying-analysis flags):
  - *Finding*: Real live flags (`corp_action_calendar_enabled`, `underlying_analyzer_enabled`) default to `false`. Dead flags right next to them (`corp_action_enabled`, `underlying_analysis_enabled`) defaulted to `true`, presenting a major confusion/operational risk.
  - *Fix Applied*: Removed dead flags `corp_action_enabled` and `underlying_analysis_enabled` from defaults and template.
  - *Files*: `json/config.template.json`, `json/index_config.defaults.json`, `schemas/index_config.schema.json`.
  - *Verification*: Schema validation passed; no code path reads the dead flags.

- **CD-RES-017** (Original Finding: Slippage calibration dead keys):
  - *Finding*: `slippage_calibration_enabled`, `slippage_calibration_min_trades`, and `slippage_calibration_days` had zero readers; real live system uses `slippage_model_*` (`core/slippage_model.py`).
  - *Fix Applied*: Removed all 3 dead slippage calibration keys.
  - *Files*: `json/config.template.json`, `json/index_config.defaults.json`, `schemas/index_config.schema.json`.
  - *Verification*: Schema validation passed cleanly.

- **CD-RES-025** (Original Finding: Dashboard/metrics ports):
  - *Finding*: `REAL_TIME_DASHBOARD_PORT` had contradictory values (8000 vs 8765) in defaults vs template and zero code readers.
  - *Fix Applied*: Removed dead key `REAL_TIME_DASHBOARD_PORT`.
  - *Files*: `json/config.template.json`, `json/index_config.defaults.json`, `schemas/index_config.schema.json`.
  - *Verification*: Schema validation passed cleanly.

### Batch 1: v2.59.0 Historical Remediation (2026-08-21)

- **CD-RES-001** (`TIER_STRONG_MIN`/`TIER_MODERATE_MIN`/`TIER_WEAK_MIN`): Added config overrides to `classify_tier` in `core/tier_engine.py`, wired live call sites.
- **CD-RES-002** (`STRONG_THRESHOLD`/`MODERATE_THRESHOLD` vs `TIER_STRONG_MIN`/`TIER_MODERATE_MIN`): Corrected warning text in `core/config_validator.py`.
- **CD-RES-003** (`RSI_OVERBOUGHT`/`RSI_OVERSOLD` flat keys): Documented separate index RSI keys.
- **CD-RES-004** (`NIFTY_LOT_SIZE` hardcoded bypass): Wired `index_map` parameter in `core/services/risk_service.py`.
- **CD-RES-005** (`RECONCILE_HALT_ON_QTY_MISMATCH` hardcoded bypass): Read from `_CFG.get(...)` in `index_app/index_trader.py`.
- **CD-RES-006** (`BROKERAGE_PER_TRADE` hardcoded bypass): Read from `_CFG.get(...)` in `index_app/index_trader.py`.
- **CD-RES-007** (`SIGNAL_TS_MAX_AGE` hardcoded bypass): Read from `_CFG.get(...)` in `index_app/index_trader.py`.
- **CD-RES-008** (`ATR_SL_MULTIPLIER` fallback mismatch): Corrected fallback to 1.5 in `core/pure_index_signal.py`.
- **CD-RES-009** (`FIB_TP2_RATIO`/`FIB_TP3_RATIO` fallback mismatch): Corrected fallbacks to 1.0/1.618 in `core/pure_index_signal.py`.
- **CD-RES-010** (`audit_log_dir` case mismatch): Standardized lowercase audit configuration keys.
- **CD-RES-011** (Max trades/day index options gap): Wired `_check_daily_trade_count` in `core/services/risk_service.py`.
- **CD-RES-012** (Qty-mismatch reconciliation halt): Wired periodic call to `_reconcile_positions_live()` in `index_app/index_trader.py`.

---

*End of Configuration Drift Register — Reconciled for v2.61.4*
