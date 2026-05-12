# Audit: Auto-Tuner & Adaptive Components for Live Risk

**Date:** 2026-05-13  
**Status:** ⚠️ REQUIRES SAFEGUARDS for live deployment  
**Target:** OPB v2.45+

---

## Executive Summary

The adaptive components (`auto_tuner`, `auto_learner`, `adaptive_learning`, `adaptive_signal`) are **philosophically sound** but require **runtime safeguards** before live deployment:

- ✅ Suggestions-over-actions design is correct
- ✅ Blocklist-based frozen params (SL_PCT, TARGET_PCT, risk keys) is correct
- ⚠️ **State file writes during live trading** need concurrency protection
- ⚠️ **Penalty system in adaptive_signal** can stack unbounded
- ⚠️ **No circuit-breaker revert** if adapting harms performance
- ⚠️ **AI journal feedback loop** lacks isolation

---

## Component Analysis

### 1. **core/auto_tuner.py** — Status: ✅ SAFE
**Philosophy:** Suggestions over actions. Stability over optimization.

**Strengths:**
- Only tunes: `AI_THRESHOLD` and `SIGNAL_ENTRY_SCORE_GAP` (white-list only)
- Frozen: 40+ critical keys (SL_PCT, TARGET_PCT, MAX_DAILY_LOSS, BROKER_CONFIG, etc.)
- High confidence gate: 30 trades minimum before HIGH confidence
- Medium confidence: 15-29 trades → suggestions only, never auto-applied
- Low confidence: <15 trades → flag only
- Cooldown window: 7 days between changes to same param
- Max changes per run: 2 (hard cap)
- Backup before write: `backup_config()` creates timestamped copy
- Dry-run default: `AUTO_TUNE_DRY_RUN=true` by default

**Risks Identified:**
1. **Config reload delay** - Changes written but not reloaded into `index_trader.py` until next restart
   - *Severity:* LOW (next market open)
   - *Mitigation:* Add "config reload required" warning in log

2. **Concurrent file writes** - If `apply_recommendations()` called during trader read
   - *Severity:* MEDIUM (atomic JSON dump helps, but TOCTOU race exists)
   - *Mitigation:* Use file locking or scheduled offline tuning only

3. **No rollback on performance degradation** - If tuned threshold harms next-day trades, no auto-revert
   - *Severity:* MEDIUM (7-day cooldown provides manual review window)
   - *Mitigation:* Add 1-day post-tune performance monitor + manual revert capability

**Recommendation:** ✅ **SAFE FOR LIVE** with:
- File locking around `apply_recommendations()`
- 1-day post-tune performance check before accepting change
- Weekly manual review of applied tunings

---

### 2. **core/adaptive_learning.py** — Status: ✅ SAFE
**Philosophy:** Pure functions, no I/O, no threading.

**Key Functions:**
- `recent_trade_learning_snapshot()` — Summarize last N closes
  - Win rate, avg net, loss streak, by_regime, by_strength
- `adaptive_threshold_adjustment()` — Return (delta, reason) to apply on base threshold
  - Input-only, no side effects
  - Configurable caps: max_bonus (default 8), max_discount (default 3)
  - Delta clamped: [-max_discount, +max_bonus]
- `live_signal_confidence()` — Heuristic 1-99 confidence band (A/B/C/D)
  - Used to tag signals, not directly control entry
- `update_learning_after_exit()` — Update learner state after trade close
  - Adjusts score_adj, confidence, streak counters

**Strengths:**
- Pure functions: no shared state mutations
- Configurable caps prevent runaway adjustments
- Loss streak detection: halt signals after N consecutive losses
- Regime/strength bucketing: differentiated learning per market condition

**Risks Identified:**
1. **Loss streak detection incomplete** - Only checks threshold, doesn't halt completely
   - *Severity:* LOW (relies on index_trader to check `loss_streak_halt`)
   - *Mitigation:* Document requirement in index_trader integration

2. **Regime/strength stats decay** - Older trades fade out via `regime_decay`
   - *Severity:* LOW (configurable, default 0.98 = slow decay)
   - *Mitigation:* Review decay rate quarterly

**Recommendation:** ✅ **SAFE FOR LIVE** as-is. Pure functions by design.

---

### 3. **core/auto_learner.py** — Status: ⚠️ NEEDS REVIEW
**Philosophy:** Wraps adaptive_learning + AI journal feedback + per-symbol state.

