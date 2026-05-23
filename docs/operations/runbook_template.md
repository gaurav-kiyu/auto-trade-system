# Runbook: {{TITLE}}

| Field | Value |
|-------|-------|
| Runbook ID | `RB-{{ID}}` |
| Severity | {{SEVERITY}} |
| Category | {{CATEGORY}} |
| Last Updated | {{DATE}} |

## Trigger Condition
{{TRIGGER}}

## Expected Symptoms
- {{SYMPTOM_1}}
- {{SYMPTOM_2}}

## Initial Diagnosis

### Step 1: Verify the symptom
```bash
{{DIAGNOSTIC_COMMAND}}
```

### Step 2: Check logs
```bash
{{LOG_CHECK_COMMAND}}
```

### Step 3: Check system state
```bash
{{STATE_CHECK_COMMAND}}
```

## Resolution Steps

### {{STEP_NUM}}: {{STEP_TITLE}}
{{STEP_DESCRIPTION}}

```bash
{{STEP_COMMAND}}
```

### {{STEP_NUM}}: {{STEP_TITLE}}
{{STEP_DESCRIPTION}}

## Verification
{{VERIFICATION_STEPS}}

## Escalation Path
1. **Level 1** — {{LEVEL1_OWNER}} — {{LEVEL1_RESPONSE_TIME}}
2. **Level 2** — {{LEVEL2_OWNER}} — {{LEVEL2_RESPONSE_TIME}}
3. **Level 3** — {{LEVEL3_OWNER}} — {{LEVEL3_RESPONSE_TIME}}

## Postmortem Required
{{POSTMORTEM_REQUIRED}}

## Related Runbooks
- {{RELATED_RB_1}}
- {{RELATED_RB_2}}
