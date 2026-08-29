# Mandatory Pre-Implementation Analysis, RCA & Risk Assessment Governance Protocol

**Document Version:** 5.0.0  
**Effective Date:** 2026-08-11  
**Scope:** All repository modifications, feature additions, enhancements, refactoring, and bug fixes across all application domains.

---

# 1. Purpose & Mandate

Before modifying any source file, configuration, database schema, or infrastructure manifest in this repository, the engineering agent or developer **MUST** perform and document a **Pre-Implementation Analysis**.

No code modification is permitted without fulfilling this mandatory 8-step protocol.

---

# 2. Dynamic Configuration & Free Signal-Mode Mandates

Before any code modification is approved, the developer MUST verify:
- ✅ **Dynamic Parameter Rule:** NO static or hardcoded constants restricting operational rules (all values MUST be dynamically loaded from `json/config.json` / `core/config_bootstrap.py` with built-in default fallbacks).
- ✅ **Free Signal & Paper Trading Rule:** Default mode MUST be `PAPER_TRADING = True` and `LIVE_TRADING_ENABLED = False` (zero monetary cost, zero paid API dependency during evaluation).
- ✅ **Real Backtest Rule:** Before evaluating live deployment, run the real backtest/walk-forward tooling — `python run_backtest.py` and `core/walkforward_engine.py`'s rolling/anchored walk-forward validation — against actual historical data, and satisfy `core/live_readiness_checker.py`'s 5 blocking criteria (this is the mechanism `create_broker_adapter()` actually enforces before honoring a real broker driver).

---

## 2.1 Backtest & Live-Readiness Evidence (corrected 2026-08-21)

The `run_5_to_10_year_backtest.py` / `run_1_to_2_year_backtest.py` / `run_3_to_6_month_backtest.py` scripts and legacy cron_backtest_doc_syncer referenced by earlier drafts of this protocol have been **deleted**: they simulated a synthetic sine-wave price path with no real historical data (identical, hand-tunable ~94-95% win rates and byte-identical NIFTY/BANKNIFTY P&L regardless of index), were never wired into the live trading loop or a real scheduler, and their only caller was their own test file. Do not recreate this pattern.

For genuine backtest/readiness evidence, use:
1. `python run_backtest.py` — the real offline backtest runner (see CLAUDE.md's Entry Points table).
2. `python -m core.walkforward_engine` — rolling/anchored walk-forward validation on real data.
3. `python -m core.live_readiness_checker` — the 5-blocking-criteria paper scorecard gate that `create_broker_adapter()` actually enforces before a real broker driver is ever honored.

---

## 2.2 Mandatory Category Score Criteria Rule (>= 9.0 / 10 or >90% across ALL Categories)

To enforce institutional-grade quality standards across the entire platform:

1. **Category Score Target:**
   - The 111 categories are real (`scripts/score_system.py`'s `ConstitutionValidator`, 31 classic + 80 v4.0 — confirmed by running `python scripts/score_system.py --json`). **9.0/10 is an aspirational target, not today's enforced floor.**
   - **Corrected 2026-08-21:** `.github/workflows/ci.yml`'s `governance` job actually runs `python scripts/score_system.py --ci --check-min 5.0` — the real CI-blocking floor is **5.0**, not 9.0. Raising it to 9.0 is a deliberate policy change to propose separately, not a documentation fix, since it would newly fail CI for any category currently between 5.0 and 9.0.
   - **Caveat on the current all-10.0 result:** running the scorer today returns `10.0/10` for all 111/111 categories. Each category's formula is `score = min(max_score, base_score(8.5) + evidence_bonus)`, i.e. a fixed 8.5 baseline plus a bonus term that saturates the 10.0 ceiling once evidence_count is modestly large — so a perfect 111/111 is close to the formula's structural ceiling, not necessarily proof every category is defect-free (this same session found live math/wiring bugs in modules scoring 10.0). Treat a 10.0 as "evidence exists," not as "verified defect-free," until the scoring formula itself is reviewed.
2. **Automated Enforcement (as actually wired):**
   - `python scripts/score_system.py --check-min <threshold>` is real and CI-wired at threshold 5.0. Use `python scripts/score_system.py` (no args) for the full per-category report.

## 2.3 Repository Hygiene — Corrected 2026-08-21

The `file:///d:/AI_APPs/TRADING_APP/OPB_FINAL_MT/...` absolute paths and `docs/MASTER_INDEX.md` references below were copied from an unrelated project (this repo lives under a different path entirely) and pointed at files that don't exist here; `docs/MASTER_INDEX.md` itself was deleted as part of the same fabricated-doc cleanup that removed the backtest-report cluster (see CLAUDE.md's bug-fix history). Corrected to reality:

1. **Batch launchers in root:** actual current set is `setup.bat`, `start.bat`, `open_admin.bat`, `open_app.bat`, `run_final_certification.bat`, `run_low_capital.bat`, `build_exe.bat`, `START_REALTIME_MARKET_SCANNER.bat`, `START_AFTER_HOURS_SCANNER.bat` — re-verify with `ls *.bat` rather than trusting a hardcoded list here, since this drifts.
2. **PowerPoint decks:** there is no single canonical `docs/*.pptx` file today. Presentation generation is a real, live-wired dashboard feature (`core/presentation_generator.py`, `/api/intelligence/presentation/generate*` in `core/enterprise_dashboard/routes/intelligence_bi.py`, `templates/enterprise/presentation.html`) that writes user-triggered decks to `reports/presentations/` — that's the canonical mechanism now, not a single static file in `docs/`.
3. **Root markdown guides:** `QUICK_START_GUIDE.md`, `SETUP_AND_TRADING_GUIDE.md`, `STEP_BY_STEP_GUIDE.md` don't exist in root today — this rule is currently satisfied trivially.

---

# 3. Mandatory 8-Step Pre-Implementation Workflow

```text
STEP 1: Problem & Objective Definition
        ↓
STEP 2: Root Cause Analysis (RCA) & Empirical Evidence
        ↓
STEP 3: Scope Boundary & Dependency Mapping
        ↓
STEP 4: Change Impact Analysis & Risk Assessment Matrix
        ↓
STEP 5: Dynamic Config & Paper Trading Compliance Verification
        ↓
STEP 6: Minimal Change & Reversibility Strategy
        ↓
STEP 7: Auto-Healing & Test Verification Strategy
        ↓
STEP 8: Approval & Execution Gate
```

---

## Step 1: Problem & Objective Definition
- Clear statement of the requested feature, enhancement, or defect.
- Business context, user impact, and expected system behavior.

## Step 2: Root Cause Analysis (RCA) & Empirical Evidence
- **Symptom:** Exact failure mode, error code, or missing capability.
- **Root Cause:** In-depth technical explanation of why the issue exists.
- **Empirical Evidence:** Log excerpts, stack trace, exception traceback, or test output.

## Step 3: Scope Boundary & Dependency Mapping
- Explicit listing of target files to be modified or created.
- Inspection of all upstream consumers, imported modules, and downstream callers.

---

**End of Governance Protocol Document**
