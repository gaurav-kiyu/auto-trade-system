# Runbook: Constitution Self-Healing Bridge

| Field | Value |
|-------|-------|
| Runbook ID | `RB-016` |
| Severity | MEDIUM |
| Category | Governance |
| Last Updated | 2026-07-26 |

## Trigger Condition
- Automatic: Constitution health score drops below thresholds (warn: 7.0, crit: 5.0)
- Constitutionself-healing bridge registers failure patterns in the SelfHealingOrchestrator
- Evidence gaps detected (>20 categories missing evidence)
- Regression spikes (>5 open regressions)
- Manual: Operator notices constitution health declining in dashboard

## Expected Symptoms
- `constitution_self_healing_bridge` log entries showing triggered patterns
- SelfHealingOrchestrator action log shows constitution-related recovery attempts
- Dashboard constitution v4.0 score trending down over multiple checks
- Alert bridge may also fire notifications for same root cause

## Initial Diagnosis

### Step 1: Check constitution health score
```bash
python -c "
from core.constitution import get_validator
v = get_validator()
h = v.comprehensive_health_check()
print(f'Overall: {h[\"overall_score\"]:.2f}/10')
print(f'Status: {\"CRITICAL\" if h[\"overall_score\"] < 5.0 else \"WARNING\" if h[\"overall_score\"] < 7.0 else \"HEALTHY\"}')
print(f'Categories: {h[\"total_categories\"]}')
print(f'Evidence: {h[\"total_evidence\"]}')
print(f'Regressions: {h[\"open_regressions\"]}')
"
```

### Step 2: Check self-healing bridge status
```bash
python -c "
from core.self_healing.orchestrator import get_orchestrator
o = get_orchestrator()
status = o.get_health_status()
print(f'Monitor running: {status[\"monitor_running\"]}')
print(f'Patterns registered: {status[\"patterns_registered\"]}')
for a in status['recent_actions'][:5]:
    print(f'  Action: {a[\"action\"]} on {a[\"component\"]} — {a[\"status\"]}')
"
```

### Step 3: Check which categories are low
```bash
python -c "
from core.constitution import get_validator
v = get_validator()
report = v.generate_report()
for cid in sorted(report.categories.keys()):
    cat = report.categories[cid]
    score_pct = (cat.effective_score / cat.max_score * 100) if cat.max_score > 0 else 0
    if score_pct < 50:
        print(f'  LOW: {cid} ({cat.category_name}) — {cat.effective_score:.1f}/{cat.max_score:.1f} ({score_pct:.0f}%) — {len(cat.evidence)} evidence items')
"
```

## Resolution Steps

### 1: Check what the self-healing bridge has already done
```bash
python -c "
from core.constitution_self_healing_bridge import check_and_heal_constitution
result = check_and_heal_constitution()
print(f'Score: {result[\"overall_score\"]}')
print(f'Status: {result[\"health_status\"]}')
for action in result['healing_actions']:
    print(f'  Action: {action[\"action\"]} — {action[\"status\"]} — {action[\"message\"][:80]}')
"
```

### 2: Re-run auto-evidence collection
```bash
python -c "
from core.constitution import get_validator
from core.constitution.evidence import collect_auto_evidence
v = get_validator()
collect_auto_evidence(v)
report = v.generate_report()
print(f'After re-collection: {report.total_evidence_items} evidence items')
"
```

### 3: Run the full CI compliance check
```bash
python scripts/run_constitution_checks.py --check-v4-health
```

### 4: Generate a health report for analysis
```bash
python scripts/generate_constitution_report.py --days 30
```

### 5: Clear regressions if operator-verified (use with caution)
```bash
python -c "
from core.constitution import get_validator
v = get_validator()
# Check which categories have regressions
report = v.generate_report()
regs = {cid: cat for cid, cat in report.categories.items() if cat.regressions}
if regs:
    for cid, cat in regs.items():
        print(f'{cid} regressions: {cat.regressions}')
else:
    print('No regressions found')
"
```

### 6: If score remains low — add manual evidence
```bash
python -c "
from core.constitution import get_validator
v = get_validator()
# Add evidence for a specific low-scoring category
count = v.add_evidence('LAY-01', 'Manual verification: Business Layer operational', 'code_review', 0.5)
print(f'Evidence added: {count}')
print(f'Updated score: {v.get_category_score(\"LAY-01\").effective_score:.2f}')
"
```

## Verification
- [ ] Constitution health score is stable or improving
- [ ] Self-healing bridge shows patterns registered (5 total)
- [ ] Evidence count is sufficient across all 111 categories
- [ ] No critical regressions remain
- [ ] Dashboard constitution tab shows accurate data

## Prevention
- Run `python scripts/generate_constitution_report.py --save` weekly to track trends
- Keep evidence collectors up to date when adding new modules
- Ensure `wire_constitution_self_healing()` is called at startup (it is in `startup.py`)

## Escalation Path
1. **Level 1** — Operator on duty — 15 minutes
2. **Level 2** — Governance team lead — 1 hour
3. **Level 3** — System architect — 4 hours

## Postmortem Required
If constitution score drops below 5.0 (CRITICAL) and does not recover within 1 hour.

## Related Runbooks
- RB-015: Constitution Alert Bridge
- RB-013: Telegram Notification Outage
