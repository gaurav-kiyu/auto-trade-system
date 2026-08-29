# OPB Web Clean Release — Signal Engine Hardened Final

Baseline:
- OPB_WEB_CLEAN_RELEASE_v18_SIGNAL_LIFECYCLE_HARDENED.zip
- Baseline SHA-256: 7a39d93fb115af02db0a39d795bb96eecb9f2d53e6d872d496a2fa3ae1ba0f5

Release focus:
This release preserves the v18 web/mobile/theme/authentication/registration/permissions/reporting work and adds the production signal-engine corrections derived from the AWS forensic review.

## Signal-engine corrections

1. Canonical base-score normalization
   - Retains an uncapped component score for audit.
   - Normalizes the base score once instead of repeatedly clamping intermediate totals.
   - Default theoretical base ceiling is 150.
   - Prevents every raw score >=100 from being indistinguishable.
   - Stores raw component score separately from normalized 0-100 score.

2. ML governance
   - External alert admission requires ML probability >= ML_ALERT_MIN_PROBABILITY (default 0.65).
   - A missing/unavailable model's neutral 0.5 fallback cannot qualify for the elite notification tier.
   - High-conviction mode, when explicitly enabled, is a real admission gate rather than a reporting-only annotation.

3. Persistent opportunity deduplication
   - Opportunity identity no longer contains live price/target values.
   - Active opportunities are suppressed even when the market price changes.
   - Deduplication survives process restarts through the SignalTracker database.

4. Candidate ranking and notification protection
   - Full scan completes before external dispatch.
   - Top candidates are selected after ranking, with category diversity.
   - Default maximum: 10 alerts per cycle.
   - Default rolling maximum: 20 alerts per 5 minutes.
   - Default daily maximum: 100 unique generated signals.
   - This is a protection layer; it does not replace strategy quality.

5. Permission enforcement
   - Legacy system-level EMAIL_TO/CHAT_ID broadcast is opt-in only.
   - Per-user permission/notification eligibility remains the authoritative delivery gate.

6. Manual-only safety
   - Telegram "1-Click Execute" button is disabled by default and only appears when explicitly enabled in AUTO/PAPER modes.
   - Current default remains SIGNAL_ONLY/manual.

7. Delivery idempotency
   - If persistent signal tracking rejects a duplicate or fails to produce a signal ID, external Telegram/SMTP dispatch is suppressed.
   - Prevents a previous v18 failure mode where a deduplicated DB record could still be externally notified.

8. Audit integrity
   - Production audit path is now project-relative instead of a hard-coded Windows D: path.
   - Fabricated expected-value and calibrated-probability placeholders were removed from forward audit records; unavailable calibrated metrics are recorded as null.

9. Alert evidence
   - Alerts expose raw component score and ML win probability so a displayed 100/100 cannot be mistaken for an uncapped perfect score.

## Existing v18 functionality retained

- Registration lifecycle and notification flow
- User signal permissions/RBAC
- CSRF/authentication protections
- Web/mobile/theme fixes
- Reporting infrastructure
- Excel-style report filtering
- PDF/XLSX export infrastructure
- Signal lifecycle/outcome tracking
- Scan-cycle observability
- Production URL resolution
- Security hardening

## Validation

Passed targeted regression suites covering:
- signal-engine hardening
- v18 signal lifecycle
- signal evaluator
- ML classifier
- user signal permissions
- notification filters/service
- report filter coverage
- registration/security regressions
- enterprise dashboard notification behavior
- production notification URL contract

All selected suites passed.

The complete repository test suite could not be certified in this environment because several optional test dependencies are absent (Hypothesis, DuckDB, yfinance). No dependency was installed or modified merely to force the suite to pass.

## Deployment safety

Do NOT copy local database files over the AWS production database.

Before deployment:
1. Back up AWS application directory and all DB/WAL/SHM files.
2. Replace code/config from this release.
3. Preserve production DBs.
4. Verify EXECUTION_MODE=SIGNAL_ONLY.
5. Verify ENABLE_TELEGRAM_EXECUTE_BUTTON=false.
6. Verify ML_REQUIRED_FOR_ALERTS=true.
7. Verify notification rate limits.
8. Run the production smoke test.
9. Monitor signal-cycle metrics and notification counts.

This package is a release candidate for controlled AWS deployment, not a claim that live market performance has been proven. Historical outcome quality must continue to be measured after deployment.
