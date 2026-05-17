# OPB Testing Checklist

**MUST RUN before any testing, regression, or deployment validation**

---

## Step 1: Syntax & Compile Check (30 seconds)

```powershell
# Full codebase syntax validation (excludes tests/)
cd "D:\TRADING_APP\12MAY2026\OPB_FINAL_MT"
Get-ChildItem -Recurse -Filter "*.py" -File | Where-Object { $_.FullName -notmatch "\\tests\\" } | ForEach-Object { python -m py_compile $_.FullName 2>&1 } | Select-String -Pattern "SyntaxError|Error"
```

**Quick single command:**
```powershell
python -m py_compile core/**/*.py infrastructure/**/*.py index_app/**/*.py reports/**/*.py
```

---

## Step 2: Import Verification (10 seconds)

```powershell
python -c "import core.execution.order_manager; import core.persistence.state.manager; import infrastructure.adapters.persistence.sqlite_adapter; import core.risk.risk_engine; print('All core imports OK')"
```

---

## Step 3: Critical Test Suites (2 minutes)

```powershell
# Core trading logic
python -m pytest tests/test_capital_manager.py tests/test_execution_policy.py tests/test_risk_engine.py tests/test_position_sizer.py -v --tb=short

# Execution safety
python -m pytest tests/test_execution_engine_retry.py tests/test_broker_failover.py -v --tb=short
```

---

## Step 4: Full Test Run (if needed)

```powershell
python -m pytest tests/ -v --tb=short
```

---

## Quick Reference

| Command | Purpose | Time |
|---------|---------|------|
| `python -m py_compile **/*.py` | Syntax errors | 30s |
| `pylint core/ --disable=R,C` | Code quality | 2min |
| `flake8 core/ --select=E9,F63` | Critical errors only | 10s |
| `mypy core/ --ignore-missing-imports` | Type checking | 1min |

---

## CI/CD Integration (Optional)

Add to `.github/workflows/test.yml`:
```yaml
- name: Syntax Check
  run: |
    find . -name "*.py" -not -path "./tests/*" -exec python -m py_compile {} +
```

---

**Last Updated: 16 May 2026**