**Key Features:**
- Persistent state: JSON file (`AUTO_LEARNER_STATE_FILE`)
- AI journal integration: Reweights wins/losses from LLM verdicts (default weight 0.3)
- Per-symbol learning (optional, `AUTO_LEARNER_PER_SYMBOL`)
- Configurable rates: win_score_decay, loss_score_inc, etc.
- Auto-save after each exit record

**Strengths:**
- Thread lock (_lock) protects state reads/writes
- Configurable learning rates allow tuning to market conditions
- Per-symbol state reduces cross-symbol interference

**Risks Identified:**
1. **State file write during live trading** ⚠️ **CRITICAL**
   - Called in `record_exit()` which is called after every close
   - If index_trader and learner both write to same file in parallel → corruption risk
   - *Severity:* **CRITICAL** for live
   - *Mitigation:* 
     - Add atomic write with temp file + rename
     - OR: Use separate lock file (`.learner_state.lock`)
     - OR: Batch writes to EOD only

2. **AI journal validation** ⚠️ **MEDIUM**
   - AI journal sourced from LLM verdicts, no human veto
   - If AI hallucinating, wrong verdicts affect learning state
   - *Severity:* MEDIUM (0.3 weight limits impact, but compounds over time)
   - *Mitigation:*
     - Add human review queue for AI verdicts
     - Daily audit of journal vs trade results
     - Config gate: `AUTO_LEARNER_AI_JOURNAL_WEIGHT=0.0` to disable

3. **No isolation from index_trader state** ⚠️ **MEDIUM**
   - Learner state updates index_trader's global state directly
   - If learner glitches, corrupts trader state
   - *Severity:* MEDIUM (state only affects threshold, not risk logic)
   - *Mitigation:*
     - Separate learner state from trader state (not merged)
     - Add validation: threshold delta must be in [-3, +8]
     - Periodic state audit

4. **Runaway learning on streak** ⚠️ **LOW**
   - Consecutive wins triggers boost (streak_boost_at, default 3)
   - But max_discount caps it at -3 points
   - *Severity:* LOW (capped, configurable)
   - *Mitigation:* No action needed, already safe

**Recommendation:** ⚠️ **CONDITIONAL LIVE** with:
- [ ] Atomic file write with lock file
- [ ] AI journal verdicts sampled daily for accuracy
- [ ] `AUTO_LEARNER_ENABLED=false` by default (opt-in)
- [ ] Weekly state audit + validation checks

---

### 4. **core/adaptive_signal.py** — Status: ⚠️ NEEDS REVIEW
**Philosophy:** Soft-rejection wrapper around signal generation.

**Key Components:**
- `AdaptiveSignal` dataclass: carries score, penalty, blockers, explanation
- `evaluate_adaptive_signal()` — Multi-phase scoring:
  1. IV Rank (Phase 1)
  2. Session classifier (Phase 3)
  3. ML classifier (Phase 5)
  4. Strike selector (Phase 4)
  5. And more (event calendar, correlation guard, etc.)

**Risks Identified:**
1. **Penalty stacking** ⚠️ **MEDIUM**
   - Multiple phases can apply penalties (news_level, iv_skew, correlation, etc.)
   - No cap on total penalty stack
   - *Severity:* MEDIUM (can suppress valid signals unbounded)
   - *Mitigation:*
     - Add `MAX_TOTAL_PENALTY` cap (e.g., -50 points)
     - Log total penalty per signal
     - Alert if total penalty > threshold

