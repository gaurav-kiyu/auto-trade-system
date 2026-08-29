# OPB v17 Deep Signal & Reporting Audit

## Scope
Deep static review of v16 covering reporting/export architecture, report-table filtering,
signal history/outcome tracking, score construction, category reachability, notification
gates, and configuration consistency.

## Confirmed findings

1. **Report table filtering was inconsistent.** `admin_signals.html` had column filters,
   but most report pages did not. v17 adds a shared Excel-like column filter layer to
   report pages and dynamic tables.

2. **Generic report exports were key/value dumps.** v17 retains the dedicated structured
   Signal Intelligence export and adds a bounded rendered-table export endpoint so report
   pages without a dedicated backend builder can export their current tables to PDF/XLSX.
   Excel exports use native autofilters and frozen header rows.

3. **Outcome tracking could falsely prefer T2 over SL/T1 when one polling observation
   crossed multiple barriers.** v17 records outcome observations and marks simultaneous
   barrier crossings `AMBIGUOUS` rather than treating them as a win. Exact first-touch
   ordering still requires intrabar/event-level data.

4. **Score saturation is real in the index scoring design.** The index score has a
   theoretical component sum above 100, then clamps to 100. Therefore `100/100` is a
   saturation bucket, not necessarily an exact score of 100. v17 preserves an uncapped
   evidence score and exposes saturation diagnostics.

5. **Category reachability is inconsistent with a raw 100 gate.** The shared
   equity/futures scorer has a theoretical maximum of 83 points before normalization,
   while `CATEGORY_SCORE_THRESHOLDS` currently sets raw 100 for stock options,
   equities, futures, commodities, currencies and ETFs/REITs. Those categories are
   therefore unreachable under that raw gate. v17 does NOT silently lower the threshold;
   it reports the configuration defect and recommends category-specific normalization
   or scoring redesign.

6. **Index execution gate and notification gate are separate.** The current execution
   loop uses `AI_THRESHOLD` (60) while the all-NSE notification scanner enforces raw
   100. The project is currently `SIGNAL_ONLY`, but this distinction must be resolved
   before enabling automated execution.

7. **Historical production signal data is not present in the v16/v17 release ZIP.**
   The clean release intentionally excludes runtime DBs. Therefore no honest claim can
   be made about last-week 500–700/day volumes, actual 100-score frequency, or SL-before-
   T1 rate from the release archive alone. The deployed `db/signals_history.db` is
   required for those empirical conclusions.

## Recommendations

- Keep live automatic tuning disabled until sufficient historical evidence is available.
- Do not automatically change SL/T1/thresholds based on in-sample outcomes.
- Add intrabar/event-level market observations for exact first-touch analysis.
- Use score saturation rate, raw score distribution, category, regime, session and
  direction as mandatory dimensions in tuning reports.
- Before enabling non-index categories under a raw 100 policy, redesign their scoring
  scale or establish validated category-specific thresholds.
- For the 500–700/day observation, first measure:
  generated -> evaluated -> accepted -> notified -> deduplicated,
  by symbol/category/time/session/score/raw-score. This will identify whether the
  volume is caused by generation, score saturation, notification routing, or duplicate
  dispatch.
