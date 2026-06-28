---
name: Bug Report
about: Create a report to help us improve the trading platform
title: "[BUG] "
labels: bug
assignees: ''

---

## Bug Description

A clear and concise description of the bug.

## Steps to Reproduce

1. Configure: `python index_app/index_trader.py --paper`
2. Run with config: `...`
3. Observe: `...`

## Expected Behavior

A clear description of what you expected to happen.

## Actual Behavior

A clear description of what actually happened, including error messages or logs.

## Environment

- **OS:** (e.g., Windows 10, Ubuntu 22.04, macOS 14)
- **Python Version:** (e.g., 3.10, 3.11, 3.12)
- **Bot Version:** (from `VERSION` file or `git describe --tags`)
- **Deployment:** (Direct, Docker, Docker Compose)
- **Broker Mode:** (Paper, Manual Signal, Live)
- **Config:** (list any non-default config values)

## Logs & Diagnostics

```
Paste relevant log output here (redact any secrets/API keys)
```

## Diagnostic Commands

Run these and paste output:

```bash
python --version
python -m core.health_checker --format json
python -c "from core.version_compatibility import check; print(check())"
```

## Possible Fix

If you have an idea of what might be causing the issue, describe it here.

## Checklist

- [ ] I have redacted all API keys, tokens, and secrets from the above
- [ ] I have checked that this is not a known issue in the documentation
- [ ] I have included relevant logs and configuration (with secrets redacted)
- [ ] I am running the latest version of the software

## Additional Context

Add any other context about the problem here (screenshots, references, etc.).
