# Version Compatibility Matrix — OPB v2.53.0

**Last Updated:** 2026-06-28
**Target:** Phase 29 — Version Governance & Compatibility Framework

---

## Overview

This document defines the version compatibility requirements across all major system components. It serves as the authoritative reference for determining which component versions can be safely combined in a deployment.

---

## Compatibility Rules

| Rule | Description | Enforcement |
|------|-------------|-------------|
| **R1** | Major version must match across all core components | Runtime check |
| **R2** | Minor version can differ by at most 1 | Runtime warning |
| **R3** | Patch version can differ arbitrarily | Advisory only |
| **R4** | DB schema version must be compatible with core version | Migration check |
| **R5** | Config schema version must be compatible with core version | Startup validation |
| **R6** | ML model version must be compatible with feature store version | Inference check |

---

## Core Component Compatibility

### v2.53.x Series

| Component | Min Version | Max Version | Compatible DB Schema | Compatible Config Schema |
|-----------|-------------|-------------|----------------------|--------------------------|
| Core Engine | 2.53.0 | 2.53.x | v4 | v4 |
| Execution Service | 2.53.0 | 2.53.x | v3 | v4 |
| Risk Service | 2.53.0 | 2.53.x | v3 | v4 |
| Signal Generator | 2.53.0 | 2.53.x | v2 | v4 |
| Order Manager | 2.53.0 | 2.53.x | v3 | v4 |
| Dashboard | 2.53.0 | 2.53.x | v2 | v4 |
| Auth System | 2.53.0 | 2.53.x | v2 | v4 |
| ML Classifier | 2.53.0 | 2.53.x | v2 | v4 |

### v2.52.x Series

| Component | Min Version | Max Version | Compatible DB Schema | Compatible Config Schema |
|-----------|-------------|-------------|----------------------|--------------------------|
| Core Engine | 2.52.0 | 2.52.x | v3 | v3 |
| Execution Service | 2.52.0 | 2.52.x | v2 | v3 |
| Risk Service | 2.52.0 | 2.52.x | v2 | v3 |
| Signal Generator | 2.52.0 | 2.52.x | v2 | v3 |
| Order Manager | 2.52.0 | 2.52.x | v2 | v3 |
| Dashboard | 2.52.0 | 2.52.x | v1 | v3 |
| Auth System | 2.52.0 | 2.52.x | v1 | v3 |
| ML Classifier | 2.52.0 | 2.52.x | v1 | v3 |

---

## Database Schema Compatibility

### Schema Versions

| Schema | DB | Introduced In | Breaking Changes | Migration Path |
|--------|-----|---------------|-------------------|----------------|
| v1 | trades.db | 2.50.0 | — | — |
| v2 | trades.db | 2.51.0 | Added `exit_reason`, `slippage` cols | `ALTER TABLE ADD COLUMN IF NOT EXISTS` |
| v3 | trades.db | 2.52.0 | Added `correlation_id`, `strategy_name` | `ALTER TABLE ADD COLUMN IF NOT EXISTS` |
| v4 | trades.db | 2.53.0 | Added `regime_code`, `session_code` | `ALTER TABLE ADD COLUMN IF NOT EXISTS` |

### Cross-DB Compatibility

| DB | Schema v1 | Schema v2 | Schema v3 | Schema v4 |
|----|-----------|-----------|-----------|-----------|
| trades.db | ✅ | ✅ | ✅ | ✅ |
| trade_journal.db | ✅ | ✅ | ✅ | ✅ |
| ml_tracker.db | ✅ | ✅ | ✅ | ✅ |
| oi_snapshots.db | ✅ | ✅ | ✅ | ✅ |

**Note:** All migrations are backward-compatible using `ALTER TABLE ADD COLUMN IF NOT EXISTS` pattern.

---

## Config Schema Compatibility

### Config Schema Versions

| Schema Version | Introduced In | Key Changes |
|----------------|---------------|-------------|
| v1 | 2.50.0 | Initial schema (350 keys) |
| v2 | 2.51.0 | Added ML config, risk limits (500 keys) |
| v3 | 2.52.0 | Added environment, governance (700 keys) |
| v4 | 2.53.0 | Added observability, finops (860+ keys) |

### Cross-Version Config Loading

| Running Version | Config Schema v1 | Config Schema v2 | Config Schema v3 | Config Schema v4 |
|-----------------|------------------|------------------|------------------|------------------|
| Core v2.53 | ⚠️ Fallback defaults | ⚠️ Fallback defaults | ⚠️ Partial | ✅ Full |
| Core v2.52 | ⚠️ Missing keys | ⚠️ Missing keys | ✅ Full | ❌ Unknown keys |
| Core v2.51 | ✅ Full | ⚠️ Missing keys | ❌ Unknown keys | ❌ Unknown keys |

---

## ML Model Compatibility

| Feature Set Version | Compatible Models | Features | Retrain Required? |
|--------------------|-------------------|----------|-------------------|
| v1 (9 features) | All existing models | score, confidence, direction, is_strong, is_moderate, is_weak, has_soft_blocks, day_of_week, hour_of_entry | No (predict_win_prob returns 0.5 on mismatch) |
| v2 (14 features) | v2.53+ models | v1 + iv_rank, vix, pcr, regime_code, session_code | Yes (retrain for new features) |

---

## Python Version Compatibility

| Python Version | Core | Tests | Dashboard | ML |
|----------------|------|-------|-----------|-----|
| 3.10 | ✅ | ✅ | ✅ | ✅ |
| 3.11 | ✅ | ✅ | ✅ | ✅ |
| 3.12 | ✅ | ✅ | ✅ | ✅ |
| 3.13 | ✅ | ✅ | ✅ | ✅ |
| 3.14 | ✅ | ⚠️ (minor issues) | ✅ | ✅ |

---

## Dependency Compatibility

### Core Dependencies (pinned in requirements-lock.txt)

| Package | Min Version | Max Version | Notes |
|---------|-------------|-------------|-------|
| Python | 3.10 | 3.19 | Enforced at startup |
| yfinance | 0.2.0 | latest | Market data |
| lightgbm | 3.3.0 | latest | ML classifier |
| scikit-learn | 1.0.0 | latest | Feature engineering |
| reportlab | 3.6.0 | latest | PDF generation |
| fastapi | 0.100.0 | latest | Web dashboard |
| uvicorn | 0.20.0 | latest | ASGI server |
| jinja2 | 3.0.0 | latest | Template rendering |

---

## Compatibility Verification

### Startup Checks

The following checks run at startup via `core/version_compatibility.py`:

```python
check_python_version()    # R1: Python >= 3.10
check_dependency_versions()  # R2: Core dependencies
check_db_schema()         # R4: Schema version check
check_config_schema()     # R5: Config schema check
```

### CI Pipeline Checks

The following checks run in CI (`.github/workflows/ci.yml`):

- `pip install -e ".[dev]"` — Verifies dependency resolution
- `python scripts/generate_config_schemas.py --check` — Config schema sync
- `python scripts/sync_artifacts.py --ci` — Artifact version sync

---

*Generated by Codebuff AI — June 28, 2026*
*Based on actual code analysis of version_compatibility.py, db_migration.py, config schemas.*