2. **Soft-penalty vs hard-block distinction unclear** ⚠️ **LOW**
   - Some phases add to penalty (score reduction)
   - Some add to soft_blocks (informational)
   - Mixing these makes it unclear what suppresses entry
   - *Severity:* LOW (doesn't break logic, just transparency)
   - *Mitigation:*
     - Document each penalty type + threshold
     - Separate penalty (score) from block (hard gate)

3. **No fallback if all phases penalize** ⚠️ **LOW**
   - If extreme market condition hits all phases, signals always rejected
   - *Severity:* LOW (correct behavior for extreme conditions)
   - *Mitigation:* No action needed

**Recommendation:** ⚠️ **LIVE WITH MONITORING** of:
- Daily penalty distribution (histogram)
- Phase-by-phase rejection rates
- Alert if >60% of signals rejected by penalty

---

## Live Deployment Checklist

### Pre-Live (Day -7)
- [ ] Run 1-week paper backtest with `AUTO_LEARNER_ENABLED=true`
- [ ] Audit learner state file for corruption
- [ ] Validate AI journal verdicts (sample 20 trades, check LLM accuracy)
- [ ] Verify config backups created on test apply

### Day 0 (Go-Live)
- [ ] `AUTO_TUNER_ENABLED=false` (dry-run only)
- [ ] `AUTO_LEARNER_ENABLED=false` (monitor-only)
- [ ] `ADAPTIVE_SIGNAL_SOFT_BLOCK_ON_PENALTY=false` (no auto-reject)
- [ ] Log all adaptive adjustments to separate `adaptive.log`

### Day 1-7 (Monitoring)
- [ ] Check adaptive.log for penalty stacking issues
- [ ] Validate learner state consistency
- [ ] Monitor win-rate drift (should be stable ±5%)
- [ ] If win-rate drops >10%, disable adapting immediately

### Day 8+
- [ ] Gradual enable: `AUTO_LEARNER_ENABLED=true` (read-only first)
- [ ] Next week: `AUTO_TUNER_ENABLED=true` (dry-run)
- [ ] Week 3: Enable actual tuning if metrics stable

---

## Specific Fixes Needed

### Fix 1: Auto-Learner Atomic File Write
**File:** `core/auto_learner.py`  
**Issue:** Line ~450 `self.save()` can corrupt state during concurrent access  
**Fix:** Use atomic write pattern

### Fix 2: Adaptive Signal Penalty Cap
**File:** `core/adaptive_signal.py`  
**Issue:** No upper bound on total penalty stack  
**Fix:** Add `MAX_TOTAL_PENALTY = -50` config key, enforce in signal.py

### Fix 3: Config Reload Live Gate
**File:** `core/auto_tuner.py` & `index_app/index_trader.py`  
**Issue:** Tuned config not reloaded until restart  
**Fix:** Add config reload handler or document restart requirement

### Fix 4: Post-Tune Performance Check
**File:** `core/auto_tuner.py`  
**Issue:** No validation that tuning improved outcomes  
**Fix:** Add 1-day post-tune win-rate check, auto-revert if <45%

---

## Configuration Recommendations

Add to `index_config.defaults.json`:

```json
{
  "AUTO_TUNER_ENABLED": false,
  "AUTO_TUNER_DRY_RUN": true,
  "AUTO_TUNER_COOLDOWN_DAYS": 7,
  "AUTO_TUNER_POST_TUNE_VALIDATION_DAYS": 1,
  "AUTO_TUNER_MIN_WIN_RATE_POST_TUNE": 0.45,

  "AUTO_LEARNER_ENABLED": false,
  "AUTO_LEARNER_STATE_FILE": "backups/learner_state.json",
  "AUTO_LEARNER_STATE_LOCK_FILE": "backups/.learner_state.lock",
  "AUTO_LEARNER_ATOMIC_WRITE": true,
  "AUTO_LEARNER_AI_JOURNAL_WEIGHT": 0.0,
  "AUTO_LEARNER_DAILY_AUDIT": true,

  "ADAPTIVE_SIGNAL_MAX_TOTAL_PENALTY": -50,
  "ADAPTIVE_SIGNAL_SOFT_BLOCK_ON_PENALTY": false,
  "ADAPTIVE_SIGNAL_PENALTY_ALERT_THRESHOLD": 0.6,

  "ADAPTIVE_LEARNING_LOSS_STREAK_HALT": 3,
  "ADAPTIVE_LEARNING_MAX_BONUS": 8,
  "ADAPTIVE_LEARNING_MAX_DISCOUNT": 3
}
```

---

## Conclusion

**Verdict:** Adaptive components are **philosophically sound** but need **operational safeguards** for live deployment.

| Component | Status | Gate | Action |
|-----------|--------|------|--------|
| auto_tuner | ✅ SAFE | Manual review | Dry-run first |
| adaptive_learning | ✅ SAFE | None | Live OK |
| auto_learner | ⚠️ CONDITIONAL | Disable AI journal | Enable with monitoring |
| adaptive_signal | ⚠️ MONITORING | Monitor penalty stack | Alert + cap |

**Recommendation:** Deploy with all adaptive features **disabled by default**. Enable one at a time after 1-week validation window.
