# OPB Index Options Buying Bot — Complete Manual

**Version:** v2.59.0 (see `/VERSION`) | **Last verified against code:** 2026-08-21

> This replaces a previous version of this file that described a fabricated
> "v6.0-LOCKED-PROD" architecture (a 16-factor scoring model with invented
> weights, none of which exist in the real code). Everything below is
> written from the actual source — screens from the real route/template
> files, config from the real defaults file, strategy logic from the real
> signal-evaluation code — not from marketing copy. Where a widely-repeated
> claim turned out not to match the code, that's called out explicitly
> rather than repeated.

## Contents

1. [What this system actually is](#1-what-this-system-actually-is)
2. [Safety model — read this before anything else](#2-safety-model--read-this-before-anything-else)
3. [Getting started](#3-getting-started)
4. [The trading logic — how a signal actually becomes a trade](#4-the-trading-logic--how-a-signal-actually-becomes-a-trade)
5. [The "16 strategies" claim — verified reality](#5-the-16-strategies-claim--verified-reality)
6. [Every dashboard screen](#6-every-dashboard-screen)
7. [Configuration reference](#7-configuration-reference)
8. [Known issues and gaps (as of this manual)](#8-known-issues-and-gaps-as-of-this-manual)
9. [Broker integrations](#9-broker-integrations)

---

## 1. What this system actually is

An automated trading system for NSE index options (NIFTY / BANKNIFTY /
FINNIFTY, plus MIDCPNIFTY/SENSEX support) built around one deterministic
technical-scoring engine (`core/pure_index_signal.py` → `core/adaptive_signal.py`),
with an enterprise web dashboard (`core/enterprise_dashboard/`, FastAPI +
Jinja2), paper and live execution modes, and a separate signal-only stock
scanner covering the broader NSE universe. It also has partially-built
support for ETFs, REITs, InvITs, commodities, currencies, and index
futures — all disabled by default. Real, code-level broker adapters now
exist for eight brokers (Zerodha Kite, Angel One, m.Stock, IIFL Markets,
Groww, Upstox, Dhan, ICICI Direct) — see [§9](#9-broker-integrations) for
exactly what's verified vs. an honest gap per broker. None have been
validated against a live/sandbox account, and the master lockout (§2)
blocks all of them from placing a real order regardless.

## 2. Safety model — read this before anything else

Two independent layers stand between this system and placing a real order,
both enforced in `core/adapters/broker_adapters.py::create_broker_adapter()`
— the single function every broker-construction path in the app goes
through, regardless of asset class:

1. **`live_trading_lockout_enabled`** (default `true`). While on, any real
   broker driver is forced back to paper, full stop, no matter what any
   other config flag says. This is the master switch — flip it to `false`
   only when you've decided you're ready to risk real capital.
2. **Automatic readiness gate.** Even with the lockout off, a real driver
   is only honored if `core.live_readiness_checker.check_live_readiness()`
   says your paper-trading track record actually passes 5 blocking
   criteria (min 50 trades, ≥55% win rate, ≥1.5 profit factor, ≤15% max
   drawdown, ≥20 distinct trading days over a 60-day window). It fails
   closed — if the check itself errors for any reason, you stay in paper
   mode.

Until you've been running in paper/signal-only mode for a meaningful
period and are comfortable with the results, leave the lockout on. There
is no way to place a real order while it's on, regardless of what else is
misconfigured.

Other real, always-on safety systems: hard-halt on loss breach, a
file-based kill switch (drop `STOP_TRADING` in the project root), a
watchdog thread, capital reservation locking, and LTP outlier rejection.
See `CLAUDE.md`'s "Safety Systems (Never Disable)" section for the current
list.

## 3. Getting started

```bash
# Paper mode (safe — the lockout above blocks real orders anyway)
python index_app/index_trader.py --paper

# Launcher GUI
./OPBuying_INDEX_Launcher.exe

# Enterprise dashboard (opt-in — set web_dashboard_enabled: true in json/config.json)
# then browse to http://localhost:8765/
```

Full setup steps (installing dependencies, first-run config, Docker/K8s
deployment) are in `SYSTEM_SETUP_GUIDE.md` and `docs/HOW_TO_USE_SYSTEM.md` —
this manual doesn't repeat them, to avoid the exact kind of doc drift this
cleanup was fixing.

## 4. The trading logic — how a signal actually becomes a trade

This is the real, verified call chain for the core index-options bot (not
the stock scanner — see [§5](#5-the-16-strategies-claim--verified-reality)
for that):

```
TradingLoopService.run()  (index_app/domains/trading/service.py)
  → SignalEvaluator.evaluate()  (index_app/domains/signal/evaluator.py)
    → evaluate_adaptive_signal()  (core/adaptive_signal.py)
      → evaluate_dual_direction_signal() / compute_index_score()  (core/pure_index_signal.py)
        — hard gates: 1m/5m/15m data-length, frame alignment, bad price, IV spike
        — base score: RSI + MACD + ADX + VWAP + volume + PCR + smart-money,
          weighted and summed to 0–100 (core/pure_index_signal.py::compute_index_score)
        — bonus/penalty layers: breakout, ADX trend/chop, VWAP reclaim,
          regime penalty, opening-range breakout
      → sequential score adjusters (core/adaptive_signal_score_adjusters.py):
          IV rank (always on) → session time-of-day (always on) →
          ML classifier win-probability (always on, LightGBM) →
          IV skew / FII-DII / implied-move / GEX / regime-transition /
          MA-crossover / mean-reversion (all off by default — enable via
          config if you want them; see §7)
      → tier classification (STRONG/MODERATE/WEAK/IGNORE) → position sizing
  → mandate check → reentry cooldown → correlation guard (blocks
    same-direction entries across highly-correlated indices)
  → PositionService.enter_trade()  (core/position_service.py)
    — hard-halt / kill-file → intraday P&L halt → news-sentinel risk gate
      → warm-up gate → expiry-day gate → auction-session gate
      → RiskService.evaluate_trade() → signal staleness check
      → (opt-in, off by default) strike selector → (opt-in, effectively
        inert until a live option-quote feed exists) liquidity guard
      → order submitted under lock
```

**Important limitation, verified in code:** exits (stop-loss, target,
trailing stop) are computed from the **underlying index's** percentage
move, not the option's actual premium — there is no live option-premium
feed wired into the live/paper monitoring path (`core/option_premium_model.py`
is backtest-only). This means a real option position's theta decay and IV
changes aren't reflected in when it exits. This is the single largest gap
between "what the bot optimizes for" and "what actually happens to your
money" and should be understood before trusting real capital to it.

## 5. The "16 strategies" claim — verified reality

`CHANGELOG.md` describes a "16 Quant Strategies Quantitative Diagnostic
Engine" powering `core/all_nse_scanner.py`, a separate feature that scans
the full NSE stock universe (not just the 3 index options) and sends
Telegram/Gmail alerts. This claim was checked directly against the code.

**Bottom line: the claim is materially inflated.** The scanner does not
run 16 independent strategies — it calls the exact same signal-scoring
engine described in §4 (`SignalEvaluator.evaluate()` →
`evaluate_adaptive_signal()`), just against stock symbols instead of
indices. Of the 16 named strategies:

| # | Named strategy | Verified status |
|---|---|---|
| 1 | Multi-Timeframe Trend Following | Partially real — one scoring component (EMA alignment across 5m/15m), not a standalone strategy |
| 2 | Options Greeks Tail Risk Hedging | **Not found** — no hedging logic exists anywhere in this path |
| 3 | Mean Reversion & Bollinger Bands | Partially real — real Bollinger-band code exists (`core/strategy/mean_reversion.py`) but is **off by default** |
| 4 | VWAP Distance & Volume Ratio | Confirmed real — genuine scoring component |
| 5 | Quantitative DCF Fair Value Yield | **Not found** — no fundamental valuation logic anywhere |
| 6 | Volatility Arbitrage & Squeeze | Mislabeled — no arbitrage logic; the "squeeze" half is the same off-by-default Bollinger code as #3 |
| 7 | Momentum Divergence (RSI/MACD) | Partially real — RSI/MACD are scored, but true divergence detection (price vs. indicator disagreement) isn't implemented |
| 8 | Beta Neutralization & Tail-VaR | **Not found** |
| 9 | ML Supervised XGBoost/LightGBM | Partially real — LightGBM is genuinely used and active by default; **XGBoost is not used anywhere in this repository** |
| 10 | Support/Resistance Breakout | Partially real — a generic momentum/volume breakout check exists; actual pivot-point S/R levels exist in code but aren't used here |
| 11 | Liquidity & Order Book Imbalance | Mislabeled — no order-book data exists; what's used is options open-interest sentiment, fed neutral defaults for cash stocks |
| 12 | Dividend Safety & Balance Sheet Health | **Not found** |
| 13 | Event-Driven & Earnings Catalyst | **Not found** — only a generic "EVENT" regime penalty exists, unrelated to earnings |
| 14 | Microstructure Alpha | **Not found** |
| 15 | Smart Order Routing Slippage Minimizer | **Not found** — the scanner places no orders at all (signal-only) |
| 16 | AutoML Bayesian Hyperparameter Fit | **Not found** — `core/ai/automl_optimizer.py` exists but isn't imported by this scanner |

Also verified wrong: the changelog's claimed alert thresholds (score ≥80
STRONG / ≥68 MODERATE) don't match the actual dispatch gate, which requires
≥85 for index categories and ≥95 for stock/cash-equity categories
(`get_min_score_for_category()`, `core/all_nse_scanner.py`) — considerably
stricter than advertised.

**Confirmed accurate:** the universe iteration (full NSE `EQUITY_L.csv`,
20 parallel workers, daily refresh) and the fact that this feature is
genuinely signal-only — no broker/order-placement call exists anywhere in
`all_nse_scanner.py`.

**A related, more serious finding:** the Telegram alert includes a "🚀
1-Click Execute" button. Clicking it calls `core/telegram/callback_handler.py`,
which does **not** place any order — it logs a fake action and replies with
a canned success message ("🚀 Broker Limit Order Dispatched... via Active
OAuth Session!") regardless of what actually happened, which is nothing.
**Treat this button as non-functional; do not rely on it believing an order
was placed.** This is flagged for a fix — see [§8](#8-known-issues-and-gaps-as-of-this-manual).

## 6. Every dashboard screen

All pages are served by `core/enterprise_dashboard/` (FastAPI + Jinja2),
templates in `templates/enterprise/`. (A confirmed-dead, stale duplicate
directory, `core/templates/enterprise/`, was never referenced by
`core.enterprise_dashboard.main.EnterpriseDashboard._ensure_templates()` —
which always resolves to the root `templates/enterprise/` when it exists —
and has been deleted, 2026-08-21.) Auth: pages either require login and
redirect to `/login` if none, render with optional/anonymous auth
(personalizes if logged in but doesn't require it), or are admin-only
(`role == "admin"`, else a 403 page).

### Public pages (no login required)

| Page | What it does |
|---|---|
| `/login` | Sign-in form; theme switcher; link to register |
| `/register` | Self-service signup — all new accounts default to the `viewer` role |
| `/forgot-password` | Two recovery paths: emailed reset link, or an "Emergency Master Code" flow. **The UI's placeholder text shows a default master key literally — rotate this before going anywhere near production**, see §8 |
| `/reset-password?token=...` | Token-based password reset landing page |
| `/change-password` | Password change form. **Note:** unlike almost every other page, this one renders with no session check at all — the backend API call is the only thing enforcing auth here |

### End-user pages (login required unless noted "optional auth")

| Page | What it shows |
|---|---|
| `/` | Main cockpit — capital/P&L/win-rate stat strip, Overview/Recent Trades/Live Signals/System Health/Constitution tabs, a "⚡ Trade" one-click paper-trade button per signal |
| `/my-signals` | Your personal signal history with entry/target/SL, live outcome status, a step-by-step exit-plan modal, and a one-click paper-trade action |
| `/performance` | Win rate, Sharpe, profit factor, drawdown; breakdowns by regime and vs. a buy-and-hold benchmark |
| `/options-chain` | Live NIFTY/BANKNIFTY/FINNIFTY option chain with OI, volume, IV, and Greeks per strike |
| `/trade-journal` | Execution-quality journal — fill rate, slippage, latency, a per-order quality badge |
| `/live-pnl` | Real-time P&L broken down by direction, regime, session, score tier, and asset |
| `/system-health` | Component health, uptime, notifications, raw diagnostics |
| `/event-store` | Viewer for the hash-chained audit event log, with a "Verify Chain" integrity check |
| `/ab-tester` | Paper-trading A/B experiment results (control vs. variant, Mann-Whitney significance) |
| `/governance` | Strategy approval workflow — pending approvals, request history, data-quality scores |
| `/capacity` | Resource utilization, DB growth forecasts, throughput trend |
| `/metrics-trend` | Constitution health-metric trend across releases (dead code, duplicates, productivity) |
| `/data-quality` | Per-source data-quality scores, ML feature freshness SLAs, data lineage diagram |
| `/observability` | SLO compliance, error budgets, MTTR/MTBF, recent incidents |
| `/intelligence` | The largest console — code quality, security, performance, architecture, incidents, deployments, recommendations |
| `/security` | Security posture overview — users/roles, audit log, rate-limit config (read-only/informational; nothing here can be toggled) |
| `/intelligence/presentation` | Generates a PPTX summary deck of repo/quality data |
| `/sector-radar` *(optional auth)* | NSE sector-rotation radar (leading/improving/weakening/lagging quadrants) |
| `/margin-radar` *(optional auth)* | Multi-broker margin/collateral utilization with a safety badge |
| `/strategy-sandbox` *(optional auth)* | Parameter-tuning sandbox and gallery for the 16-strategy stock engine — see §5 for what's actually real behind these cards |
| `/fii-dii-radar` *(optional auth)* | FII/DII/Pro/Retail positioning radar with a "smart money trap" alert |
| `/expiry-harvester` *(optional auth)* | 0DTE straddle-selling monitor with per-leg theta-decay tracking |
| `/pricing-plans` *(optional auth)* | Subscription plans with a UPI QR-code payment flow |

Eight additional routes (`/trading`, `/signals`, `/risk`, `/broker`, `/ml`,
`/health`, `/logs`, `/system/state`) are legacy redirect stubs to SPA
anchors on `/` — not real screens.

### Admin-only pages

| Page | What it does |
|---|---|
| `/admin/users` | User management — roles, signal permissions, category subscriptions, quotas, audit trail |
| `/admin/config` | The live configuration editor — see [§7](#7-configuration-reference) for what's actually exposed here today vs. the full config surface |
| `/admin/signals` | System-wide signal analytics across 8 market categories |
| `/admin/kill-switch` | Halt/resume trading, with a typed-reason requirement and a full audit log |
| `/trade-copier` | Multi-account trade copier — replicates a master trade across linked client broker accounts (admin-gated despite its URL not starting with `/admin/`) |
| `/admin/portfolio-analyzer` | Multi-broker portfolio inspector against the 16-strategy engine, auto-hedging, tax-loss harvesting. **This route currently has no auth check at all — not even a login redirect.** Flagged in §8; fix before relying on this being admin-only |

## 7. Configuration reference

`json/index_config.defaults.json` has **over 1,700 lines and 1000+ keys**
and is the single source of truth for defaults (3-layer merge: defaults →
`json/config.json` → `json/config.local.json` → `OPBUYING_*` env vars).
This section groups the most operationally important areas; it does not
restate every single key (that would immediately go stale) — for the full
current list, read the JSON file directly, grouped by its own
`"_comment_*"` section markers.

### Areas you're most likely to actually touch

| Area | Key knobs | Notes |
|---|---|---|
| Capital & risk | `BASE_CAPITAL`, `MAX_DAILY_LOSS`, `MANDATE_RISK_PER_TRADE`, `MANDATE_DAILY_HARD_STOP` | Two parallel risk layers exist (`MAX_*`/legacy vs `MANDATE_*`/enforced) — both are live simultaneously |
| Exit prices | `SL_PCT`, `TARGET_PCT`, `TRAIL_PCT`, `TRAIL_ACTIVATE` | Multipliers of entry price, computed off the **underlying**, not option premium — see §4 |
| Execution mode | `EXECUTION_MODE`, `BROKER_DRIVER`, `BROKER_API_ENABLED`, `MANUAL_SIGNALS_ONLY` | `live_trading_lockout_enabled` (§2) sits above all of these |
| Signal thresholds | `AI_THRESHOLD`, `IV_SPIKE_THRESHOLD`, `VOL_RATIO_MIN` | Primary day-to-day signal-quality tuning surface |
| Live readiness | `live_trading_lockout_enabled`, `live_readiness_min_*` | See §2 — this now actually gates live execution, not just reports |
| Optional score layers | `mean_reversion_score_adjustment_enabled`, `ma_crossover_score_adjustment_enabled`, `gex_enabled`, `fii_dii_enabled`, `implied_move_enabled`, `regime_transition_enabled` | All off by default; the v2.54/v2.45 feature announcements describe what happens if you turn these on |
| Strike selection (opt-in) | `strike_selector_enabled` (default off), `strike_selection_mode` | See §4's premium-tracking caveat before enabling |
| Liquidity guard (opt-in, currently inert) | `liquidity_guard_enabled` | Wired but has no real bid/ask data source yet — see §8 |

### Duplicate/contradictory keys found during this audit — do not trust both sides blindly

A full pass found the same setting defined more than once, sometimes with
**different values**, across the file. The most operationally important
ones:

- **`NIFTY_LOT_SIZE=25`** vs **`INDEX_MAP.NIFTY.lot=50`** / **`instruments.NIFTY.lot_size=50`** — verified the live code path (`RiskService._get_lot_size`, now fixed to read `INDEX_MAP`) does **not** read the flat `NIFTY_LOT_SIZE` key, so this specific one isn't actively dangerous, but the flat key is stale/misleading and should be removed rather than left to confuse a future edit.
- Three independent time-of-day session-scoring systems with **different hour boundaries** (`session_classifier_enabled`'s 11:30/13:30/14:15 bands, `market.session_*_adj`'s mirror of it, and a third ungrouped block using 10:00/14:00 boundaries) — editing the wrong one silently does nothing.
- `RSI_OVERBOUGHT/OVERSOLD=70/30` vs `indicator.rsi_overbought/oversold=75/25` vs `INDEX_RSI_OVERBOUGHT/OVERSOLD=75/25`.
- `STRONG_THRESHOLD/MODERATE_THRESHOLD=80/68` = `TIER_STRONG_MIN/MODERATE_MIN=80/68`, but `indicator.strong_threshold/moderate_threshold=85/70`.
- Four different "reconciliation interval" values (`RECONCILE_INTERVAL=90`, `RECONCILIATION_INTERVAL_SEC=60`, `RECONCILIATION_ACTIVE_INTERVAL_SEC=30`, `RECONCILIATION_IDLE_INTERVAL_SEC=300`).
- `BROKERAGE_PER_TRADE=40` vs `MANDATE_COST_BROKERAGE=20` vs `financial.default_brokerage_per_order=20` — affects expected-value math differently depending on which one a given code path reads.
- Two enable-flags for the same feature defaulting to **opposite** values: `corp_action_enabled=true` vs `corp_action_calendar_enabled=false`; `underlying_analysis_enabled=true` vs `underlying_analyzer_enabled=false`.
- Retention policy duplicated with different numbers in two places: `RETENTION_LOGS_MAX_FILES/DAYS=20/14` vs `data_retention_logs_max_files/days=30/30`; similarly for reports and audit logs.

This list isn't exhaustive — a full accounting of every duplicate found
lives in the audit notes; reconciling all of them is real follow-up work
(see [§8](#8-known-issues-and-gaps-as-of-this-manual)), not something to
treat as already fixed by this manual documenting it.

### Making config editable from the Admin UI

`/admin/config` already exists as a live editor with Save/Preview/History/Rollback
and tabs for Execution, Risk, Broker, Signals, ML, Notifications, and
System — but it covers a curated subset of keys, not the full 1000+-key
surface documented above. Extending it to cover every key dynamically
(rather than requiring a code change to add a new field to the editor) is
tracked as follow-up work — see [§8](#8-known-issues-and-gaps-as-of-this-manual).

## 8. Known issues and gaps (as of this manual)

Real, verified findings from this audit that are not yet fixed:

1. **Exits are underlying-price-based, not option-premium-based** (§4) — the biggest gap between intended and actual risk behavior for an options-buying bot.
2. **The stock scanner's "16 strategies" claim is largely inflated** (§5) — most named strategies don't exist; two enable-flags for real features default to opposite states in two places.
3. ~~The Telegram "1-Click Execute" button sends a fake success message~~ **Fixed** — `core/telegram/callback_handler.py` now honestly reports that live execution via this button isn't implemented, rather than claiming an order was placed.
4. ~~`/admin/portfolio-analyzer` has no auth check at all~~ **Fixed** — now requires the same admin role check as every other admin page, with a regression test.
5. ~~The `/forgot-password` page's UI shows a default master-recovery-key placeholder in plaintext~~ **Fixed 2026-08-21** — the 3 hardcoded master-recovery keys (one shown in plaintext on this public page) are gone; the emergency-reset feature now requires `OPBUYING_EMERGENCY_MASTER_RECOVERY_KEY` to be set and is disabled (fail-closed) otherwise.
6. ~~`core/templates/enterprise/` is a dead, partially-divergent duplicate...~~ **Resolved 2026-08-21** — confirmed via file mtimes that the live `templates/enterprise/` copies were the newer, more complete ones (the dead copy's `admin_config.html` even had a realistic-looking Telegram bot token/chat-ID example in a tooltip, where the live one uses a generic placeholder); deleted `core/templates/enterprise/`.
7. **~20+ config-key duplicate/contradiction clusters** (§7) — most are latent (not currently causing wrong behavior) but risk silent drift if only one side of a pair gets edited in the future.
8. **The liquidity guard and (if enabled) strike selector are mechanically wired but functionally inert** without a live option-quote/bid-ask feed — see §4.
9. **Admin config UI doesn't yet cover the full config surface** — extending it to every key, dynamically, with tests, is open work (per the user's explicit request that all config be UI-editable and tested).
10. **Four additional broker integrations (mStock, Groww, Upstox, Dhan, IIFL, ICICI Direct) are in progress** — see [§9](#9-broker-integrations) for current status; none place real orders yet.
11. **A full audit of all 34 dashboard screens (2026-08-21)** found and fixed a large batch of fabricated-data and broken-wiring issues — full findings are in `.claude/skills/trading-bot-governance/references/lessons-learned.md`. Highlights, all fixed same day:
    - `admin.py`'s Portfolio Analyzer API (9 endpoints, including live hedge-order execution) had zero auth despite the page requiring admin — fixed.
    - The kill-switch screen's Resume button called the *kill* endpoint (never actually cleared the halt, while showing a false "resumed" toast); the audit log never recorded kill/resume events; 3 of 4 status cards read fields the endpoint never returned — all fixed, with regression tests.
    - `_check_health()` (feeds System Health + Observability screens) was 100% hardcoded "6/6 healthy" literals — now wired to the real `core.health_checker.run_full_health_check()`.
    - The Architecture Analysis tab's "10.0/10, 0 violations" was hardcoded — now wired to the real `core.architecture_analyzer.ArchitectureAnalyzer`, which immediately surfaced 4 real findings (1 boundary violation, 2 false-positive circular-import flags caused by a gap in the checker itself, all now fixed — the tab now genuinely reports 10.0/10 HEALTHY, evidence-checked, not restated). The Security-scan and Performance-analysis tabs had no real implementation at all; rather than fabricate a result, they now honestly report "not implemented."
    - `sector_rotation_radar.py`/`margin_radar.py`/`fii_dii_flow_radar.py`/`expiry_0dte_harvester.py` return fully static data with no real feed behind any of them — labeled `is_demo_data: true` with a visible UI banner rather than presented as live (building real feeds needs external subscriptions this environment doesn't have).
    - The 1-click "Trade" button on the dashboard/my-signals screens called a route that never existed, and always showed a fake "trade executed" success alert regardless — now genuinely wired to the real `ManualSignalQueue` (paper-mode queueing, not an instant fill) with an honest status message.
    - The trade-copier module claimed `"FILLED"` for any account in `"LIVE"` mode despite never calling a real broker — fixed to always report `"SIMULATED"` (this module has no real broker linkage at all; its accounts are seeded demo data, now labeled as such).
    - The UPI billing "I Have Paid" endpoint had no auth and accepted an arbitrary `username` in the body — anyone could self-grant paid tiers to any account for free. Now requires login, always provisions the caller's own account, and is audit-logged (there is still no real payment-gateway verification — that would need a real PSP integration).
    - The event-store screen's type-filter dropdown sent invented labels that don't match the real `EventType` enum, and — once that was fixed — the filter still returned nothing because it read a *different* `EventStore` implementation than the one the rest of the endpoint uses; both are now fixed to read the same source.
    - `presentation.html` had a template-structure bug (two `{% include %}`s placed after a `<script>` block had already closed with `})();` but before its own `</script>`) that broke the page's JS parse — every button on that screen was dead. Fixed.
    - A test file (`test_all_ui_screens_and_navigation.py`) had no path isolation and was writing test data directly into the real `json/config.json` — confirmed corrupted on disk, restored, and the fixture fixed.
    - `/api/broker/info` hardcoded `"status": "connected"` unconditionally, and `core/adapters/broker_health_monitor.py` (despite its name and docstring) never pings any real broker — both now report honestly (configured mode / labeled sample data) instead of fabricated connectivity.
    - `admin_portfolio_analyzer.html`'s per-row P&L was two hardcoded literals (`-15.4%`/`+18.2%`) and its "Qty" column showed the page-wide count, not that row's real quantity — the API response object never carried the real per-position values at all; added them.
    - The dead "Execute Harvesting Swap" button now honestly says automated execution isn't built yet, rather than doing nothing silently. `admin_config.html`'s real, already-tested rollback endpoint had no button calling it — added one.
    - The trade-journal endpoint's `fill_rate: 0.998` was hardcoded with no real "orders attempted vs filled" data behind it — now reported honestly as not-tracked (`null`), and the demo-trades fallback is now labeled `is_demo_data: true`. Separately noted: `core/trade_journal.py` (a real, complete execution-quality journal module) has zero callers anywhere in the live trading loop — a genuine feature-completion gap, not something silently faked here.

## 9. Broker integrations

| Broker | Status |
|---|---|
| Zerodha Kite | Real adapter exists (`infrastructure/adapters/brokers/kite/adapter.py`); order placement, cancellation, status, and fill-price/quantity reporting are implemented and unit-tested against a mocked SDK. **A separate bug was found and fixed this session**: `create_broker_adapter()`'s KITE dispatch was constructing `KiteBrokerAdapter(context)` directly with the wrong context shape, which would have raised `AttributeError` on first use — never caught because every real deployment path was already blocked by `PAPER_MODE`/`BROKER_API_ENABLED` defaults. Fixed to use `create_kite_adapter_from_context()`. Not yet validated against a live/sandbox account. |
| Angel One | Real adapter exists (`core/adapters/broker_adapters.py::AngelBrokerAdapter`); same scope as Kite. Not yet validated against a live/sandbox account. |
| m.Stock | **New this session.** Real adapter built (`infrastructure/adapters/brokers/mstock/adapter.py`) against mStock's published Type A REST API docs (verified 2026-08-20: login/OTP/TOTP session flow, order placement/cancel/modify, order book with fill price/quantity, positions). Order placement, cancellation, modification, status, fill-price/quantity, and positions are implemented and unit-tested against a mocked HTTP session. `get_quote`/`get_historical_data` intentionally raise `NotImplementedError` rather than guess an unverified endpoint — mStock's live-quote/historical-data API wasn't part of the docs pages checked; verify and implement before relying on this adapter for market data (the core bot uses yfinance for that regardless). Not yet validated against a live/sandbox account. Wire credentials via `BROKER_CONFIG.api_key`/`access_token` (or `MSTOCK_API_KEY`/`MSTOCK_ACCESS_TOKEN` as a fallback), set `BROKER_DRIVER=MSTOCK`. |
| IIFL Markets | **New this session.** Real adapter built (`infrastructure/adapters/brokers/iifl/adapter.py`) against IIFL's white-labelled XTS "Interactive" API, verified against the official Symphony Fintech SDK source and docs: login, order placement/cancel/modify, order book with fill price/quantity, positions. Two things are explicitly **not** guessed and must be supplied by you: (1) the real base URL (`root_url`) — XTS is white-labelled per broker, there's no public "the IIFL URL" answer, get it from IIFL directly; (2) `exchangeInstrumentID` resolution — the symbol-lookup endpoint lives in XTS's separate Market Data API, not verified here, so callers must supply a pre-resolved numeric instrument ID. `get_quote`/`get_historical_data` raise `NotImplementedError` for the same reason. Set `BROKER_DRIVER=IIFL`, `BROKER_CONFIG.root_url`/`api_key`/`secret`. Not validated against a live/sandbox account. |
| Groww | **New this session.** Real adapter built (`infrastructure/adapters/brokers/groww/adapter.py`) against Groww's official first-party REST API docs (verified 2026-08-21: Orders and Portfolio pages). Order placement/cancel/modify/status/fill-price/quantity and positions implemented and unit-tested against a mocked HTTP session. Groww's positions endpoint doesn't return a live last-traded-price field, so `unrealized_pnl` is left at `0.0` rather than computed from a guessed price source. `get_quote`/`get_historical_data` raise `NotImplementedError` — Groww's "Live Data API"/"Historical Data API" are separate products from the docs pages checked. This adapter accepts a pre-obtained access token; Groww's TOTP-based automated token-refresh flow uses their own SDK internals not verified here. Set `BROKER_DRIVER=GROWW`, `BROKER_CONFIG.access_token`. Not validated against a live/sandbox account. |
| Upstox | **New this session.** Real adapter built (`infrastructure/adapters/brokers/upstox/adapter.py`) against Upstox's official REST API v2 docs (verified 2026-08-21: Place/Modify/Cancel Order, Get Order Details, Get Positions pages). Note two different hosts are used — order mutations go through the low-latency `api-hft.upstox.com` host, reads through `api.upstox.com`, both confirmed from the real docs, not assumed. Implemented and unit-tested against a mocked HTTP session. `instrument_token` resolution from a plain symbol and the quote/historical-data endpoints weren't part of the docs checked, so those raise `NotImplementedError`/require a pre-resolved token from the caller, same pattern as IIFL. Set `BROKER_DRIVER=UPSTOX`, `BROKER_CONFIG.access_token`. Not validated against a live/sandbox account. |
| Dhan | **New this session.** Real adapter built (`infrastructure/adapters/brokers/dhan/adapter.py`) against the official DhanHQ-py SDK source on GitHub (verified 2026-08-21 directly from source code, since the marketing docs site didn't expose raw endpoint details). Order placement/cancel/modify/status and positions implemented and unit-tested. **Lower confidence than the other four adapters on one point**: Dhan's order-detail response doesn't carry a fill-price field the way Kite/mStock/IIFL/Groww/Upstox's do — fill data instead comes from a separate "trade book" endpoint (`GET /trades/{order_id}`), confirmed to exist with a `tradedPrice` field, but the exact per-trade *quantity* field name (`tradedQuantity`) was inferred from Dhan's naming convention elsewhere, not independently confirmed. Verify against a real order before trusting `get_filled_quantity()` for this broker specifically. Auth uses plain `access-token`/`client-id` headers, not Bearer — different from every other adapter here. Set `BROKER_DRIVER=DHAN`, `BROKER_CONFIG.user_id`/`access_token`. Not validated against a live/sandbox account. |
| ICICI Direct (Breeze API) | **New this session — completes the queued broker list.** Real adapter built (`infrastructure/adapters/brokers/icicidirect/adapter.py`) against ICICI Securities' official Breeze API REST docs (verified 2026-08-21: full checksum-based auth scheme, order placement/cancel/modify/detail, portfolio positions). Uses a genuinely different auth scheme from every other adapter here — SHA256 checksum of `timestamp + json_payload + secret_key`, sent as `X-Checksum`, plus `X-AppKey`/`X-SessionToken`/`X-Timestamp` headers (not a Bearer token). **Real, confirmed constraint**: Breeze does not support market orders at all — `place_order()` raises a clear error for `order_type=MARKET` rather than silently substituting a limit price. Implemented and unit-tested against a mocked HTTP session, including a dedicated test that verifies the checksum algorithm matches the documented spec exactly. Set `BROKER_DRIVER=ICICIDIRECT`, `BROKER_CONFIG.api_key`/`secret`/`access_token` (the session token). Not validated against a live/sandbox account. |

Both the master lockout and the automatic readiness gate (§2) apply to
every broker above uniformly, including any new ones added — none of them
can place a real order while the lockout is on, regardless of how complete
their adapter code is.
